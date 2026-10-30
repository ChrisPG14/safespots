import { setTimeout as pausa } from "node:timers/promises";

const TEMPORALES = new Set([500, 502, 503, 504]);
export class ErrorConexionGemini extends Error {
  constructor() { super("No se pudo conectar con Gemini."); this.name = "ErrorConexionGemini"; }
}

/** Hasta tres intentos, con un único plazo total impuesto por el llamador.
 * No reintenta cuotas, credenciales, modelos inexistentes ni contenido inválido. */
export async function consultarGemini(
  url: string,
  opciones: RequestInit & { signal: AbortSignal },
  dependencias = {
    fetch: globalThis.fetch,
    esperar: (ms: number, signal: AbortSignal) => pausa(ms, undefined, { signal }),
  },
) {
  for (let intento = 1; intento <= 3; intento++) {
    opciones.signal.throwIfAborted();
    let respuesta: Response;
    try {
      respuesta = await dependencias.fetch(url, opciones);
    } catch (error) {
      opciones.signal.throwIfAborted();
      if (error instanceof Error && ["AbortError", "TimeoutError"].includes(error.name)) throw error;
      if (intento === 3) throw new ErrorConexionGemini();
      await dependencias.esperar(500 * 2 ** (intento - 1), opciones.signal);
      continue;
    }
    if (!TEMPORALES.has(respuesta.status) || intento === 3) return { respuesta, intentos: intento };
    const retryAfter = respuesta.headers.get("retry-after");
    const segundos = retryAfter ? Number(retryAfter) : NaN;
    const esperaProveedor = retryAfter
      ? Number.isFinite(segundos) ? segundos * 1000 : Date.parse(retryAfter) - Date.now()
      : 0;
    // No ocupar el plazo total con esperas largas solicitadas por el proveedor.
    if (esperaProveedor > 3000) return { respuesta, intentos: intento };
    await respuesta.body?.cancel();
    await dependencias.esperar(Math.max(500 * 2 ** (intento - 1), Number.isFinite(esperaProveedor) ? esperaProveedor : 0), opciones.signal);
  }
  throw new ErrorConexionGemini();
}
