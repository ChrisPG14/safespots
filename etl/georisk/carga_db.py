"""Carga de geografía, incidencia y riesgo a PostgreSQL/PostGIS.

PostGIS es el sistema de registro y el motor de análisis del proyecto: aquí
viven las series completas, los índices espaciales GiST y la trazabilidad de
cada carga. Lo que consume la web es un GeoJSON precalculado que produce
`georisk.cli construir`, para no depender de la base en cada visita.

Requiere que las migraciones ya estén aplicadas:

    ./db/apply.sh "postgresql://..."
"""

from __future__ import annotations

import io
from datetime import date

import geopandas as gpd
import pandas as pd
import psycopg

from .config import DATABASE_URL
from .fuentes import COLONIAS_IIEG, INCIDENCIA_COLONIAS

# Tablas que deben existir antes de cargar. Se verifican de golpe para poder
# dar un mensaje único y accionable en lugar de fallar en la primera consulta.
_TABLAS_REQUERIDAS = (
    "unidad_geografica",
    "incidencia_agregada",
    "riesgo_unidad",
    "delito",
    "perfil_riesgo",
    "lote_ingesta",
)


def _verificar_esquema(con: psycopg.Connection) -> None:
    faltantes = [
        t
        for t in _TABLAS_REQUERIDAS
        if con.execute(
            "SELECT to_regclass(%s) IS NULL", (f"public.{t}",)
        ).fetchone()[0]
    ]
    if faltantes:
        raise RuntimeError(
            "Faltan tablas en la base: " + ", ".join(faltantes) + "\n"
            "  Aplica las migraciones primero:  ./db/apply.sh"
        )

    postgis = con.execute(
        "SELECT extname FROM pg_extension WHERE extname = 'postgis'"
    ).fetchone()
    if not postgis:
        raise RuntimeError(
            "La extensión PostGIS no está instalada en esta base.\n"
            "  En Neon o Supabase:  CREATE EXTENSION postgis;"
        )


def _abrir_lote(
    con: psycopg.Connection,
    fuente: str,
    descripcion: str,
    url: str,
    periodo: tuple[date, date] | None = None,
) -> int:
    fila = con.execute(
        """
        INSERT INTO lote_ingesta
            (fuente, descripcion, url_origen, periodo_inicio, periodo_fin)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            fuente,
            descripcion,
            url,
            periodo[0] if periodo else None,
            periodo[1] if periodo else None,
        ),
    ).fetchone()
    assert fila is not None
    return int(fila[0])


def _cerrar_lote(
    con: psycopg.Connection,
    lote_id: int,
    leidas: int,
    insertadas: int,
    rechazadas: int = 0,
    error: str | None = None,
) -> None:
    con.execute(
        """
        UPDATE lote_ingesta
           SET filas_leidas = %s,
               filas_insertadas = %s,
               filas_rechazadas = %s,
               estado = %s,
               mensaje_error = %s,
               terminado_en = now()
         WHERE id = %s
        """,
        (
            leidas,
            insertadas,
            rechazadas,
            "fallido" if error else "completado",
            error,
            lote_id,
        ),
    )


def cargar_unidades(
    con: psycopg.Connection, colonias: gpd.GeoDataFrame, lote_id: int
) -> int:
    """Inserta o actualiza las colonias en `unidad_geografica`.

    Es un upsert sobre (tipo, clave) para que volver a correr el ETL sobre una
    base ya poblada actualice en lugar de duplicar. Las claves son estables
    entre corridas —se derivan del nombre normalizado, no del orden del
    shapefile—, así que las referencias desde riesgo_unidad sobreviven.
    """
    registros = []
    for fila in colonias.itertuples():
        poblacion = getattr(fila, "poblacion", None)
        registros.append(
            (
                "colonia",
                fila.clave,
                fila.nombre,
                fila.municipio_clave,
                None if pd.isna(poblacion) else int(poblacion),
                float(fila.area_m2) if not pd.isna(fila.area_m2) else None,
                COLONIAS_IIEG.clave,
                getattr(fila, "fuente_version", None),
                # WKB en bytes; PostGIS lo interpreta y se le fija el SRID.
                fila.geometry.wkb,
            )
        )

    with con.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO unidad_geografica
                (tipo, clave, nombre, municipio_clave, poblacion, area_m2,
                 fuente, fuente_version, geom)
            VALUES (%s::tipo_unidad, %s, %s, %s, %s, %s, %s, %s,
                    ST_Multi(ST_SetSRID(ST_GeomFromWKB(%s), 4326)))
            ON CONFLICT (tipo, clave) DO UPDATE SET
                nombre          = EXCLUDED.nombre,
                municipio_clave = EXCLUDED.municipio_clave,
                poblacion       = EXCLUDED.poblacion,
                area_m2         = EXCLUDED.area_m2,
                fuente          = EXCLUDED.fuente,
                fuente_version  = EXCLUDED.fuente_version,
                geom            = EXCLUDED.geom,
                actualizado_en  = now()
            """,
            registros,
        )

    # El vínculo con el municipio se resuelve después, con una sola sentencia:
    # así no importa el orden en que se hayan insertado las unidades.
    con.execute(
        """
        UPDATE unidad_geografica u
           SET parent_id = m.id
          FROM unidad_geografica m
         WHERE u.tipo = 'colonia'
           AND m.tipo = 'municipio'
           AND m.clave = u.municipio_clave
           AND (u.parent_id IS DISTINCT FROM m.id)
        """
    )
    return len(registros)


def _copiar(
    con: psycopg.Connection,
    df: pd.DataFrame,
    tabla_temporal: str,
    columnas: list[str],
    ddl: str,
) -> None:
    """Sube un DataFrame a una tabla temporal con COPY.

    COPY y no executemany porque la incidencia son más de 150 mil filas: por
    sentencia individual la carga tarda minutos, con COPY son segundos.
    """
    con.execute(f"CREATE TEMPORARY TABLE {tabla_temporal} ({ddl}) ON COMMIT DROP")

    buffer = io.StringIO()
    df[columnas].to_csv(buffer, index=False, header=False, na_rep="\\N")
    buffer.seek(0)

    with con.cursor().copy(
        f"COPY {tabla_temporal} ({', '.join(columnas)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')"
    ) as copia:
        while bloque := buffer.read(1 << 16):
            copia.write(bloque)


def cargar_incidencia(
    con: psycopg.Connection, incidencia: pd.DataFrame, lote_id: int
) -> int:
    """Carga la incidencia agregada por colonia, delito, año y mes."""
    datos = incidencia.copy()
    datos["lote_id"] = lote_id
    datos["fuente"] = INCIDENCIA_COLONIAS.clave

    columnas = ["clave", "delito_clave", "anio", "mes", "conteo", "fuente", "lote_id"]
    _copiar(
        con,
        datos,
        "tmp_incidencia",
        columnas,
        """
        clave        text,
        delito_clave text,
        anio         smallint,
        mes          smallint,
        conteo       integer,
        fuente       text,
        lote_id      bigint
        """,
    )

    # El join traduce la clave de colonia a unidad_id. Si una clave no existe
    # en unidad_geografica la fila se descarta aquí en lugar de violar la
    # llave foránea y abortar toda la carga.
    resultado = con.execute(
        """
        INSERT INTO incidencia_agregada
            (fuente, unidad_id, delito_clave, anio, mes, conteo, lote_id)
        SELECT t.fuente, u.id, t.delito_clave, t.anio, t.mes, t.conteo, t.lote_id
          FROM tmp_incidencia t
          JOIN unidad_geografica u
            ON u.tipo = 'colonia' AND u.clave = t.clave
        ON CONFLICT (fuente, unidad_id, delito_clave, anio, mes)
        DO UPDATE SET conteo = EXCLUDED.conteo, lote_id = EXCLUDED.lote_id
        """
    )
    return resultado.rowcount


def cargar_riesgo(con: psycopg.Connection, riesgo: pd.DataFrame) -> int:
    """Carga el índice de riesgo calculado, para todos los perfiles."""
    datos = riesgo.copy()

    # La tabla guarda la tasa cruda del perfil; `medida_suavizada` y las
    # columnas de diagnóstico se conservan en el CSV de data/processed.
    columnas = [
        "clave", "perfil", "periodo_inicio", "periodo_fin",
        "incidentes", "incidentes_ponderados", "poblacion",
        "tasa_100k", "densidad_km2", "indice", "percentil", "estrato",
        "ic_inferior", "ic_superior", "muestra_baja",
        "calidad_dato", "metodo", "metodo_version",
    ]
    for c in columnas:
        if c not in datos.columns:
            datos[c] = None

    _copiar(
        con,
        datos,
        "tmp_riesgo",
        columnas,
        """
        clave                 text,
        perfil                text,
        periodo_inicio        date,
        periodo_fin           date,
        incidentes            integer,
        incidentes_ponderados double precision,
        poblacion             integer,
        tasa_100k             double precision,
        densidad_km2          double precision,
        indice                double precision,
        percentil             double precision,
        estrato               text,
        ic_inferior           double precision,
        ic_superior           double precision,
        muestra_baja          boolean,
        calidad_dato          text,
        metodo                text,
        metodo_version        text
        """,
    )

    resultado = con.execute(
        """
        INSERT INTO riesgo_unidad
            (unidad_id, perfil, periodo_inicio, periodo_fin,
             incidentes, incidentes_ponderados, poblacion,
             tasa_100k, densidad_km2, indice, percentil, estrato,
             ic_inferior, ic_superior, muestra_baja,
             calidad_dato, metodo, metodo_version)
        SELECT u.id, t.perfil, t.periodo_inicio, t.periodo_fin,
               t.incidentes, t.incidentes_ponderados, t.poblacion,
               t.tasa_100k, t.densidad_km2, t.indice, t.percentil, t.estrato,
               t.ic_inferior, t.ic_superior, t.muestra_baja,
               t.calidad_dato, t.metodo, t.metodo_version
          FROM tmp_riesgo t
          JOIN unidad_geografica u
            ON u.tipo = 'colonia' AND u.clave = t.clave
        ON CONFLICT (unidad_id, perfil, periodo_inicio, periodo_fin, metodo_version)
        DO UPDATE SET
            incidentes            = EXCLUDED.incidentes,
            incidentes_ponderados = EXCLUDED.incidentes_ponderados,
            poblacion             = EXCLUDED.poblacion,
            tasa_100k             = EXCLUDED.tasa_100k,
            densidad_km2          = EXCLUDED.densidad_km2,
            indice                = EXCLUDED.indice,
            percentil             = EXCLUDED.percentil,
            estrato               = EXCLUDED.estrato,
            ic_inferior           = EXCLUDED.ic_inferior,
            ic_superior           = EXCLUDED.ic_superior,
            muestra_baja          = EXCLUDED.muestra_baja,
            calidad_dato          = EXCLUDED.calidad_dato,
            metodo                = EXCLUDED.metodo,
            calculado_en          = now()
        """
    )
    return resultado.rowcount


def cargar_todo(
    url: str | None = None,
    solo_nucleo: bool = True,
    meses: int = 0,
) -> int:
    """Pipeline completo hacia PostGIS. Devuelve un código de salida."""
    from .geografia import cargar_colonias, cargar_municipios, unificar_por_nombre
    from .incidencia import cargar_incidencia as leer_incidencia
    from .riesgo import calcular_riesgo, ventana_ultimos_meses
    from .taxonomia import PERFILES

    conexion = url or DATABASE_URL
    # Nunca imprimir la URL completa: en Neon lleva la contraseña embebida.
    visible = conexion.split("@")[-1] if "@" in conexion else conexion
    print(f"\n=== Conectando a {visible}")

    print("\n=== Leyendo fuentes")
    colonias = unificar_por_nombre(cargar_colonias(solo_nucleo=solo_nucleo))
    incidencia, reporte = leer_incidencia(colonias, solo_nucleo=solo_nucleo)
    reporte.imprimir()

    ventana = ventana_ultimos_meses(incidencia, meses=meses or None)
    print(f"\n=== Ventana: {ventana}")

    unidades = colonias.drop(columns="geometry")
    riesgos = [
        calcular_riesgo(incidencia, unidades, clave, ventana)
        for clave in sorted(PERFILES, key=lambda c: PERFILES[c].orden)
    ]
    riesgo = pd.concat(riesgos, ignore_index=True)

    try:
        with psycopg.connect(conexion) as con:
            _verificar_esquema(con)

            print("\n=== Municipios (contexto)")
            municipios = cargar_municipios(solo_nucleo=solo_nucleo)
            with con.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO unidad_geografica
                        (tipo, clave, nombre, municipio_clave, area_m2, fuente,
                         fuente_version, geom)
                    VALUES ('municipio', %s, %s, %s, %s, %s, %s,
                            ST_Multi(ST_SetSRID(ST_GeomFromWKB(%s), 4326)))
                    ON CONFLICT (tipo, clave) DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        area_m2 = EXCLUDED.area_m2,
                        geom = EXCLUDED.geom,
                        actualizado_en = now()
                    """,
                    [
                        (
                            f.clave, f.nombre, f.municipio_clave,
                            float(f.area_m2), f.fuente,
                            getattr(f, "fuente_version", None), f.geometry.wkb,
                        )
                        for f in municipios.itertuples()
                    ],
                )
            print(f"    {len(municipios)} municipios")

            print("\n=== Colonias")
            lote_geo = _abrir_lote(
                con, COLONIAS_IIEG.clave, COLONIAS_IIEG.nombre, COLONIAS_IIEG.url
            )
            n_unidades = cargar_unidades(con, colonias, lote_geo)
            _cerrar_lote(con, lote_geo, len(colonias), n_unidades)
            print(f"    {n_unidades} unidades")

            print("\n=== Incidencia")
            lote_inc = _abrir_lote(
                con,
                INCIDENCIA_COLONIAS.clave,
                INCIDENCIA_COLONIAS.nombre,
                INCIDENCIA_COLONIAS.url,
                periodo=(
                    date.fromisoformat(ventana.inicio_iso),
                    date.fromisoformat(ventana.fin_iso),
                ),
            )
            n_inc = cargar_incidencia(con, incidencia, lote_inc)
            _cerrar_lote(
                con,
                lote_inc,
                len(incidencia),
                n_inc,
                rechazadas=len(incidencia) - n_inc,
            )
            print(f"    {n_inc:,} filas de incidencia")

            print("\n=== Riesgo")
            n_riesgo = cargar_riesgo(con, riesgo)
            print(f"    {n_riesgo:,} filas de riesgo")

            con.commit()

            print("\n=== Verificación en la base")
            for consulta, etiqueta in (
                ("SELECT count(*) FROM unidad_geografica WHERE tipo='colonia'", "colonias"),
                ("SELECT count(*) FROM incidencia_agregada", "incidencia"),
                ("SELECT count(*) FROM riesgo_unidad", "riesgo"),
                ("SELECT count(*) FROM v_riesgo_vigente", "vista vigente"),
            ):
                total = con.execute(consulta).fetchone()[0]
                print(f"    {etiqueta:<16} {total:>10,}")

    except psycopg.OperationalError as exc:
        print(f"\nERROR de conexión: {exc}")
        print("  ¿Está arriba la base?  docker compose up -d")
        print("  ¿DATABASE_URL apunta al lugar correcto?")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR durante la carga: {exc}")
        return 1

    print("\nCarga completada.")
    return 0
