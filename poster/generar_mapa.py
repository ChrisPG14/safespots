"""Genera figuras/mapa-riesgo.svg a partir de la capa publicada por la web.

El mapa del póster sale del mismo GeoJSON que sirve la aplicación, así que la
figura coincide con lo que el jurado ve en la demostración. Es vectorial para
que no se pixele al imprimir en lona.
"""
import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
GEOJSON = RAIZ.parent / "web" / "public" / "datos" / "colonias-riesgo.geojson"
SALIDA = RAIZ / "figuras" / "mapa-riesgo.svg"

# Misma paleta YlOrRd que web/lib/riesgo.ts.
COLOR = {"bajo": "#ffffb2", "moderado": "#fecc5c", "alto": "#fd8d3c", "critico": "#e31a1c"}

perfil = sys.argv[1] if len(sys.argv) > 1 else "general"
datos = json.loads(GEOJSON.read_text(encoding="utf-8"))

def poligonos(g):
    """Aplana Polygon, MultiPolygon y GeometryCollection a lista de polígonos."""
    if g["type"] == "Polygon":
        return [g["coordinates"]]
    if g["type"] == "MultiPolygon":
        return g["coordinates"]
    if g["type"] == "GeometryCollection":
        return [p for h in g["geometries"] for p in poligonos(h)]
    return []


anillos = []
for f in datos["features"]:
    anillos.append((f["properties"], poligonos(f["geometry"])))

lons = [x for _, ps in anillos for p in ps for r in p for x, _ in r]
lats = [y for _, ps in anillos for p in ps for r in p for _, y in r]
x0, x1, y0, y1 = min(lons), max(lons), min(lats), max(lats)
k = math.cos(math.radians((y0 + y1) / 2))  # equirectangular corregida
ANCHO = 1000.0
esc = ANCHO / ((x1 - x0) * k)
ALTO = (y1 - y0) * esc


def pt(x, y):
    return f"{(x - x0) * k * esc:.1f},{(y1 - y) * esc:.1f}"


trazos = []
for props, polis in anillos:
    est = props.get(f"est_{perfil}")
    fill = COLOR.get(est, "#dddddd")
    op = ' fill-opacity="0.35"' if props.get(f"baja_{perfil}") else ""
    d = "".join("M" + "L".join(pt(x, y) for x, y in r) + "Z" for p in polis for r in p)
    trazos.append(f'<path d="{d}" fill="{fill}"{op}/>')

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ANCHO:.0f} {ALTO:.0f}">'
    f'<g stroke="#5b5b5b" stroke-width="0.35" fill-rule="evenodd">{"".join(trazos)}</g></svg>'
)
SALIDA.parent.mkdir(exist_ok=True)
SALIDA.write_text(svg, encoding="utf-8")
print(SALIDA, f"{ANCHO:.0f}x{ALTO:.0f}", len(svg) // 1024, "KB")
