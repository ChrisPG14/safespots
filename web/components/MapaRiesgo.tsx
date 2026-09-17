"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AttributionControl,
  // Se importa con alias: `Map` a secas taparía el Map de JavaScript, que
  // este componente usa para el índice de municipios.
  MapLibreMap,
  Marker,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type ErrorEvent,
  type MapGeoJSONFeature,
  type MapLayerMouseEvent,
} from "maplibre-gl";
import type {
  ExpressionSpecification,
  StyleSpecification,
} from "@maplibre/maplibre-gl-style-spec";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  COLOR_ESTRATO,
  ETIQUETA_ESTRATO,
  ORDEN_ESTRATOS,
  VISTA_INICIAL,
  decimal,
  esEstrato,
  numero,
  TEXTO_SOBRE_ESTRATO,
} from "@/lib/riesgo";
import type { Meta, Perfil, PropiedadesColonia } from "@/lib/tipos";

import AsesorColonia from "./AsesorColonia";
import { limitesColonia, normalizarBusqueda, puntoColonia, type Colonia, type Coordenadas, type DatosColonias } from "@/lib/geografia";
import type { Objetivo } from "@/lib/asesor";
import Logo from "./Logo";

const URL_GEOJSON = "/datos/colonias-riesgo.geojson";
const FUENTE = "colonias";
const CAPA_RELLENO = "colonias-relleno";
const CAPA_BORDE = "colonias-borde";
const CAPA_SELECCION = "colonias-seleccion";

/**
 * URL del worker de MapLibre, servido por nosotros desde public/maplibre/.
 *
 * Es OBLIGATORIO bajo el empaquetador de Next.js. MapLibre deduce la URL de su
 * worker a partir de `import.meta.url`, que aquí no es una URL http(s), así
 * que calcula una cadena vacía y termina haciendo `new Worker("")`, lo que
 * apunta al propio HTML de la página.
 *
 * El síntoma es engañoso: el mapa se construye, el evento `load` se dispara y
 * las teselas raster aparecen, pero ninguna fuente GeoJSON carga jamás y no
 * se registra ningún error. Ver el comentario extenso en
 * scripts/copiar-worker-maplibre.mjs, que es el que pone ahí el archivo.
 */
const URL_WORKER = "/maplibre/maplibre-gl-worker.mjs";

/**
 * Estilo base definido aquí mismo, no cargado desde una URL remota.
 *
 * Con un estilo remoto, MapLibre no emite `load` hasta haber descargado ese
 * JSON. Si el CDN está bloqueado —un bloqueador de anuncios, el firewall de
 * una red universitaria, una caída— el evento nunca llega, las capas de
 * riesgo nunca se agregan y el usuario ve un mapa en blanco sin explicación.
 * Con el estilo incrustado, `load` no depende de la red: si las teselas
 * fallan se pierde el mapa de referencia, pero la coropleta —que es el
 * producto— se dibuja igual sobre el color de fondo.
 *
 * Se usan teselas de OpenStreetMap y no las raster de CARTO porque el
 * endpoint gratuito de CARTO (`basemaps.cartocdn.com/light_all`) ahora
 * devuelve las imágenes estampadas con "API KEY REQUIRED".
 *
 * NOTA PARA PRODUCCIÓN: la política de uso de teselas de OSM está pensada
 * para tráfico bajo. Es razonable para un proyecto académico, pero si esto
 * crece hay que pasar a un proveedor con llave (MapTiler, CARTO, Protomaps) o
 * autoalojar las teselas. Solo hay que cambiar este bloque.
 */
const ESTILO_BASE: StyleSpecification = {
  version: 8,
  sources: {
    base: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
    },
  },
  layers: [
    // El fondo se pinta explícitamente para que un fallo de teselas deje un
    // lienzo con color, no un hueco donde la coropleta flote sin contexto.
    {
      id: "fondo",
      type: "background",
      paint: { "background-color": "#eeece7" },
    },
    {
      id: "base",
      type: "raster",
      source: "base",
      paint: {
        // El estilo estándar de OSM es muy colorido y compite con la rampa
        // amarillo-rojo del riesgo: desaturarlo y aclararlo lo convierte en
        // un mapa de referencia gris que deja resaltar la coropleta, que es
        // lo que el usuario tiene que leer.
        "raster-saturation": -0.85,
        "raster-brightness-min": 0.15,
        "raster-opacity": 0.6,
      },
    },
  ],
};

interface Props {
  meta: Meta;
}

export default function MapaRiesgo({ meta }: Props) {
  const contenedor = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapLibreMap | null>(null);
  const ubicacionMarker = useRef<Marker | null>(null);
  const solicitudUbicacion = useRef(0);
  const claveResaltada = useRef<string | null>(null);

  const [listo, setListo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [perfilActivo, setPerfilActivo] = useState(meta.perfiles[0].clave);
  const [seleccion, setSeleccion] = useState<PropiedadesColonia | null>(null);
  const [panelAbierto, setPanelAbierto] = useState(false);
  const [colonias, setColonias] = useState<Colonia[]>([]);
  const [busqueda, setBusqueda] = useState("");
  const [nombres, setNombres] = useState(true);
  const [vista, setVista] = useState<"explorar" | "asesor">("explorar");
  const [objetivo, setObjetivo] = useState<Objetivo>("turismo");
  const [referencia, setReferencia] = useState<PropiedadesColonia | null>(null);
  const [ubicacion, setUbicacion] = useState<Coordenadas | null>(null);
  const [precisionUbicacion, setPrecisionUbicacion] = useState<number | null>(null);
  const [ajustandoUbicacion, setAjustandoUbicacion] = useState(false);
  const [ubicando, setUbicando] = useState(false);
  const [errorUbicacion, setErrorUbicacion] = useState<string | null>(null);
  const [metodologiaAbierta, setMetodologiaAbierta] = useState(false);

  const perfil = useMemo(
    () => meta.perfiles.find((p) => p.clave === perfilActivo) ?? meta.perfiles[0],
    [meta.perfiles, perfilActivo],
  );

  const municipios = useMemo(
    () => new Map(meta.municipios.map((m) => [m.clave, m.nombre])),
    [meta.municipios],
  );

  /** Pinta cada colonia según su estrato en el perfil activo. */
  const expresionColor = useCallback(
    (p: Perfil): ExpressionSpecification => [
      "match",
      ["get", p.campo_estrato],
      "bajo",
      COLOR_ESTRATO.bajo,
      "moderado",
      COLOR_ESTRATO.moderado,
      "alto",
      COLOR_ESTRATO.alto,
      "critico",
      COLOR_ESTRATO.critico,
      // Gris para las colonias sin clasificación. No se ocultan: un hueco en
      // el mapa se lee como "aquí no pasa nada", que es lo contrario de
      // "aquí no sabemos".
      "#d4d4d4",
    ],
    [],
  );

  /**
   * Las colonias con muestra insuficiente se dibujan translúcidas.
   *
   * Es una decisión de honestidad visual: en más de la mitad de las colonias
   * la estimación no es interpretable por sí sola, y pintarlas con la misma
   * intensidad que las demás transmitiría una certeza que no existe.
   */
  const expresionOpacidad = useCallback(
    (p: Perfil): ExpressionSpecification => [
      "case",
      ["boolean", ["get", p.campo_muestra_baja], false],
      0.3,
      0.75,
    ],
    [],
  );

  // --- construcción del mapa --------------------------------------------
  useEffect(() => {
    if (!contenedor.current || mapa.current) return;

    // Antes de construir el mapa: sin esto las fuentes GeoJSON nunca cargan.
    setWorkerUrl(URL_WORKER);

    const m = new MapLibreMap({
      container: contenedor.current,
      style: ESTILO_BASE,
      center: VISTA_INICIAL.centro,
      zoom: VISTA_INICIAL.zoom,
      maxBounds: VISTA_INICIAL.limites,
      attributionControl: false,
    });
    mapa.current = m;

    m.addControl(new NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");
    m.addControl(
      new AttributionControl({
        compact: true,
        // La atribución del mapa base la declara el propio estilo; aquí
        // solo se agrega la de los datos de riesgo.
        customAttribution:
          'Riesgo y colonias: <a href="https://iieg.gob.mx" target="_blank" rel="noreferrer">IIEG Jalisco</a>',
      }),
      "bottom-right",
    );

    m.on("error", (e: ErrorEvent) => {
      // Sin esto, un fallo de red en las teselas deja un lienzo en blanco sin
      // ninguna pista de qué pasó.
      console.error("MapLibre:", e.error?.message ?? e);
    });

    const controller = new AbortController();
    m.on("load", async () => {
      try {
        const resp = await fetch(URL_GEOJSON, { signal: controller.signal });
        if (!resp.ok) {
          throw new Error(`El servidor respondió ${resp.status} al pedir la capa de riesgo`);
        }
        const geojson: DatosColonias = await resp.json();
        if (controller.signal.aborted) return;
        setColonias(geojson.features);

        m.addSource(FUENTE, {
          type: "geojson",
          data: geojson,
          // promoteId permite usar feature-state para el resaltado sin tener
          // que redibujar toda la capa en cada movimiento del cursor.
          promoteId: "clave",
        });

        m.addLayer({
          id: CAPA_RELLENO,
          type: "fill",
          source: FUENTE,
          paint: {
            "fill-color": expresionColor(perfil),
            "fill-opacity": expresionOpacidad(perfil),
          },
        });

        m.addLayer({
          id: CAPA_BORDE,
          type: "line",
          source: FUENTE,
          paint: {
            "line-color": "#78716c",
            "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.2, 14, 0.7],
            "line-opacity": 0.6,
          },
        });

        m.addLayer({
          id: CAPA_SELECCION,
          type: "line",
          source: FUENTE,
          paint: {
            "line-color": "#1c1917",
            "line-width": [
              "case",
              ["boolean", ["feature-state", "activa"], false],
              2.5,
              0,
            ],
          },
        });

        setListo(true);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(
          err instanceof Error
            ? err.message
            : "No se pudo cargar la capa de riesgo",
        );
      }
    });

    // MapLibre fija el tamaño del lienzo al construirse y no lo reajusta por
    // su cuenta cuando el contenedor cambia. Sin esto, girar el teléfono o
    // abrir el panel deja el mapa recortado.
    const observador = new ResizeObserver(() => m.resize());
    observador.observe(contenedor.current);

    return () => {
      controller.abort();
      solicitudUbicacion.current++;
      observador.disconnect();
      ubicacionMarker.current?.remove();
      m.remove();
      mapa.current = null;
    };
    // Las expresiones y el perfil inicial solo se usan al construir; los
    // cambios posteriores se aplican en el efecto de abajo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- interacción -------------------------------------------------------
  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo) return;

    const resaltar = (clave: string | null) => {
      if (claveResaltada.current === clave) return;
      if (claveResaltada.current !== null) {
        m.setFeatureState(
          { source: FUENTE, id: claveResaltada.current },
          { activa: false },
        );
      }
      if (clave !== null) {
        m.setFeatureState({ source: FUENTE, id: clave }, { activa: true });
      }
      claveResaltada.current = clave;
    };

    const alEntrar = (e: MapLayerMouseEvent) => {
      m.getCanvas().style.cursor = "pointer";
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (f?.properties) resaltar(String(f.properties.clave));
    };

    const alSalir = () => {
      m.getCanvas().style.cursor = "";
      resaltar(seleccion ? String(seleccion.clave) : null);
    };

    const alHacerClic = (e: MapLayerMouseEvent) => {
      if (ajustandoUbicacion) return;
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (!f?.properties) return;
      setSeleccion(f.properties as PropiedadesColonia);
      setReferencia(f.properties as PropiedadesColonia);
      setUbicacion(null);
      solicitudUbicacion.current++;
      setUbicando(false);
      resaltar(String(f.properties.clave));
    };

    resaltar(seleccion ? String(seleccion.clave) : null);
    m.on("mousemove", CAPA_RELLENO, alEntrar);
    m.on("mouseleave", CAPA_RELLENO, alSalir);
    m.on("click", CAPA_RELLENO, alHacerClic);

    return () => {
      m.off("mousemove", CAPA_RELLENO, alEntrar);
      m.off("mouseleave", CAPA_RELLENO, alSalir);
      m.off("click", CAPA_RELLENO, alHacerClic);
    };
  }, [listo, seleccion, ajustandoUbicacion]);

  // --- cambio de perfil --------------------------------------------------
  // Solo se reescriben las expresiones de pintado. Los datos ya están en el
  // navegador con todos los perfiles, así que cambiar de perfil no vuelve a
  // pedir nada a la red y se siente instantáneo.
  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo || !m.getLayer(CAPA_RELLENO)) return;
    m.setPaintProperty(CAPA_RELLENO, "fill-color", expresionColor(perfil));
    m.setPaintProperty(CAPA_RELLENO, "fill-opacity", expresionOpacidad(perfil));
  }, [perfil, listo, expresionColor, expresionOpacidad]);

  const indiceColonias = useMemo(() => colonias.map((colonia) => ({
    colonia, punto: puntoColonia(colonia),
    texto: normalizarBusqueda(`${colonia.properties.nombre} ${municipios.get(colonia.properties.municipio_clave) ?? ""}`),
  })), [colonias, municipios]);
  const resultados = useMemo(() => {
    const q = normalizarBusqueda(busqueda);
    return q.length < 2 ? [] : indiceColonias.filter((c) => c.texto.includes(q)).slice(0, 8);
  }, [busqueda, indiceColonias]);

  // Etiquetas locales: no dependen de un servicio externo de fuentes.
  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo || !nombres) return;
    let etiquetas: Marker[] = [];
    const actualizar = () => {
      etiquetas.forEach((e) => e.remove());
      etiquetas = [];
      if (m.getZoom() < 10.8) return;
      const ocupados: { x: number; y: number; ancho: number }[] = [];
      const candidatas = indiceColonias.filter((c) => m.getBounds().contains(c.punto))
        .sort((a, b) => Number(b.colonia.properties.area_km2) - Number(a.colonia.properties.area_km2));
      for (const c of candidatas) {
        const pixel = m.project(c.punto);
        const ancho = Math.min(180, c.colonia.properties.nombre.length * 6 + 12);
        if (ocupados.some((o) => Math.abs(o.x - pixel.x) < (ancho + o.ancho) / 2 + 12 && Math.abs(o.y - pixel.y) < 38)) continue;
        ocupados.push({ x: pixel.x, y: pixel.y, ancho });
        const elemento = document.createElement("span");
        elemento.className = "colonia-label";
        elemento.textContent = c.colonia.properties.nombre;
        etiquetas.push(new Marker({ element: elemento }).setLngLat(c.punto).addTo(m));
        if (etiquetas.length >= 45) break;
      }
    };
    actualizar();
    m.on("moveend", actualizar);
    m.on("resize", actualizar);
    return () => { m.off("moveend", actualizar); m.off("resize", actualizar); etiquetas.forEach((e) => e.remove()); };
  }, [listo, nombres, indiceColonias]);

  function verColonia(clave: string, comoReferencia = false) {
    const colonia = colonias.find((c) => c.properties.clave === clave);
    if (!colonia) return;
    setSeleccion(colonia.properties);
    if (comoReferencia) { setReferencia(colonia.properties); setUbicacion(null); solicitudUbicacion.current++; setUbicando(false); setAjustandoUbicacion(false); }
    setBusqueda("");
    setPanelAbierto(false);
    const movil = window.innerWidth < 1024;
    mapa.current?.fitBounds(limitesColonia(colonia), {
      padding: movil ? { top: 75, left: 35, right: 35, bottom: Math.min(window.innerHeight * 0.38, 300) } : { top: 90, left: 395, right: 365, bottom: 80 },
      maxZoom: 14, duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 700,
    });
  }

  const fijarPunto = useCallback((punto: Coordenadas, precision: number | null = null) => {
    const [[oeste, sur], [este, norte]] = VISTA_INICIAL.limites;
    if (punto[0] < oeste || punto[0] > este || punto[1] < sur || punto[1] > norte) {
      setErrorUbicacion("Ese punto está fuera de la cobertura de la ZMG. Elige un punto de destino en el mapa.");
      return false;
    }
    setUbicacion(punto);
    setPrecisionUbicacion(precision);
    setReferencia(null);
    setSeleccion(null);
    setErrorUbicacion(null);
    return true;
  }, []);

  // Un marcador ajustable conserva las coordenadas elegidas, no el centro de la colonia.
  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo || !ubicacion) return;
    const marker = new Marker({ color: "#0f766e", draggable: true }).setLngLat(ubicacion).addTo(m);
    ubicacionMarker.current = marker;
    const elemento = marker.getElement();
    elemento.setAttribute("aria-label", "Punto de referencia. Arrastra o usa las flechas para ajustarlo.");
    elemento.setAttribute("title", "Arrastra para corregir tu ubicación");
    elemento.tabIndex = 0;
    const mover = (punto: Coordenadas) => {
      solicitudUbicacion.current++;
      setUbicando(false);
      if (!fijarPunto(punto)) { marker.setLngLat(ubicacion); return; }
      setAjustandoUbicacion(false);
      setVista("asesor");
      setPanelAbierto(true);
    };
    marker.on("dragend", () => { const punto = marker.getLngLat(); mover([punto.lng, punto.lat]); });
    const teclado = (event: KeyboardEvent) => {
      const pasos: Record<string, Coordenadas> = { ArrowLeft: [-0.0001, 0], ArrowRight: [0.0001, 0], ArrowUp: [0, 0.0001], ArrowDown: [0, -0.0001] };
      const paso = pasos[event.key];
      if (!paso) return;
      event.preventDefault();
      event.stopPropagation();
      mover([ubicacion[0] + paso[0], ubicacion[1] + paso[1]]);
      // El siguiente marcador se crea al actualizar el estado.
      requestAnimationFrame(() => ubicacionMarker.current?.getElement().focus());
    };
    elemento.addEventListener("keydown", teclado);
    return () => { elemento.removeEventListener("keydown", teclado); marker.remove(); ubicacionMarker.current = null; };
  }, [ubicacion, listo, fijarPunto]);

  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo || !ajustandoUbicacion) return;
    const elegir = (event: { lngLat: { lng: number; lat: number } }) => {
      if (!fijarPunto([event.lngLat.lng, event.lngLat.lat])) return;
      setAjustandoUbicacion(false);
      setVista("asesor");
      setPanelAbierto(true);
    };
    m.on("click", elegir);
    return () => { m.off("click", elegir); };
  }, [ajustandoUbicacion, listo, fijarPunto]);

  function ajustarUbicacion() {
    solicitudUbicacion.current++;
    setUbicando(false);
    setAjustandoUbicacion(true);
    setPanelAbierto(false);
    setErrorUbicacion(null);
  }

  function localizar() {
    setErrorUbicacion(null);
    setAjustandoUbicacion(false);
    if (!navigator.geolocation) { setErrorUbicacion("Tu navegador no permite obtener la ubicación. Elige un punto en el mapa."); return; }
    const solicitud = ++solicitudUbicacion.current;
    setUbicando(true);
    navigator.geolocation.getCurrentPosition((pos) => {
      if (solicitud !== solicitudUbicacion.current) return;
      const punto: Coordenadas = [pos.coords.longitude, pos.coords.latitude];
      setUbicando(false);
      if (!fijarPunto(punto, pos.coords.accuracy)) return;
      if (pos.coords.accuracy > 100) setErrorUbicacion(`La ubicación tiene una precisión aproximada de ±${Math.ceil(pos.coords.accuracy)} m. Puedes corregirla con «Elegir punto» o arrastrando el marcador.`);
      const movil = window.innerWidth < 1024;
      mapa.current?.flyTo({ center: punto, zoom: pos.coords.accuracy <= 100 ? 15 : 13,
        offset: movil ? [0, 0] : [175, 0],
        duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 700,
      });
    }, (err) => {
      if (solicitud !== solicitudUbicacion.current) return;
      setUbicando(false);
      setErrorUbicacion(err.code === 1 ? "No se autorizó la ubicación. Puedes elegir un punto en el mapa." : "No pudimos obtener una ubicación nueva. Intenta otra vez o elige un punto en el mapa.");
    }, { timeout: 20000, maximumAge: 0, enableHighAccuracy: true });
  }

  function abrirAsesor(nuevoObjetivo: Objetivo) {
    setObjetivo(nuevoObjetivo);
    setPerfilActivo(nuevoObjetivo === "estacionamiento" ? "vehicular" : nuevoObjetivo === "renta" ? "residencial" : "peaton");
    setVista("asesor");
    setPanelAbierto(true);
  }

  // --- datos de la colonia seleccionada ---------------------------------
  const detalle = useMemo(() => {
    if (!seleccion) return null;
    const estrato = seleccion[perfil.campo_estrato];
    return {
      nombre: String(seleccion.nombre ?? "Sin nombre"),
      municipio: municipios.get(String(seleccion.municipio_clave)) ?? "—",
      poblacion: seleccion.poblacion as number | null,
      areaKm2: seleccion.area_km2 as number,
      incidentes: seleccion[perfil.campo_incidentes] as number,
      tasa: seleccion[perfil.campo_tasa] as number | null,
      indice: seleccion[perfil.campo_indice] as number | null,
      percentil: seleccion[perfil.campo_percentil] as number | null,
      estrato: esEstrato(estrato) ? estrato : null,
      muestraBaja: Boolean(seleccion[perfil.campo_muestra_baja]),
    };
  }, [seleccion, perfil, municipios]);

  return (
    <div className="map-app">
      <header className="app-header">
        <div className="brand"><span className="brand-mark"><Logo className="brand-logo" /></span><div><h1>Safe<span>Spots</span></h1><p>Conoce la zona. Planea tu estancia.</p></div></div>
        <div className="search-container">
          <label htmlFor="buscar-colonia" className="sr-only">Buscar colonia o municipio</label>
          <span className="search-icon" aria-hidden>⌕</span>
          <input id="buscar-colonia" type="search" autoComplete="off" placeholder={listo ? "Buscar colonia o municipio…" : "Cargando colonias…"} disabled={!listo} value={busqueda} onChange={(e) => setBusqueda(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setBusqueda(""); }} aria-controls={busqueda.length >= 2 ? "resultados-colonias" : undefined} />
          {busqueda.trim().length >= 2 && <div id="resultados-colonias" className="search-results" aria-label="Resultados de colonias">
            {resultados.map(({ colonia }) => <button key={colonia.properties.clave} onClick={() => verColonia(colonia.properties.clave, true)}><strong>{colonia.properties.nombre}</strong><span>{municipios.get(colonia.properties.municipio_clave)}</span></button>)}
            {resultados.length === 0 && <p role="status">No encontramos esa colonia. Prueba otro nombre.</p>}
          </div>}
        </div>
        <div className="header-coverage"><span className="status-dot" />{numero(meta.unidad_analisis.total)} colonias<span className="block pl-3 text-[11px] text-slate-400">Guadalajara y su zona metropolitana</span></div>
      </header>
      <div className="history-strip"><span aria-hidden>◷</span> Historial {meta.periodo.inicio.slice(0, 4)}–{meta.periodo.fin.slice(0, 4)} · No representa la seguridad actual.</div>
      <div className={`map-stage ${ajustandoUbicacion ? "choosing-location" : ""}`}>
      <div ref={contenedor} className="h-full w-full" aria-label="Mapa de incidencia histórica por colonia" />
      <div className="map-quick-actions">
        <button onClick={() => abrirAsesor("estacionamiento")} aria-pressed={perfilActivo === "vehicular"}>Dejar mi auto</button>
        <button onClick={() => abrirAsesor("turismo")}>Dónde alojarme ↗</button>
        <button onClick={localizar} disabled={ubicando}>{ubicando ? "Ubicando…" : "Mi ubicación ◎"}</button>
        <button onClick={ajustarUbicacion} aria-pressed={ajustandoUbicacion}>Elegir punto ⌖</button>
      </div>
      {ajustandoUbicacion && <div className="choose-location-notice" role="status"><p>Toca el mapa en tu ubicación o destino. También puedes arrastrar el marcador.</p><button onClick={() => { setAjustandoUbicacion(false); setPanelAbierto(true); }}>Cancelar</button></div>}
      <div className={`map-legend ${panelAbierto ? "panel-visible" : ""}`} aria-label="Leyenda del riesgo histórico">
        <strong>{perfil.clave === "vehicular" ? "Auto · historial vehicular" : perfil.nombre + " · historial"}</strong>
        <div>{ORDEN_ESTRATOS.map((e) => <span key={e}><i style={{ backgroundColor: COLOR_ESTRATO[e] }} />{ETIQUETA_ESTRATO[e]}</span>)}</div>
        <small>Translúcido: muestra insuficiente · gris: sin clasificación</small>
      </div>
      <aside id="panel-mapa" aria-label={vista === "asesor" ? "Asistente de colonias" : "Perfiles y leyenda"} className={`control-panel ${panelAbierto ? "is-open" : ""}`}>
        <div className="panel-tabs">
          <button aria-pressed={vista === "explorar"} onClick={() => setVista("explorar")}>Explorar mapa</button>
          <button aria-pressed={vista === "asesor"} onClick={() => setVista("asesor")}>Asistente IA <span>✦</span></button>
        </div>
        <div className="panel-content">
        <div hidden={vista !== "asesor"}>
          <AsesorColonia objetivo={objetivo} onObjetivo={abrirAsesor} referencia={referencia ? { clave: referencia.clave, nombre: `${referencia.nombre}, ${municipios.get(referencia.municipio_clave) ?? ""}` } : null} ubicacion={ubicacion} precisionUbicacion={precisionUbicacion} onUbicacion={localizar} onAjustarUbicacion={ajustarUbicacion} ubicando={ubicando} onVerColonia={verColonia} />
        </div>
        <div hidden={vista !== "explorar"} className="explore-content">
        <header>
          <div className="section-eyebrow">EXPLORA CON CONTEXTO</div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">Cada colonia, una historia</h2>
          <p className="mt-1 text-sm leading-relaxed text-slate-500">Elige qué quieres consultar y toca una zona para conocer sus datos.</p>
        </header>
        <div className="intent-grid">
          <button onClick={() => abrirAsesor("turismo")}><span aria-hidden>⌂</span>De turismo<span className="intent-caption">Dónde alojarte</span></button>
          <button onClick={() => abrirAsesor("renta")}><span aria-hidden>⌑</span>Buscar renta<span className="intent-caption">Tu próxima colonia</span></button>
        </div>
        {/* La limitación más importante del proyecto, no escondida en una nota
            al pie: los datos terminan en febrero de 2021. */}
        <div className="rounded-md border border-amber-300 bg-amber-50 p-2.5">
          <p className="text-xs leading-relaxed text-amber-900">
            <strong className="font-semibold">Datos históricos.</strong>{" "}
            {meta.advertencia_principal}
          </p>
        </div>

        <section>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-500">
            Perfil de riesgo
          </h2>
          <div className="profile-options">
            {meta.perfiles.map((p) => (
              <button
                key={p.clave}
                onClick={() => setPerfilActivo(p.clave)}
                aria-pressed={p.clave === perfilActivo}
                className={`rounded-md px-2.5 py-2 text-left text-sm transition-colors ${
                  p.clave === perfilActivo
                    ? "bg-stone-900 text-white"
                    : "text-stone-700 hover:bg-stone-100"
                }`}
              >
                <span className="font-medium">{p.clave === "vehicular" ? "Auto y estacionamiento" : p.nombre}</span>
                <span
                  className={`block text-xs ${
                    p.clave === perfilActivo ? "text-stone-300" : "text-stone-500"
                  }`}
                >
                  {p.unidad_tasa}
                </span>
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-stone-600">
            {perfil.descripcion}
          </p>
          {perfil.advertencia && (
            <p className="mt-2 rounded border border-stone-300 bg-stone-50 p-2 text-xs leading-relaxed text-stone-700">
              {perfil.advertencia}
            </p>
          )}
        </section>

        <section>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-500">
            Estrato de riesgo
          </h2>
          <ul className="flex flex-col gap-1">
            {ORDEN_ESTRATOS.map((e) => (
              <li key={e} className="flex items-center gap-2 text-xs text-stone-700">
                <span
                  className="h-3.5 w-6 shrink-0 rounded-sm ring-1 ring-black/10"
                  style={{ backgroundColor: COLOR_ESTRATO[e] }}
                />
                <span className="font-medium">{ETIQUETA_ESTRATO[e]}</span>
                <span className="ml-auto tabular-nums text-stone-500">
                  {numero(perfil.resumen_estratos[e] ?? 0)}
                </span>
              </li>
            ))}
            <li className="mt-1 flex items-center gap-2 text-xs text-stone-600">
              <span className="h-3.5 w-6 shrink-0 rounded-sm bg-stone-400 opacity-30 ring-1 ring-black/10" />
              <span>Translúcido: muestra insuficiente</span>
            </li>
          </ul>
        </section>

        <label className="flex min-h-11 items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={nombres} onChange={(e) => setNombres(e.target.checked)} className="h-4 w-4 accent-teal-700" /> Nombres de colonias al acercar</label>
        <section className="mt-auto border-t border-stone-200 pt-3">
          <button
            onClick={() => setMetodologiaAbierta((v) => !v)}
            aria-expanded={metodologiaAbierta}
            className="flex w-full items-center justify-between text-xs font-semibold uppercase tracking-wide text-stone-500 hover:text-stone-800"
          >
            Metodología y fuentes
            <span aria-hidden>{metodologiaAbierta ? "−" : "+"}</span>
          </button>

          {metodologiaAbierta && (
            <div className="mt-2 flex flex-col gap-2 text-xs leading-relaxed text-stone-600">
              <p>
                <strong className="text-stone-800">Periodo analizado:</strong>{" "}
                {meta.periodo.etiqueta}
              </p>
              <p>{meta.metodologia.descripcion}</p>
              <p>
                <strong className="text-stone-800">Cobertura:</strong> se ubicó en
                una colonia el{" "}
                {decimal(meta.cobertura_empate.porcentaje_ubicado)}% de los{" "}
                {numero(meta.cobertura_empate.incidentes_totales)} incidentes
                registrados. La fuente reporta{" "}
                {numero(meta.cobertura_empate.incidentes_sin_colonia_en_fuente)} sin
                colonia, y{" "}
                {numero(meta.cobertura_empate.incidentes_sin_poligono)} corresponden
                a nombres que no existen en el padrón de polígonos.
              </p>
              <p>{meta.metodologia.umbral_muestra_baja.nota}</p>
              <ul className="flex flex-col gap-1">
                {meta.fuentes.slice(0, 4).map((f) => (
                  <li key={f.clave}>
                    <a
                      href={f.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-stone-700 underline decoration-stone-300 hover:decoration-stone-700"
                    >
                      {f.institucion}
                    </a>{" "}
                    — {f.nombre}
                  </li>
                ))}
              </ul>
              <p className="text-stone-400">
                Método v{meta.metodo_version} · generado{" "}
                {new Date(meta.generado_en).toLocaleDateString("es-MX")}
              </p>
            </div>
          )}
        </section>
        </div>
        </div>
      </aside>

      {/* Ficha de la colonia seleccionada */}
      {detalle && (
        <section aria-label="Detalle de la colonia" className={`colony-detail ${panelAbierto ? "mobile-hidden" : ""}`}>
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold leading-tight text-stone-900">
                {detalle.nombre}
              </h3>
              <p className="text-xs text-stone-500">{detalle.municipio}</p>
            </div>
            <button
              onClick={() => setSeleccion(null)}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100"
              aria-label="Cerrar ficha"
            >
              ✕
            </button>
          </div>

          {detalle.estrato && (
            <div className="mt-2.5 flex items-center gap-2">
              <span
                className="rounded px-2 py-0.5 text-xs font-semibold"
                style={{ backgroundColor: COLOR_ESTRATO[detalle.estrato], color: TEXTO_SOBRE_ESTRATO[detalle.estrato] }}
              >
                Histórico: {ETIQUETA_ESTRATO[detalle.estrato].toLowerCase()}
              </span>
              <span className="text-xs text-stone-500">
                índice {decimal(detalle.indice)} / 100
              </span>
            </div>
          )}

          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
            <div>
              <dt className="text-stone-500">Incidentes históricos</dt>
              <dd className="font-medium tabular-nums text-stone-900">
                {numero(detalle.incidentes)}
              </dd>
            </div>
            <div>
              <dt className="text-stone-500">{perfil.unidad_tasa}</dt>
              <dd className="font-medium tabular-nums text-stone-900">
                {decimal(detalle.tasa)}
              </dd>
            </div>
            <div>
              <dt className="text-stone-500">Población 2020</dt>
              <dd className="font-medium tabular-nums text-stone-900">
                {numero(detalle.poblacion)}
              </dd>
            </div>
            <div>
              <dt className="text-stone-500">Superficie</dt>
              <dd className="font-medium tabular-nums text-stone-900">
                {decimal(detalle.areaKm2)} km²
              </dd>
            </div>
          </dl>

          {perfilActivo === "vehicular" && <div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">
            <strong className="block text-slate-900">Antes de dejar tu auto</strong>
            {detalle.muestraBaja || !detalle.estrato ? "La información es insuficiente para valorar esta colonia." : detalle.estrato === "alto" || detalle.estrato === "critico" ? "Esta colonia registró incidencia vehicular elevada. Prioriza un estacionamiento con acceso controlado y verifica sus condiciones actuales." : "Una incidencia histórica menor no garantiza que sea seguro estacionarse en la calle. Verifica iluminación, vigilancia y acceso controlado."}
            <p className="mt-1">Incluye robos de vehículos, autopartes y objetos del interior; también otros hechos del perfil vehicular.</p>
          </div>}
          {detalle.percentil !== null && (
            <p className="mt-2.5 text-xs text-stone-600">
              Más incidencia que el {decimal(detalle.percentil)}% de las colonias
              de la zona metropolitana.
            </p>
          )}

          {detalle.muestraBaja && (
            <p className="mt-2.5 rounded border border-stone-300 bg-stone-50 p-2 text-xs leading-relaxed text-stone-700">
              Muestra insuficiente: con{" "}
              {numero(detalle.incidentes)} incidentes y esta superficie o
              población, la cifra de esta colonia no es concluyente por sí sola.
            </p>
          )}
          <button onClick={() => { if (seleccion) { setReferencia(seleccion); setUbicacion(null); } abrirAsesor(perfilActivo === "vehicular" ? "estacionamiento" : "turismo"); }} className="primary-button mt-3 w-full">{perfilActivo === "vehicular" ? "Consultar dónde dejar mi auto" : "Buscar alojamiento cerca"} ↗</button>
          <p className="mt-2 text-[10px] text-slate-500">Periodo: {meta.periodo.etiqueta}. No garantiza seguridad actual.</p>
        </section>
      )}

      <nav className="mobile-nav" aria-label="Navegación del mapa">
        <button aria-pressed={!panelAbierto} onClick={() => setPanelAbierto(false)}>◎<span>Mapa</span></button>
        <button aria-expanded={panelAbierto && vista === "explorar"} aria-controls="panel-mapa" onClick={() => { setVista("explorar"); setPanelAbierto(true); }}>☷<span>Perfiles</span></button>
        <button aria-expanded={panelAbierto && vista === "asesor"} aria-controls="panel-mapa" onClick={() => { setVista("asesor"); setPanelAbierto(true); }}>✦<span>Asistente</span></button>
      </nav>
      {errorUbicacion && <div role="alert" className="location-error"><p>{errorUbicacion}</p><button onClick={() => setErrorUbicacion(null)} aria-label="Cerrar aviso de ubicación">✕</button></div>}
      {!seleccion && !panelAbierto && listo && <div className="map-hint">Toca una colonia para explorar su historial</div>}

      {/* Estados de carga y error */}
      {!listo && !error && (
        <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center">
          <p className="rounded-md bg-white/90 px-4 py-2 text-sm text-stone-700 shadow-md">
            Cargando {numero(meta.unidad_analisis.total)} colonias…
          </p>
        </div>
      )}

      {error && (
        <div className="absolute inset-x-3 top-3 z-30 rounded-md border border-red-300 bg-red-50 p-3 md:left-auto md:right-3 md:w-96">
          <p className="text-sm font-medium text-red-900">
            No se pudo cargar el mapa
          </p>
          <p className="mt-1 text-xs text-red-800">{error}</p>
          <p className="mt-1 text-xs text-red-700">
            Si estás en desarrollo, corre el ETL:{" "}
            <code className="rounded bg-red-100 px-1">
              python -m georisk.cli construir
            </code>
          </p>
        </div>
      )}
      </div>
    </div>
  );
}
