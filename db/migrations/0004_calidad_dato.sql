-- ============================================================================
-- 0004 — Vocabulario real de `calidad_dato`
-- ============================================================================
-- La migración 0003 definió los valores permitidos cuando el diseño todavía
-- suponía que existirían incidentes con coordenadas. Al confirmarse que no hay
-- ninguna fuente pública de delitos geolocalizados para la ZMG, el pipeline
-- pasó a producir un valor que la restricción no contemplaba y la carga
-- abortaba con:
--
--     new row for relation "riesgo_unidad" violates check constraint
--     "riesgo_unidad_calidad_dato_check"
--
-- Se amplía el vocabulario para que describa lo que el proyecto realmente
-- genera hoy y lo que podría generar después:
--
--   colonia_historico   agregados por colonia del IIEG, 2016 a feb 2021.
--                       Es lo que produce el ETL actualmente.
--   agregado_municipal  heredado de conteos municipales (SESNSP). Todas las
--                       unidades del municipio comparten valor: el mapa NO
--                       debe sugerir variación interna.
--   puntual             derivado de incidentes con coordenadas. Reservado
--                       para cuando se consigan por transparencia.
--   mixto               combinación de las anteriores.
--   sin_dato            la unidad existe pero no hay incidencia atribuible.
--
-- Mantener 'puntual' aunque hoy no se use es deliberado: el día que lleguen
-- datos geolocalizados no habrá que migrar el esquema otra vez.
-- ============================================================================

ALTER TABLE riesgo_unidad
    DROP CONSTRAINT IF EXISTS riesgo_unidad_calidad_dato_check;

ALTER TABLE riesgo_unidad
    ADD CONSTRAINT riesgo_unidad_calidad_dato_check
    CHECK (calidad_dato IN (
        'colonia_historico',
        'agregado_municipal',
        'puntual',
        'mixto',
        'sin_dato'
    ));

COMMENT ON COLUMN riesgo_unidad.calidad_dato IS
    'Procedencia del insumo: colonia_historico = agregados por colonia del '
    'IIEG (2016 a feb 2021); agregado_municipal = heredado de conteos '
    'municipales, sin variación intramunicipal real; puntual = incidentes '
    'con coordenadas.';
