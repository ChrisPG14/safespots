#!/usr/bin/env bash
# Mide el desempeño de las consultas espaciales, con y sin índice.
#
# Existe para que las cifras del reporte académico sean REPRODUCIBLES: quien
# evalúe el proyecto puede correr esto y obtener sus propios números en su
# propia máquina, en vez de creer una tabla.
#
# Uso:
#   ./db/benchmark.sh                       # solo las consultas rápidas
#   ./db/benchmark.sh --completo            # incluye el join de 100k puntos
#   ./db/benchmark.sh "postgresql://..." --completo
#
# El escenario --completo tarda MÁS DE DIEZ MINUTOS, porque la variante sin
# índice hace ~207 millones de comprobaciones de contención. Esa lentitud es
# justamente lo que se quiere demostrar.
#
# Metodología: de cada consulta se toma el MEJOR de cinco tiempos de ejecución
# reportados por EXPLAIN ANALYZE, es decir con caché caliente. Se mide así
# porque interesa el costo de la operación en régimen, no el primer acceso a
# disco, que depende del hardware y no de la estructura de datos.

set -euo pipefail

DB_URL=""
COMPLETO=0
for arg in "$@"; do
    case "$arg" in
        --completo) COMPLETO=1 ;;
        *) DB_URL="$arg" ;;
    esac
done
DB_URL="${DB_URL:-${DATABASE_URL:-postgresql://geo:geo@localhost:5433/georisk}}"

if ! psql "$DB_URL" -Atc "SELECT 1" >/dev/null 2>&1; then
    echo "ERROR: no se pudo conectar a la base." >&2
    echo "  ¿Está arriba?  docker compose up -d" >&2
    exit 1
fi

# Punto de referencia: el centro histórico de Guadalajara.
LON=-103.3496
LAT=20.6767

# Ejecuta una consulta N veces y devuelve el mejor tiempo en milisegundos.
mejor_tiempo() {
    local opciones="$1" consulta="$2" repeticiones="${3:-5}"
    local i
    for ((i = 0; i < repeticiones; i++)); do
        PGOPTIONS="$opciones" psql "$DB_URL" -Atc \
            "EXPLAIN (ANALYZE, TIMING ON, FORMAT JSON) $consulta" 2>/dev/null \
            | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Execution Time'])" 2>/dev/null
    done | sort -g | head -1
}

fila() {  # etiqueta, tiempo_sin, tiempo_con
    local etiqueta="$1" sin="$2" con="$3"
    python3 - "$etiqueta" "$sin" "$con" <<'PY'
import sys
etiqueta, sin_idx, con_idx = sys.argv[1], sys.argv[2], sys.argv[3]
def fmt(v):
    try: v = float(v)
    except (TypeError, ValueError): return "       n/d"
    return f"{v/1000:9.2f} s" if v >= 10000 else f"{v:9.2f} ms"
try:
    factor = f"{float(sin_idx)/float(con_idx):.1f}x"
except (TypeError, ValueError, ZeroDivisionError):
    factor = "  n/d"
print(f"  {etiqueta:<44} {fmt(sin_idx)}  {fmt(con_idx)}   {factor:>7}")
PY
}

SIN_INDICE="-c enable_indexscan=off -c enable_bitmapscan=off"

echo "=============================================================================="
echo " Desempeño de consultas espaciales — PostGIS"
echo "=============================================================================="
psql "$DB_URL" -Atc "SELECT '  ' || count(*) || ' colonias indexadas' FROM unidad_geografica WHERE tipo='colonia'"
echo
printf "  %-44s %12s  %12s  %8s\n" "consulta" "sin índice" "con GiST" "mejora"
printf "  %s\n" "--------------------------------------------------------------------------"

Q1="SELECT clave FROM unidad_geografica WHERE tipo='colonia'
    AND ST_Contains(geom, ST_SetSRID(ST_MakePoint($LON,$LAT),4326));"
fila "Punto en polígono (¿qué colonia es esta?)" \
     "$(mejor_tiempo "$SIN_INDICE" "$Q1")" "$(mejor_tiempo "" "$Q1")"

Q2="SELECT count(*) FROM unidad_geografica WHERE tipo='colonia'
    AND geom && ST_MakeEnvelope(-103.40,20.63,-103.30,20.72,4326);"
fila "Viewport del mapa (recuadro)" \
     "$(mejor_tiempo "$SIN_INDICE" "$Q2")" "$(mejor_tiempo "" "$Q2")"

# La comparación aquí no es índice sí/no, sino la vista contra la función: el
# DISTINCT ON de la vista impide aprovechar el índice aunque exista.
Q3V="SELECT r.nombre FROM v_riesgo_vigente r WHERE r.perfil='peaton'
     AND ST_DWithin(r.geom::geography,
         ST_SetSRID(ST_MakePoint($LON,$LAT),4326)::geography, 2000);"
Q3F="SELECT nombre FROM riesgo_cerca_de($LON, $LAT, 2000, 'peaton', 50);"
fila "Riesgo en radio de 2 km (vista vs función)" \
     "$(mejor_tiempo "" "$Q3V")" "$(mejor_tiempo "" "$Q3F")"

if [[ "$COMPLETO" -eq 1 ]]; then
    echo
    echo "  Generando 100,000 puntos aleatorios en el recuadro de la ZMG..."
    psql "$DB_URL" -q -c "
        DROP TABLE IF EXISTS banco_puntos;
        CREATE TABLE banco_puntos AS
        SELECT gs AS id,
               ST_SetSRID(ST_MakePoint(-103.55 + random()*0.45,
                                        20.45  + random()*0.40), 4326) AS geom
          FROM generate_series(1, 100000) gs;
        ANALYZE banco_puntos;"

    Q4="SELECT count(*) FROM banco_puntos p
        JOIN unidad_geografica u ON u.tipo='colonia' AND ST_Contains(u.geom, p.geom);"

    echo "  Midiendo CON índice..."
    CON=$(mejor_tiempo "" "$Q4" 2)
    echo "  Midiendo SIN índice (esto tarda más de diez minutos)..."
    SIN=$(mejor_tiempo "$SIN_INDICE -c statement_timeout=1800s" "$Q4" 1)

    echo
    fila "Asignar 100,000 puntos a su colonia" "$SIN" "$CON"
    psql "$DB_URL" -q -c "DROP TABLE IF EXISTS banco_puntos;"
else
    echo
    echo "  (Usa --completo para incluir el escenario de 100,000 puntos;"
    echo "   tarda más de diez minutos por la variante sin índice.)"
fi
echo
