import { z } from "zod";
import { distanciaAColoniaKm, puntoColonia, type Coordenadas, type DatosColonias } from "./geografia";
import { DISTANCIAS } from "./preferencias";
import { esEstrato } from "./riesgo";
import type { Meta } from "./tipos";

export const consultaSchema = z.object({
  objetivo: z.enum(["turismo", "renta", "estacionamiento"]),
  presupuesto: z.number().positive().max(1_000_000),
  radioKm: z.number().min(0.1).max(30),
  coloniaClave: z.string().max(100).optional(),
  ubicacion: z.tuple([z.number().min(-180).max(180), z.number().min(-90).max(90)]).optional(),
  pregunta: z.string().trim().max(1000).default(""),
}).refine((v) => Boolean(v.coloniaClave) !== Boolean(v.ubicacion), {
  message: "Elige una colonia o tu ubicación como referencia.",
}).refine((v) => {
  const opciones = DISTANCIAS[v.objetivo].opciones;
  return v.radioKm >= opciones[0] && v.radioKm <= opciones[opciones.length - 1];
}, {
  path: ["radioKm"],
  message: "Estacionamiento admite de 100 m a 1 km; hospedaje de 500 m a 5 km; renta de 1 a 30 km.",
});
export type Consulta = z.infer<typeof consultaSchema>;
export type Objetivo = Consulta["objetivo"];

export const respuestaModeloSchema = z.object({
  resumen: z.string().min(1).max(2000),
  recomendaciones: z.array(z.object({
    clave: z.string().min(1).max(100),
    motivo: z.string().min(1).max(1200),
    presupuesto: z.string().min(1).max(800),
    precaucion: z.string().min(1).max(800),
  })).max(4),
  consejos: z.array(z.string().min(1).max(600)).max(5),
});

export function prepararContexto(consulta: Consulta, datos: DatosColonias, meta: Meta) {
  const referencia = consulta.coloniaClave
    ? datos.features.find((f) => f.properties.clave === consulta.coloniaClave)
    : undefined;
  if (consulta.coloniaClave && !referencia) throw new Error("La colonia de referencia no existe.");
  const origen: Coordenadas = referencia ? puntoColonia(referencia) : consulta.ubicacion!;
  const claves = consulta.objetivo === "estacionamiento" ? ["vehicular"]
    : consulta.objetivo === "renta" ? ["residencial", "peaton"] : ["peaton", "residencial"];
  const perfiles = claves.map((clave) => meta.perfiles.find((p) => p.clave === clave));
  if (perfiles.some((p) => !p)) throw new Error("Faltan perfiles de riesgo para esta consulta.");
  const candidatos = datos.features.map((f) => {
    const p = f.properties;
    const distancia = distanciaAColoniaKm(origen, f);
    const riesgos = perfiles.map((perfil) => {
      const estrato = p[perfil!.campo_estrato];
      const valor = p[perfil!.campo_indice];
      return {
        perfil: perfil!.nombre,
        indice: typeof valor === "number" && Number.isFinite(valor) ? valor : null,
        estrato: esEstrato(estrato) ? estrato : null,
        muestraBaja: p[perfil!.campo_muestra_baja] !== false,
      };
    });
    return {
      clave: p.clave, nombre: p.nombre,
      municipio: meta.municipios.find((m) => m.clave === p.municipio_clave)?.nombre ?? p.municipio_clave,
      distanciaKm: distancia, riesgos,
    };
  }).filter((c) => c.distanciaKm <= consulta.radioKm);
  // La distancia se filtra antes de redondear. Una muestra insuficiente nunca
  // se convierte en recomendación por tener pocos incidentes registrados.
  const elegibles = candidatos.filter((c) => c.riesgos.every((r) =>
    !r.muestraBaja && r.indice !== null && r.estrato !== null));
  elegibles.sort((a, b) => {
    const puntaje = (c: typeof a) => c.riesgos.reduce((s, r) => s + r.indice!, 0) / c.riesgos.length + 20 * c.distanciaKm / consulta.radioKm;
    return puntaje(a) - puntaje(b);
  });
  return {
    referencia: referencia ? `${referencia.properties.nombre}, ${meta.municipios.find((m) => m.clave === referencia.properties.municipio_clave)?.nombre}` : "Punto de referencia en el mapa",
    descartadas: candidatos.length - elegibles.length,
    candidatos: elegibles.slice(0, 24).map((c) => ({ ...c, distanciaKm: Math.round(c.distanciaKm * 1000) / 1000 })),
  };
}

export type Candidato = ReturnType<typeof prepararContexto>["candidatos"][number];
export interface RespuestaAsesor {
  resumen: string;
  recomendaciones: (Candidato & { motivo: string; presupuesto: string; precaucion: string })[];
  consejos: string[];
  advertencia: string;
  periodo: string;
  referencia: string;
  descartadas: number;
}

/** La identidad, la distancia y las cifras siempre proceden del dataset. */
export function validarRespuesta(valor: unknown, candidatos: Candidato[]) {
  const respuesta = respuestaModeloSchema.parse(valor);
  const usadas = new Set<string>();
  const recomendaciones = respuesta.recomendaciones.map((r) => {
    const colonia = candidatos.find((c) => c.clave === r.clave);
    if (!colonia || usadas.has(r.clave)) throw new Error("Gemini devolvió una colonia no válida.");
    usadas.add(r.clave);
    return { ...r, ...colonia };
  });
  return { ...respuesta, recomendaciones };
}
