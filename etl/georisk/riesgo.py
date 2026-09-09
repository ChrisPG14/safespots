"""Cálculo del índice de riesgo por colonia.

Método, en orden:

  1. Filtrar los delitos que corresponden al perfil.
  2. Ponderar cada delito por su severidad y sumar.
  3. Convertir a tasa anualizada por 100 mil habitantes.
  4. Suavizar la tasa con contracción bayesiana hacia la media metropolitana.
  5. Comprimir con logaritmo y escalar a 0-100.
  6. Asignar estrato por cuantiles.

Los pasos 4 y 5 son los que evitan los dos errores clásicos de un mapa de
riesgo:

  * Sin el paso 4, una colonia con 80 habitantes y 3 robos sale con una tasa
    de 3,750 por 100 mil y pinta de rojo intenso, cuando en realidad no hay
    evidencia suficiente para afirmar nada de ella. La contracción jala esas
    estimaciones hacia el promedio de la ciudad en proporción a lo poco que
    sabemos, que es lo que hacen los atlas de mortalidad y los índices de
    incidencia serios.

  * Sin el paso 5, la distribución de tasas —muy sesgada a la derecha— hace
    que el 95% de las colonias se vean iguales y solo dos o tres destaquen.
    El logaritmo reparte el color donde está la variación real.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import METODO_VERSION
from .taxonomia import DELITOS, PERFILES, PESOS

# Población de referencia para la contracción bayesiana. Una colonia con
# exactamente esta población recibe 50% de peso propio y 50% del promedio
# metropolitano. Se fija a la mediana observada, no a un número arbitrario.
_POBLACION_REFERENCIA: int | None = None

# Cortes de estrato por percentil. La mitad menos incidente es "bajo"; el
# decil superior es "crítico". Cortes por cuantil y no absolutos, para que el
# mapa siga siendo informativo si la incidencia general sube o baja.
CORTES_ESTRATO: tuple[tuple[float, str], ...] = (
    (50.0, "bajo"),
    (75.0, "moderado"),
    (90.0, "alto"),
    (100.1, "critico"),
)

# Debajo de estos umbrales la estimación no es interpretable individualmente.
# No se oculta la colonia: se marca, y la interfaz lo indica.
#
# Calibrados contra la serie completa (62 meses), donde el promedio ronda los
# 140 incidentes por colonia. Con una ventana de solo 12 meses estos umbrales
# marcarían a la mayoría de las colonias, lo que vuelve inútil la señal: por
# eso el ETL usa por omisión toda la serie disponible.
MIN_POBLACION = 300
MIN_INCIDENTES = 20

# Superficie mínima para que una tasa por km² sea creíble. Hay 37 colonias
# por debajo de una hectárea en el padrón; dividir entre un área así
# convierte cualquier puñado de delitos en una densidad estratosférica.
MIN_AREA_KM2 = 0.02

# z para intervalos de confianza al 95%.
_Z95 = 1.959963985


@dataclass(frozen=True)
class Ventana:
    """Rango de meses sobre el que se calcula el índice."""

    anio_inicio: int
    mes_inicio: int
    anio_fin: int
    mes_fin: int

    @property
    def meses(self) -> int:
        return (
            (self.anio_fin - self.anio_inicio) * 12
            + (self.mes_fin - self.mes_inicio)
            + 1
        )

    @property
    def inicio_iso(self) -> str:
        return f"{self.anio_inicio:04d}-{self.mes_inicio:02d}-01"

    @property
    def fin_iso(self) -> str:
        # Último día del mes final
        fin = pd.Timestamp(year=self.anio_fin, month=self.mes_fin, day=1)
        return (fin + pd.offsets.MonthEnd(0)).date().isoformat()

    def contiene(self, anio: pd.Series, mes: pd.Series) -> pd.Series:
        serie = anio * 12 + mes
        desde = self.anio_inicio * 12 + self.mes_inicio
        hasta = self.anio_fin * 12 + self.mes_fin
        return (serie >= desde) & (serie <= hasta)

    def __str__(self) -> str:
        return (
            f"{self.anio_inicio}-{self.mes_inicio:02d} a "
            f"{self.anio_fin}-{self.mes_fin:02d} ({self.meses} meses)"
        )


def _desde_serial(serial: int) -> tuple[int, int]:
    return (serial - 1) // 12, (serial - 1) % 12 + 1


def ventana_ultimos_meses(incidencia: pd.DataFrame, meses: int | None = None) -> Ventana:
    """Ventana de los últimos N meses con datos, o toda la serie si `meses` es None.

    Se ancla al último mes de la FUENTE, no a la fecha de hoy: la serie del
    IIEG termina en febrero de 2021 y usar la fecha actual daría una ventana
    vacía y un mapa en blanco.
    """
    serie = incidencia["anio"] * 12 + incidencia["mes"]
    fin = int(serie.max())
    inicio = int(serie.min()) if not meses else max(int(serie.min()), fin - meses + 1)

    anio_inicio, mes_inicio = _desde_serial(inicio)
    anio_fin, mes_fin = _desde_serial(fin)
    return Ventana(anio_inicio, mes_inicio, anio_fin, mes_fin)


def _ic_poisson(conteo: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Intervalo de confianza al 95% para un conteo de Poisson (método de Byar).

    Se usa Byar en lugar de la aproximación normal porque con conteos chicos
    —que son la mayoría a nivel colonia— la normal produce límites inferiores
    negativos, que no tienen sentido para un conteo de delitos.
    """
    o = np.asarray(conteo, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        inferior = np.where(
            o > 0,
            o * (1 - 1 / (9 * o) - _Z95 / (3 * np.sqrt(np.maximum(o, 1e-9)))) ** 3,
            0.0,
        )
        superior = (o + 1) * (
            1 + 1 / (9 * (o + 1)) + _Z95 / (3 * np.sqrt(o + 1))
        ) ** 3
    return np.maximum(inferior, 0.0), superior


def _estrato_por_percentil(percentil: pd.Series) -> pd.Series:
    """Asigna estrato recorriendo los cortes de menor a mayor percentil."""
    resultado = pd.Series("critico", index=percentil.index, dtype="object")
    anterior = -np.inf
    for corte, nombre in CORTES_ESTRATO:
        resultado = resultado.mask(
            (percentil > anterior) & (percentil <= corte), nombre
        )
        anterior = corte
    return resultado


def calcular_riesgo(
    incidencia: pd.DataFrame,
    unidades: pd.DataFrame,
    perfil: str,
    ventana: Ventana,
    calidad_dato: str = "colonia_historico",
) -> pd.DataFrame:
    """Índice de riesgo de cada unidad para un perfil y una ventana.

    `incidencia` necesita: clave, delito_clave, anio, mes, conteo.
    `unidades` necesita: clave, nombre, municipio_clave, poblacion, area_m2.

    El denominador lo decide el perfil (`normalizacion`): población residente
    o superficie. Ver la nota en taxonomia.Perfil sobre por qué esto importa.
    """
    if perfil not in PERFILES:
        raise KeyError(f"Perfil desconocido: {perfil!r}. Opciones: {sorted(PERFILES)}")

    p = PERFILES[perfil]
    claves_perfil = {c for c, d in DELITOS.items() if p.incluye(d)}

    datos = incidencia[
        incidencia["delito_clave"].isin(claves_perfil)
        & ventana.contiene(incidencia["anio"], incidencia["mes"])
    ].copy()

    datos["peso"] = datos["delito_clave"].map(PESOS).fillna(1.0)
    datos["ponderado"] = datos["conteo"] * datos["peso"]

    agregado = datos.groupby("clave", as_index=False).agg(
        incidentes=("conteo", "sum"),
        incidentes_ponderados=("ponderado", "sum"),
    )

    # Left join: las unidades sin ningún incidente en la ventana deben
    # aparecer con cero, no desaparecer del mapa. Un hueco en blanco se lee
    # como "sin información" cuando en realidad significa "sin incidencia".
    base = unidades.merge(agregado, on="clave", how="left")
    base["incidentes"] = base["incidentes"].fillna(0).astype(int)
    base["incidentes_ponderados"] = base["incidentes_ponderados"].fillna(0.0)

    poblacion = pd.to_numeric(base["poblacion"], errors="coerce")
    area_km2 = pd.to_numeric(base["area_m2"], errors="coerce") / 1e6
    base["area_km2"] = area_km2.round(4)
    factor_anual = 12.0 / ventana.meses

    # --- tasas crudas, siempre las dos y sin ponderar ----------------------
    # Se reportan ambas independientemente del perfil, con conteos SIN
    # ponderar por severidad, para que sean interpretables por una persona:
    # "412 robos por 100 mil habitantes al año" se entiende; una tasa
    # multiplicada por pesos de severidad no significa nada para nadie.
    with np.errstate(divide="ignore", invalid="ignore"):
        base["tasa_100k"] = np.where(
            poblacion.to_numpy() > 0,
            base["incidentes"].to_numpy() / poblacion.to_numpy() * 100_000 * factor_anual,
            np.nan,
        )
        base["densidad_km2"] = np.where(
            area_km2.to_numpy() > 0,
            base["incidentes"].to_numpy() / area_km2.to_numpy() * factor_anual,
            np.nan,
        )

    # --- exposición según el perfil ----------------------------------------
    if p.normalizacion == "area":
        exposicion = area_km2
        escala_tasa = 1.0            # delitos por km² al año
    elif p.normalizacion == "poblacion":
        exposicion = poblacion.astype("Float64")
        escala_tasa = 100_000.0      # delitos por 100 mil habitantes al año
    else:
        raise ValueError(
            f"Normalización no reconocida en el perfil {perfil!r}: "
            f"{p.normalizacion!r}. Usa 'poblacion' o 'area'."
        )

    exp_valida = exposicion.where(exposicion > 0)
    base["exposicion"] = exp_valida

    # Medida ponderada por severidad sobre la exposición del perfil. Esta es
    # la que alimenta el índice; las tasas crudas de arriba son para mostrar.
    with np.errstate(divide="ignore", invalid="ignore"):
        medida = np.where(
            exp_valida.notna().to_numpy(),
            base["incidentes_ponderados"].to_numpy()
            / exp_valida.fillna(1).to_numpy()
            * escala_tasa
            * factor_anual,
            np.nan,
        )
    base["medida"] = medida

    # --- contracción bayesiana --------------------------------------------
    # La referencia metropolitana se calcula sobre los TOTALES, no como
    # promedio de las medidas por colonia: promediar tasas da el mismo peso a
    # una colonia de 80 habitantes que a una de 20 mil y sesga la referencia.
    total_ponderado = base.loc[exp_valida.notna(), "incidentes_ponderados"].sum()
    total_exposicion = float(exp_valida.sum() or 0.0)
    medida_global = (
        total_ponderado / total_exposicion * escala_tasa * factor_anual
        if total_exposicion
        else 0.0
    )

    # Exposición de referencia: la mediana observada. Una colonia con
    # exactamente esa exposición recibe 50% de peso propio y 50% del promedio
    # metropolitano; una diez veces más grande recibe ~91% de peso propio.
    exp_ref = _POBLACION_REFERENCIA or float(exp_valida.median() or 1.0)
    peso_propio = exp_valida / (exp_valida + exp_ref)

    base["medida_suavizada"] = (
        peso_propio * pd.Series(medida, index=base.index).fillna(medida_global)
        + (1 - peso_propio) * medida_global
    )
    # Sin exposición conocida no se puede afirmar nada propio: se queda en la
    # referencia global, que es la postura más honesta.
    base["medida_suavizada"] = base["medida_suavizada"].fillna(medida_global)

    # --- intervalo de confianza sobre la tasa cruda del perfil ------------
    ic_bajo, ic_alto = _ic_poisson(base["incidentes"].to_numpy())
    with np.errstate(divide="ignore", invalid="ignore"):
        factor_ic = np.where(
            exp_valida.notna().to_numpy(),
            escala_tasa * factor_anual / exp_valida.fillna(1).to_numpy(),
            np.nan,
        )
    base["ic_inferior"] = ic_bajo * factor_ic
    base["ic_superior"] = ic_alto * factor_ic

    # Se marca —no se oculta— la unidad cuya estimación no es interpretable
    # por sí sola. El criterio depende del denominador: una colonia diminuta
    # es problema para una tasa por km², no para una per cápita.
    muestra_baja = exp_valida.isna() | (base["incidentes"] < MIN_INCIDENTES)
    if p.normalizacion == "area":
        muestra_baja = muestra_baja | (area_km2.fillna(0) < MIN_AREA_KM2)
    else:
        muestra_baja = muestra_baja | (poblacion.fillna(0) < MIN_POBLACION)
    base["muestra_baja"] = muestra_baja

    # --- índice 0-100 ------------------------------------------------------
    # El logaritmo es indispensable: la distribución de tasas delictivas es
    # muy sesgada a la derecha y sin comprimirla el 95% de las colonias se
    # vería del mismo color mientras dos o tres acaparan toda la escala.
    log_medida = np.log1p(base["medida_suavizada"].clip(lower=0))
    lo, hi = float(log_medida.min()), float(log_medida.max())
    if hi > lo:
        base["indice"] = (100.0 * (log_medida - lo) / (hi - lo)).round(2)
    else:
        # Caso degenerado: todas iguales. Mejor 0 que dividir entre cero.
        base["indice"] = 0.0

    base["percentil"] = (base["medida_suavizada"].rank(pct=True) * 100.0).round(2)
    base["estrato"] = _estrato_por_percentil(base["percentil"])

    base["perfil"] = perfil
    base["normalizacion"] = p.normalizacion
    base["unidad_tasa"] = p.unidad_tasa
    base["periodo_inicio"] = ventana.inicio_iso
    base["periodo_fin"] = ventana.fin_iso
    base["calidad_dato"] = calidad_dato
    base["metodo"] = f"ponderada_{p.normalizacion}_suavizada_log"
    base["metodo_version"] = METODO_VERSION

    columnas = [
        "clave", "nombre", "municipio_clave", "perfil",
        "periodo_inicio", "periodo_fin",
        "incidentes", "incidentes_ponderados",
        "poblacion", "area_km2", "exposicion", "normalizacion", "unidad_tasa",
        "tasa_100k", "densidad_km2", "medida", "medida_suavizada",
        "indice", "percentil", "estrato",
        "ic_inferior", "ic_superior", "muestra_baja",
        "calidad_dato", "metodo", "metodo_version",
    ]
    return base[[c for c in columnas if c in base.columns]].copy()


def resumen(riesgo: pd.DataFrame) -> str:
    """Resumen legible para la salida del ETL."""
    conteo = riesgo["estrato"].value_counts()
    partes = [
        f"{e}={int(conteo.get(e, 0))}"
        for e in ("bajo", "moderado", "alto", "critico")
    ]
    baja = int(riesgo["muestra_baja"].sum())
    return (
        f"{len(riesgo)} unidades | " + "  ".join(partes)
        + f" | muestra baja: {baja} ({100 * baja / max(len(riesgo), 1):.0f}%)"
    )


def top_riesgo(riesgo: pd.DataFrame, n: int = 10, excluir_muestra_baja: bool = True) -> pd.DataFrame:
    """Las n unidades de mayor índice, útil para validar a ojo el resultado.

    Vale la pena revisar esta salida en cada cambio del método: si aparecen
    colonias que uno no reconocería como zonas de alta incidencia, casi
    siempre es el denominador el que está mal, no los datos.
    """
    d = riesgo
    if excluir_muestra_baja:
        d = d[~d["muestra_baja"]]
    columnas = [
        "nombre", "municipio_clave", "incidentes", "poblacion", "area_km2",
        "tasa_100k", "densidad_km2", "indice", "estrato",
    ]
    return d.nlargest(n, "indice")[[c for c in columnas if c in d.columns]].round(1)
