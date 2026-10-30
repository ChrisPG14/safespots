import { readFileSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";

/** Solo se importa desde el servidor. No copia secretos a next.config.env. */
export function configuracionGemini(
  // Se tipa como registro de cadenas y NO como NodeJS.ProcessEnv porque la
  // función solo lee dos claves. Exigir ProcessEnv obliga a quien la llame a
  // construir un entorno completo con NODE_ENV: las pruebas pasaban un objeto
  // parcial y `next build` fallaba con "Failed to type check", aunque
  // `npm test` compilara bien por usar otra configuración de TypeScript.
  entorno: Record<string, string | undefined> = process.env,
  archivoRaiz = path.resolve(process.cwd(), "..", ".env"),
) {
  let raiz: Record<string, string | undefined> = {};
  if (!entorno.GEMINI_API_KEY?.trim() || !entorno.GEMINI_MODEL?.trim()) {
    try {
      raiz = parseEnv(readFileSync(archivoRaiz, "utf8"));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  // Las variables del despliegue y de web/.env.local tienen prioridad.
  return {
    apiKey: entorno.GEMINI_API_KEY?.trim() || raiz.GEMINI_API_KEY?.trim() || "",
    modelo: entorno.GEMINI_MODEL?.trim() || raiz.GEMINI_MODEL?.trim() || "gemini-3.6-flash",
  };
}
