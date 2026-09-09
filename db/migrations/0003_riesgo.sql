-- ============================================================================
-- 0003 — Índice de riesgo y hotspots
-- ============================================================================
-- El índice de riesgo se PRECALCULA y se guarda, no se computa en cada
-- request. Razones: el cálculo involucra ventanas temporales, ponderación por
-- severidad y normalización por población sobre miles de unidades; hacerlo en
-- vivo daría respuestas de segundos y haría inviable el mapa interactivo.
--
-- Cada fila declara con qué método y con qué calidad de dato fue calculada.
-- Esto es una decisión deliberada de honestidad: un índice derivado de
-- conteos municipales del SESNSP no vale lo mismo que uno derivado de
-- incidentes con coordenadas, y la interfaz debe poder decirlo.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Perfiles de riesgo
-- ---------------------------------------------------------------------------
-- Cada perfil pondera distinto los mismos delitos, según a quién le importa.
-- Espejo de PERFILES en etl/georisk/taxonomia.py: si cambias uno, cambia el
-- otro.
--
-- Nota de honestidad: el proyecto originalmente contemplaba un perfil de
-- "peatón NOCTURNO". Se renombró a "peatonal" a secas porque la fuente de
-- incidencia por colonia del IIEG no registra la hora del hecho. Prometer un
-- análisis nocturno sin el dato de hora sería inventarlo. La columna
-- `advertencia` transporta esa limitación hasta la interfaz.
CREATE TABLE IF NOT EXISTS perfil_riesgo (
    clave       text PRIMARY KEY,
    nombre      text NOT NULL,
    descripcion text NOT NULL,
    -- Banderas de `delito` que hacen que un delito entre al perfil.
    -- Se evalúan con OR. jsonb para poder ajustar un perfil sin migrar el
    -- esquema ni recompilar la aplicación.
    banderas    text[]   NOT NULL DEFAULT '{}',
    -- Franjas horarias que considera. NULL = todas. Solo aplica a fuentes
    -- que sí traen hora, como los siniestros viales.
    franjas     text[],
    -- Limitación metodológica que la interfaz debe mostrar junto al mapa.
    advertencia text     NOT NULL DEFAULT '',
    orden       smallint NOT NULL
);

INSERT INTO perfil_riesgo (clave, nombre, descripcion, banderas, franjas, advertencia, orden) VALUES
    ('general', 'Riesgo general',
     'Todos los delitos registrados, ponderados por severidad.',
     '{}', NULL, '', 1),

    ('peaton', 'Riesgo peatonal',
     'Delitos que afectan a quien camina en vía pública: robo a persona, lesiones, homicidio.',
     ARRAY['afecta_peaton'], NULL,
     'La fuente no registra la hora del hecho, así que este perfil NO puede '
     'distinguir riesgo diurno de nocturno.', 2),

    ('vehicular', 'Riesgo vehicular',
     'Robo de vehículo, de motocicleta, al interior del vehículo y de autopartes. '
     'Responde si conviene dejar el auto en la calle.',
     ARRAY['afecta_vehiculo'], NULL, '', 3),

    ('residencial', 'Riesgo residencial',
     'Robo a casa habitación y delitos violentos. Insumo del módulo de valuación inmobiliaria.',
     ARRAY['afecta_vivienda', 'es_violento'], NULL, '', 4),

    ('negocio', 'Riesgo comercial',
     'Robo a negocio, a banco y a carga pesada. Para evaluar la ubicación de un local.',
     ARRAY['afecta_negocio'], NULL, '', 5)
ON CONFLICT (clave) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Índice de riesgo por unidad
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS riesgo_unidad (
    id              bigserial PRIMARY KEY,
    unidad_id       bigint    NOT NULL REFERENCES unidad_geografica(id) ON DELETE CASCADE,
    perfil          text      NOT NULL REFERENCES perfil_riesgo(clave),

    -- Ventana temporal analizada. Guardar el rango explícito, y no solo un
    -- "año", permite ventanas móviles de 12 meses que es lo que realmente
    -- tiene sentido estadístico con datos delictivos.
    periodo_inicio  date      NOT NULL,
    periodo_fin     date      NOT NULL,

    -- Insumos, guardados para poder explicar el número al usuario. Un índice
    -- sin desglose es una caja negra y no convence a nadie.
    incidentes            integer          NOT NULL DEFAULT 0 CHECK (incidentes >= 0),
    incidentes_ponderados double precision NOT NULL DEFAULT 0,
    poblacion             integer,
    tasa_100k             double precision,
    densidad_km2          double precision,

    -- Índice final normalizado 0-100 y su estrato. El estrato se calcula por
    -- cuantiles sobre toda la ZMG, no con cortes absolutos: los cortes fijos
    -- envejecen mal y no son comparables entre ciudades.
    indice          double precision NOT NULL CHECK (indice BETWEEN 0 AND 100),
    percentil       double precision CHECK (percentil BETWEEN 0 AND 100),
    estrato         text             NOT NULL
                    CHECK (estrato IN ('bajo', 'moderado', 'alto', 'critico')),

    -- Honestidad metodológica: de qué calidad de insumo salió este número.
    -- 'agregado_municipal' significa que todas las unidades del municipio
    -- comparten el mismo valor y el mapa NO debe sugerir variación interna.
    calidad_dato    text NOT NULL
                    CHECK (calidad_dato IN ('puntual', 'agregado_municipal', 'mixto', 'sin_dato')),

    -- Intervalo de confianza. En unidades con poca población o pocos eventos
    -- la tasa por 100 mil es ruido: mostrarla sin incertidumbre es engañoso.
    ic_inferior     double precision,
    ic_superior     double precision,
    -- Marca las unidades donde la muestra es demasiado chica para concluir.
    muestra_baja    boolean NOT NULL DEFAULT false,

    -- Reproducibilidad: qué versión del algoritmo produjo esta fila.
    metodo          text NOT NULL,
    metodo_version  text NOT NULL,
    parametros      jsonb NOT NULL DEFAULT '{}'::jsonb,

    calculado_en    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT riesgo_unidad_key
        UNIQUE (unidad_id, perfil, periodo_inicio, periodo_fin, metodo_version),
    CONSTRAINT riesgo_unidad_periodo_valido
        CHECK (periodo_fin >= periodo_inicio)
);

CREATE INDEX IF NOT EXISTS riesgo_unidad_consulta_idx
    ON riesgo_unidad (perfil, periodo_fin DESC, unidad_id);

CREATE INDEX IF NOT EXISTS riesgo_unidad_unidad_idx
    ON riesgo_unidad (unidad_id);

COMMENT ON COLUMN riesgo_unidad.calidad_dato IS
    'puntual = derivado de incidentes con coordenadas; agregado_municipal = '
    'heredado de conteos municipales, sin variación intramunicipal real.';

-- ---------------------------------------------------------------------------
-- Hotspots (clustering espacial)
-- ---------------------------------------------------------------------------
-- Resultado de DBSCAN sobre incidentes con coordenadas. Solo se puebla si
-- efectivamente existen datos puntuales; si la única fuente es agregada,
-- esta tabla queda vacía y el módulo de hotspots se desactiva en la interfaz
-- en lugar de mostrar algo fabricado.
CREATE TABLE IF NOT EXISTS hotspot (
    id              bigserial PRIMARY KEY,
    perfil          text      NOT NULL REFERENCES perfil_riesgo(clave),
    periodo_inicio  date      NOT NULL,
    periodo_fin     date      NOT NULL,

    -- Identificador del cluster que devolvió DBSCAN en esa corrida.
    cluster_num     integer   NOT NULL,
    incidentes      integer   NOT NULL CHECK (incidentes > 0),
    incidentes_ponderados double precision,

    -- Envolvente cóncava del cluster y su centroide.
    geom            geometry(Polygon, 4326) NOT NULL,
    centroide       geometry(Point, 4326)   NOT NULL,
    area_km2        double precision,
    densidad_km2    double precision,

    -- Parámetros de DBSCAN. Sin ellos el resultado no es reproducible ni
    -- defendible: eps y min_puntos cambian por completo los clusters.
    eps_metros      double precision NOT NULL,
    min_puntos      integer          NOT NULL,

    metodo_version  text NOT NULL,
    calculado_en    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT hotspot_key
        UNIQUE (perfil, periodo_inicio, periodo_fin, metodo_version, cluster_num)
);

CREATE INDEX IF NOT EXISTS hotspot_geom_gist ON hotspot USING GIST (geom);
CREATE INDEX IF NOT EXISTS hotspot_consulta_idx ON hotspot (perfil, periodo_fin DESC);

-- ---------------------------------------------------------------------------
-- Vista de consumo para la API
-- ---------------------------------------------------------------------------
-- Devuelve, por perfil, el riesgo más reciente de cada unidad junto con su
-- geometría. Concentrar el join aquí evita repetirlo en cada endpoint y
-- mantiene una sola definición de "riesgo vigente".
CREATE OR REPLACE VIEW v_riesgo_vigente AS
SELECT DISTINCT ON (r.unidad_id, r.perfil)
    r.id                AS riesgo_id,
    u.id                AS unidad_id,
    u.tipo,
    u.clave,
    u.nombre,
    u.municipio_clave,
    m.nombre_corto      AS municipio_nombre,
    u.poblacion,
    r.perfil,
    r.periodo_inicio,
    r.periodo_fin,
    r.incidentes,
    r.tasa_100k,
    r.indice,
    r.percentil,
    r.estrato,
    r.calidad_dato,
    r.muestra_baja,
    r.metodo_version,
    u.geom
FROM riesgo_unidad r
JOIN unidad_geografica u ON u.id = r.unidad_id
LEFT JOIN amg_municipio m ON m.clave = u.municipio_clave
ORDER BY r.unidad_id, r.perfil, r.periodo_fin DESC, r.calculado_en DESC;

COMMENT ON VIEW v_riesgo_vigente IS
    'Riesgo más reciente por unidad y perfil, con geometría. Fuente única de '
    'verdad para los endpoints del mapa.';
