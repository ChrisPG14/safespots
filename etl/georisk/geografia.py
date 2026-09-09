"""Carga de unidades geográficas: colonias del IIEG y municipios del INEGI."""

from __future__ import annotations

import hashlib

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import (
    CRS_ALMACEN,
    CRS_METRICO,
    MUNICIPIOS_AMG,
    MUNICIPIOS_NUCLEO,
)
from .fuentes import COLONIAS_IIEG, MARCO_GEOESTADISTICO, buscar_capa, descomprimir

# Nombre de la capa de colonias dentro del ZIP del IIEG.
_CAPA_COLONIAS = "ISDC2020_2024"


def _reparar_y_normalizar(
    gdf: gpd.GeoDataFrame, crs_origen: int | None = None
) -> gpd.GeoDataFrame:
    """Deja la geometría lista para PostGIS: válida, en 4326 y MultiPolygon.

    Los tres pasos resuelven problemas reales:

    * Los shapefiles oficiales traen autointersecciones. `make_valid` las
      corrige; sin eso, PostGIS acepta el polígono pero las operaciones
      topológicas fallan o dan resultados absurdos.
    * El CRS declarado a veces falta o es incorrecto en el .prj, así que se
      puede forzar el de origen.
    * La columna de la base es `geometry(MultiPolygon, 4326)`. Mezclar
      Polygon y MultiPolygon rompe la inserción, y el IIEG trae las dos cosas.
    """
    if crs_origen is not None and gdf.crs is None:
        gdf = gdf.set_crs(epsg=crs_origen, allow_override=True)

    invalidas = (~gdf.geometry.is_valid).sum()
    if invalidas:
        print(f"    reparando {invalidas} geometría(s) inválida(s)")
        gdf["geometry"] = gdf.geometry.make_valid()

    vacias = gdf.geometry.is_empty | gdf.geometry.isna()
    if vacias.any():
        print(f"    descartando {vacias.sum()} geometría(s) vacía(s)")
        gdf = gdf.loc[~vacias].copy()

    # El área se calcula en el CRS métrico, no en grados. Calcularla en 4326
    # devuelve "grados cuadrados", que no significan nada.
    gdf["area_m2"] = gdf.geometry.to_crs(epsg=CRS_METRICO).area

    if gdf.crs is None or gdf.crs.to_epsg() != CRS_ALMACEN:
        gdf = gdf.to_crs(epsg=CRS_ALMACEN)

    # Homogeneizar a MultiPolygon
    from shapely.geometry import MultiPolygon

    gdf["geometry"] = [
        g if g.geom_type == "MultiPolygon" else MultiPolygon([g])
        for g in gdf.geometry
    ]

    return gdf


def cargar_colonias(solo_nucleo: bool = True) -> gpd.GeoDataFrame:
    """Polígonos de colonia del IIEG, con población del Censo 2020.

    Es la unidad de análisis principal del proyecto: el INEGI no publica
    colonias y esta es la única fuente que las tiene con geometría y datos
    censales ya agregados.
    """
    carpeta = descomprimir(COLONIAS_IIEG)
    ruta = buscar_capa(carpeta, _CAPA_COLONIAS)

    print(f"    leyendo {ruta.name}")
    gdf = gpd.read_file(ruta)

    # GEOCOL empieza con la clave de municipio de 3 dígitos.
    gdf["mun_corta"] = gdf["GEOCOL"].astype(str).str.zfill(6).str[:3]
    gdf["municipio_clave"] = "14" + gdf["mun_corta"]

    objetivo = MUNICIPIOS_NUCLEO if solo_nucleo else MUNICIPIOS_AMG
    antes = len(gdf)
    gdf = gdf[gdf["municipio_clave"].isin(objetivo)].copy()
    print(f"    {len(gdf)} colonias en el alcance (de {antes} en Jalisco)")

    gdf = _reparar_y_normalizar(gdf, crs_origen=None)

    # POBTOT viene como float con nulos; la base espera entero o nulo.
    poblacion = pd.to_numeric(gdf.get("POBTOT"), errors="coerce")

    salida = gpd.GeoDataFrame(
        {
            "tipo": "colonia",
            # La clave incluye la entidad para que sea única a nivel nacional
            # y no choque si algún día se agregan otros estados.
            "clave": "14" + gdf["GEOCOL"].astype(str).str.zfill(6),
            "nombre": gdf["NOMCOL1"].astype(str).str.strip(),
            "municipio_clave": gdf["municipio_clave"],
            "poblacion": poblacion.round().astype("Int64"),
            "area_m2": gdf["area_m2"],
            "fuente": COLONIAS_IIEG.clave,
            "fuente_version": "SHAPEColonias20202024",
            "tipo_asentamiento": gdf.get("Tipo"),
            "codigo_postal": gdf.get("CP"),
            "geocol": gdf["GEOCOL"].astype(str),
            "geometry": gdf.geometry,
        },
        crs=gdf.crs,
    )

    sin_pob = salida["poblacion"].isna().sum()
    cero_pob = (salida["poblacion"] == 0).sum()
    if sin_pob or cero_pob:
        # Importa porque son las colonias donde la tasa por 100 mil no se
        # puede calcular: parques, zonas industriales, predios sin censar.
        print(
            f"    aviso: {sin_pob} colonia(s) sin población y {cero_pob} con "
            f"población 0 (no admiten tasa per cápita)"
        )

    return salida


def unificar_por_nombre(colonias: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fusiona en una sola unidad los polígonos que son la misma colonia.

    El padrón del IIEG parte varias colonias en pedazos con el mismo nombre:
    Guadalajara tiene dos polígonos "Oblatos" (de 9,087 y 26,844 habitantes),
    Tonalá tiene cuatro llamados "Tonalá" y Tlaquepaque cinco "San Juan".
    Son 109 grupos ambiguos que abarcan 242 de los 2,186 polígonos.

    Esto NO es un detalle cosmético. La incidencia delictiva reporta un único
    total para "Oblatos", así que si no se fusionan hay que elegir a cuál
    pedazo asignarle todos los delitos, y cualquier elección es arbitraria:
    mandarlos al polígono de 9,087 habitantes cuando en realidad corresponden
    a los 35,931 de ambos infla su tasa casi cuatro veces. La unidad de
    análisis correcta es la colonia completa.

    Los polígonos sin nombre utilizable ("SIN NOMBRE", cadenas vacías) se
    conservan individuales: están dispersos por el municipio y unirlos
    produciría una geometría sin sentido. Simplemente nunca reciben empate.
    """
    from .nombres import normalizar

    gdf = colonias.copy()
    gdf["_norm"] = gdf["nombre"].map(normalizar)

    # Un nombre es utilizable si normaliza a algo y no es un marcador de
    # ausencia. Sin este filtro, los nueve "SIN NOMBRE" de Zapopan se
    # fusionarían en un solo polígono imposible.
    sin_nombre = gdf["_norm"].isin({"", "SIN NOMBRE", "SN NOMBRE", "NO ESPECIFICADO"})

    gdf["_grupo"] = np.where(
        sin_nombre,
        # Clave propia para cada uno: no se fusionan con nadie.
        "solo:" + gdf["clave"].astype(str),
        gdf["municipio_clave"].astype(str) + ":" + gdf["_norm"],
    )

    tamanos = gdf.groupby("_grupo").size()
    ambiguos = int((tamanos > 1).sum())
    if ambiguos:
        print(
            f"    fusionando {ambiguos} grupo(s) de polígonos homónimos "
            f"({int(tamanos[tamanos > 1].sum())} polígonos -> {ambiguos} unidades)"
        )

    agregados = gdf.dissolve(
        by="_grupo",
        aggfunc={
            "poblacion": "sum",
            "area_m2": "sum",
            # Del resto se conserva el primer valor: son iguales dentro del
            # grupo (municipio) o intercambiables (tipo de asentamiento, CP).
            "nombre": "first",
            "municipio_clave": "first",
            "tipo": "first",
            "fuente": "first",
            "fuente_version": "first",
        },
        as_index=False,
    )

    # La clave de la unidad fusionada se deriva del grupo, no del polígono,
    # para que sea estable entre corridas del ETL. Si dependiera del primer
    # polígono del archivo, un reordenamiento del shapefile cambiaría las
    # claves y rompería cualquier dato histórico ligado a ellas.
    agregados["clave"] = agregados["_grupo"].map(_clave_estable)
    agregados = agregados.drop(columns=["_grupo"])

    # `dissolve` con sum convierte los nulos en 0. Para la población eso es
    # una mentira: 0 habitantes significa algo distinto a "no se sabe".
    poblacion_conocida = (
        gdf.loc[~gdf["poblacion"].isna()]
        .groupby("_grupo")
        .size()
        .rename("con_dato")
    )
    esperado = gdf.groupby("_grupo").size().rename("total")
    cobertura = pd.concat([poblacion_conocida, esperado], axis=1).fillna(0)
    sin_ningun_dato = set(cobertura.index[cobertura["con_dato"] == 0])
    if sin_ningun_dato:
        claves = {_clave_estable(g) for g in sin_ningun_dato}
        agregados.loc[agregados["clave"].isin(claves), "poblacion"] = pd.NA

    agregados["poblacion"] = agregados["poblacion"].astype("Int64")

    print(f"    {len(agregados)} unidades de análisis (de {len(gdf)} polígonos)")
    return agregados


def _clave_estable(grupo: str) -> str:
    """Clave corta, determinista y legible para una unidad fusionada.

    Se usa un hash del nombre normalizado en lugar del nombre completo para
    que la clave tenga longitud fija y no traiga acentos ni espacios, pero
    conservando el prefijo del municipio para poder leerla a simple vista.
    """
    if grupo.startswith("solo:"):
        return grupo[len("solo:"):]
    municipio, _, nombre = grupo.partition(":")
    huella = hashlib.sha1(nombre.encode("utf-8")).hexdigest()[:8]
    return f"{municipio}-{huella}"


def cargar_municipios(solo_nucleo: bool = True) -> gpd.GeoDataFrame:
    """Polígonos municipales del Marco Geoestadístico del INEGI.

    Sirven de contexto en el mapa y de unidad de respaldo para las fuentes que
    solo publican a nivel municipio, como el SESNSP.
    """
    carpeta = descomprimir(MARCO_GEOESTADISTICO)
    ruta = buscar_capa(carpeta, "14mun")

    print(f"    leyendo {ruta.name}")
    gdf = gpd.read_file(ruta)

    if "CVEGEO" not in gdf.columns:
        gdf["CVEGEO"] = gdf["CVE_ENT"].astype(str) + gdf["CVE_MUN"].astype(str)

    objetivo = MUNICIPIOS_NUCLEO if solo_nucleo else MUNICIPIOS_AMG
    gdf = gdf[gdf["CVEGEO"].isin(objetivo)].copy()
    print(f"    {len(gdf)} municipios en el alcance")

    # El Marco Geoestadístico viene en EPSG:6372, no en WGS84.
    gdf = _reparar_y_normalizar(gdf, crs_origen=None)

    # Verificar que el nombre del INEGI coincida con el catálogo del proyecto.
    # Una clave equivocada contamina todo el análisis en silencio, así que
    # vale la pena avisar fuerte.
    col_nombre = next(
        (c for c in ("NOMGEO", "NOM_MUN", "NOMBRE") if c in gdf.columns), None
    )
    if col_nombre:
        for cvegeo, nombre_inegi in zip(gdf["CVEGEO"], gdf[col_nombre]):
            esperado = objetivo.get(cvegeo)
            if esperado and esperado.lower() != str(nombre_inegi).strip().lower():
                print(
                    f"    AVISO: clave {cvegeo} el INEGI la llama "
                    f"'{nombre_inegi}' y el catálogo del proyecto "
                    f"'{esperado}'. Revisar config.MUNICIPIOS_*."
                )

    return gpd.GeoDataFrame(
        {
            "tipo": "municipio",
            "clave": gdf["CVEGEO"],
            "nombre": gdf[col_nombre] if col_nombre else gdf["CVEGEO"],
            "municipio_clave": gdf["CVEGEO"],
            "poblacion": pd.Series([pd.NA] * len(gdf), dtype="Int64"),
            "area_m2": gdf["area_m2"],
            "fuente": MARCO_GEOESTADISTICO.clave,
            "fuente_version": "MG2025",
            "geometry": gdf.geometry,
        },
        crs=gdf.crs,
    )
