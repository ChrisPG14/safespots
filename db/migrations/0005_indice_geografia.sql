-- ============================================================================
-- 0005 — Índice para búsquedas por radio en metros
-- ============================================================================
-- El índice GiST de la migración 0001 es sobre `geom`, que está en grados
-- (EPSG:4326). Sirve para "qué contiene este punto" y para el recuadro del
-- viewport, que son operaciones en el mismo sistema de coordenadas.
--
-- Pero la consulta más útil de cara al usuario es otra: "qué tan riesgosa es
-- la zona en un radio de 2 km de donde estoy". Eso exige metros, y en PostGIS
-- se resuelve casteando a `geography`. El problema es que
-- `ST_DWithin(geom::geography, ..., 2000)` NO puede usar un índice construido
-- sobre `geom`: el casteo produce un valor distinto del indexado, así que el
-- planificador recorre y evalúa las 2,068 colonias una por una.
--
-- Medido antes de este índice: 119 ms, con "Rows Removed by Filter: 2040".
--
-- Un índice funcional sobre la expresión casteada sí es aprovechable.
-- ============================================================================

CREATE INDEX IF NOT EXISTS unidad_geografica_geog_gist
    ON unidad_geografica USING GIST ((geom::geography));

COMMENT ON INDEX unidad_geografica_geog_gist IS
    'Para ST_DWithin/ST_Distance en METROS. El índice sobre geom (grados) no '
    'sirve para predicados sobre geom::geography.';

-- ---------------------------------------------------------------------------
-- Búsqueda por cercanía
-- ---------------------------------------------------------------------------
-- Se ofrece como función y no como vista a propósito. La vista
-- `v_riesgo_vigente` lleva un DISTINCT ON, y eso obliga al planificador a
-- materializar TODAS las unidades antes de poder aplicar cualquier filtro
-- espacial: el índice queda inutilizado aunque exista.
--
-- Aquí el filtro espacial va primero, sobre la tabla, donde sí se aprovecha el
-- índice; el riesgo se resuelve después y solo para las pocas unidades que
-- sobrevivieron al filtro.
CREATE OR REPLACE FUNCTION riesgo_cerca_de(
    lon          double precision,
    lat          double precision,
    radio_metros double precision DEFAULT 1000,
    perfil_clave text DEFAULT 'general',
    limite       integer DEFAULT 20
)
RETURNS TABLE (
    clave            text,
    nombre           text,
    municipio        text,
    distancia_metros double precision,
    indice           double precision,
    estrato          text,
    incidentes       integer,
    muestra_baja     boolean
)
LANGUAGE sql
STABLE
AS $$
    WITH cercanas AS (
        SELECT u.id, u.clave, u.nombre, u.municipio_clave,
               ST_Distance(
                   u.geom::geography,
                   ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
               ) AS distancia
          FROM unidad_geografica u
         WHERE u.tipo = 'colonia'
           AND ST_DWithin(
                   u.geom::geography,
                   ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                   radio_metros
               )
    ),
    vigente AS (
        SELECT DISTINCT ON (r.unidad_id)
               r.unidad_id, r.indice, r.estrato, r.incidentes, r.muestra_baja
          FROM riesgo_unidad r
          JOIN cercanas c ON c.id = r.unidad_id
         WHERE r.perfil = perfil_clave
         ORDER BY r.unidad_id, r.periodo_fin DESC, r.calculado_en DESC
    )
    SELECT c.clave, c.nombre, m.nombre_corto, c.distancia,
           v.indice, v.estrato, v.incidentes, v.muestra_baja
      FROM cercanas c
      JOIN vigente v ON v.unidad_id = c.id
      LEFT JOIN amg_municipio m ON m.clave = c.municipio_clave
     ORDER BY v.indice DESC NULLS LAST
     LIMIT limite;
$$;

COMMENT ON FUNCTION riesgo_cerca_de IS
    'Colonias dentro de un radio en metros, ordenadas por índice de riesgo. '
    'Filtra por espacio ANTES de resolver el riesgo vigente, para que el '
    'índice geográfico sea aprovechable.';
