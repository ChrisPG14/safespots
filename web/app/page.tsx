import { readFile } from "node:fs/promises";
import path from "node:path";

import MapaRiesgo from "@/components/MapaRiesgo";
import type { Meta } from "@/lib/tipos";

/**
 * El metadato se lee del sistema de archivos en el servidor, no con fetch en
 * el navegador. Así viaja dentro del HTML inicial: la interfaz puede rotular
 * el periodo y mostrar la advertencia sobre la antigüedad de los datos desde
 * el primer pintado, sin un salto visual ni una petición extra.
 *
 * El GeoJSON sí se pide desde el cliente, porque son casi 3 MB y no tiene
 * sentido incrustarlos en el HTML.
 */
async function leerMeta(): Promise<Meta> {
  const ruta = path.join(process.cwd(), "public", "datos", "meta.json");
  const contenido = await readFile(ruta, "utf-8");
  return JSON.parse(contenido) as Meta;
}

export default async function Pagina() {
  let meta: Meta;
  try {
    meta = await leerMeta();
  } catch {
    // Falla útil: si el ETL no ha corrido, decir exactamente qué hacer en
    // lugar de mostrar una pantalla en blanco o un error de Next.js.
    return (
      <main className="flex min-h-dvh items-center justify-center bg-stone-100 p-6">
        <div className="max-w-lg rounded-lg border border-stone-300 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-stone-900">
            Faltan los datos del mapa
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-stone-600">
            No se encontró{" "}
            <code className="rounded bg-stone-100 px-1 py-0.5 text-xs">
              web/public/datos/meta.json
            </code>
            . Ese archivo lo produce el ETL a partir de las fuentes oficiales.
          </p>
          <p className="mt-3 text-sm text-stone-600">Desde la raíz del proyecto:</p>
          <pre className="mt-2 overflow-x-auto rounded bg-stone-900 p-3 text-xs leading-relaxed text-stone-100">
            {`cd etl
.venv/bin/python -m georisk.cli descargar
PYTHONPATH=. .venv/bin/python -m georisk.cli construir`}
          </pre>
        </div>
      </main>
    );
  }

  return (
    <main className="h-dvh w-full overflow-hidden">
      <MapaRiesgo meta={meta} />
    </main>
  );
}
