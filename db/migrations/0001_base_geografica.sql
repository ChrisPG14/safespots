-- ============================================================================
-- 0001 — Extensiones y base geográfica
-- ============================================================================
-- Decisiones de diseño relevantes:
--
-- 1) Todo se almacena en EPSG:4326 (lat/lon WGS84). Es lo que consumen
--    GeoJSON y MapLibre sin reproyección, y lo que devuelven casi todas las
--    fuentes oficiales.
--    Las operaciones que necesitan METROS (distancias, áreas, DBSCAN) se
--    proyectan en la consulta a EPSG:32613 (UTM zona 13N, la que cubre
--    Guadalajara) o se castean a `geography`. No guardamos una segunda
--    columna proyectada: duplicar geometría se desincroniza y las columnas
--    generadas con ST_Transform son frágiles entre versiones de PostGIS.
--
-- 2) UNA sola tabla de unidades geográficas con discriminador `tipo`, en vez
--    de tablas separadas para municipio/AGEB/colonia. Razón: al momento de
--    diseñar esto no está confirmado a qué granularidad existen datos
--    delictivos públicos. Con este modelo el cálculo de riesgo y la API
--    funcionan igual sea municipio, AGEB o colonia, y podemos subir o bajar
--    de granularidad sin migrar el esquema.
--
-- 3) No ponemos CHECK (ST_IsValid(geom)). Los shapefiles del INEGI traen
--    autointersecciones con frecuencia; el ETL aplica ST_MakeValid antes de
--    insertar. Un CHECK aquí solo lograría que la carga falle a medias.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- Control de migraciones aplicadas (lo usa db/apply.sh)
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text        PRIMARY KEY,
    aplicada_en timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Tipos de unidad geográfica
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_unidad') THEN
        CREATE TYPE tipo_unidad AS ENUM ('municipio', 'ageb', 'colonia');
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Unidades geográficas
-- ---------------------------------------------------------------------------
-- `clave` es el CVEGEO del INEGI cuando la unidad viene del Marco
-- Geoestadístico:
--     municipio -> 5 caracteres  : entidad(2) + municipio(3)      ej. 14039
--     ageb      -> 13 caracteres : ent(2)+mun(3)+localidad(4)+ageb(4)
-- Para colonias la clave depende de la fuente (municipal, IIEG u OSM), porque
-- el INEGI no publica un catálogo oficial de polígonos de colonia.
CREATE TABLE IF NOT EXISTS unidad_geografica (
    id              bigserial   PRIMARY KEY,
    tipo            tipo_unidad NOT NULL,
    clave           text        NOT NULL,
    nombre          text,

    -- Municipio al que pertenece (CVEGEO de 5 caracteres). Desnormalizado a
    -- propósito: casi toda consulta filtra por municipio y así evitamos un
    -- join recursivo o un ST_Within en cada request.
    municipio_clave char(5),

    -- Jerarquía: una AGEB apunta a su municipio. Permite agregar hacia arriba
    -- sin operaciones espaciales.
    parent_id       bigint      REFERENCES unidad_geografica(id) ON DELETE SET NULL,

    -- Población del Censo 2020. Indispensable para tasas por 100 mil
    -- habitantes: los conteos crudos solo dicen dónde vive más gente.
    poblacion       integer     CHECK (poblacion IS NULL OR poblacion >= 0),

    -- Área en metros cuadrados, calculada por el ETL con geography.
    -- Se guarda porque se usa en cada cálculo de densidad y recalcularla
    -- en cada consulta es desperdicio.
    area_m2         double precision CHECK (area_m2 IS NULL OR area_m2 > 0),

    -- Procedencia del dato. Sin esto es imposible auditar o citar la fuente
    -- en el documento académico.
    fuente          text        NOT NULL,
    fuente_version  text,

    -- Atributos extra que dependen de la fuente y no merecen columna propia
    -- (clave de localidad, ámbito urbano/rural, código postal, etc.)
    atributos       jsonb       NOT NULL DEFAULT '{}'::jsonb,

    geom            geometry(MultiPolygon, 4326) NOT NULL,

    creado_en       timestamptz NOT NULL DEFAULT now(),
    actualizado_en  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT unidad_geografica_tipo_clave_key UNIQUE (tipo, clave)
);

-- Índice espacial GiST: es el que hace que las consultas topológicas
-- (¿qué unidad contiene este punto?, ¿qué unidades cruzan este viewport?)
-- pasen de segundos a milisegundos.
CREATE INDEX IF NOT EXISTS unidad_geografica_geom_gist
    ON unidad_geografica USING GIST (geom);

CREATE INDEX IF NOT EXISTS unidad_geografica_tipo_municipio_idx
    ON unidad_geografica (tipo, municipio_clave);

CREATE INDEX IF NOT EXISTS unidad_geografica_parent_idx
    ON unidad_geografica (parent_id);

COMMENT ON TABLE unidad_geografica IS
    'Polígonos de municipios, AGEBs y colonias de la ZMG. Una sola tabla con '
    'discriminador de tipo para que el pipeline de riesgo sea agnóstico a la '
    'granularidad disponible.';

-- ---------------------------------------------------------------------------
-- Catálogo del Área Metropolitana de Guadalajara
-- ---------------------------------------------------------------------------
-- Alcance del proyecto. Se siembra con claves conocidas del INEGI para poder
-- filtrar descargas nacionales sin depender de nombres (que varían en
-- acentuación y en "San Pedro Tlaquepaque" vs "Tlaquepaque").
--
-- El ETL DEBE verificar que el nombre del INEGI coincida con `nombre_inegi` y
-- avisar si no: una clave equivocada aquí contamina silenciosamente todo el
-- análisis posterior.
CREATE TABLE IF NOT EXISTS amg_municipio (
    clave        char(5) PRIMARY KEY,
    nombre_inegi text    NOT NULL,
    nombre_corto text    NOT NULL,
    -- Los 6 municipios de la conurbación central concentran la mancha urbana
    -- continua. Los otros 4 son parte del AMG oficial pero mayormente rurales;
    -- útil para poder arrancar el MVP con el núcleo.
    es_nucleo    boolean NOT NULL DEFAULT false,
    orden        smallint NOT NULL
);

INSERT INTO amg_municipio (clave, nombre_inegi, nombre_corto, es_nucleo, orden) VALUES
    ('14039', 'Guadalajara',                  'Guadalajara',  true,  1),
    ('14120', 'Zapopan',                      'Zapopan',      true,  2),
    ('14098', 'San Pedro Tlaquepaque',        'Tlaquepaque',  true,  3),
    ('14101', 'Tonalá',                       'Tonalá',       true,  4),
    ('14097', 'Tlajomulco de Zúñiga',         'Tlajomulco',   true,  5),
    ('14070', 'El Salto',                     'El Salto',     true,  6),
    ('14051', 'Juanacatlán',                  'Juanacatlán',  false, 7),
    ('14044', 'Ixtlahuacán de los Membrillos','Ixtlahuacán',  false, 8),
    ('14124', 'Zapotlanejo',                  'Zapotlanejo',  false, 9),
    ('14002', 'Acatlán de Juárez',            'Acatlán',      false, 10)
ON CONFLICT (clave) DO NOTHING;

COMMENT ON TABLE amg_municipio IS
    'Alcance geográfico del proyecto: los 10 municipios del Área '
    'Metropolitana de Guadalajara. es_nucleo marca la conurbación central.';
