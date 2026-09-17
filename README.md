# SafeSpots — Riesgo delictivo por colonia en la ZMG

Plataforma web que mapea la incidencia delictiva por colonia en la Zona
Metropolitana de Guadalajara a partir de datos oficiales, la convierte en un
índice de riesgo por perfil de usuario, y ofrece orientación asistida por un
modelo de lenguaje para tres decisiones concretas: dónde alojarse, dónde rentar
y dónde dejar el auto.

**Proyecto Modular** · Christian Moisés de Alba Velarde · Departamento de
Ciencias Computacionales, CUCEI, Universidad de Guadalajara.

> **Cómo usar este documento.** Está escrito para servir de base al reporte
> académico. La sección [§16](#16-correspondencia-con-el-documento-académico)
> indica qué apartado del README alimenta cada sección del paper, y la
> [§17](#17-qué-debe-corregirse-del-documento-original) lista lo que el
> planteamiento original afirmaba y los datos no sostienen.

---

## Índice

1. [Qué hace el sistema](#1-qué-hace-el-sistema)
2. [Lo que los datos públicos permiten y lo que no](#2-lo-que-los-datos-públicos-permiten-y-lo-que-no)
3. [Arquitectura](#3-arquitectura)
4. [Fuentes de datos](#4-fuentes-de-datos)
5. [El pipeline ETL](#5-el-pipeline-etl)
6. [Empate de nombres de colonia](#6-empate-de-nombres-de-colonia)
7. [El índice de riesgo](#7-el-índice-de-riesgo)
8. [Perfiles de usuario](#8-perfiles-de-usuario)
9. [Asistente con Gemini](#9-asistente-con-gemini)
10. [Interfaz](#10-interfaz)
11. [Base de datos y consultas espaciales](#11-base-de-datos-y-consultas-espaciales)
12. [Resultados medidos](#12-resultados-medidos)
13. [Verificación y pruebas](#13-verificación-y-pruebas)
14. [Puesta en marcha](#14-puesta-en-marcha)
15. [Estructura del repositorio](#15-estructura-del-repositorio)
16. [Correspondencia con el documento académico](#16-correspondencia-con-el-documento-académico)
17. [Qué debe corregirse del documento original](#17-qué-debe-corregirse-del-documento-original)
18. [Trabajo futuro](#18-trabajo-futuro)
19. [Fuentes, licencia y referencias](#19-fuentes-licencia-y-referencias)

---

## 1. Qué hace el sistema

Tres capacidades, construidas una sobre otra:

**Mapa de incidencia por colonia.** 2,068 colonias de los seis municipios del
núcleo del Área Metropolitana de Guadalajara, coloreadas por estrato de riesgo,
con búsqueda por nombre y ficha de detalle con las cifras que sustentan cada
color.

**Índice de riesgo por perfil.** La misma incidencia produce cinco lecturas
distintas —general, peatonal, vehicular, residencial y comercial— porque cada
perfil pondera delitos diferentes y, sobre todo, se normaliza con un
denominador diferente. Una zona puede ser tranquila para quien vive ahí y
riesgosa para quien deja el auto en la calle.

**Orientación asistida.** El usuario indica qué va a hacer (turismo, renta o
estacionamiento), desde dónde, con cuánto presupuesto y a qué distancia máxima.
El sistema selecciona las colonias candidatas con sus métricas reales y un
modelo de lenguaje redacta la comparación. El modelo no decide qué colonias
existen ni cuáles son sus cifras: solo redacta sobre lo que el sistema le
entrega.

---

## 2. Lo que los datos públicos permiten y lo que no

Esta sección va antes que la arquitectura porque la condiciona por completo.

**No existe ninguna fuente pública de delitos geolocalizados para la ZMG.** Se
verificó fuente por fuente:

| Fuente | Granularidad | Uso en el proyecto |
|---|---|---|
| **IIEG — incidencia por colonia** | **Colonia**, mes, 20 tipos de delito. 2016 a **feb 2021**. 241,702 registros | **Núcleo del sistema.** Única fuente pública bajo nivel municipal |
| IIEG — colonias (shapefile) | 6,624 polígonos de Jalisco con 232 campos censales | Geometrías y población |
| INEGI — Marco Geoestadístico 2025 | Municipios, localidades, AGEB, manzanas. **Sin colonias** | Contexto municipal |
| INEGI — Censo 2020 por AGEB | Población a nivel AGEB | Denominadores alternativos |
| SESNSP — Datos Abiertos | **Solo municipio**, mes. Sin coordenadas, colonia ni hora | Tendencia, no detalle |

Cuatro consecuencias, todas asumidas en el código y visibles en la interfaz:

1. **DBSCAN y KDE sobre delitos no son implementables con datos públicos.** El
   clustering de densidad necesita incidentes con coordenadas y no existen. El
   esquema conserva las tablas `incidente` y `hotspot`, hoy vacías, para cuando
   se consigan datos puntuales.
2. **No hay análisis diurno ni nocturno.** La fuente no registra la hora del
   hecho. Por eso el perfil se llama "peatonal" y no "peatón nocturno".
3. **La serie termina en febrero de 2021.** El IIEG descontinuó la publicación;
   se comprobó que las entregas posteriores devuelven 404. El mapa describe un
   patrón histórico y lo advierte de forma visible, no en una nota al pie.
4. **Portales que se daban por existentes están caídos:** `datos.jalisco.gob.mx`
   no resuelve DNS, `datos.zapopan.gob.mx` responde HTTP 500 y
   `transparencia.guadalajara.gob.mx` tiene el certificado TLS vencido.

La única vía para obtener delito geolocalizado y actual es una **solicitud de
transparencia al C5 Jalisco o a la Fiscalía del Estado** pidiendo carpetas de
investigación con colonia y hora. Los datos existen internamente; no son
públicos.

---

## 3. Arquitectura

```
Fuentes oficiales          ETL (Python)                 Publicación
─────────────────          ────────────                 ───────────
IIEG colonias (SHP)  ──┐
IIEG incidencia(CSV) ──┼──▶  georisk/              ──┬──▶ PostgreSQL + PostGIS
INEGI Marco Geo(SHP) ──┤     empate de nombres      │    registro y análisis
INEGI Censo (CSV)    ──┘     índice de riesgo       │
                                                    └──▶ GeoJSON + meta.json
                                                         │
                                        ┌────────────────┴───────────────┐
                                        ▼                                ▼
                                 Next.js + MapLibre            /api/asesor
                                 (mapa, capa estática)         (servidor)
                                                                     │
                                                                     ▼
                                                            API de Gemini
```

**Por qué la web no consulta la base en cada visita.** La capa de riesgo son
2,068 colonias: unos 2.8 MB de GeoJSON simplificado. Servirla como archivo
estático desde el CDN es instantáneo, gratuito, y evita el arranque en frío de
Neon, que suspende el cómputo tras cinco minutos de inactividad —justo el patrón
de uso de un proyecto académico—. PostGIS sigue siendo el sistema de registro:
ahí viven las series completas, los índices espaciales y la bitácora de cargas.

**Stack**

| Capa | Tecnología |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, Tailwind 4, MapLibre GL 6 |
| API | Route Handler de Next.js en runtime Node.js |
| ETL y modelado | Python 3.14, GeoPandas, pandas, RapidFuzz, scikit-learn |
| Base de datos | PostgreSQL 17 + PostGIS 3.5 |
| Modelo de lenguaje | Gemini vía API REST con salida estructurada |
| Validación | Zod 4 (entrada y salida del modelo) |
| Despliegue | Vercel (web) + Neon (base de datos) |

---

## 4. Fuentes de datos

Cada fuente está declarada en [`etl/georisk/fuentes.py`](etl/georisk/fuentes.py)
con su URL, cadencia de publicación y limitaciones. La descarga guarda el
**SHA-256** de cada archivo en `data/raw/manifiesto.json` y lo registra en la
tabla `lote_ingesta`, de modo que el reporte pueda afirmar exactamente qué
archivo se usó y detectar cuándo la fuente publica una actualización.

Detalle que rompe el pipeline si se ignora: **las fuentes oficiales no publican
en WGS84**. El Marco Geoestadístico del INEGI viene en EPSG:6372
(cónica conforme de Lambert para México) y las colonias del IIEG en EPSG:32613
(UTM 13N). Sin reproyectar, la ZMG aparece en medio del océano. Los cálculos
métricos —áreas y distancias— se hacen proyectados en UTM 13N, nunca en grados.

---

## 5. El pipeline ETL

```bash
python -m georisk.cli info        # catálogo de fuentes y su estado
python -m georisk.cli descargar   # descarga con caché y huella SHA-256
python -m georisk.cli construir   # procesa y exporta el mapa
python -m georisk.cli cargar-db   # carga a PostGIS
```

`construir` tarda unos cinco segundos y ejecuta:

1. **Carga de polígonos** y reparación de geometrías inválidas con
   `ST_MakeValid`; los shapefiles oficiales traen autointersecciones.
2. **Fusión de polígonos homónimos** (§6).
3. **Carga de incidencia** y traducción de etiquetas a la taxonomía canónica.
4. **Empate de nombres de colonia** (§6).
5. **Cálculo del índice** para los cinco perfiles (§7).
6. **Exportación** del GeoJSON y del `meta.json` que lleva las advertencias.

El comando reporta la **cobertura del empate**, que es el indicador de calidad
más importante del pipeline. Si baja del 80% avisa de forma explícita: significa
que la fuente cambió su forma de escribir los nombres.

### Taxonomía de delitos

Cada fuente nombra los delitos distinto, y la misma fuente se contradice a sí
misma: el archivo del IIEG trae `ROBO A BANCO` y `ROBO A BANCOS` como categorías
separadas, y `VIOLENCIA FAMILIAR` con dos capitalizaciones. Si el ETL insertara
las etiquetas crudas, cualquier agregación posterior mentiría.

La solución es una taxonomía canónica propia con una tabla de equivalencias que
traduce etiqueta-de-fuente a clave canónica. Cuando aparece una etiqueta no
mapeada, el ETL **no adivina**: la registra para revisión humana y la cuenta como
`otro`.

---

## 6. Empate de nombres de colonia

Es la parte más costosa del proyecto y donde se concentra el riesgo de error
silencioso. La incidencia identifica la colonia por **nombre**, escrito por
capturistas distintos a lo largo de cinco años y lleno de abreviaturas
(`JARDS. DEL BOSQUE`); los polígonos usan otro nombre, más formal
(`Jardines del Bosque`). Sin un empate confiable no hay mapa.

[`etl/georisk/nombres.py`](etl/georisk/nombres.py) resuelve el cruce en cuatro
pasos, del más al menos confiable:

1. **Exacto** tras normalizar: mayúsculas, sin acentos, sin puntuación,
   abreviaturas expandidas y números romanos convertidos a dígitos.
2. **Nombres alternativos** que el propio padrón declara entre paréntesis:
   `Villaseñor (Santa Teresita)` son dos nombres del mismo lugar.
3. **Tokens ordenados**, para nombres escritos al revés.
4. **Difuso** con `token_sort_ratio` y umbral 82, siempre acotado al municipio.

**Cobertura: 84.4% de todos los incidentes** (90.7% de los que traen nombre de
colonia). El resto se reporta y se muestra en la interfaz: 6% viene sin colonia
en la fuente y 9.7% son colonias que no existen en el padrón de polígonos —
Lafayette, Santuario y Capilla de Jesús son colonias reales de Guadalajara que
el padrón del IIEG, basado en secciones electorales agrupadas, no contiene.

### Tres errores encontrados y corregidos

Valen como hallazgo metodológico porque ninguno produce un fallo visible:

**`token_set_ratio` es inservible para esto.** Devuelve 100 cuando los tokens de
un nombre son subconjunto del otro, así que `La Loma` absorbía `Loma Dorada
Delegación A/B/C/D`, `Loma del Zalate` y `Loma Linda`: acumulaba **2,935
incidentes en una colonia que tenía 18**. El código usa `token_sort_ratio` con
guardas que exigen coincidencia de puntos cardinales, números y letras de
sección, más una lista curada de excepciones (`La Nopalera` y `La Nogalera`
difieren en una letra y son lugares distintos).

**El padrón parte colonias en pedazos homónimos.** Guadalajara tiene dos
polígonos `Oblatos`, de 9,087 y 26,844 habitantes; Tonalá tiene cuatro llamados
`Tonalá`. Como la incidencia reporta un único total por nombre, asignarlo a un
pedazo infla su tasa casi cuatro veces. El ETL fusiona los 107 grupos afectados
(225 polígonos) en una sola unidad de análisis, sumando población y uniendo
geometría.

**`groupby` de pandas descarta filas en silencio.** La fuente deja vacía la
columna `Número_mes` en 2,623 filas del alcance, y pandas omite por omisión las
filas con clave de agrupación nula: **4,230 incidentes desaparecían** mientras
el reporte los daba por ubicados. Se verificó que todas son de septiembre y que
la columna con el nombre del mes está intacta, así que el mes se deduce en lugar
de perder el dato. El ETL incluye ahora un **cuadre obligatorio** que lanza una
excepción ante cualquier descuadre entre lo ubicado y lo agregado.

---

## 7. El índice de riesgo

Implementado en [`etl/georisk/riesgo.py`](etl/georisk/riesgo.py):

1. **Filtrar** los delitos del perfil según sus banderas.
2. **Ponderar** por severidad (escala 1–10 definida en
   [`taxonomia.py`](etl/georisk/taxonomia.py); es un juicio del proyecto, no un
   dato de la fuente, y por eso está versionado y documentado).
3. **Normalizar** por el denominador del perfil (§8).
4. **Suavizar** con contracción bayesiana hacia la media metropolitana.
5. **Comprimir** con logaritmo y escalar a 0–100.
6. **Estratificar** por cuantiles: bajo (<p50), moderado (p50–p75), alto
   (p75–p90), crítico (>p90).

### Las dos decisiones que más importan

**El denominador depende del perfil.** A quien camina por una zona le importa
cuántos delitos ocurren en ese territorio; a quien compra una casa le importa la
proporción respecto a quienes viven ahí. Por eso los perfiles peatonal,
vehicular y comercial se normalizan **por km²**, y el general y el residencial
**por 100 mil habitantes**.

Usar población para todo produce el error clásico de estos mapas: el Centro de
Guadalajara tiene 2,585 residentes censados pero cientos de miles de personas
circulando, así que dividir entre residentes lo pinta como la zona más peligrosa
del planeta. En una versión previa de este código, *La Loma* en Tonalá salía con
**488,206 delitos por 100 mil habitantes**.

**La contracción bayesiana evita que el ruido gane.** Una colonia de 80
habitantes con 3 robos tiene una tasa altísima sin evidencia suficiente para
afirmar nada. El suavizado jala esas estimaciones hacia el promedio
metropolitano en proporción a lo poco que se sabe de ellas, con peso
`w = exposición / (exposición + exposición_de_referencia)`, donde la referencia
es la mediana observada. Es el mismo principio de los atlas de mortalidad
[5]. Además se calculan **intervalos de confianza de Poisson por el método de
Byar** [6], y las unidades con muestra insuficiente se marcan y se dibujan
translúcidas.

La referencia metropolitana se calcula sobre los **totales**, no como promedio de
las tasas por colonia: promediar tasas da el mismo peso a una colonia de 80
habitantes que a una de 20 mil y sesga la referencia.

---

## 8. Perfiles de usuario

| Perfil | Delitos que incluye | Normalización | Responde a |
|---|---|---|---|
| **General** | Todos, ponderados | por 100 mil hab. | Panorama de la zona |
| **Peatonal** | Robo a persona, lesiones, homicidio | por km² | ¿Es seguro caminar aquí? |
| **Vehicular** | Robo de vehículo, motocicleta, interior y autopartes | por km² | ¿Dejo el auto en la calle? |
| **Residencial** | Robo a casa habitación y delitos violentos | por 100 mil hab. | ¿Vivo o invierto aquí? |
| **Comercial** | Robo a negocio, banco y carga pesada | por km² | ¿Pongo un local aquí? |

Cada perfil lleva en `meta.json` su propia **advertencia metodológica**, que
viaja con el dato hasta la interfaz en lugar de estar codificada en el frontend.
La del perfil peatonal dice explícitamente que la fuente no registra la hora y
que por tanto no puede distinguir riesgo diurno de nocturno.

---

## 9. Asistente con Gemini

Módulo que traduce el índice en una recomendación redactada.
[`web/app/api/asesor/route.ts`](web/app/api/asesor/route.ts) y
[`web/lib/asesor.ts`](web/lib/asesor.ts).

### Flujo

1. El usuario elige **objetivo** (turismo, renta o estacionamiento),
   **presupuesto** en MXN, **distancia máxima** y una **referencia**: una colonia
   del mapa o su ubicación.
2. El servidor calcula la **distancia real a la superficie** de cada colonia, no
   a su centro. Importa a distancias cortas: con el centroide, la colonia donde
   estás parado puede quedar excluida de un radio de 100 m.
3. Descarta las colonias con **muestra insuficiente**, para que nunca se
   recomiende una zona solo porque tiene pocos incidentes registrados.
4. Ordena las candidatas por el promedio de los índices relevantes al objetivo
   más una **penalización por distancia** de hasta 20 puntos, y toma las 24
   mejores.
5. Gemini recibe esa lista con sus métricas y redacta hasta cuatro
   recomendaciones con motivo, qué verificar con el presupuesto y una
   precaución.
6. La respuesta se **valida contra la lista enviada**: si el modelo menciona una
   colonia que no estaba, o la repite, la respuesta se rechaza.

Rangos de distancia por objetivo: estacionamiento de 100 m a 1 km, hospedaje de
500 m a 5 km, renta de 1 a 30 km.

### Decisiones de diseño defendibles

Este módulo es el más fácil de criticar en una defensa, así que conviene tener
claras sus garantías:

**El modelo no inventa lugares.** La identidad, la distancia y las cifras de
cada recomendación provienen siempre del dataset; el modelo solo aporta la
redacción. `validarRespuesta` lo hace cumplir.

**No se envían las coordenadas del dispositivo al proveedor.** Se usan
únicamente en el servidor para calcular distancias; a Gemini viajan las colonias
candidatas y las preferencias, nunca la ubicación exacta del usuario.

**La consulta del usuario es dato, no instrucción.** La instrucción de sistema
declara explícitamente que los nombres y el texto libre no pueden alterar las
reglas, que es la mitigación básica contra inyección de prompt.

**El modelo tiene prohibido afirmar seguridad.** No puede llamar segura a una
colonia ni asegurar que un auto puede dejarse en la calle, debe explicar los
compromisos entre incidencia histórica y distancia, y puede devolver cero
recomendaciones si todas las opciones tienen incidencia alta.

**No hay datos de precios.** El presupuesto orienta qué verificar; el modelo
tiene prohibido asignar rangos de precio o suponer que una colonia es barata.

**Límites operativos:** entrada máxima de 8 KB, salida estructurada validada con
Zod, timeout de 35 s en el servidor y 45 s en el cliente, y tope de 20 consultas
por minuto con 3 concurrentes **por proceso**. Un despliegue con varias
instancias necesita además una cuota compartida.

**Degradación limpia:** sin clave configurada el mapa funciona igual y el
asistente informa que no está habilitado, en vez de fallar.

---

## 10. Interfaz

Aplicación de una sola página con el mapa a pantalla completa y un panel
lateral de dos pestañas: **Explorar mapa** y **Asistente IA**. En móvil se
reorganiza en tres vistas.

- **Búsqueda** de colonia o municipio, insensible a acentos.
- **Accesos directos** por intención (*Dónde alojarme*, *Dejar mi auto*), que
  fijan a la vez el perfil del mapa y el objetivo del asistente.
- **Etiquetas de colonia** sobre el mapa al acercarse.
- **Ficha de detalle** al tocar una colonia, con incidentes, ambas tasas,
  población, superficie y percentil.
- **Ubicación del dispositivo** con aviso de precisión y opción de corregir el
  punto manualmente, porque una geolocalización de ±500 m cambia el resultado a
  radios cortos.
- Las colonias con muestra insuficiente se dibujan **translúcidas**: no se
  ocultan, se marcan.

La rampa de color es **YlOrRd de ColorBrewer**, de un solo tono. Se eligió sobre
la clásica verde-amarillo-rojo porque esta sí es distinguible con daltonismo
rojo-verde, que afecta a cerca del 8% de los hombres; con la rampa verde a roja,
el estrato bajo y el crítico se ven casi iguales para esas personas, que es el
peor error posible en un mapa de seguridad.

---

## 11. Base de datos y consultas espaciales

Seis migraciones en [`db/migrations/`](db/migrations/), aplicadas en orden por
`db/apply.sh`, que es idempotente y lleva registro en `schema_migrations`.

**Decisión de diseño central:** una sola tabla `unidad_geografica` con
discriminador de tipo (municipio / AGEB / colonia) en lugar de tres tablas. Al
momento de diseñar el esquema no estaba confirmado a qué granularidad existirían
datos, y con este modelo el cálculo de riesgo y la API funcionan igual sea cual
sea, sin migrar el esquema.

Tablas principales: `unidad_geografica`, `delito` y `delito_alias`,
`incidencia_agregada`, `riesgo_unidad`, `perfil_riesgo`, `lote_ingesta`, y las
reservadas `incidente` y `hotspot`.

La columna `calidad_dato` de `riesgo_unidad` declara de qué calidad de insumo
salió cada número (`colonia_historico`, `agregado_municipal`, `puntual`). Es una
decisión deliberada de honestidad: un índice derivado de conteos municipales no
vale lo mismo que uno derivado de incidentes con coordenadas, y la interfaz debe
poder decirlo.

**Para búsquedas por radio hay que usar `riesgo_cerca_de()`, no la vista.** La
vista `v_riesgo_vigente` lleva un `DISTINCT ON` que obliga al planificador a
materializar las 2,068 unidades antes de aplicar cualquier filtro espacial, y
además un predicado sobre `geom::geography` no puede usar el índice construido
sobre `geom`. La función filtra por espacio primero, apoyada en un índice
funcional sobre la expresión casteada.

---

## 12. Resultados medidos

Obtenidos con `./db/benchmark.sh --completo` sobre las 2,068 colonias cargadas,
con PostgreSQL 17.5 y PostGIS 3.5.2 en contenedor. De cada consulta se toma el
**mejor de cinco ejecuciones con caché caliente**, porque interesa el costo en
régimen y no el primer acceso a disco.

### Desempeño de consultas espaciales

| Consulta | Sin índice | Con índice GiST | Mejora |
|---|---:|---:|---:|
| Punto en polígono (¿qué colonia es esta?) | 1.23 ms | **0.23 ms** | 5.3× |
| Viewport del mapa (recuadro) | 1.94 ms | **1.21 ms** | 1.6× |
| Riesgo en radio de 2 km | 124.29 ms | **13.07 ms** | 9.5× |
| Asignar 100,000 puntos a su colonia | 636.15 s | **3.42 s** | **186×** |

Tres lecturas honestas de esta tabla, que conviene anticipar en la defensa:

**Con 2,068 polígonos el índice aporta poco en consultas simples.** El recorrido
secuencial sobre una tabla tan chica ya es rápido. Presumir órdenes de magnitud
en las dos primeras filas sería engañoso.

**Donde el índice decide es en volumen.** Asignar 100 mil puntos pasa de diez
minutos y medio a tres segundos y medio. Ese es el escenario que justifica
PostGIS frente a una hoja de cálculo, y es el que habría que correr si llegan
datos delictivos geolocalizados.

**La tercera fila no compara índice sí/no, sino vista contra función.** La
mejora de 9.5× salió de rediseñar la consulta, no de agregar hardware.

### Cobertura del procesamiento

| Métrica | Valor |
|---|---:|
| Colonias en el padrón (6 municipios) | 2,186 polígonos |
| Unidades de análisis tras fusionar homónimos | **2,068** |
| Registros de incidencia en el alcance | 181,851 filas |
| Incidentes totales en el alcance | 346,384 |
| **Incidentes ubicados en una colonia** | **292,190 (84.4%)** |
| Sin colonia en la fuente | 20,683 (6.0%) |
| Nombre sin polígono correspondiente | 33,511 (9.7%) |
| Filas agregadas cargadas a PostGIS | 156,346 |
| Filas de riesgo (2,068 × 5 perfiles) | 10,340 |

Integridad verificada en la base: **cero** huérfanos, **cero** geometrías
inválidas, **cero** colonias sin municipio padre, y la suma de incidencia en la
base coincide exactamente con lo reportado por el ETL.

### Distribución por municipio (perfil general)

| Municipio | Colonias | Incidentes | Índice medio | Críticas |
|---|---:|---:|---:|---:|
| Guadalajara | 279 | 120,024 | 44.3 | 100 |
| Zapopan | 728 | 71,052 | 38.9 | 52 |
| Tlaquepaque | 250 | 37,056 | 39.8 | 28 |
| Tonalá | 336 | 29,113 | 39.7 | 14 |
| Tlajomulco | 366 | 23,164 | 37.1 | 9 |
| El Salto | 109 | 8,014 | 38.0 | 4 |

---

## 13. Verificación y pruebas

```bash
cd web
npm test        # 9 pruebas, Gemini simulado, sin gastar cuota
npm run lint
npm run build
```

La suite cubre la validación de entrada y sus límites por objetivo, la lectura
de configuración sin filtrar secretos, la geometría sobre los polígonos reales
(incluido el caso del punto interior que debe evitar el hueco de un polígono),
el filtrado por distancia y muestra insuficiente para los tres objetivos, el
rechazo de colonias inventadas o duplicadas, y el ida y vuelta completo con la
API simulada, incluyendo cuota agotada, timeout y referencia fuera de cobertura.

El desempeño de la base se reproduce con `./db/benchmark.sh`, que genera los
datos, mide y limpia lo que creó. Las cifras del reporte no deberían pedirse de
buena fe: quien evalúe el proyecto puede obtener las suyas.

---

## 14. Puesta en marcha

### Requisitos

Node.js 24+, Python 3.12+, Docker (o una base en Neon) y `psql`.

### 1. ETL

```bash
cd etl
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m georisk.cli descargar
PYTHONPATH=. .venv/bin/python -m georisk.cli construir --top 10
```

### 2. Web

```bash
cd web
npm install
npm run dev     # http://localhost:3000
```

### 3. Asistente (opcional)

Consigue una clave en [Google AI Studio](https://aistudio.google.com/apikey) y
ponla en el `.env` de la raíz del proyecto:

```dotenv
GEMINI_API_KEY=tu_clave
GEMINI_MODEL=gemini-2.5-flash
```

**No hace falta reiniciar el servidor:** la configuración se relee en cada
petición. Sin clave, el mapa funciona igual y el asistente informa que no está
habilitado. La clave se usa solo en el servidor; nunca con el prefijo
`NEXT_PUBLIC_`, que la publicaría en el navegador.

### 4. Base de datos (opcional para el mapa, necesaria para el análisis)

```bash
docker compose up -d
./db/apply.sh "postgresql://geo:geo@localhost:5433/georisk"
cd etl
export DATABASE_URL="postgresql://geo:geo@localhost:5433/georisk"
PYTHONPATH=. .venv/bin/python -m georisk.cli cargar-db
```

Si tu usuario no está en el grupo `docker` hará falta `sudo` solo en el primer
comando: una vez publicado el puerto 5433, el resto corre sin privilegios.

---

## 15. Estructura del repositorio

```
app/
├── db/
│   ├── migrations/
│   │   ├── 0001_base_geografica.sql   extensiones y unidades geográficas
│   │   ├── 0002_incidencia.sql        taxonomía de delitos e incidencia
│   │   ├── 0003_riesgo.sql            índice, perfiles y hotspots
│   │   ├── 0004_calidad_dato.sql      vocabulario real de calidad_dato
│   │   ├── 0005_indice_geografia.sql  índice en metros y riesgo_cerca_de()
│   │   └── 0006_vista_densidad.sql    la vista expone ambas tasas
│   ├── apply.sh                       aplica lo pendiente, idempotente
│   └── benchmark.sh                   mide consultas espaciales
├── etl/georisk/
│   ├── config.py        alcance, rutas y CRS
│   ├── fuentes.py       catálogo de fuentes y descarga con caché
│   ├── taxonomia.py     delitos canónicos, severidades y perfiles
│   ├── nombres.py       normalización y empate de colonias
│   ├── geografia.py     carga y fusión de polígonos
│   ├── incidencia.py    carga de incidencia y cuadre
│   ├── riesgo.py        cálculo del índice
│   ├── exportar.py      GeoJSON y metadatos
│   ├── carga_db.py      escritura a PostGIS
│   └── cli.py           línea de comandos
├── web/
│   ├── app/
│   │   ├── api/asesor/route.ts   endpoint del asistente
│   │   ├── page.tsx              lectura de metadatos en servidor
│   │   └── layout.tsx
│   ├── components/
│   │   ├── MapaRiesgo.tsx        mapa, panel y ficha
│   │   └── AsesorColonia.tsx     formulario y recomendaciones
│   ├── lib/
│   │   ├── asesor.ts             contexto, validación y esquemas
│   │   ├── geografia.ts          distancias y punto interior
│   │   ├── riesgo.ts             paleta y formato
│   │   ├── tipos.ts              tipos de meta.json y del GeoJSON
│   │   └── configuracion-servidor.ts
│   ├── tests/                    pruebas con Gemini simulado
│   └── public/datos/             GeoJSON y meta.json que produce el ETL
├── data/                         descargas y resultados (no se versiona)
└── docker-compose.yml            PostGIS local
```

---

## 16. Correspondencia con el documento académico

| Sección del paper | De dónde sale |
|---|---|
| **Abstract** | §1 y las cifras de §12 |
| **I. Introducción** | §1 y §2 (la limitación de datos es el planteamiento del problema) |
| **II. Trabajos relacionados** | §19, más la comparación con plataformas gubernamentales |
| **III.A Arquitectura y stack** | §3 |
| **III.B Modelado de riesgo** | §7, con las dos decisiones metodológicas |
| **III.C Módulo turístico y vial** | §8, perfiles peatonal y vehicular |
| **III.D Módulo inmobiliario** | §8, perfil residencial |
| **III.E ETL y persistencia** | §4, §5, §6 y §11 |
| **III.F Asistente con IA** | §9 (módulo nuevo, no estaba en el planteamiento original) |
| **IV. Resultados** | §12 completo, y §13 para la reproducibilidad |
| **V. Conclusiones y trabajo futuro** | §18 |
| **Referencias** | §19 |

**Sugerencia de enfoque para la defensa.** El aporte más sólido de este proyecto
no es el mapa: es haber demostrado, con verificación fuente por fuente, que el
análisis de riesgo delictivo intraurbano en Guadalajara **está limitado por la
disponibilidad de datos públicos, no por la técnica**, y haber construido aun
así un sistema que declara sus límites en lugar de disimularlos. Eso es un
resultado, no una disculpa. El §6 y el §7 aportan además hallazgos
metodológicos reutilizables por cualquiera que trabaje con estas fuentes.

---

## 17. Qué debe corregirse del documento original

El planteamiento inicial contiene afirmaciones que los datos no sostienen. Van
aquí para que la nueva versión las sustituya:

| Afirmación original | Qué corresponde escribir |
|---|---|
| Clustering espacial con **DBSCAN y KDE** sobre delitos | No implementable: no existen delitos geolocalizados públicos. Describir el análisis por unidad administrativa y dejar DBSCAN como trabajo futuro condicionado a obtener datos puntuales |
| **Random Forest** con **F1-Score de 89.4%** | No hay modelo supervisado entrenado ni etiquetas para entrenarlo. Debe eliminarse o convertirse en trabajo futuro |
| "**1,420 ms → 45 ms** (PostGIS GiST)" | Sustituir por la tabla medida de §12, que además es reproducible |
| Análisis de **seguridad peatonal nocturna** | La fuente no registra la hora. Renombrar a riesgo peatonal y declarar la limitación |
| Datos del **SESNSP** como insumo geoespacial | El SESNSP es municipal-mensual. Sirve como tendencia, no como detalle |
| "Grupo guía para la excelencia inmobiliaria" | Frase promocional sin contenido técnico; conviene retirarla de un texto académico |
| Fuentes de **2026** del IIEG y SESNSP | La serie por colonia del IIEG termina en **febrero de 2021**; citar el año real del corte |

Añadir, en cambio, lo que sí se construyó y no estaba previsto: el módulo de
orientación asistida por modelo de lenguaje (§9), el tratamiento del denominador
por perfil (§7), la contracción bayesiana, y la metodología de empate de nombres
con sus tres hallazgos (§6).

---

## 18. Trabajo futuro

- **Solicitud de transparencia al C5 Jalisco o a la Fiscalía** pidiendo carpetas
  de investigación con colonia y hora. Es la llave que habilitaría el clustering
  espacial, el análisis nocturno y el modelo supervisado.
- **Integrar el SESNSP municipal** como capa de tendencia reciente, etiquetada
  como interpolación y no como detalle geográfico.
- **Módulo de seguridad vial peatonal** con la capa `iieg:siniestros`, que sí
  tiene coordenadas y franjas horarias de dos horas. Limitaciones duras: son
  atropellamientos, no delitos, y solo del año 2019. Debe ir como capa separada
  y rotulada con honestidad, nunca fusionada con el índice delictivo.
- **Valuación inmobiliaria:** cruzar el estrato de riesgo con precio por metro
  cuadrado de portales de bienes raíces.
- **Cuota compartida y autenticación** para el asistente antes de un despliegue
  público.
- **Aplicación móvil**, reutilizando el mismo GeoJSON, metadatos y API.

---

## 19. Fuentes, licencia y referencias

Datos de incidencia delictiva y polígonos de colonia: **IIEG Jalisco**, con
datos de la Fiscalía del Estado. Cartografía y censo: **INEGI**. Mapa base:
**OpenStreetMap**. Cada fuente queda registrada con su URL y su huella SHA-256
en `data/raw/manifiesto.json` y en la tabla `lote_ingesta`.

Código bajo licencia MIT.

### Referencias

1. Instituto de Información Estadística y Geográfica de Jalisco (IIEG),
   *Incidencia delictiva por colonia* y *Información sociodemográfica por
   colonia*. https://iieg.gob.mx
2. Instituto Nacional de Estadística y Geografía (INEGI), *Marco Geoestadístico
   2025* y *Censo de Población y Vivienda 2020*. https://www.inegi.org.mx
3. Secretariado Ejecutivo del Sistema Nacional de Seguridad Pública (SESNSP),
   *Datos Abiertos de Incidencia Delictiva*. https://www.gob.mx/sesnsp
4. M. Ester, H.-P. Kriegel, J. Sander y X. Xu, "A density-based algorithm for
   discovering clusters in large spatial databases with noise", *Proc. KDD*,
   1996. (Citado como referencia del método, no como técnica implementada.)
5. D. Clayton y J. Kaldor, "Empirical Bayes estimates of age-standardized
   relative risks for use in disease mapping", *Biometrics*, vol. 43, núm. 3,
   1987.
6. N. E. Breslow y N. E. Day, *Statistical Methods in Cancer Research, Vol. II*,
   IARC, 1987. (Método de Byar para intervalos de Poisson.)
7. C. A. Brewer, *ColorBrewer: Color Advice for Maps*. https://colorbrewer2.org
8. PostGIS Development Group, *PostGIS Documentation*. https://postgis.net
9. Google, *Gemini API — Structured output*.
   https://ai.google.dev/gemini-api/docs/generate-content/structured-output

> Verifica los datos bibliográficos exactos de [5] y [6] antes de entregar: son
> referencias canónicas del método, pero conviene confirmar páginas y volumen en
> la fuente original.
