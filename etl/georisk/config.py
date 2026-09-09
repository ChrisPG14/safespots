"""Configuración central del ETL.

Todo lo que dependa del entorno (rutas, credenciales) o del alcance del
proyecto (qué municipios, qué CRS) vive aquí. La regla es simple: si un valor
aparece en dos módulos, pertenece a este archivo.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
# config.py está en etl/georisk/, así que la raíz del repo son dos niveles
# arriba de la carpeta del paquete.
PAQUETE_DIR = Path(__file__).resolve().parent
ETL_DIR = PAQUETE_DIR.parent
RAIZ_DIR = ETL_DIR.parent

load_dotenv(RAIZ_DIR / ".env")

DATA_DIR = Path(os.getenv("GEORISK_DATA_DIR", RAIZ_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"          # descargas tal cual, nunca se editan
INTERIM_DIR = DATA_DIR / "interim"  # descomprimidos y transformaciones intermedias
PROCESSED_DIR = DATA_DIR / "processed"

for _d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://geo:geo@localhost:5433/georisk",
)

# ---------------------------------------------------------------------------
# Sistemas de referencia de coordenadas
# ---------------------------------------------------------------------------
# Almacenamiento: WGS84. Es lo que consumen GeoJSON y MapLibre sin
# reproyectar, y evita sorpresas al servir teselas.
CRS_ALMACEN = 4326

# Cálculos métricos (distancias, áreas, eps de DBSCAN): UTM zona 13N, que es
# la que cubre Guadalajara (~103.3° W). Hacer DBSCAN sobre grados es un error
# clásico: un grado de longitud y uno de latitud no miden lo mismo, así que
# los clusters saldrían deformados en dirección este-oeste.
CRS_METRICO = 32613

# El Marco Geoestadístico del INEGI NO viene en WGS84 sino en la proyección
# cónica conforme de Lambert para México (MEXICO_ITRF_2008_LCC).
# Ignorar esto coloca toda la ZMG en medio del océano.
CRS_INEGI_MG = 6372

# Los shapefiles de colonias del IIEG vienen ya en UTM 13N.
CRS_IIEG_COLONIAS = 32613

# ---------------------------------------------------------------------------
# Alcance geográfico: Área Metropolitana de Guadalajara
# ---------------------------------------------------------------------------
CVE_ENTIDAD_JALISCO = "14"

# Los 6 municipios de la conurbación central. El MVP arranca aquí porque
# concentran la mancha urbana continua y la mayoría de la población.
MUNICIPIOS_NUCLEO: dict[str, str] = {
    "14039": "Guadalajara",
    "14120": "Zapopan",
    "14098": "San Pedro Tlaquepaque",
    "14101": "Tonalá",
    "14097": "Tlajomulco de Zúñiga",
    "14070": "El Salto",
}

# Los 4 restantes del AMG oficial, mayormente rurales.
MUNICIPIOS_PERIFERIA: dict[str, str] = {
    "14051": "Juanacatlán",
    "14044": "Ixtlahuacán de los Membrillos",
    "14124": "Zapotlanejo",
    "14002": "Acatlán de Juárez",
}

MUNICIPIOS_AMG: dict[str, str] = {**MUNICIPIOS_NUCLEO, **MUNICIPIOS_PERIFERIA}


def claves_municipios(solo_nucleo: bool = True) -> list[str]:
    """Claves CVEGEO de municipio dentro del alcance."""
    return sorted(MUNICIPIOS_NUCLEO if solo_nucleo else MUNICIPIOS_AMG)


def claves_municipio_cortas(solo_nucleo: bool = True) -> list[str]:
    """Las mismas claves pero solo la parte de municipio (3 dígitos).

    Los shapefiles del INEGI traen CVE_ENT y CVE_MUN por separado, así que
    para filtrar hace falta la clave corta.
    """
    return sorted(c[2:] for c in claves_municipios(solo_nucleo))


# ---------------------------------------------------------------------------
# Versionado del método de cálculo
# ---------------------------------------------------------------------------
# Cambiar esto cuando se modifique la fórmula del índice de riesgo. Queda
# guardado en cada fila de riesgo_unidad para poder reproducir resultados y
# comparar versiones del modelo.
METODO_VERSION = "0.1.0"
