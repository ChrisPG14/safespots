# SafeSpots — aplicación web

Interfaz de SafeSpots: mapa de riesgo por colonia de la Zona Metropolitana de
Guadalajara y asistente de orientación.

**La documentación del proyecto vive en el [README de la raíz](../README.md).**
Ahí están la metodología, las fuentes, los resultados medidos y la
correspondencia con el reporte académico. Este archivo cubre solo lo específico
de la aplicación web.

## Desarrollo

```bash
npm install
npm run dev     # http://localhost:3000
```

El mapa lee `public/datos/colonias-riesgo.geojson` y `public/datos/meta.json`,
que **produce el ETL**, no la aplicación. Si faltan, la página lo dice y explica
qué comando correr. Para regenerarlos:

```bash
cd ../etl && PYTHONPATH=. .venv/bin/python -m georisk.cli construir
```

## Asistente

Para habilitarlo, pon una clave de [Google AI Studio](https://aistudio.google.com/apikey)
en el `.env` **de la raíz del proyecto** (no en `web/`):

```dotenv
GEMINI_API_KEY=tu_clave
GEMINI_MODEL=gemini-3.6-flash
```

**No hace falta reiniciar el servidor:** `configuracionGemini()` relee el archivo
en cada petición. Guardar el `.env` basta.

También se admiten variables de entorno del despliegue o un `web/.env.local`,
que tienen prioridad sobre el `.env` de la raíz. La clave se usa únicamente en el
servidor; nunca con el prefijo `NEXT_PUBLIC_`, que la publicaría en el navegador.

Sin clave, el mapa funciona igual y el asistente responde que todavía no está
habilitado, con HTTP 503 y un mensaje explícito.

### Cómo usarlo

1. Busca o toca una colonia, o pulsa **Mi ubicación** (requiere permiso del
   navegador y HTTPS, salvo en localhost).
2. Abre **Asistente IA**, elige turismo, renta o estacionamiento e indica tu
   máximo en MXN por noche, mes u hora respectivamente.
3. Elige el radio y, opcionalmente, escribe tus preferencias.

### Qué hace el endpoint

`POST /api/asesor` valida la consulta, lee los datos en el servidor, filtra por
radio con la distancia a la **superficie** de la colonia —no a su centro— y
descarta las muestras insuficientes. Ordena hasta 24 candidatas por el promedio
de los índices relevantes más una penalización por distancia de hasta 20 puntos.
Gemini recibe esa lista y redacta; las identidades y métricas de la respuesta se
validan contra ella, así que el modelo no puede inventar colonias.

Las coordenadas del dispositivo **no se envían al proveedor**: se usan solo en
nuestro servidor para calcular distancias.

Usa [salida estructurada](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).
Hay un plazo total de 60 s, con hasta tres intentos ante fallos de red o
HTTP 500/502/503/504, esperas de 0.5 y 1 s y respeto de `Retry-After`. No se
reintentan cuotas, claves rechazadas, modelos inexistentes ni respuestas
incompletas. El servidor registra solo modelo, código HTTP e intentos; nunca
claves, coordenadas ni preferencias. El cliente espera hasta 75 s; con
`gemini-3.6-flash` se usa razonamiento `low` para reducir latencia, según la
[configuración de pensamiento de Gemini](https://ai.google.dev/gemini-api/docs/generate-content/thinking). Hay manejo de cuota y de respuesta incompleta, y un tope de 20
consultas por minuto con 3 concurrentes **por proceso**. Un despliegue con varias
instancias necesita además cuota compartida o autenticación.

### Alcance de las recomendaciones

El dataset termina en **febrero de 2021**. No hay seguridad en tiempo real,
inventario de alojamientos, precios, disponibilidad ni estacionamientos
verificados. El presupuesto orienta qué verificar; no garantiza que una colonia
tenga ofertas dentro de ese importe. El perfil vehicular incluye homicidio
culposo además de los robos relacionados con vehículos.

## Verificación

```bash
npm test         # pruebas con Gemini simulado, sin gastar cuota
npm run lint
npm run build
```

## Notas de implementación

Dos incompatibilidades documentadas en detalle en el README de la raíz, que
conviene conocer antes de tocar el mapa:

- **El worker de MapLibre** no funciona bajo el empaquetador de Next.js sin
  `setWorkerUrl`. El síntoma es un mapa que carga sin errores pero cuyas capas
  de datos nunca aparecen. Lo resuelve `scripts/copiar-worker-maplibre.mjs`, que
  corre solo en `predev` y `prebuild`.
- **El CSS de MapLibre vence a Tailwind** en el contenedor del mapa: su regla
  `position: relative` gana al utilitario `absolute`. La altura se da con
  `h-full`.

## Marca

El logotipo es una sola silueta que lee como escudo y como pin de mapa a la vez,
con el punto central **calado** para que funcione en un solo color sobre
cualquier fondo. Vive en dos lugares que deben mantenerse iguales:
[`components/Logo.tsx`](components/Logo.tsx) para la cabecera y
[`app/icon.svg`](app/icon.svg) para el favicon.
