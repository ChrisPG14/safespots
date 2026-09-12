-- ============================================================================
-- 0006 — La vista vigente expone también la densidad por km²
-- ============================================================================
-- `v_riesgo_vigente` se definió en la migración 0003, antes de decidir que el
-- denominador depende del perfil. Exponía `tasa_100k` pero no `densidad_km2`,
-- así que para los tres perfiles normalizados por superficie —peatonal,
-- vehicular y comercial— la vista mostraba una cifra per cápita que NO es la
-- que produjo su índice. Quien consultara la base directamente se llevaría una
-- lectura equivocada.
--
-- Se recrea con DROP + CREATE en lugar de CREATE OR REPLACE porque este último
-- solo admite añadir columnas al final y aquí conviene dejarlas junto a las
-- métricas con las que se leen.
-- ============================================================================

DROP VIEW IF EXISTS v_riesgo_vigente;

CREATE VIEW v_riesgo_vigente AS
SELECT DISTINCT ON (r.unidad_id, r.perfil)
    r.id                AS riesgo_id,
    u.id                AS unidad_id,
    u.tipo,
    u.clave,
    u.nombre,
    u.municipio_clave,
    m.nombre_corto      AS municipio_nombre,
    u.poblacion,
    round((u.area_m2 / 1e6)::numeric, 4) AS area_km2,
    r.perfil,
    p.nombre            AS perfil_nombre,
    -- Con qué se normalizó: dice cuál de las dos tasas de abajo es la que
    -- sustenta el índice de esta fila.
    CASE
        WHEN 'afecta_peaton'   = ANY(p.banderas) THEN 'area'
        WHEN 'afecta_vehiculo' = ANY(p.banderas) THEN 'area'
        WHEN 'afecta_negocio'  = ANY(p.banderas) THEN 'area'
        ELSE 'poblacion'
    END                 AS normalizacion,
    r.periodo_inicio,
    r.periodo_fin,
    r.incidentes,
    r.incidentes_ponderados,
    r.tasa_100k,
    r.densidad_km2,
    r.indice,
    r.percentil,
    r.estrato,
    r.ic_inferior,
    r.ic_superior,
    r.muestra_baja,
    r.calidad_dato,
    r.metodo,
    r.metodo_version,
    u.geom
FROM riesgo_unidad r
JOIN unidad_geografica u ON u.id = r.unidad_id
JOIN perfil_riesgo p     ON p.clave = r.perfil
LEFT JOIN amg_municipio m ON m.clave = u.municipio_clave
ORDER BY r.unidad_id, r.perfil, r.periodo_fin DESC, r.calculado_en DESC;

COMMENT ON VIEW v_riesgo_vigente IS
    'Riesgo más reciente por unidad y perfil, con geometría y AMBAS tasas '
    'crudas. La columna `normalizacion` indica cuál de las dos sustenta el '
    'índice. Para búsquedas por radio usar riesgo_cerca_de(): el DISTINCT ON '
    'de esta vista impide aprovechar el índice espacial.';
