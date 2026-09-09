"""Catálogo de fuentes de datos y descarga con caché.

Todas las URLs de aquí fueron verificadas con petición real. Cuando una
fuente cambia de ubicación —pasa seguido en portales de gobierno— este es el
único archivo que hay que tocar.

La descarga guarda el SHA-256 de cada archivo. Sirve para dos cosas: detectar
que la fuente publicó una actualización, y poder afirmar en el reporte
académico exactamente qué archivo se usó.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import INTERIM_DIR, RAW_DIR


@dataclass(frozen=True)
class Fuente:
    """Una fuente de datos descargable."""

    clave: str
    nombre: str
    institucion: str
    url: str
    archivo: str
    descripcion: str
    # Cadencia con la que la institución publica. Determina cada cuánto vale
    # la pena volver a correr el ETL.
    cadencia: str = "desconocida"
    notas: str = ""
    # Sufijos de capas que nos interesan del ZIP, si aplica.
    capas: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Registro de fuentes
# ---------------------------------------------------------------------------

MARCO_GEOESTADISTICO = Fuente(
    clave="inegi_mg_2025",
    nombre="Marco Geoestadístico 2025 — Jalisco",
    institucion="INEGI",
    url=(
        "https://www.inegi.org.mx/contenidos/productos/prod_serv/contenidos/"
        "espanol/bvinegi/productos/geografia/marcogeo/794551163061/14_jalisco.zip"
    ),
    archivo="mg14.zip",
    descripcion=(
        "Polígonos oficiales de entidad, municipios, localidades, AGEB urbanas "
        "y rurales, y manzanas. Corte cartográfico julio 2025."
    ),
    cadencia="anual (~diciembre)",
    notas=(
        "OJO: viene en EPSG:6372 (MEXICO_ITRF_2008_LCC), no en WGS84. "
        "129 MB porque incluye manzanas y ejes de vialidad de todo Jalisco."
    ),
    capas=("14ent", "14mun", "14a", "14ar", "14l"),
)

CENSO_AGEB = Fuente(
    clave="inegi_censo_2020_ageb",
    nombre="Censo 2020 — resultados por AGEB y manzana urbana, Jalisco",
    institucion="INEGI",
    url=(
        "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/"
        "ageb_manzana/ageb_mza_urbana_14_cpv2020_csv.zip"
    ),
    archivo="ageb14.zip",
    descripcion=(
        "Población y características de vivienda a nivel AGEB y manzana. "
        "Es el denominador para calcular tasas por 100 mil habitantes."
    ),
    cadencia="decenal (próximo censo 2030)",
    notas=(
        "Filtrar NOM_LOC = 'Total AGEB urbana' para quedarse con el nivel AGEB. "
        "Los valores confidenciales vienen como '*' y hay que tratarlos como nulos."
    ),
)

COLONIAS_IIEG = Fuente(
    clave="iieg_colonias_2024",
    nombre="Colonias de Jalisco con información sociodemográfica",
    institucion="IIEG Jalisco",
    url="https://iieg.gob.mx/ns/wp-content/uploads/2024/11/SHAPEColonias20202024.zip",
    archivo="col.zip",
    descripcion=(
        "Polígonos de colonias con 232 campos censales ya agregados. "
        "Esta es la pieza que el INEGI no ofrece: el INEGI solo publica AGEBs "
        "y manzanas, nunca colonias."
    ),
    cadencia="irregular",
    notas=(
        "Viene en EPSG:32613. Llave GEOCOL. El marco de referencia es del INE "
        "2024, así que las colonias son las secciones del padrón electoral "
        "agrupadas, no una división administrativa municipal."
    ),
)


INCIDENCIA_COLONIAS = Fuente(
    clave="iieg_colonias_delitos",
    nombre="Incidencia delictiva por colonia — Jalisco 2016 a feb 2021",
    institucion="IIEG Jalisco (con datos de la Fiscalía del Estado)",
    url="https://iieg.gob.mx/ns/wp-content/uploads/2021/03/FEB2021.zip",
    archivo="incidencia_colonias_feb2021.zip",
    descripcion=(
        "241,702 registros de delito por colonia, municipio, año y mes, con 20 "
        "categorías de delito. Es la única fuente pública encontrada que baja "
        "de nivel municipal para la ZMG."
    ),
    cadencia="DESCONTINUADA",
    notas=(
        "LIMITACIÓN CENTRAL DEL PROYECTO: la serie termina en febrero de 2021. "
        "Se verificó que no existen entregas posteriores (DIC2021 a 2025 "
        "devuelven 404). Identifica la colonia por NOMBRE, no por clave, así "
        "que requiere el empate difuso de georisk.nombres. No incluye hora "
        "del hecho, por lo que NO permite análisis diurno vs nocturno."
    ),
)

# El SESNSP no tiene URL estable de descarga: publica los archivos en un
# SharePoint cuyo enlace cambia. Se documenta la fuente pero la descarga es
# manual. Además, en 2026 hubo ruptura metodológica: las series 2015-2025 y
# 2026+ son archivos distintos y no comparables entre sí.
SESNSP_MUNICIPAL = Fuente(
    clave="sesnsp_municipal",
    nombre="Incidencia delictiva del Fuero Común, nivel municipal",
    institucion="SESNSP",
    url="https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva",
    archivo="sesnsp_municipal.csv",
    descripcion=(
        "Conteos mensuales por municipio, tipo, subtipo y modalidad de delito. "
        "Formato ancho: una fila por municipio-delito-año con 12 columnas de meses."
    ),
    cadencia="mensual",
    notas=(
        "DESCARGA MANUAL: el enlace real vive en sharepoint y no es estable. "
        "NO contiene coordenadas ni colonia; es la razón por la que el "
        "clustering espacial de delitos no es viable con datos públicos. "
        "Se usa como capa de tendencia reciente, no de detalle geográfico."
    ),
)


FUENTES: dict[str, Fuente] = {
    f.clave: f
    for f in (
        MARCO_GEOESTADISTICO,
        CENSO_AGEB,
        COLONIAS_IIEG,
        INCIDENCIA_COLONIAS,
        SESNSP_MUNICIPAL,
    )
}


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

_MANIFIESTO = RAW_DIR / "manifiesto.json"


def _leer_manifiesto() -> dict:
    if _MANIFIESTO.exists():
        return json.loads(_MANIFIESTO.read_text(encoding="utf-8"))
    return {}


def _escribir_manifiesto(datos: dict) -> None:
    _MANIFIESTO.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def sha256_archivo(ruta: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        while chunk := fh.read(bloque):
            h.update(chunk)
    return h.hexdigest()


def descargar(fuente: Fuente, forzar: bool = False) -> Path:
    """Descarga una fuente a data/raw/ y registra su huella.

    Si el archivo ya existe no lo vuelve a bajar, salvo `forzar=True`. Estos
    archivos pesan más de 100 MB y los portales de gobierno son lentos; bajar
    de nuevo en cada corrida haría el ETL inutilizable.
    """
    destino = RAW_DIR / fuente.archivo

    if destino.exists() and not forzar:
        print(f"    en caché: {destino.name} ({destino.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"    descargando {fuente.nombre}")
        print(f"      {fuente.url}")
        temporal = destino.with_suffix(destino.suffix + ".parcial")
        with requests.get(fuente.url, stream=True, timeout=(30, 600)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            escritos = 0
            with temporal.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
                    escritos += len(chunk)
                    if total:
                        pct = 100 * escritos / total
                        print(f"\r      {pct:5.1f}%  {escritos/1e6:7.1f} MB", end="")
            print()
        # Renombrar al final: si la descarga se interrumpe no queda un archivo
        # truncado que la caché daría por bueno.
        temporal.replace(destino)

    huella = sha256_archivo(destino)
    manifiesto = _leer_manifiesto()
    anterior = manifiesto.get(fuente.clave, {}).get("sha256")
    if anterior and anterior != huella:
        print(f"    AVISO: el archivo cambió respecto a la última descarga.")
        print(f"      antes: {anterior[:16]}...  ahora: {huella[:16]}...")

    manifiesto[fuente.clave] = {
        "nombre": fuente.nombre,
        "institucion": fuente.institucion,
        "url": fuente.url,
        "archivo": fuente.archivo,
        "sha256": huella,
        "bytes": destino.stat().st_size,
        "descargado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _escribir_manifiesto(manifiesto)

    return destino


def descomprimir(fuente: Fuente, forzar: bool = False) -> Path:
    """Descomprime en data/interim/<clave>/ y devuelve esa carpeta."""
    zip_path = RAW_DIR / fuente.archivo
    if not zip_path.exists():
        raise FileNotFoundError(
            f"Falta {zip_path}. Corre primero la descarga de '{fuente.clave}'."
        )

    destino = INTERIM_DIR / fuente.clave
    if destino.exists() and any(destino.iterdir()) and not forzar:
        print(f"    ya descomprimido: {destino}")
        return destino

    destino.mkdir(parents=True, exist_ok=True)
    print(f"    descomprimiendo {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(destino)
    return destino


def buscar_capa(carpeta: Path, sufijo: str) -> Path:
    """Localiza un .shp dentro de un árbol descomprimido.

    Los ZIP del INEGI y del IIEG anidan de forma distinta e inconsistente
    (`conjunto_de_datos/`, subcarpetas con el nombre del producto, etc.), así
    que buscar recursivamente es más robusto que codificar la ruta.
    """
    candidatos = sorted(carpeta.rglob(f"{sufijo}.shp"))
    if not candidatos:
        disponibles = sorted(p.stem for p in carpeta.rglob("*.shp"))
        raise FileNotFoundError(
            f"No se encontró la capa '{sufijo}.shp' en {carpeta}.\n"
            f"Capas disponibles: {', '.join(disponibles) or '(ninguna)'}"
        )
    if len(candidatos) > 1:
        print(f"    aviso: varias coincidencias para {sufijo}.shp, uso la primera")
    return candidatos[0]
