#!/usr/bin/env bash
# Aplica las migraciones pendientes en orden y registra cuáles ya corrieron.
#
# Uso:
#   ./db/apply.sh                          # usa $DATABASE_URL
#   ./db/apply.sh "postgresql://..."       # o una URL explícita
#
# Idempotente: relee schema_migrations y solo ejecuta lo que falta, así que
# se puede correr sobre una base local o sobre Neon sin pensarlo.

set -euo pipefail

DB_URL="${1:-${DATABASE_URL:-}}"

if [[ -z "$DB_URL" ]]; then
    echo "ERROR: falta la URL de conexión." >&2
    echo "  Define DATABASE_URL o pásala como primer argumento." >&2
    echo "  Local con docker compose: postgresql://geo:geo@localhost:5433/georisk" >&2
    exit 1
fi

MIGRATIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/migrations"

if ! command -v psql >/dev/null 2>&1; then
    echo "ERROR: no se encontró psql en el PATH." >&2
    exit 1
fi

echo "==> Verificando conexión"
if ! psql "$DB_URL" -Atc "SELECT 1" >/dev/null 2>&1; then
    echo "ERROR: no se pudo conectar a la base de datos." >&2
    echo "  ¿Está arriba el contenedor?  docker compose up -d" >&2
    exit 1
fi

# La tabla de control la crea la migración 0001, pero necesitamos consultarla
# antes de que exista. Si no está, tratamos la lista de aplicadas como vacía.
aplicadas="$(psql "$DB_URL" -Atc \
    "SELECT version FROM schema_migrations ORDER BY version" 2>/dev/null || true)"

pendientes=0
for archivo in "$MIGRATIONS_DIR"/*.sql; do
    [[ -e "$archivo" ]] || { echo "No hay migraciones en $MIGRATIONS_DIR"; exit 0; }
    version="$(basename "$archivo" .sql)"

    if grep -qxF "$version" <<< "$aplicadas"; then
        echo "    ya aplicada: $version"
        continue
    fi

    echo "==> Aplicando $version"
    # ON_ERROR_STOP y una sola transacción por archivo: si algo falla, la
    # migración no queda a medias.
    psql "$DB_URL" \
        --single-transaction \
        --set ON_ERROR_STOP=on \
        --quiet \
        -f "$archivo"

    psql "$DB_URL" --quiet -c \
        "INSERT INTO schema_migrations (version) VALUES ('$version')
         ON CONFLICT (version) DO NOTHING"

    echo "    OK $version"
    pendientes=$((pendientes + 1))
done

if [[ "$pendientes" -eq 0 ]]; then
    echo "==> Sin cambios: la base ya estaba al día."
else
    echo "==> Listo: $pendientes migración(es) aplicada(s)."
fi

echo
echo "==> Estado"
psql "$DB_URL" -c "SELECT postgis_version() AS postgis" 2>/dev/null || true
psql "$DB_URL" -c "
    SELECT tipo, count(*) AS unidades
    FROM unidad_geografica GROUP BY tipo ORDER BY tipo" 2>/dev/null || true
