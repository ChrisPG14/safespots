import { test, after, mock } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import * as configuracion from "../lib/configuracion-servidor";
import { DISTANCIAS } from "../lib/preferencias";
import { consultaSchema, prepararContexto, validarRespuesta, type Consulta } from "../lib/asesor";
import { distanciaKm, distanciaAColoniaKm, normalizarBusqueda, puntoColonia, type Colonia, type DatosColonias } from "../lib/geografia";
import type { Meta } from "../lib/tipos";
import { POST } from "../app/api/asesor/route";

const datos: DatosColonias = JSON.parse(readFileSync("public/datos/colonias-riesgo.geojson", "utf8"));
const meta: Meta = JSON.parse(readFileSync("public/datos/meta.json", "utf8"));
const consulta: Consulta = { objetivo: "turismo", presupuesto: 1200, radioKm: 5, coloniaClave: datos.features[0].properties.clave, pregunta: "" };
const originalKey = process.env.GEMINI_API_KEY;
after(() => { if (originalKey === undefined) delete process.env.GEMINI_API_KEY; else process.env.GEMINI_API_KEY = originalKey; mock.restoreAll(); });
const request = (body: unknown, origin = "http://localhost") => new Request("http://localhost/api/asesor", { method: "POST", headers: { "Content-Type": "application/json", origin }, body: JSON.stringify(body) });

// Casos de frontera que podrían convertir datos insuficientes en recomendaciones.
test("valida límites y exige exactamente una referencia", () => {
  assert.ok(consultaSchema.safeParse(consulta).success);
  assert.ok(!consultaSchema.safeParse({ ...consulta, presupuesto: -1 }).success);
  assert.ok(!consultaSchema.safeParse({ ...consulta, radioKm: 31 }).success);
  assert.ok(!consultaSchema.safeParse({ ...consulta, coloniaClave: undefined }).success);
  assert.ok(!consultaSchema.safeParse({ ...consulta, ubicacion: [-103.3, 20.6] }).success);
  assert.ok(!consultaSchema.safeParse({ ...consulta, pregunta: "x".repeat(1001) }).success);
});

test("límites específicos: auto 100 m–1 km, hospedaje 500 m–5 km y renta 1–30 km", async () => {
  for (const objetivo of ["turismo", "renta", "estacionamiento"] as const) {
    const opciones = DISTANCIAS[objetivo].opciones;
    for (const radioKm of opciones) assert.ok(consultaSchema.safeParse({ ...consulta, objetivo, radioKm }).success);
    for (const radioKm of [opciones[0] - 0.01, opciones[opciones.length - 1] + 0.01]) {
      assert.ok(!consultaSchema.safeParse({ ...consulta, objetivo, radioKm }).success);
      assert.equal((await POST(request({ ...consulta, objetivo, radioKm }))).status, 400);
    }
  }
});

test("lee .env raíz sin publicar secretos ni sustituir variables del servidor", () => {
  const carpeta = mkdtempSync(path.join(tmpdir(), "entorno-env-"));
  const archivo = path.join(carpeta, ".env");
  try {
    writeFileSync(archivo, 'GEMINI_API_KEY="clave-de-prueba"\nGEMINI_MODEL=modelo-prueba\nDATABASE_URL=no-se-exporta\n');
    assert.deepEqual(configuracion.configuracionGemini({}, archivo), { apiKey: "clave-de-prueba", modelo: "modelo-prueba" });
    assert.deepEqual(configuracion.configuracionGemini({ GEMINI_API_KEY: "clave-servidor", GEMINI_MODEL: "modelo-servidor" }, archivo), { apiKey: "clave-servidor", modelo: "modelo-servidor" });
    writeFileSync(archivo, "GEMINI_API_KEY=\n");
    assert.equal(configuracion.configuracionGemini({}, archivo).apiKey, "");
    // Se vuelve a leer: guardar la clave en la raíz no requiere reinicio.
    writeFileSync(archivo, "GEMINI_API_KEY=clave-nueva\n");
    assert.equal(configuracion.configuracionGemini({}, archivo).apiKey, "clave-nueva");
    assert.equal(configuracion.configuracionGemini({}, path.join(carpeta, "no-existe")).apiKey, "");
  } finally { rmSync(carpeta, { recursive: true, force: true }); }
});

test("todas las geometrías reales producen puntos finitos y la búsqueda ignora acentos", () => {
  for (const f of datos.features) assert.ok(puntoColonia(f).every(Number.isFinite));
  assert.equal(normalizarBusqueda("  Jardínes de ZÚÑIGA "), "jardines de zuniga");
  assert.equal(distanciaKm([-103, 20], [-103, 20]), 0);
});

test("el punto interior evita el hueco de un polígono", () => {
  const f: Colonia = { ...datos.features[0], geometry: { type: "Polygon", coordinates: [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]],
  ] } };
  const [x, y] = puntoColonia(f);
  assert.equal(y, 5);
  assert.ok(x < 3 || x > 7);
  assert.equal(distanciaAColoniaKm([1, 1], f), 0);
  assert.equal(distanciaAColoniaKm([0, 1], f), 0);
  assert.ok(distanciaAColoniaKm([5, 5], f) > 200);
  assert.ok(distanciaAColoniaKm([-0.001, 1], f) > 0.1);
  assert.ok(distanciaAColoniaKm([-0.001, 1], f) < 0.12);
});

test("filtra distancia exacta y muestras insuficientes para los tres objetivos", () => {
  for (const objetivo of ["turismo", "renta", "estacionamiento"] as const) {
    const radioKm = DISTANCIAS[objetivo].inicial;
    const contexto = prepararContexto({ ...consulta, objetivo, radioKm }, datos, meta);
    assert.ok(contexto.candidatos.length > 0);
    for (const c of contexto.candidatos) {
      const f = datos.features.find((f) => f.properties.clave === c.clave)!;
      assert.ok(distanciaAColoniaKm(puntoColonia(datos.features[0]), f) <= radioKm);
      assert.ok(c.riesgos.every((r) => !r.muestraBaja && r.indice !== null));
      if (objetivo === "estacionamiento") assert.equal(c.riesgos[0].perfil, "Riesgo vehicular");
    }
  }
  assert.equal(prepararContexto({ ...consulta, coloniaClave: undefined, ubicacion: [0, 0] }, datos, meta).candidatos.length, 0);
  assert.throws(() => prepararContexto({ ...consulta, coloniaClave: "inventada" }, datos, meta));
});

test("rechaza colonias inventadas y duplicadas; conserva métricas del dataset", () => {
  const candidatos = prepararContexto(consulta, datos, meta).candidatos;
  const recomendacion = { clave: candidatos[0].clave, motivo: "Comparación histórica", presupuesto: "Verificar precio", precaucion: "Confirmar condiciones actuales", nombre: "Nombre inventado", distanciaKm: 999 };
  const respuesta = { resumen: "Orientación", recomendaciones: [recomendacion], consejos: [] };
  const validada = validarRespuesta(respuesta, candidatos);
  assert.equal(validada.recomendaciones[0].nombre, candidatos[0].nombre);
  assert.equal(validada.recomendaciones[0].distanciaKm, candidatos[0].distanciaKm);
  assert.throws(() => validarRespuesta({ ...respuesta, recomendaciones: [{ ...recomendacion, clave: "inventada" }] }, candidatos));
  assert.throws(() => validarRespuesta({ ...respuesta, recomendaciones: [recomendacion, recomendacion] }, candidatos));
});

test("API: errores de entrada, origen y configuración sin llamar a Gemini", async () => {
  delete process.env.GEMINI_API_KEY;
  const sinClave = mock.method(configuracion, "configuracionGemini", () => ({ apiKey: "", modelo: "modelo-prueba" }));
  try {
  assert.equal((await POST(request(consulta, "https://ajeno.example"))).status, 403);
  assert.equal((await POST(request({ ...consulta, presupuesto: 0 }))).status, 400);
  assert.equal((await POST(request({ ...consulta, pregunta: "x".repeat(9000) }))).status, 413);
  assert.equal((await POST(request(consulta))).status, 503);
  assert.equal((await POST(new Request("http://localhost/api/asesor", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{" }))).status, 400);
  } finally { sinClave.mock.restore(); }
});

test("API: ida y vuelta estructurada, cuota, timeout, contenido inventado y referencia fuera de cobertura", async () => {
  process.env.GEMINI_API_KEY = "clave-falsa-para-pruebas";
  const fetchMock = mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body));
    const contexto = JSON.parse(body.contents[0].parts[0].text);
    assert.equal(contexto.presupuestoMXN, consulta.presupuesto);
    assert.equal(contexto.objetivo, consulta.objetivo);
    assert.equal(contexto.ubicacion, undefined);
    assert.ok(body.generationConfig.responseJsonSchema);
    return Response.json({ candidates: [{ finishReason: "STOP", content: { parts: [{ text: JSON.stringify({ resumen: "Orientación con datos históricos", recomendaciones: [{ clave: contexto.candidatos[0].clave, motivo: "Menor índice histórico y cercanía", presupuesto: "Confirma la tarifa por noche", precaucion: "Verifica condiciones actuales" }], consejos: ["Revisar reseñas recientes"] }) }] } }] });
  });
  const res = await POST(request(consulta));
  assert.equal(res.status, 200);
  const json = await res.json();
  assert.equal(json.recomendaciones.length, 1);
  assert.equal(json.advertencia, meta.advertencia_principal);
  assert.equal(res.headers.get("Cache-Control"), "no-store");
  const llamadas = fetchMock.mock.callCount();
  assert.equal((await POST(request({ ...consulta, coloniaClave: "inexistente" }))).status, 400);
  const sinDatos = await POST(request({ ...consulta, coloniaClave: undefined, ubicacion: [0, 0] }));
  assert.equal((await sinDatos.json()).recomendaciones.length, 0);
  assert.equal(fetchMock.mock.callCount(), llamadas);
  fetchMock.mock.mockImplementation(async () => Response.json({}, { status: 429 }));
  assert.equal((await POST(request(consulta))).status, 429);
  fetchMock.mock.mockImplementation(async () => { throw new DOMException("Timeout", "TimeoutError"); });
  assert.equal((await POST(request(consulta))).status, 504);
  fetchMock.mock.mockImplementation(async () => Response.json({ candidates: [{ finishReason: "STOP", content: { parts: [{ text: '{"resumen":"x","recomendaciones":[{"clave":"inventada","motivo":"x","presupuesto":"x","precaucion":"x"}],"consejos":[]}' }] } }] }));
  assert.equal((await POST(request(consulta))).status, 502);
  fetchMock.mock.mockImplementation(async () => Response.json({ candidates: [{ finishReason: "MAX_TOKENS" }] }));
  assert.equal((await POST(request(consulta))).status, 502);
  fetchMock.mock.restore();
});
