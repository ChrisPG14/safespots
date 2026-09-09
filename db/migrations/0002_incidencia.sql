-- ============================================================================
-- 0002 — Taxonomía de delitos e incidencia delictiva
-- ============================================================================
-- El problema central que resuelve esta migración: cada fuente nombra los
-- delitos distinto. El SESNSP usa una jerarquía de cuatro niveles
-- (bien jurídico / tipo / subtipo / modalidad), la Fiscalía de Jalisco usa
-- sus propias etiquetas, y los portales municipales otra cosa. Si el ETL
-- inserta las etiquetas crudas, cualquier agregación posterior miente.
--
-- Solución: una taxonomía canónica propia (`delito`) más una tabla de
-- equivalencias (`delito_alias`) que traduce etiqueta-de-fuente -> clave
-- canónica. Toda la lógica de negocio consulta solo la canónica.
--
-- Segunda decisión: `incidente` guarda hechos con ubicación puntual y
-- `incidencia_agregada` guarda conteos por unidad y periodo. Existen las dos
-- porque las fuentes tienen granularidades incompatibles y no queremos
-- inventar coordenadas que no existen. El índice de riesgo sabe consumir
-- ambas y declara con qué calidad de dato fue calculado.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Taxonomía canónica
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS delito (
    clave           text     PRIMARY KEY,
    nombre          text     NOT NULL,
    categoria       text     NOT NULL,

    -- Peso de severidad en escala 1-10, usado para ponderar el índice de
    -- riesgo. NO es un dato objetivo: es un juicio de valor del proyecto y
    -- por eso vive en la base de datos, versionado y citable, en lugar de
    -- estar escondido en el código. Debe justificarse en el documento.
    peso_severidad  numeric(3,1) NOT NULL CHECK (peso_severidad BETWEEN 0 AND 10),

    es_violento     boolean  NOT NULL DEFAULT false,

    -- Banderas de relevancia por perfil de usuario. Son las que alimentan los
    -- módulos de turismo e inmobiliario sin tener que enlistar claves a mano
    -- en las consultas.
    afecta_peaton   boolean  NOT NULL DEFAULT false,
    afecta_vehiculo boolean  NOT NULL DEFAULT false,
    afecta_negocio  boolean  NOT NULL DEFAULT false,
    afecta_vivienda boolean  NOT NULL DEFAULT false,

    notas           text
);

COMMENT ON COLUMN delito.peso_severidad IS
    'Ponderador subjetivo 1-10 definido por el proyecto, no por la fuente. '
    'Documentar el criterio en el reporte académico.';

-- Las claves marcadas [IIEG] son las que efectivamente aparecen en el
-- catálogo real de la incidencia por colonia del IIEG (verificado sobre el
-- archivo, no supuesto). Las demás quedan definidas de antemano porque el
-- SESNSP sí las reporta a nivel municipal y las vamos a necesitar al integrar
-- esa fuente; mientras tanto simplemente no tienen filas.
INSERT INTO delito (clave, nombre, categoria, peso_severidad, es_violento,
                    afecta_peaton, afecta_vehiculo, afecta_negocio, afecta_vivienda, notas) VALUES
    -- Contra la vida y la integridad
    ('homicidio_doloso',      'Homicidio doloso',                 'vida',        10.0, true,  true,  false, false, false, '[IIEG]'),
    ('feminicidio',           'Feminicidio',                      'vida',        10.0, true,  true,  false, false, false, '[IIEG]'),
    ('parricidio',            'Parricidio',                       'vida',        10.0, true,  false, false, false, true,  '[IIEG] Ocurre en el domicilio'),
    ('lesiones_dolosas',      'Lesiones dolosas',                 'integridad',   6.5, true,  true,  false, false, false, '[IIEG]'),
    ('violencia_familiar',    'Violencia familiar',               'integridad',   6.0, true,  false, false, false, true,  '[IIEG] Ocurre en domicilio: NO indica riesgo en vía pública'),
    ('homicidio_culposo',     'Homicidio culposo',                'vida',         6.0, false, true,  true,  false, false, 'Mayormente hechos de tránsito'),

    -- Robo sobre la persona en vía pública: el indicador más directo de
    -- riesgo peatonal. El IIEG no distingue si hubo violencia.
    ('robo_persona',          'Robo a persona',                   'patrimonio',   7.5, true,  true,  false, false, false, '[IIEG] Indicador principal de riesgo peatonal'),
    ('robo_cuentahabientes',  'Robo a cuentahabientes',           'patrimonio',   7.5, true,  true,  false, false, false, '[IIEG] Ocurre al salir del banco o del cajero'),

    -- Vehicular
    ('robo_vehiculo',         'Robo de vehículo particular',      'patrimonio',   6.5, false, false, true,  false, false, '[IIEG]'),
    ('robo_motocicleta',      'Robo de motocicleta',              'patrimonio',   6.0, false, false, true,  false, false, '[IIEG]'),
    ('robo_interior_vehiculo','Robo al interior de vehículo',     'patrimonio',   4.0, false, false, true,  false, false, '[IIEG] Relevante para estacionar en vía pública'),
    ('robo_autopartes',       'Robo de autopartes',               'patrimonio',   3.0, false, false, true,  false, false, '[IIEG] Espejos, llantas, faros'),

    -- Vivienda y negocio
    ('robo_casa_habitacion',  'Robo a casa habitación',           'patrimonio',   7.0, false, false, false, false, true,  '[IIEG] Indicador principal del módulo inmobiliario'),
    ('robo_negocio',          'Robo a negocio',                   'patrimonio',   6.0, false, false, false, true,  false, '[IIEG]'),
    ('robo_banco',            'Robo a banco',                     'patrimonio',   7.0, true,  false, false, true,  false, '[IIEG] Muy poco frecuente'),
    ('robo_carga_pesada',     'Robo a carga pesada',              'patrimonio',   5.0, false, false, false, true,  false, '[IIEG] Se concentra en corredores industriales'),

    -- Definidos para la futura integración del SESNSP
    ('violacion',             'Violación',                        'sexual',       9.5, true,  true,  false, false, false, NULL),
    ('abuso_sexual',          'Abuso sexual',                     'sexual',       7.5, true,  true,  false, false, false, NULL),
    ('secuestro',             'Secuestro',                        'libertad',    10.0, true,  true,  false, false, false, NULL),
    ('extorsion',             'Extorsión',                        'libertad',     6.0, false, false, false, true,  false, 'Mayormente telefónica, poco valor geoespacial'),
    ('narcomenudeo',          'Narcomenudeo',                     'otros',        4.5, false, false, false, false, false, NULL),
    ('danio_propiedad',       'Daño a la propiedad',              'patrimonio',   2.5, false, false, false, true,  true,  NULL),

    ('otro',                  'Otro delito no clasificado',       'otros',        1.0, false, false, false, false, false, 'Bolsa de residuo; vigilar que no crezca demasiado')
ON CONFLICT (clave) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Equivalencias fuente -> taxonomía canónica
-- ---------------------------------------------------------------------------
-- El ETL consulta esta tabla para traducir. Si encuentra una etiqueta que no
-- está aquí, NO debe adivinar: la registra en `delito_alias_pendiente` para
-- revisión humana y cuenta el incidente como 'otro'. Adivinar equivalencias
-- es la forma más fácil de arruinar las cifras sin darse cuenta.
CREATE TABLE IF NOT EXISTS delito_alias (
    id             bigserial PRIMARY KEY,
    fuente         text      NOT NULL,
    etiqueta       text      NOT NULL,
    delito_clave   text      NOT NULL REFERENCES delito(clave),
    creado_en      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT delito_alias_fuente_etiqueta_key UNIQUE (fuente, etiqueta)
);

CREATE INDEX IF NOT EXISTS delito_alias_lookup_idx
    ON delito_alias (fuente, etiqueta);

-- Equivalencias del catálogo real del IIEG (incidencia por colonia).
-- Las etiquetas se guardan en MAYÚSCULAS y el ETL normaliza antes de buscar,
-- porque la fuente mezcla capitalizaciones ("VIOLENCIA FAMILIAR" y
-- "Violencia Familiar" en el mismo archivo) y también duplica categorías en
-- singular y plural ("ROBO A BANCO" / "ROBO A BANCOS"). Sin esta tabla, esas
-- variantes se contarían como delitos distintos.
INSERT INTO delito_alias (fuente, etiqueta, delito_clave) VALUES
    ('iieg_colonias', 'FEMINICIDIO',                   'feminicidio'),
    ('iieg_colonias', 'HOMICIDIO DOLOSO',              'homicidio_doloso'),
    ('iieg_colonias', 'PARRICIDIO',                    'parricidio'),
    ('iieg_colonias', 'LESIONES DOLOSAS',              'lesiones_dolosas'),
    ('iieg_colonias', 'VIOLENCIA FAMILIAR',            'violencia_familiar'),
    ('iieg_colonias', 'ROBO A PERSONA',                'robo_persona'),
    ('iieg_colonias', 'ROBO A CUENTAHABIENTES',        'robo_cuentahabientes'),
    ('iieg_colonias', 'ROBO A VEHICULOS PARTICULARES', 'robo_vehiculo'),
    ('iieg_colonias', 'ROBO DE MOTOCICLETA',           'robo_motocicleta'),
    ('iieg_colonias', 'ROBO A INT DE VEHICULOS',       'robo_interior_vehiculo'),
    ('iieg_colonias', 'ROBO AUTOPARTES',               'robo_autopartes'),
    ('iieg_colonias', 'ROBO DE AUTOPARTES',            'robo_autopartes'),
    ('iieg_colonias', 'ROBO CASA HABITACION',          'robo_casa_habitacion'),
    ('iieg_colonias', 'ROBO A NEGOCIO',                'robo_negocio'),
    ('iieg_colonias', 'ROBO A BANCO',                  'robo_banco'),
    ('iieg_colonias', 'ROBO A BANCOS',                 'robo_banco'),
    ('iieg_colonias', 'ROBO A CARGA PESADA',           'robo_carga_pesada')
ON CONFLICT (fuente, etiqueta) DO NOTHING;

-- Etiquetas vistas en los datos que todavía nadie mapeó. Es una bandeja de
-- trabajo, no un error: las fuentes cambian su catálogo sin avisar.
CREATE TABLE IF NOT EXISTS delito_alias_pendiente (
    id           bigserial PRIMARY KEY,
    fuente       text      NOT NULL,
    etiqueta     text      NOT NULL,
    ocurrencias  bigint    NOT NULL DEFAULT 1,
    primera_vez  timestamptz NOT NULL DEFAULT now(),
    ultima_vez   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT delito_alias_pendiente_key UNIQUE (fuente, etiqueta)
);

-- ---------------------------------------------------------------------------
-- Franja horaria
-- ---------------------------------------------------------------------------
-- Función propia e IMMUTABLE para poder usarla en una columna generada.
-- La franja 'noche' es la que sostiene el módulo de seguridad peatonal
-- nocturna, así que su definición debe ser explícita y auditable, no un
-- BETWEEN suelto repetido en varias consultas.
CREATE OR REPLACE FUNCTION franja_horaria(h time)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN h IS NULL                              THEN NULL
        WHEN h >= time '00:00' AND h < time '06:00'  THEN 'madrugada'
        WHEN h >= time '06:00' AND h < time '12:00'  THEN 'manana'
        WHEN h >= time '12:00' AND h < time '18:00'  THEN 'tarde'
        ELSE                                              'noche'
    END;
$$;

COMMENT ON FUNCTION franja_horaria(time) IS
    'madrugada 00-06, manana 06-12, tarde 12-18, noche 18-24. '
    'Sin acento en manana para evitar problemas de codificación en la API.';

-- ---------------------------------------------------------------------------
-- Incidentes con ubicación puntual
-- ---------------------------------------------------------------------------
-- `geom` es NULLABLE a propósito. Varias fuentes dan calle y colonia pero no
-- coordenadas; se guardan igual y se geocodifican después, o se usan solo
-- agregados. Fabricar un punto para cumplir un NOT NULL sería inventar datos.
CREATE TABLE IF NOT EXISTS incidente (
    id              bigserial PRIMARY KEY,

    -- Trazabilidad: de dónde salió y con qué id en el origen. La pareja
    -- (fuente, id_origen) evita duplicados al reingerir el mismo archivo,
    -- que es el error más común en un ETL que corre periódicamente.
    fuente          text      NOT NULL,
    id_origen       text,
    lote_id         bigint,

    fecha           date      NOT NULL,
    hora            time,
    franja          text      GENERATED ALWAYS AS (franja_horaria(hora)) STORED,

    delito_clave    text      NOT NULL REFERENCES delito(clave),
    etiqueta_origen text,

    -- Ubicación textual tal como viene en la fuente, por si hay que
    -- geocodificar o auditar después.
    colonia_texto   text,
    calle_texto     text,

    geom            geometry(Point, 4326),

    -- Resueltos por join espacial en el ETL, no por el texto de la colonia
    -- (que viene con erratas y sin normalizar).
    unidad_id       bigint    REFERENCES unidad_geografica(id) ON DELETE SET NULL,
    municipio_clave char(5),

    -- Qué tan confiable es la ubicación. Sin esto no se puede distinguir un
    -- punto real de uno geocodificado a nivel colonia, y el mapa acabaría
    -- mostrando precisión que no tiene.
    precision_geo   text      CHECK (precision_geo IN
                                ('exacta', 'calle', 'colonia', 'municipio', 'sin_ubicacion')),

    atributos       jsonb     NOT NULL DEFAULT '{}'::jsonb,
    creado_en       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT incidente_fuente_origen_key UNIQUE (fuente, id_origen)
);

CREATE INDEX IF NOT EXISTS incidente_geom_gist
    ON incidente USING GIST (geom) WHERE geom IS NOT NULL;

CREATE INDEX IF NOT EXISTS incidente_fecha_idx        ON incidente (fecha);
CREATE INDEX IF NOT EXISTS incidente_delito_idx       ON incidente (delito_clave);
CREATE INDEX IF NOT EXISTS incidente_unidad_idx       ON incidente (unidad_id);
CREATE INDEX IF NOT EXISTS incidente_municipio_idx    ON incidente (municipio_clave);

-- Índice compuesto para la consulta más frecuente del mapa: incidentes de
-- cierto tipo, en cierta franja, en un rango de fechas.
CREATE INDEX IF NOT EXISTS incidente_consulta_mapa_idx
    ON incidente (municipio_clave, delito_clave, franja, fecha);

-- ---------------------------------------------------------------------------
-- Incidencia agregada
-- ---------------------------------------------------------------------------
-- Para fuentes que solo publican conteos, como el SESNSP (municipio-mes-tipo).
-- Es la vía honesta de usar esos datos: sin coordenadas falsas.
CREATE TABLE IF NOT EXISTS incidencia_agregada (
    id            bigserial PRIMARY KEY,
    fuente        text      NOT NULL,
    unidad_id     bigint    NOT NULL REFERENCES unidad_geografica(id) ON DELETE CASCADE,
    delito_clave  text      NOT NULL REFERENCES delito(clave),
    anio          smallint  NOT NULL CHECK (anio BETWEEN 2010 AND 2100),
    mes           smallint  NOT NULL CHECK (mes BETWEEN 1 AND 12),
    conteo        integer   NOT NULL CHECK (conteo >= 0),
    lote_id       bigint,
    creado_en     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT incidencia_agregada_key
        UNIQUE (fuente, unidad_id, delito_clave, anio, mes)
);

CREATE INDEX IF NOT EXISTS incidencia_agregada_periodo_idx
    ON incidencia_agregada (anio, mes);

CREATE INDEX IF NOT EXISTS incidencia_agregada_unidad_idx
    ON incidencia_agregada (unidad_id, delito_clave);

-- ---------------------------------------------------------------------------
-- Bitácora de cargas del ETL
-- ---------------------------------------------------------------------------
-- Sin esto no hay forma de responder "¿de cuándo son los datos que está
-- mostrando el mapa?", que es justo lo que va a preguntar un evaluador.
CREATE TABLE IF NOT EXISTS lote_ingesta (
    id                bigserial PRIMARY KEY,
    fuente            text      NOT NULL,
    descripcion       text,
    url_origen        text,
    -- Huella del archivo descargado: permite detectar que la fuente publicó
    -- una actualización y evitar reprocesar lo idéntico.
    sha256_archivo    text,
    periodo_inicio    date,
    periodo_fin       date,
    filas_leidas      integer,
    filas_insertadas  integer,
    filas_rechazadas  integer,
    estado            text      NOT NULL DEFAULT 'en_proceso'
                                CHECK (estado IN ('en_proceso', 'completado', 'fallido')),
    mensaje_error     text,
    iniciado_en       timestamptz NOT NULL DEFAULT now(),
    terminado_en      timestamptz
);

CREATE INDEX IF NOT EXISTS lote_ingesta_fuente_idx ON lote_ingesta (fuente, iniciado_en DESC);
