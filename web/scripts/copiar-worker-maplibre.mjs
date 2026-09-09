/**
 * Copia el worker de MapLibre a public/maplibre/ para poder servirlo nosotros.
 *
 * POR QUÉ ES NECESARIO
 *
 * MapLibre 6.x calcula la URL de su worker así:
 *
 *     const url = import.meta.url;
 *     if (!/^https?:/.test(url)) return "";          // <-- aquí
 *     return new URL("./maplibre-gl-worker.mjs", url).href;
 *
 * Empaquetado por Turbopack, `import.meta.url` no es una URL http(s), así que
 * la función devuelve cadena vacía y MapLibre acaba ejecutando
 * `new Worker("", { type: "module" })`. Una URL vacía resuelve al documento
 * actual, el navegador descarga el HTML de la aplicación esperando
 * JavaScript, y falla con:
 *
 *     Failed to load module script: The server responded with a
 *     non-JavaScript MIME type of "text/html"
 *
 * El síntoma es desconcertante: el mapa se construye, el evento `load` se
 * dispara y las teselas raster se dibujan —porque se decodifican en el hilo
 * principal—, pero NINGUNA fuente GeoJSON llega a cargar nunca. La fuente se
 * queda en `loaded() === false` con cero features, sin un solo error en
 * consola, porque su procesamiento vive en el worker que no existe.
 *
 * La solución es pasarle una URL explícita del mismo origen con
 * `setWorkerUrl`, y para eso el archivo tiene que estar en public/.
 *
 * Se copian DOS archivos: el worker importa `./maplibre-gl-shared.mjs` de
 * forma relativa, así que ambos deben quedar en la misma carpeta.
 *
 * Se regenera en cada compilación (scripts `prebuild` y `predev`) en lugar de
 * versionarse en git: si se actualiza maplibre-gl y el worker servido se
 * quedara viejo, el hilo principal y el worker hablarían protocolos distintos
 * y los fallos serían intermitentes e imposibles de rastrear.
 */

import { copyFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ_WEB = path.resolve(AQUI, "..");
const ORIGEN = path.join(RAIZ_WEB, "node_modules", "maplibre-gl", "dist");
const DESTINO = path.join(RAIZ_WEB, "public", "maplibre");

const ARCHIVOS = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

async function main() {
  let version = "desconocida";
  try {
    const pkg = JSON.parse(
      await readFile(
        path.join(RAIZ_WEB, "node_modules", "maplibre-gl", "package.json"),
        "utf-8",
      ),
    );
    version = pkg.version;
  } catch {
    console.error(
      "No se encontró maplibre-gl en node_modules. ¿Corriste npm install?",
    );
    process.exit(1);
  }

  await mkdir(DESTINO, { recursive: true });

  for (const archivo of ARCHIVOS) {
    const desde = path.join(ORIGEN, archivo);
    const hacia = path.join(DESTINO, archivo);
    try {
      await copyFile(desde, hacia);
    } catch (err) {
      console.error(`No se pudo copiar ${archivo}: ${err.message}`);
      console.error(
        "Sin el worker, el mapa carga pero las capas de riesgo quedan vacías.",
      );
      process.exit(1);
    }
  }

  console.log(
    `worker de maplibre-gl ${version} copiado a public/maplibre/ ` +
      `(${ARCHIVOS.join(", ")})`,
  );
}

await main();
