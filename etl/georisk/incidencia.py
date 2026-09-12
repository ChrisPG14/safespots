"""Carga de la incidencia delictiva por colonia del IIEG.

Salida: una tabla ordenada de (colonia, delito canónico, año, mes, conteo),
más un reporte del empate de nombres para poder auditar qué se quedó fuera.

El reporte no es un extra: el 5% de incidentes que no empatan es un dato que
debe declararse en el reporte académico y mostrarse en la interfaz. Ocultarlo
haría que los totales del mapa no cuadren con los oficiales sin explicación.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import INTERIM_DIR, MUNICIPIOS_AMG, MUNICIPIOS_NUCLEO, RAW_DIR
from .fuentes import INCIDENCIA_COLONIAS
from .nombres import EmparejadorColonias, normalizar
from .taxonomia import ALIAS_IIEG

# Nombre del CSV dentro del ZIP del IIEG.
_CSV_ESPERADO = "delitos_colonia_paginaweb_feb21.csv"

# Nombre de mes -> número. Sirve para reparar un hueco real de la fuente: en
# 3,591 filas la columna `Número_mes` viene vacía mientras que `Mes` sí dice
# "Septiembre". Sin esta reparación esas filas desaparecen en el groupby sin
# dejar rastro, porque pandas descarta por omisión las filas cuya clave de
# agrupación es nula.
_MESES: dict[str, int] = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}


@dataclass
class ReporteEmpate:
    """Qué tan bien se pudieron ubicar los incidentes en un polígono."""

    incidentes_totales: int = 0
    incidentes_ubicados: int = 0
    incidentes_sin_colonia: int = 0   # la fuente dice "N.D."
    incidentes_sin_empate: int = 0    # tiene nombre pero no existe polígono
    incidentes_sin_periodo: int = 0   # no se pudo determinar el mes
    meses_recuperados: int = 0        # mes deducido del nombre del mes
    nombres_unicos: int = 0
    nombres_empatados: int = 0
    por_metodo: dict[str, int] = field(default_factory=dict)
    # Nombres que no se pudieron ubicar, con su peso. Es la lista de trabajo
    # pendiente, ordenada por impacto.
    sin_empate: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def cobertura(self) -> float:
        if not self.incidentes_totales:
            return 0.0
        return 100.0 * self.incidentes_ubicados / self.incidentes_totales

    def imprimir(self) -> None:
        print(f"    incidentes totales:     {self.incidentes_totales:>9,}")
        print(
            f"    ubicados en colonia:    {self.incidentes_ubicados:>9,}  "
            f"({self.cobertura:.1f}%)"
        )
        print(
            f"    sin colonia en fuente:  {self.incidentes_sin_colonia:>9,}  "
            f"({100 * self.incidentes_sin_colonia / max(self.incidentes_totales, 1):.1f}%)"
        )
        print(
            f"    nombre sin polígono:    {self.incidentes_sin_empate:>9,}  "
            f"({100 * self.incidentes_sin_empate / max(self.incidentes_totales, 1):.1f}%)"
        )
        if self.incidentes_sin_periodo:
            print(
                f"    sin periodo utilizable: {self.incidentes_sin_periodo:>9,}  "
                f"({100 * self.incidentes_sin_periodo / max(self.incidentes_totales, 1):.1f}%)"
            )
        if self.meses_recuperados:
            print(
                f"    mes recuperado:         {self.meses_recuperados:>9,}  "
                f"(deducido del nombre del mes)"
            )
        print(
            f"    nombres únicos:         {self.nombres_empatados:>9,} de "
            f"{self.nombres_unicos:,} empatados"
        )
        if self.por_metodo:
            detalle = "  ".join(f"{k}={v}" for k, v in sorted(self.por_metodo.items()))
            print(f"    método de empate:       {detalle}")


def _localizar_csv() -> Path:
    """Encuentra el CSV de incidencia, ya venga suelto o dentro del ZIP."""
    directo = RAW_DIR / _CSV_ESPERADO
    if directo.exists():
        return directo

    zip_path = RAW_DIR / INCIDENCIA_COLONIAS.archivo
    if zip_path.exists():
        destino = INTERIM_DIR / INCIDENCIA_COLONIAS.clave
        destino.mkdir(parents=True, exist_ok=True)
        candidato = destino / _CSV_ESPERADO
        if not candidato.exists():
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(destino)
        encontrados = sorted(destino.rglob("*.csv"))
        if encontrados:
            return encontrados[0]

    raise FileNotFoundError(
        f"No se encontró la incidencia por colonia.\n"
        f"  Se buscó: {directo}\n"
        f"            {zip_path}\n"
        f"  Corre: python -m georisk.cli descargar"
    )


def cargar_incidencia(
    colonias: gpd.GeoDataFrame,
    solo_nucleo: bool = True,
) -> tuple[pd.DataFrame, ReporteEmpate]:
    """Lee la incidencia del IIEG y la empata contra los polígonos de colonia.

    `colonias` debe traer las columnas `clave`, `nombre` y `municipio_clave`,
    tal como las devuelve `geografia.cargar_colonias`.
    """
    ruta = _localizar_csv()
    print(f"    leyendo {ruta.name}")

    df = pd.read_csv(ruta, dtype={"Clave_Mun": "Int64"})
    df.columns = [c.strip() for c in df.columns]

    columnas = {"Año", "Número_mes", "Clave_Mun", "Colonia", "Delito", "Cantidad"}
    faltantes = columnas - set(df.columns)
    if faltantes:
        raise ValueError(
            f"El CSV no trae las columnas esperadas. Faltan: {sorted(faltantes)}\n"
            f"Columnas encontradas: {list(df.columns)}"
        )

    objetivo = MUNICIPIOS_NUCLEO if solo_nucleo else MUNICIPIOS_AMG
    # El CSV trae la clave de municipio sin la entidad y sin ceros a la
    # izquierda (39 en lugar de 039), así que se reconstruye el CVEGEO.
    df["municipio_clave"] = "14" + df["Clave_Mun"].astype("string").str.zfill(3)

    antes = len(df)
    df = df[df["municipio_clave"].isin(objetivo)].copy()
    print(f"    {len(df):,} filas en el alcance (de {antes:,} en Jalisco)")

    df["Cantidad"] = pd.to_numeric(df["Cantidad"], errors="coerce").fillna(0).astype(int)

    reporte = ReporteEmpate()
    reporte.incidentes_totales = int(df["Cantidad"].sum())

    # --- periodo -----------------------------------------------------------
    # Reparar el mes antes de cualquier agrupación. La fuente deja vacío
    # `Número_mes` en varios miles de filas de septiembre pero conserva el
    # nombre del mes; se verificó que la correspondencia nombre -> número es
    # 1:1 en el resto del archivo, así que deducirlo es seguro.
    df["anio"] = pd.to_numeric(df["Año"], errors="coerce").astype("Int64")
    mes = pd.to_numeric(df["Número_mes"], errors="coerce").astype("Int64")

    falta_mes = mes.isna()
    if falta_mes.any():
        desde_nombre = (
            df.loc[falta_mes, "Mes"]
            .astype("string")
            .str.strip()
            .str.upper()
            .map(_MESES)
            .astype("Int64")
        )
        recuperadas = desde_nombre.notna()
        reporte.meses_recuperados = int(
            df.loc[falta_mes].loc[recuperadas, "Cantidad"].sum()
        )
        mes = mes.fillna(desde_nombre)
        if reporte.meses_recuperados:
            print(
                f"    recuperado el mes desde su nombre en "
                f"{int(recuperadas.sum()):,} fila(s) "
                f"({reporte.meses_recuperados:,} incidentes)"
            )
    df["mes"] = mes

    # Lo que siga sin periodo válido no se puede ubicar en el tiempo. Se
    # descarta de forma EXPLÍCITA y se contabiliza, en vez de dejar que el
    # groupby lo haga en silencio.
    sin_periodo = df["anio"].isna() | df["mes"].isna() | ~df["mes"].between(1, 12)
    if sin_periodo.any():
        reporte.incidentes_sin_periodo = int(df.loc[sin_periodo, "Cantidad"].sum())
        print(
            f"    AVISO: {int(sin_periodo.sum()):,} fila(s) sin periodo utilizable "
            f"({reporte.incidentes_sin_periodo:,} incidentes); se excluyen"
        )
        df = df.loc[~sin_periodo].copy()

    # --- delito canónico ---------------------------------------------------
    # Se normaliza a mayúsculas sin espacios extra antes de buscar, porque la
    # fuente mezcla capitalizaciones del mismo delito.
    etiqueta = df["Delito"].astype("string").str.strip().str.upper()
    df["delito_clave"] = etiqueta.map(ALIAS_IIEG)

    desconocidos = df.loc[df["delito_clave"].isna(), "Delito"].value_counts()
    if not desconocidos.empty:
        # No se adivina: van a 'otro' y se avisa, para que alguien decida.
        print("    AVISO: etiquetas de delito no mapeadas (se cuentan como 'otro'):")
        for nombre, n in desconocidos.items():
            print(f"      {nombre!r}: {n:,} filas")
        df["delito_clave"] = df["delito_clave"].fillna("otro")

    # --- empate de colonia -------------------------------------------------
    sin_colonia = df["Colonia"].map(lambda x: normalizar(x) == "")
    reporte.incidentes_sin_colonia = int(df.loc[sin_colonia, "Cantidad"].sum())
    con_nombre = df.loc[~sin_colonia].copy()

    print("    empatando nombres de colonia contra los polígonos")
    mapa_claves: dict[tuple[str, str], str] = {}
    metodos: dict[str, int] = {}

    for municipio_clave in sorted(objetivo):
        padron = {
            fila.clave: fila.nombre
            for fila in colonias[
                colonias["municipio_clave"] == municipio_clave
            ].itertuples()
        }
        if not padron:
            print(f"      aviso: sin polígonos para el municipio {municipio_clave}")
            continue

        emparejador = EmparejadorColonias(padron)
        del_municipio = con_nombre[con_nombre["municipio_clave"] == municipio_clave]

        for nombre in del_municipio["Colonia"].dropna().unique():
            empate = emparejador.empatar(nombre)
            metodos[empate.metodo] = metodos.get(empate.metodo, 0) + 1
            reporte.nombres_unicos += 1
            if empate.resuelto:
                reporte.nombres_empatados += 1
                mapa_claves[(municipio_clave, nombre)] = empate.clave_destino

    reporte.por_metodo = metodos

    con_nombre["clave"] = [
        mapa_claves.get((m, c))
        for m, c in zip(con_nombre["municipio_clave"], con_nombre["Colonia"])
    ]

    sin_empate = con_nombre["clave"].isna()
    reporte.incidentes_sin_empate = int(con_nombre.loc[sin_empate, "Cantidad"].sum())

    pendientes = (
        con_nombre.loc[sin_empate]
        .groupby(["municipio_clave", "Colonia"], dropna=False)["Cantidad"]
        .sum()
        .sort_values(ascending=False)
    )
    reporte.sin_empate = [
        (str(m), str(c), int(n)) for (m, c), n in pendientes.items()
    ]

    ubicados = con_nombre.loc[~sin_empate].copy()
    reporte.incidentes_ubicados = int(ubicados["Cantidad"].sum())

    # --- agregar -----------------------------------------------------------
    # El groupby es obligatorio, no una optimización: dos etiquetas distintas
    # de la fuente ("ROBO AUTOPARTES" y "ROBO DE AUTOPARTES") colapsan a la
    # misma clave canónica y hay que sumarlas, no dejarlas duplicadas.
    salida = (
        ubicados.groupby(
            ["clave", "municipio_clave", "delito_clave", "anio", "mes"],
            as_index=False,
            dropna=False,
        )["Cantidad"]
        .sum()
        .rename(columns={"Cantidad": "conteo"})
    )
    salida["anio"] = salida["anio"].astype(int)
    salida["mes"] = salida["mes"].astype(int)
    salida["fuente"] = INCIDENCIA_COLONIAS.clave

    # Cuadre obligatorio. Un groupby descarta en silencio las filas cuya clave
    # de agrupación sea nula, y así se perdieron 4,230 incidentes sin que nada
    # lo delatara: el reporte los daba por ubicados y en la base no estaban.
    # Esta comprobación convierte ese fallo mudo en un error ruidoso.
    agregado = int(salida["conteo"].sum())
    if agregado != reporte.incidentes_ubicados:
        raise RuntimeError(
            "Descuadre al agregar la incidencia: se ubicaron "
            f"{reporte.incidentes_ubicados:,} incidentes pero la tabla agregada "
            f"suma {agregado:,} (diferencia de "
            f"{reporte.incidentes_ubicados - agregado:,}).\n"
            "  Suele significar que alguna columna de agrupación trae nulos."
        )

    print(f"    {len(salida):,} filas agregadas (colonia-delito-año-mes)")
    return salida, reporte


def periodo_disponible(incidencia: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Primer y último mes con datos. Se usa para rotular el mapa."""
    fechas = pd.to_datetime(
        dict(year=incidencia["anio"], month=incidencia["mes"], day=1)
    )
    return fechas.min(), fechas.max()
