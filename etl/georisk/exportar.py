"""Exportación de la capa de riesgo para el frontend.

Se genera UN GeoJSON con la geometría de las colonias y el índice de TODOS
los perfiles como propiedades, más un `meta.json` con la procedencia y las
limitaciones de los datos.

Por qué un archivo estático y no una consulta a la base en cada visita:

  * 2,186 colonias simplificadas pesan pocos megabytes. Cabe de sobra en el
    hosting gratuito de Vercel y se sirve desde CDN.
  * Neon suspende el cómputo tras cinco minutos de inactividad. Una visita
    esporádica —justo el patrón de un proyecto académico— pagaría el arranque
    en frío en cada carga del mapa.
  * Cambiar de perfil en la interfaz no vuelve a pedir datos: ya vienen todos.

PostGIS sigue siendo el sistema de registro y el motor de análisis. Este
archivo es el resultado publicado, no la fuente de verdad.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import CRS_ALMACEN, CRS_METRICO, METODO_VERSION
from .fuentes import FUENTES
from .riesgo import CORTES_ESTRATO, MIN_INCIDENTES, MIN_POBLACION, Ventana
from .taxonomia import DELITOS, PERFILES

# Tolerancia de simplificación en metros. A 15 m el contorno de una colonia
# se ve idéntico a escala de ciudad y el archivo baja de tamaño de forma
# notable. Subirlo más empieza a despegar polígonos vecinos.
TOLERANCIA_SIMPLIFICACION_M = 15.0

# Decimales de coordenada. 5 decimales ≈ 1 metro, de sobra para este mapa y
# la mitad de bytes que los 15 decimales que escribe GDAL por omisión.
PRECISION_COORDENADAS = 5


def _propiedades_por_perfil(riesgos: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aplana los resultados de varios perfiles en una fila por colonia."""
    tabla: pd.DataFrame | None = None

    for perfil, df in riesgos.items():
        origen = [
            "clave", "indice", "estrato", "incidentes", "percentil",
            "tasa_100k", "densidad_km2", "muestra_baja",
        ]
        columnas = df[[c for c in origen if c in df.columns]].copy()
        columnas = columnas.rename(
            columns={
                "indice": f"idx_{perfil}",
                "estrato": f"est_{perfil}",
                "incidentes": f"inc_{perfil}",
                "percentil": f"pct_{perfil}",
                # Se exportan las dos tasas crudas para que la ficha de la
                # colonia pueda mostrar la que corresponde al perfil y el
                # usuario vea de dónde sale el color.
                "tasa_100k": f"tasa_{perfil}",
                "densidad_km2": f"dens_{perfil}",
                "muestra_baja": f"baja_{perfil}",
            }
        )
        # Redondear antes de serializar: nadie necesita 12 decimales en un
        # índice 0-100 y cada decimal extra son bytes en el archivo.
        for col in columnas.columns:
            if col.startswith(("idx_", "tasa_", "pct_", "dens_")):
                columnas[col] = columnas[col].round(1)

        tabla = columnas if tabla is None else tabla.merge(columnas, on="clave", how="outer")

    assert tabla is not None, "No se recibió ningún perfil"
    return tabla


def exportar_geojson(
    colonias: gpd.GeoDataFrame,
    riesgos: dict[str, pd.DataFrame],
    destino: Path,
    simplificar: bool = True,
) -> Path:
    """Escribe el GeoJSON de colonias con el riesgo de todos los perfiles."""
    destino.parent.mkdir(parents=True, exist_ok=True)

    gdf = colonias[
        ["clave", "nombre", "municipio_clave", "poblacion", "area_m2", "geometry"]
    ].copy()

    if simplificar:
        antes = gdf.geometry.to_wkb().str.len().sum()
        # Simplificar en metros, no en grados: la tolerancia tiene que
        # significar algo físico.
        gdf["geometry"] = (
            gdf.geometry.to_crs(epsg=CRS_METRICO)
            .simplify(TOLERANCIA_SIMPLIFICACION_M, preserve_topology=True)
            .to_crs(epsg=CRS_ALMACEN)
        )
        despues = gdf.geometry.to_wkb().str.len().sum()
        print(
            f"    geometría simplificada: {antes / 1e6:.1f} MB -> "
            f"{despues / 1e6:.1f} MB de WKB"
        )

    props = _propiedades_por_perfil(riesgos)
    gdf = gdf.merge(props, on="clave", how="left")

    gdf["poblacion"] = pd.to_numeric(gdf["poblacion"], errors="coerce").astype("Int64")
    gdf["area_km2"] = (gdf["area_m2"] / 1e6).round(4)
    gdf = gdf.drop(columns=["area_m2"])

    if destino.exists():
        destino.unlink()

    gdf.to_file(
        destino,
        driver="GeoJSON",
        engine="pyogrio",
        # RFC7946 fuerza WGS84 y orden de anillos correcto; sin esto algunos
        # visores dibujan los huecos al revés.
        RFC7946="YES",
        COORDINATE_PRECISION=PRECISION_COORDENADAS,
    )

    tam = destino.stat().st_size
    print(f"    escrito {destino} ({tam / 1e6:.2f} MB)")
    return destino


def exportar_meta(
    destino: Path,
    ventana: Ventana,
    riesgos: dict[str, pd.DataFrame],
    reporte_empate,
    municipios: dict[str, str],
) -> Path:
    """Escribe el metadato que la interfaz usa para rotular y advertir.

    Todo lo que limita la interpretación del mapa viaja aquí: periodo de los
    datos, cobertura del empate de colonias, y la advertencia de cada perfil.
    Si el frontend tuviera que codificar esto a mano, quedaría desactualizado
    en la primera corrida del ETL.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)

    cobertura = {
        "incidentes_totales": reporte_empate.incidentes_totales,
        "incidentes_ubicados": reporte_empate.incidentes_ubicados,
        "porcentaje_ubicado": round(reporte_empate.cobertura, 2),
        "incidentes_sin_colonia_en_fuente": reporte_empate.incidentes_sin_colonia,
        "incidentes_sin_poligono": reporte_empate.incidentes_sin_empate,
        "nombres_unicos": reporte_empate.nombres_unicos,
        "nombres_empatados": reporte_empate.nombres_empatados,
        "metodos_de_empate": reporte_empate.por_metodo,
        # Las 30 colonias sin polígono con más incidentes: es la lista de
        # trabajo pendiente y también evidencia de transparencia.
        "principales_sin_poligono": [
            {"municipio": m, "colonia": c, "incidentes": n}
            for m, c, n in reporte_empate.sin_empate[:30]
        ],
    }

    meta = {
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metodo_version": METODO_VERSION,
        "periodo": {
            "inicio": ventana.inicio_iso,
            "fin": ventana.fin_iso,
            "meses": ventana.meses,
            "etiqueta": str(ventana),
        },
        # Advertencia que la interfaz debe mostrar de forma visible. Es la
        # limitación más importante del proyecto y no debe quedar sepultada.
        "advertencia_principal": (
            "Los datos de incidencia delictiva por colonia terminan en febrero "
            "de 2021, porque el IIEG descontinuó esa publicación. El mapa "
            "describe un patrón histórico, no la situación actual."
        ),
        "municipios": [
            {"clave": clave, "nombre": nombre} for clave, nombre in sorted(municipios.items())
        ],
        "unidad_analisis": {
            "tipo": "colonia",
            "total": int(len(next(iter(riesgos.values())))),
            "fuente_poligonos": FUENTES["iieg_colonias_2024"].nombre,
        },
        "perfiles": [
            {
                "clave": p.clave,
                "nombre": p.nombre,
                "descripcion": p.descripcion,
                "advertencia": p.advertencia,
                "orden": p.orden,
                # El denominador con el que se normalizó. La interfaz lo
                # necesita para rotular la cifra correcta y para explicar por
                # qué dos perfiles ordenan las colonias distinto.
                "normalizacion": p.normalizacion,
                "unidad_tasa": p.unidad_tasa,
                "campo_indice": f"idx_{p.clave}",
                "campo_estrato": f"est_{p.clave}",
                "campo_incidentes": f"inc_{p.clave}",
                "campo_tasa": (
                    f"dens_{p.clave}" if p.normalizacion == "area" else f"tasa_{p.clave}"
                ),
                "campo_muestra_baja": f"baja_{p.clave}",
                "campo_percentil": f"pct_{p.clave}",
                "delitos": sorted(c for c, d in DELITOS.items() if p.incluye(d)),
                "resumen_estratos": (
                    riesgos[p.clave]["estrato"].value_counts().to_dict()
                    if p.clave in riesgos
                    else {}
                ),
            }
            for p in sorted(PERFILES.values(), key=lambda x: x.orden)
            if p.clave in riesgos
        ],
        "estratos": [
            {"clave": nombre, "percentil_hasta": min(corte, 100.0)}
            for corte, nombre in CORTES_ESTRATO
        ],
        "metodologia": {
            "descripcion": (
                "Conteos por colonia ponderados por severidad del delito, "
                "convertidos a tasa anual por 100 mil habitantes, suavizados "
                "con contracción bayesiana hacia la media metropolitana, "
                "comprimidos logarítmicamente y escalados a 0-100."
            ),
            "umbral_muestra_baja": {
                "poblacion_minima": MIN_POBLACION,
                "incidentes_minimos": MIN_INCIDENTES,
                "nota": (
                    "Las colonias por debajo de estos umbrales se marcan porque "
                    "su tasa no es interpretable individualmente."
                ),
            },
            "pesos_severidad": {c: d.peso_severidad for c, d in sorted(DELITOS.items())},
        },
        "cobertura_empate": cobertura,
        "fuentes": [
            {
                "clave": f.clave,
                "nombre": f.nombre,
                "institucion": f.institucion,
                "url": f.url,
                "cadencia": f.cadencia,
                "notas": f.notas,
            }
            for f in FUENTES.values()
        ],
    }

    destino.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"    escrito {destino} ({destino.stat().st_size / 1e3:.1f} KB)")
    return destino
