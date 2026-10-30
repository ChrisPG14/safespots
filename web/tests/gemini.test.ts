import { test } from "node:test";
import assert from "node:assert/strict";
import { consultarGemini, ErrorConexionGemini } from "../lib/gemini";

const url = "https://example.test/gemini";
const opciones = () => ({ method: "POST", body: "{}", signal: AbortSignal.timeout(5000) });

test("Gemini: recupera un 503 y un 502 sin cambiar el cuerpo ni el plazo", async () => {
  const init = opciones();
  const esperas: number[] = [];
  let llamadas = 0;
  const resultado = await consultarGemini(url, init, {
    fetch: async (_url, recibidas) => {
      assert.equal(recibidas, init);
      return Response.json({}, { status: [503, 502, 200][llamadas++] });
    },
    esperar: async (ms, signal) => { assert.equal(signal, init.signal); esperas.push(ms); },
  });
  assert.equal(resultado.respuesta.status, 200);
  assert.equal(resultado.intentos, 3);
  assert.deepEqual(esperas, [500, 1000]);
});

test("Gemini: una caída persistente termina tras tres intentos", async () => {
  let llamadas = 0;
  const resultado = await consultarGemini(url, opciones(), {
    fetch: async () => { llamadas++; return Response.json({}, { status: 503 }); },
    esperar: async () => {},
  });
  assert.equal(resultado.respuesta.status, 503);
  assert.equal(llamadas, 3);
});

test("Gemini: no reintenta credenciales, modelo, cuota ni una respuesta exitosa", async () => {
  for (const status of [200, 400, 401, 403, 404, 429]) {
    let llamadas = 0;
    const resultado = await consultarGemini(url, opciones(), {
      fetch: async () => { llamadas++; return Response.json({}, { status }); },
      esperar: async () => { assert.fail("No debe esperar"); },
    });
    assert.equal(resultado.respuesta.status, status);
    assert.equal(llamadas, 1);
  }
});

test("Gemini: respeta Retry-After y no insiste ante una espera larga", async () => {
  let llamadas = 0;
  const esperas: number[] = [];
  await consultarGemini(url, opciones(), {
    fetch: async () => Response.json({}, { status: ++llamadas === 1 ? 503 : 200, headers: { "retry-after": "2" } }),
    esperar: async (ms) => { esperas.push(ms); },
  });
  assert.deepEqual(esperas, [2000]);
  const resultado = await consultarGemini(url, opciones(), {
    fetch: async () => Response.json({}, { status: 503, headers: { "retry-after": "60" } }),
    esperar: async () => { assert.fail("No debe esperar un minuto"); },
  });
  assert.equal(resultado.intentos, 1);
});

test("Gemini: limita fallos de red y puede recuperarse del primero", async () => {
  let llamadas = 0;
  const resultado = await consultarGemini(url, opciones(), {
    fetch: async () => { if (++llamadas === 1) throw new TypeError("fetch failed"); return Response.json({}); },
    esperar: async () => {},
  });
  assert.equal(resultado.intentos, 2);
  llamadas = 0;
  await assert.rejects(consultarGemini(url, opciones(), {
    fetch: async () => { llamadas++; throw new TypeError("fetch failed"); },
    esperar: async () => {},
  }), ErrorConexionGemini);
  assert.equal(llamadas, 3);
});

test("Gemini: cancelar o agotar el plazo detiene los reintentos", async () => {
  const controller = new AbortController();
  let llamadas = 0;
  await assert.rejects(consultarGemini(url, { ...opciones(), signal: controller.signal }, {
    fetch: async () => { llamadas++; return Response.json({}, { status: 503 }); },
    esperar: async () => { controller.abort(); },
  }), { name: "AbortError" });
  assert.equal(llamadas, 1);
  await assert.rejects(consultarGemini(url, opciones(), {
    fetch: async () => { throw new DOMException("timeout", "TimeoutError"); },
    esperar: async () => { assert.fail("No debe reintentar después de agotar el plazo"); },
  }), { name: "TimeoutError" });
});
