/**
 * Paleta, etiquetas y formato de las cifras de riesgo.
 */

import type { ClaveEstrato } from "./tipos";

/**
 * Paleta secuencial YlOrRd de ColorBrewer, cuatro clases.
 *
 * Se eligió una rampa de un solo tono (amarillo a rojo) y no la clásica
 * verde-amarillo-rojo porque esta sí es distinguible con daltonismo
 * rojo-verde, que afecta a cerca del 8% de los hombres. Con la rampa verde a
 * roja, el estrato "bajo" y el "crítico" se ven casi iguales para esas
 * personas, que es el peor error posible en un mapa de seguridad.
 */
export const COLOR_ESTRATO: Record<ClaveEstrato, string> = {
  bajo: "#ffffb2",
  moderado: "#fecc5c",
  alto: "#fd8d3c",
  critico: "#e31a1c",
};

export const ETIQUETA_ESTRATO: Record<ClaveEstrato, string> = {
  bajo: "Bajo",
  moderado: "Moderado",
  alto: "Alto",
  critico: "Crítico",
};

/** Color de texto legible sobre cada color de estrato. */
export const TEXTO_SOBRE_ESTRATO: Record<ClaveEstrato, string> = {
  bajo: "#4a3f00",
  moderado: "#4a3200",
  alto: "#3d1a00",
  critico: "#ffffff",
};

export const ORDEN_ESTRATOS: ClaveEstrato[] = [
  "bajo",
  "moderado",
  "alto",
  "critico",
];

/** Encuadre inicial del mapa: la mancha urbana de la ZMG. */
export const VISTA_INICIAL = {
  centro: [-103.36, 20.65] as [number, number],
  zoom: 10.4,
  /**
   * Límites de paneo. Encierran los seis municipios del núcleo con holgura,
   * para que el usuario no se pierda navegando fuera del área con datos y
   * concluya que el mapa está roto.
   */
  limites: [
    [-103.75, 20.35],
    [-102.95, 20.95],
  ] as [[number, number], [number, number]],
};

const FORMATO_ENTERO = new Intl.NumberFormat("es-MX", {
  maximumFractionDigits: 0,
});

const FORMATO_DECIMAL = new Intl.NumberFormat("es-MX", {
  maximumFractionDigits: 1,
});

export function numero(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return FORMATO_ENTERO.format(valor);
}

export function decimal(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return FORMATO_DECIMAL.format(valor);
}

/** "2016-01-01" y "2021-02-28" -> "enero 2016 – febrero 2021" */
export function rangoLegible(inicio: string, fin: string): string {
  const fmt = new Intl.DateTimeFormat("es-MX", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  return `${fmt.format(new Date(inicio))} – ${fmt.format(new Date(fin))}`;
}

export function esEstrato(valor: unknown): valor is ClaveEstrato {
  return (
    typeof valor === "string" &&
    (ORDEN_ESTRATOS as string[]).includes(valor)
  );
}
