"""Interfaz de línea de comandos del ETL.

    python -m georisk.cli descargar     # baja las fuentes a data/raw/
    python -m georisk.cli construir     # pipeline completo -> GeoJSON del mapa
    python -m georisk.cli cargar-db     # carga a PostGIS
    python -m georisk.cli info          # catálogo de fuentes y su estado
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import (
    MUNICIPIOS_AMG,
    MUNICIPIOS_NUCLEO,
    PROCESSED_DIR,
    RAIZ_DIR,
    RAW_DIR,
)
from .fuentes import FUENTES, SESNSP_MUNICIPAL, descargar
from .taxonomia import PERFILES

# El frontend lee de aquí. public/ se sirve estático en Vercel.
DESTINO_WEB = RAIZ_DIR / "web" / "public" / "datos"


def _titulo(texto: str) -> None:
    print(f"\n=== {texto}")


def cmd_info(args: argparse.Namespace) -> int:
    print("Fuentes registradas:\n")
    for f in FUENTES.values():
        ruta = RAW_DIR / f.archivo
        if ruta.exists():
            estado = f"descargada ({ruta.stat().st_size / 1e6:.1f} MB)"
        else:
            estado = "no descargada"
        print(f"  [{f.clave}]")
        print(f"    {f.nombre}")
        print(f"    institución : {f.institucion}")
        print(f"    cadencia    : {f.cadencia}")
        print(f"    estado      : {estado}")
        if f.notas:
            print(f"    notas       : {f.notas}")
        print()

    print("Perfiles de riesgo:\n")
    for p in sorted(PERFILES.values(), key=lambda x: x.orden):
        print(f"  {p.clave:<14} {p.nombre}")
        if p.advertencia:
            print(f"                 advertencia: {p.advertencia}")
    return 0


def cmd_descargar(args: argparse.Namespace) -> int:
    objetivo = (
        [FUENTES[c] for c in args.fuente]
        if args.fuente
        else [f for f in FUENTES.values() if f.clave != SESNSP_MUNICIPAL.clave]
    )

    for f in objetivo:
        _titulo(f.nombre)
        if f.clave == SESNSP_MUNICIPAL.clave:
            print("    descarga MANUAL: el enlace del SESNSP no es estable.")
            print(f"    {f.url}")
            continue
        try:
            descargar(f, forzar=args.forzar)
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR al descargar {f.clave}: {exc}", file=sys.stderr)
            return 1

    print(f"\nListo. Archivos en {RAW_DIR}")
    return 0


def cmd_construir(args: argparse.Namespace) -> int:
    # Los import van aquí y no arriba para que `info` y `descargar` arranquen
    # al instante: importar geopandas tarda unos segundos.
    import pandas as pd

    from .exportar import exportar_geojson, exportar_meta
    from .geografia import cargar_colonias, unificar_por_nombre
    from .incidencia import cargar_incidencia
    from .riesgo import calcular_riesgo, resumen, top_riesgo, ventana_ultimos_meses

    t0 = time.time()
    solo_nucleo = not args.amg_completa
    municipios = MUNICIPIOS_NUCLEO if solo_nucleo else MUNICIPIOS_AMG

    _titulo("1/5 Polígonos de colonia (IIEG)")
    colonias = cargar_colonias(solo_nucleo=solo_nucleo)
    if not args.sin_fusionar:
        colonias = unificar_por_nombre(colonias)

    _titulo("2/5 Incidencia delictiva por colonia (IIEG)")
    incidencia, reporte = cargar_incidencia(colonias, solo_nucleo=solo_nucleo)
    print()
    reporte.imprimir()

    if reporte.cobertura < 80:
        # Umbral de alarma: por debajo de esto el mapa deja de representar la
        # incidencia real y no debe publicarse sin revisar el empate.
        print(
            f"\n    ATENCIÓN: solo se ubicó el {reporte.cobertura:.1f}% de los "
            f"incidentes. Revisa georisk/nombres.py antes de confiar en el mapa."
        )

    _titulo("3/5 Ventana de análisis")
    ventana = ventana_ultimos_meses(incidencia, meses=args.meses or None)
    print(f"    {ventana}")
    print(
        "    anclada al último mes de la fuente, no a la fecha de hoy: "
        "la serie del IIEG termina en feb 2021"
    )

    _titulo("4/5 Índice de riesgo por perfil")
    unidades = colonias.drop(columns="geometry")
    riesgos: dict[str, pd.DataFrame] = {}
    for clave in sorted(PERFILES, key=lambda c: PERFILES[c].orden):
        df = calcular_riesgo(incidencia, unidades, clave, ventana)
        riesgos[clave] = df
        print(f"    {clave:<14} {resumen(df)}")

    if args.top:
        for clave, df in riesgos.items():
            print(f"\n    Mayor riesgo — perfil '{clave}':")
            print(top_riesgo(df, n=args.top).to_string(index=False))

    _titulo("5/5 Exportación")
    destino = Path(args.destino) if args.destino else DESTINO_WEB
    exportar_geojson(colonias, riesgos, destino / "colonias-riesgo.geojson")
    exportar_meta(destino / "meta.json", ventana, riesgos, reporte, municipios)

    # Copia de los resultados tabulares, útil para el análisis del reporte y
    # para cargar a la base después sin recalcular.
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tabla = pd.concat(riesgos.values(), ignore_index=True)
    tabla.to_csv(PROCESSED_DIR / "riesgo_unidad.csv", index=False)
    incidencia.to_csv(PROCESSED_DIR / "incidencia_agregada.csv", index=False)
    print(f"    escrito {PROCESSED_DIR / 'riesgo_unidad.csv'} ({len(tabla):,} filas)")

    print(f"\nListo en {time.time() - t0:.1f} s. El mapa ya puede leer {destino}")
    return 0


def cmd_cargar_db(args: argparse.Namespace) -> int:
    from .carga_db import cargar_todo

    return cargar_todo(
        url=args.url,
        solo_nucleo=not args.amg_completa,
        meses=args.meses,
    )


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="georisk",
        description="ETL del sistema de riesgo delictivo de la ZMG.",
    )
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("info", help="catálogo de fuentes y su estado")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("descargar", help="baja las fuentes oficiales")
    s.add_argument("--fuente", action="append", choices=sorted(FUENTES), help="solo esta fuente")
    s.add_argument("--forzar", action="store_true", help="volver a bajar aunque exista")
    s.set_defaults(func=cmd_descargar)

    s = sub.add_parser("construir", help="pipeline completo y exportación del mapa")
    s.add_argument(
        "--meses", type=int, default=0,
        help="tamaño de la ventana en meses; 0 (por omisión) usa toda la serie disponible",
    )
    s.add_argument("--amg-completa", action="store_true", help="los 10 municipios, no solo el núcleo")
    s.add_argument("--destino", help="carpeta de salida (por omisión web/public/datos)")
    s.add_argument("--top", type=int, default=0, help="mostrar las N colonias de mayor riesgo")
    s.add_argument(
        "--sin-fusionar", action="store_true",
        help="no unir polígonos homónimos; solo para diagnosticar el padrón, "
             "produce tasas infladas en las colonias partidas en pedazos",
    )
    s.set_defaults(func=cmd_construir)

    s = sub.add_parser("cargar-db", help="carga geografía, incidencia y riesgo a PostGIS")
    s.add_argument("--url", help="URL de conexión (por omisión $DATABASE_URL)")
    s.add_argument("--meses", type=int, default=0)
    s.add_argument("--amg-completa", action="store_true")
    s.set_defaults(func=cmd_cargar_db)

    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
