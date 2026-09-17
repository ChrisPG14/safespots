import type { Feature, FeatureCollection, Geometry, Position } from "geojson";
import type { PropiedadesColonia } from "./tipos";

export type DatosColonias = FeatureCollection<Geometry, PropiedadesColonia>;
export type Colonia = Feature<Geometry, PropiedadesColonia>;
export type Coordenadas = [number, number];

function poligonos(geometria: Geometry): Position[][][] {
  if (geometria.type === "Polygon") return [geometria.coordinates];
  if (geometria.type === "MultiPolygon") return geometria.coordinates;
  if (geometria.type === "GeometryCollection") return geometria.geometries.flatMap(poligonos);
  return [];
}

export function limitesColonia(colonia: Colonia): [Coordenadas, Coordenadas] {
  const puntos = poligonos(colonia.geometry).flat(2);
  return [
    [Math.min(...puntos.map((p) => p[0])), Math.min(...puntos.map((p) => p[1]))],
    [Math.max(...puntos.map((p) => p[0])), Math.max(...puntos.map((p) => p[1]))],
  ];
}

/** Punto interior por barrido horizontal; respeta huecos y polígonos cóncavos. */
export function puntoColonia(colonia: Colonia): Coordenadas {
  let mejor: Coordenadas | undefined;
  let ancho = -1;
  for (const anillos of poligonos(colonia.geometry)) {
    const ys = anillos[0].map((p) => p[1]);
    const y = (Math.min(...ys) + Math.max(...ys)) / 2;
    const cortes: number[] = [];
    for (const anillo of anillos) {
      for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
        const a = anillo[i], b = anillo[j];
        if ((a[1] > y) !== (b[1] > y)) {
          cortes.push(a[0] + ((y - a[1]) * (b[0] - a[0])) / (b[1] - a[1]));
        }
      }
    }
    cortes.sort((a, b) => a - b);
    for (let i = 0; i + 1 < cortes.length; i += 2) {
      if (cortes[i + 1] - cortes[i] > ancho) {
        ancho = cortes[i + 1] - cortes[i];
        mejor = [(cortes[i] + cortes[i + 1]) / 2, y];
      }
    }
  }
  if (!mejor) throw new Error("La colonia no contiene un polígono válido.");
  return mejor;
}

export function distanciaKm(a: Coordenadas, b: Coordenadas): number {
  const rad = Math.PI / 180;
  const h = Math.sin((b[1] - a[1]) * rad / 2) ** 2 +
    Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin((b[0] - a[0]) * rad / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}

function dentroAnillo(punto: Coordenadas, anillo: Position[]): boolean {
  let dentro = false;
  for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
    const a = anillo[i], b = anillo[j];
    if ((a[1] > punto[1]) !== (b[1] > punto[1]) &&
        punto[0] < (b[0] - a[0]) * (punto[1] - a[1]) / (b[1] - a[1]) + a[0]) dentro = !dentro;
  }
  return dentro;
}

/** Cercanía a la superficie de la colonia; evita excluir la zona donde estás
 * solo porque su punto representativo queda lejos, especialmente a 100–500 m.
 * Los segmentos usan una proyección local y el resultado es aproximado. */
export function distanciaAColoniaKm(origen: Coordenadas, colonia: Colonia): number {
  let menor = Infinity;
  const cos = Math.cos(origen[1] * Math.PI / 180);
  for (const anillos of poligonos(colonia.geometry)) {
    if (dentroAnillo(origen, anillos[0]) && !anillos.slice(1).some((a) => dentroAnillo(origen, a))) return 0;
    for (const anillo of anillos) {
      for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
        const a = anillo[j], b = anillo[i];
        const ax = (a[0] - origen[0]) * cos, ay = a[1] - origen[1];
        const dx = (b[0] - a[0]) * cos, dy = b[1] - a[1];
        const largo2 = dx * dx + dy * dy;
        const t = largo2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / largo2)) : 0;
        menor = Math.min(menor, distanciaKm(origen, [a[0] + t * (b[0] - a[0]), a[1] + t * dy]));
      }
    }
  }
  return menor;
}

export function normalizarBusqueda(texto: string): string {
  return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}
