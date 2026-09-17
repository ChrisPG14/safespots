/** Opciones compartidas por el formulario y la validación de la API. */
export const DISTANCIAS = {
  estacionamiento: { opciones: [0.1, 0.25, 0.5, 0.75, 1], inicial: 0.5 },
  turismo: { opciones: [0.5, 1, 2, 3, 5], inicial: 3 },
  renta: { opciones: [1, 3, 5, 10, 20, 30], inicial: 5 },
} as const;

export function distanciaLegible(km: number): string {
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km} km`;
}
