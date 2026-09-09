# Riesgo delictivo por colonia — Zona Metropolitana de Guadalajara

Plataforma web que mapea la incidencia delictiva por colonia en los seis
municipios del núcleo de la ZMG, a partir de datos oficiales, con un índice de
riesgo por perfil de usuario: peatonal, vehicular, residencial y comercial.

Proyecto Modular · Christian Moisés de Alba Velarde · CUCEI, Universidad de
Guadalajara.

---

## Antes que nada: lo que los datos públicos permiten y lo que no

Esta sección va primero porque condiciona todo el diseño, y porque el
documento original del proyecto partía de un supuesto que resultó falso.

**No existe ninguna fuente pública de delitos geolocalizados para la ZMG.**
Se verificó fuente por fuente:

| Fuente | Qué publica | Sirve para |
|---|---|---|
| **IIEG — incidencia por colonia** | 241,702 registros de delito por **colonia**, municipio, año y mes. 2016 a **feb 2021**. 20 tipos de delito. | **El núcleo de este proyecto.** Única fuente pública que baja de nivel municipal. |
| IIEG — colonias (shapefile) | Polígonos de 6,624 colonias de Jalisco con 232 campos censales. | Las geometrías del mapa y la población. |
| INEGI — Marco Geoestadístico 2025 | Municipios, localidades, AGEB, manzanas. **No publica colonias.** | Contexto municipal. |
| INEGI — Censo 2020 por AGEB | Población a nivel AGEB. | Denominadores alternativos. |
| SESNSP — Datos Abiertos | Conteos mensuales **solo por municipio**. Sin coordenadas, sin colonia, sin hora. | Tendencia reciente, no detalle geográfico. |

Consecuencias concretas, todas asumidas en el código y visibles en la interfaz:

1. **DBSCAN y KDE sobre delitos no son implementables con datos públicos.**
   El clustering espacial de densidad necesita incidentes con coordenadas, y
   no existen. El esquema conserva las tablas `incidente` y `hotspot` para
   cuando se consigan datos puntuales, pero hoy están vacías y el módulo
   correspondiente no se muestra.
2. **No hay análisis nocturno.** La fuente no registra la hora del hecho, así
   que el perfil se llama "peatonal" y no "peatón nocturno". La interfaz lo
   dice explícitamente.
3. **La serie termina en febrero de 2021**, porque el IIEG descontinuó esa
   publicación (se verificó que las entregas posteriores devuelven 404). El
   mapa describe un patrón histórico, no la situación actual, y lo advierte de
   forma visible.

Si se necesita delito geolocalizado y actual, la única vía es una solicitud de
transparencia al C5 Jalisco o a la Fiscalía del Estado pidiendo carpetas de
investigación con colonia y hora. Los datos existen internamente; no son
públicos.

---

## Arquitectura

```
Fuentes oficiales           ETL (Python)              Publicación
─────────────────           ────────────              ───────────
IIEG colonias (SHP)   ──┐
IIEG incidencia (CSV) ──┼──▶  georisk/         ──┬──▶ PostgreSQL + PostGIS
INEGI Marco Geo (SHP) ──┤     empate, índice     │    (registro y análisis)
INEGI Censo (CSV)     ──┘     de riesgo          │
                                                 └──▶ GeoJSON estático
                                                      ──▶ Next.js + MapLibre
```

**Por qué la web no consulta la base en cada visita.** La capa de riesgo son
2,068 colonias: unos 2.8 MB de GeoJSON simplificado. Servirla como archivo
estático desde el CDN de Vercel es instantáneo, gratuito, y evita el arranque
en frío de Neon, que suspende el cómputo tras cinco minutos de inactividad
—justo el patrón de uso de un proyecto académico—. PostGIS sigue siendo el
sistema de registro: ahí viven las series completas, los índices GiST y la
bitácora de cada carga.

**Stack**

- **Frontend:** Next.js 16 + React 19 + Tailwind 4 + MapLibre GL 6
- **ETL y modelado:** Python 3.14, GeoPandas, pandas, scikit-learn, RapidFuzz
- **Base de datos:** PostgreSQL 17 + PostGIS 3.5
- **Despliegue:** Vercel (web) + Neon (base de datos)

---

## Puesta en marcha

### Requisitos

- Node.js 24 o superior
- Python 3.12 o superior
- Docker (solo para la base local) o una base en Neon
- `psql` (solo para aplicar migraciones)

### 1. ETL: descargar datos y generar el mapa

```bash
cd etl
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Descarga las fuentes oficiales a data/raw/ (unos 170 MB, con caché)
PYTHONPATH=. .venv/bin/python -m georisk.cli descargar

# Procesa todo y escribe el GeoJSON que consume la web
PYTHONPATH=. .venv/bin/python -m georisk.cli construir --top 10
```

`construir` tarda unos cinco segundos y reporta la **cobertura del empate de
colonias**, que es el indicador de calidad más importante del pipeline. Si baja
del 80% avisa de forma explícita: significa que la fuente cambió su forma de
escribir los nombres y hay que revisar `etl/georisk/nombres.py`.

### 2. Web

```bash
cd web
npm install
npm run dev     # http://localhost:3000
```

### 3. Base de datos (opcional para ver el mapa, necesaria para el análisis)

```bash
docker compose up -d
./db/apply.sh "postgresql://geo:geo@localhost:5433/georisk"

cd etl
PYTHONPATH=. .venv/bin/python -m georisk.cli cargar-db
```

---

## Comandos del ETL

| Comando | Qué hace |
|---|---|
| `georisk.cli info` | Catálogo de fuentes, su estado de descarga y sus limitaciones |
| `georisk.cli descargar` | Baja las fuentes a `data/raw/` con caché y huella SHA-256 |
| `georisk.cli construir` | Pipeline completo: empate, índice y exportación del mapa |
| `georisk.cli cargar-db` | Carga geografía, incidencia y riesgo a PostGIS |

Opciones útiles de `construir`:

- `--top N` — muestra las N colonias de mayor riesgo por perfil. **Conviene
  revisar esta salida en cada cambio del método:** si aparecen colonias que
  nadie reconocería como zonas de alta incidencia, casi siempre el denominador
  está mal.
- `--meses N` — ventana de análisis. Por omisión usa toda la serie (62 meses).
- `--amg-completa` — los 10 municipios del AMG en lugar de los 6 del núcleo.
- `--sin-fusionar` — diagnóstico: no une polígonos homónimos.

---

## Cómo funciona el índice de riesgo

1. **Filtrar** los delitos del perfil según sus banderas (`afecta_peaton`,
   `afecta_vehiculo`, …).
2. **Ponderar** cada delito por su severidad (escala 1-10, definida en
   `etl/georisk/taxonomia.py`; es un juicio del proyecto, no un dato de la
   fuente, y por eso está versionado y documentado).
3. **Normalizar** por el denominador que le corresponde al perfil.
4. **Suavizar** con contracción bayesiana hacia la media metropolitana.
5. **Comprimir** con logaritmo y escalar a 0-100.
6. **Estratificar** por cuantiles: bajo (<p50), moderado (p50-p75), alto
   (p75-p90), crítico (>p90).

### Las dos decisiones metodológicas que más importan

**El denominador depende del perfil.** A quien camina por una zona le importa
cuántos delitos ocurren en ese territorio, no la proporción respecto a quienes
viven ahí. A quien compra una casa le importa lo contrario. Por eso los
perfiles peatonal, vehicular y comercial se normalizan **por km²**, y el
general y el residencial **por 100 mil habitantes**.

Usar población para todo produce el error clásico de estos mapas: el Centro de
Guadalajara tiene 2,585 residentes censados pero cientos de miles de personas
circulando a diario, así que dividir entre residentes lo pinta como la zona más
peligrosa del planeta. En una versión previa de este código, "La Loma" en
Tonalá salía con 488,206 delitos por 100 mil habitantes.

**La contracción bayesiana evita que el ruido gane.** Una colonia de 80
habitantes con 3 robos tiene una tasa altísima sin que haya evidencia
suficiente para afirmar nada. El suavizado jala esas estimaciones hacia el
promedio metropolitano en proporción a lo poco que se sabe de ellas, como hacen
los atlas de mortalidad. Además se calculan intervalos de confianza de Poisson
por el método de Byar, y las unidades con muestra insuficiente se marcan y se
dibujan translúcidas en el mapa.

---

## El empate de nombres de colonia

Es la parte más costosa del proyecto y donde se concentran los riesgos de
error. La incidencia identifica la colonia por **nombre**, escrito por
capturistas distintos a lo largo de cinco años; los polígonos usan otro nombre,
más formal. `etl/georisk/nombres.py` resuelve el cruce en cuatro pasos, del más
al menos confiable: exacto con abreviaturas expandidas, nombres alternativos
que el padrón declara entre paréntesis, tokens ordenados, y difuso con guardas.

**Cobertura actual: 84.4% de todos los incidentes** (90.7% de los que traen
nombre de colonia). El resto se reporta, no se esconde: 6% viene sin colonia en
la fuente y 9.7% son colonias que no existen en el padrón de polígonos —
Lafayette, Santuario y Capilla de Jesús son colonias reales de Guadalajara que
el padrón del IIEG, basado en secciones electorales agrupadas, no contiene.

Dos errores que se encontraron y corrigieron aquí, por si sirven de advertencia:

- **`token_set_ratio` es inservible para esto.** Devuelve 100 cuando los
  tokens de un nombre son subconjunto del otro, así que "La Loma" absorbía
  "Loma Dorada Delegación A/B/C/D", "Loma del Zalate" y "Loma Linda":
  concentraba 2,935 incidentes en una colonia que tenía 18. El código usa
  `token_sort_ratio` con guardas que exigen que coincidan los puntos
  cardinales, los números y las letras de sección.
- **El padrón parte colonias en pedazos homónimos.** Guadalajara tiene dos
  polígonos "Oblatos", de 9,087 y 26,844 habitantes. Asignar todos los delitos
  a uno infla su tasa casi cuatro veces. El ETL los fusiona en una sola unidad
  de análisis (107 grupos, 225 polígonos).

---

## Estructura

```
app/
├── db/
│   ├── migrations/          esquema PostGIS, aplicado en orden
│   └── apply.sh             aplica lo pendiente, idempotente
├── etl/
│   ├── requirements.txt
│   └── georisk/
│       ├── config.py        alcance, rutas, CRS
│       ├── fuentes.py       catálogo de fuentes y descarga con caché
│       ├── taxonomia.py     delitos canónicos, severidades, perfiles
│       ├── nombres.py       normalización y empate de colonias
│       ├── geografia.py     carga de polígonos
│       ├── incidencia.py    carga de incidencia delictiva
│       ├── riesgo.py        cálculo del índice
│       ├── exportar.py      GeoJSON y metadatos para la web
│       ├── carga_db.py      escritura a PostGIS
│       └── cli.py           línea de comandos
├── web/
│   ├── app/                 páginas (App Router)
│   ├── components/          mapa
│   ├── lib/                 tipos y paleta
│   ├── scripts/             copia del worker de MapLibre
│   └── public/datos/        GeoJSON y meta.json que produce el ETL
├── data/                    descargas y resultados (no se versiona)
└── docker-compose.yml       PostGIS local
```

---

## Notas de implementación que ahorran horas

**El worker de MapLibre bajo Next.js.** MapLibre 6 deduce la URL de su worker
de `import.meta.url`; empaquetado por Turbopack esa URL no es `http(s)`, la
función devuelve cadena vacía y MapLibre ejecuta `new Worker("")`, que apunta al
propio HTML de la página. El síntoma es cruel: el mapa se construye, el evento
`load` se dispara, las teselas raster se dibujan, y **ninguna fuente GeoJSON
carga nunca, sin un solo error en consola**. La solución es servir el worker
desde `public/` y pasar la URL con `setWorkerUrl`; lo automatiza
`web/scripts/copiar-worker-maplibre.mjs` en cada compilación.

**El CSS de MapLibre vence a Tailwind.** MapLibre le agrega al contenedor la
clase `maplibregl-map`, cuya regla `position: relative` gana al utilitario
`absolute` de Tailwind. Si la altura del contenedor dependía de
`absolute inset-0`, el div queda con altura cero y el mapa no aparece. La altura
se da con `h-full`.

**Los CRS de las fuentes oficiales no son WGS84.** El Marco Geoestadístico del
INEGI viene en EPSG:6372 y las colonias del IIEG en EPSG:32613. Ignorarlo
coloca toda la ZMG en medio del océano. Los cálculos métricos —áreas,
distancias— se hacen proyectados en UTM 13N, nunca en grados.

---

## Trabajo pendiente

- Integrar el SESNSP municipal como capa de tendencia reciente, etiquetada como
  interpolación y no como detalle geográfico.
- Módulo de seguridad vial peatonal con `iieg:siniestros`, que **sí** tiene
  puntos con coordenadas y franjas horarias de dos horas, pero solo del año
  2019 y son atropellamientos, no delitos. Debe ir como capa separada y
  rotulada con honestidad, no fusionada con el índice delictivo.
- Solicitud de transparencia al C5 Jalisco por carpetas con colonia y hora.
- Módulo de valuación inmobiliaria: cruzar el estrato de riesgo con precio por
  metro cuadrado.
- Aplicación móvil, reutilizando el mismo GeoJSON y metadatos.

---

## Fuentes y licencia

Datos de incidencia delictiva y polígonos de colonia: **IIEG Jalisco**, con
datos de la Fiscalía del Estado. Cartografía y censo: **INEGI**. Mapa base:
**OpenStreetMap**. Cada fuente queda registrada con su URL y su huella SHA-256
en `data/raw/manifiesto.json` y en la tabla `lote_ingesta`.

Código bajo licencia MIT.
