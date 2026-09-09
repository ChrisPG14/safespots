"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AttributionControl,
  // Se importa con alias: `Map` a secas taparía el Map de JavaScript, que
  // este componente usa para el índice de municipios.
  MapLibreMap,
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
} from "@/lib/riesgo";
import type { Meta, Perfil, PropiedadesColonia } from "@/lib/tipos";

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
  const claveResaltada = useRef<string | null>(null);

  const [listo, setListo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [perfilActivo, setPerfilActivo] = useState(meta.perfiles[0].clave);
  const [seleccion, setSeleccion] = useState<PropiedadesColonia | null>(null);
  const [panelAbierto, setPanelAbierto] = useState(false);
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

    m.on("load", async () => {
      try {
        const resp = await fetch(URL_GEOJSON);
        if (!resp.ok) {
          throw new Error(`El servidor respondió ${resp.status} al pedir la capa de riesgo`);
        }
        const geojson = await resp.json();

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
      observador.disconnect();
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
      if (!seleccion) resaltar(null);
    };

    const alHacerClic = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (!f?.properties) return;
      setSeleccion(f.properties as PropiedadesColonia);
      resaltar(String(f.properties.clave));
    };

    m.on("mousemove", CAPA_RELLENO, alEntrar);
    m.on("mouseleave", CAPA_RELLENO, alSalir);
    m.on("click", CAPA_RELLENO, alHacerClic);

    return () => {
      m.off("mousemove", CAPA_RELLENO, alEntrar);
      m.off("mouseleave", CAPA_RELLENO, alSalir);
      m.off("click", CAPA_RELLENO, alHacerClic);
    };
  }, [listo, seleccion]);

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
    <div className="relative h-full w-full">
      {/*
        La altura se da con h-full y NO con `absolute inset-0`.
        Razón: MapLibre le agrega a este div la clase `maplibregl-map`, cuya
        hoja de estilos declara `position: relative`. Esa regla vence al
        utilitario `absolute` de Tailwind, el div se queda sin caja, y
        MapLibre acaba dibujando un lienzo de 300 px de alto sobre un
        contenedor de altura cero: el mapa no aparece y nada falla de forma
        visible. Con `h-full` la altura no depende del posicionamiento.
      */}
      <div ref={contenedor} className="h-full w-full" />

      {/* Panel de control */}
      <button
        onClick={() => setPanelAbierto((v) => !v)}
        className="absolute left-3 top-3 z-20 rounded-md bg-white px-3 py-2 text-sm font-medium shadow-md ring-1 ring-black/10 md:hidden"
        aria-expanded={panelAbierto}
      >
        {panelAbierto ? "Cerrar" : "Capas y leyenda"}
      </button>

      <aside
        className={`absolute z-10 flex flex-col gap-4 overflow-y-auto bg-white/95 p-4 shadow-xl ring-1 ring-black/10 backdrop-blur
          ${panelAbierto ? "inset-x-3 bottom-3 top-16 rounded-lg" : "hidden"}
          md:left-3 md:top-3 md:bottom-3 md:right-auto md:block md:w-80 md:rounded-lg`}
      >
        <header>
          <h1 className="text-base font-semibold leading-tight text-stone-900">
            Riesgo delictivo por colonia
          </h1>
          <p className="mt-0.5 text-xs text-stone-500">
            Zona Metropolitana de Guadalajara · {numero(meta.unidad_analisis.total)}{" "}
            colonias
          </p>
        </header>

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
          <div className="flex flex-col gap-1">
            {meta.perfiles.map((p) => (
              <button
                key={p.clave}
                onClick={() => setPerfilActivo(p.clave)}
                className={`rounded-md px-2.5 py-2 text-left text-sm transition-colors ${
                  p.clave === perfilActivo
                    ? "bg-stone-900 text-white"
                    : "text-stone-700 hover:bg-stone-100"
                }`}
              >
                <span className="font-medium">{p.nombre}</span>
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

        <section className="mt-auto border-t border-stone-200 pt-3">
          <button
            onClick={() => setMetodologiaAbierta((v) => !v)}
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
      </aside>

      {/* Ficha de la colonia seleccionada */}
      {detalle && (
        <div className="absolute bottom-3 left-3 right-3 z-20 rounded-lg bg-white/95 p-4 shadow-xl ring-1 ring-black/10 backdrop-blur md:left-auto md:right-3 md:w-80">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold leading-tight text-stone-900">
                {detalle.nombre}
              </h3>
              <p className="text-xs text-stone-500">{detalle.municipio}</p>
            </div>
            <button
              onClick={() => setSeleccion(null)}
              className="-mr-1 -mt-1 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
              aria-label="Cerrar ficha"
            >
              ✕
            </button>
          </div>

          {detalle.estrato && (
            <div className="mt-2.5 flex items-center gap-2">
              <span
                className="rounded px-2 py-0.5 text-xs font-semibold"
                style={{ backgroundColor: COLOR_ESTRATO[detalle.estrato] }}
              >
                Riesgo {ETIQUETA_ESTRATO[detalle.estrato].toLowerCase()}
              </span>
              <span className="text-xs text-stone-500">
                índice {decimal(detalle.indice)} / 100
              </span>
            </div>
          )}

          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
            <div>
              <dt className="text-stone-500">Incidentes</dt>
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
        </div>
      )}

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
  );
}
