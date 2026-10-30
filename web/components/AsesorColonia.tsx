"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Objetivo, RespuestaAsesor } from "@/lib/asesor";
import type { Coordenadas } from "@/lib/geografia";
import { decimal, ETIQUETA_ESTRATO } from "@/lib/riesgo";
import { DISTANCIAS, distanciaLegible } from "@/lib/preferencias";

interface Props {
  objetivo: Objetivo;
  onObjetivo: (objetivo: Objetivo) => void;
  referencia: { clave: string; nombre: string } | null;
  ubicacion: Coordenadas | null;
  precisionUbicacion: number | null;
  onUbicacion: () => void;
  onAjustarUbicacion: () => void;
  ubicando: boolean;
  onVerColonia: (clave: string) => void;
}

const OPCIONES: { clave: Objetivo; nombre: string; unidad: string; presupuesto: number }[] = [
  { clave: "turismo", nombre: "De turismo", unidad: "noche", presupuesto: 1200 },
  { clave: "renta", nombre: "Buscar renta", unidad: "mes", presupuesto: 10000 },
  { clave: "estacionamiento", nombre: "Dejar mi auto", unidad: "hora", presupuesto: 40 },
];

export default function AsesorColonia({ objetivo, onObjetivo, referencia, ubicacion, precisionUbicacion, onUbicacion, onAjustarUbicacion, ubicando, onVerColonia }: Props) {
  const [presupuestos, setPresupuestos] = useState<Record<Objetivo, string>>({ turismo: "1200", renta: "10000", estacionamiento: "40" });
  const [radios, setRadios] = useState<Record<Objetivo, number>>({ turismo: DISTANCIAS.turismo.inicial, renta: DISTANCIAS.renta.inicial, estacionamiento: DISTANCIAS.estacionamiento.inicial });
  const radio = radios[objetivo];
  const [pregunta, setPregunta] = useState("");
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultado, setResultado] = useState<{ datos: RespuestaAsesor; firma: string } | null>(null);
  const peticion = useRef<AbortController | null>(null);
  const opcion = OPCIONES.find((o) => o.clave === objetivo)!;
  const firma = JSON.stringify([objetivo, presupuestos[objetivo], radio, pregunta, referencia?.clave, ubicacion]);
  const respuesta = resultado?.firma === firma ? resultado.datos : null;

  useEffect(() => () => peticion.current?.abort(), []);

  async function consultar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (cargando) return;
    if (!referencia && !ubicacion) { setError("Busca o toca una colonia en el mapa, o usa tu ubicación."); return; }
    const controller = new AbortController();
    peticion.current = controller;
    setCargando(true);
    setError(null);
    setResultado(null);
    try {
      const res = await fetch("/api/asesor", {
        method: "POST", headers: { "Content-Type": "application/json" },
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(75_000)]),
        body: JSON.stringify({ objetivo, presupuesto: Number(presupuestos[objetivo]), radioKm: Number(radio), pregunta,
          ...(referencia ? { coloniaClave: referencia.clave } : { ubicacion }),
        }),
      });
      const datos = await res.json();
      if (!res.ok) throw new Error(datos.error || "No se pudo completar la consulta.");
      setResultado({ datos, firma });
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error && err.name === "TimeoutError" ? "La consulta tardó demasiado. Vuelve a intentarlo." : err instanceof Error ? err.message : "No hay conexión con el asistente.");
    } finally { setCargando(false); }
  }

  return (
    <section className="asesor">
      <div className="section-eyebrow">TU PRÓXIMA PARADA</div>
      <h2 className="text-xl font-semibold tracking-tight text-slate-900">Encuentra tu zona</h2>
      <p className="mt-1 text-sm leading-relaxed text-slate-500">Compara colonias con ayuda de Gemini según tu plan, cercanía y presupuesto.</p>
      <form onSubmit={consultar} className="mt-5 space-y-4">
        <fieldset disabled={cargando} className="space-y-4 disabled:opacity-60">
          <legend className="sr-only">Preferencias de tu consulta</legend>
          <div className="purpose-options">
            {OPCIONES.map((o) => <button type="button" key={o.clave} aria-pressed={objetivo === o.clave} onClick={() => { onObjetivo(o.clave); setError(null); }} className={objetivo === o.clave ? "active" : ""}>{o.nombre}</button>)}
          </div>
          <div className="reference-card">
            <span className="section-eyebrow">CERCA DE</span>
            <p className="mt-1 text-sm font-semibold text-slate-800">{referencia?.nombre ?? (ubicacion ? precisionUbicacion === null ? "Punto elegido en el mapa" : "Ubicación del dispositivo" : "Elige una colonia en el mapa")}</p>
            {ubicacion && precisionUbicacion !== null && <p className={`mt-2 text-xs leading-relaxed ${precisionUbicacion > 100 ? "text-amber-800" : "text-slate-500"}`}>Precisión aproximada: ±{Math.ceil(precisionUbicacion)} m.{precisionUbicacion > 100 ? " La ubicación puede estar desplazada. Ajusta el punto antes de buscar cerca." : " Puedes ajustar el punto si no coincide."}</p>}
            <button type="button" onClick={onUbicacion} disabled={ubicando} className="mt-2 text-xs font-semibold text-teal-700 underline underline-offset-4">{ubicando ? "Buscando ubicación…" : "Usar mi ubicación"}</button>
            <button type="button" onClick={onAjustarUbicacion} className="mt-1 block min-h-11 text-xs font-semibold text-teal-700 underline underline-offset-4">Elegir o corregir punto en el mapa</button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="field-label">MXN por {opcion.unidad}
              <input required type="number" inputMode="decimal" min="1" max="1000000" step="1" value={presupuestos[objetivo]} onChange={(e) => setPresupuestos((p) => ({ ...p, [objetivo]: e.target.value }))} />
            </label>
            <label className="field-label">Distancia máxima
              <select value={radio} onChange={(e) => setRadios((r) => ({ ...r, [objetivo]: Number(e.target.value) }))}>
                {DISTANCIAS[objetivo].opciones.map((km) => <option key={km} value={km}>{distanciaLegible(km)}</option>)}
              </select>
            </label>
          </div>
          <label className="field-label">¿Qué necesitas? <span className="font-normal text-slate-400">Opcional</span>
            <textarea rows={3} maxLength={1000} value={pregunta} onChange={(e) => setPregunta(e.target.value)} placeholder={objetivo === "estacionamiento" ? "Quiero dejar mi auto mientras recorro el centro…" : "Viajo en pareja, prefiero caminar y estar cerca de mi destino…"} />
          </label>
          <p className="text-xs leading-relaxed text-slate-500">El presupuesto orienta la consulta. No contamos con precios ni disponibilidad de alojamientos, rentas o estacionamientos.</p>
          <button type="submit" className="primary-button w-full" disabled={!referencia && !ubicacion}>Consultar con Gemini <span aria-hidden>↗</span></button>
        </fieldset>
        {cargando && <div role="status" className="rounded-xl bg-teal-50 p-3 text-sm text-teal-800">Comparando colonias y preparando tu orientación… Puede tardar hasta un minuto; si hay un fallo temporal, reintentaremos automáticamente.</div>}
        {error && <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
        <p className="text-[11px] leading-relaxed text-slate-400">Al consultar, se envían a Gemini tus preferencias y las colonias cercanas. Las coordenadas del dispositivo solo se usan en nuestro servidor para calcular distancias.</p>
      </form>
      {respuesta && <div className="mt-5 space-y-3" aria-live="polite">
        <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-teal-600" /><h3 className="text-sm font-semibold">Tu orientación</h3></div>
        <p className="text-sm leading-relaxed text-slate-700">{respuesta.resumen}</p>
        <p className="text-xs text-slate-500">Referencia: {respuesta.referencia} · distancia aproximada en línea recta hasta la colonia (0 si el punto está dentro). No es la distancia a un establecimiento; la colonia puede extenderse fuera del radio.</p>
        {respuesta.recomendaciones.map((r, i) => <article key={r.clave} className="recommendation-card">
          <div className="flex items-start gap-3"><span className="recommendation-number">{i + 1}</span><div className="min-w-0"><h4 className="font-semibold text-slate-900">{r.nombre}</h4><p className="text-xs text-slate-500">{r.municipio} · {r.distanciaKm === 0 ? "El punto está en esta colonia" : r.distanciaKm < 1 ? distanciaLegible(r.distanciaKm) : `${decimal(r.distanciaKm)} km`}</p></div></div>
          <div className="mt-3 flex flex-wrap gap-1">{r.riesgos.map((riesgo) => <span key={riesgo.perfil} className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">{riesgo.perfil}: {riesgo.estrato ? ETIQUETA_ESTRATO[riesgo.estrato] : "Sin datos"}</span>)}</div>
          <p className="mt-3 text-sm leading-relaxed text-slate-700">{r.motivo}</p>
          <p className="mt-2 text-xs leading-relaxed text-slate-600"><strong>Presupuesto por verificar:</strong> {r.presupuesto}</p>
          <p className="mt-2 text-xs leading-relaxed text-slate-600">{r.precaucion}</p>
          <button type="button" className="mt-3 min-h-11 text-sm font-semibold text-teal-700" onClick={() => onVerColonia(r.clave)}>Ver colonia en el mapa ↗</button>
        </article>)}
        {respuesta.consejos.length > 0 && <ul className="list-disc space-y-2 pl-4 text-xs leading-relaxed text-slate-600">{respuesta.consejos.map((c, i) => <li key={i}>{c}</li>)}</ul>}
        <p className="rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">{respuesta.advertencia} No garantiza seguridad. Periodo: {respuesta.periodo}.</p>
        {respuesta.descartadas > 0 && <p className="text-xs text-slate-500">Se excluyeron {respuesta.descartadas} colonias cercanas con datos insuficientes.</p>}
      </div>}
    </section>
  );
}
