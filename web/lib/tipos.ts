/**
 * Tipos del metadato y de las propiedades que produce el ETL.
 *
 * Espejo de lo que escribe etl/georisk/exportar.py. Si cambia la salida del
 * ETL, esto tiene que cambiar con ella.
 */

export type ClaveEstrato = "bajo" | "moderado" | "alto" | "critico";

export type Normalizacion = "poblacion" | "area";

export interface Perfil {
  clave: string;
  nombre: string;
  descripcion: string;
  /** Limitación metodológica que la interfaz debe mostrar. Puede venir vacía. */
  advertencia: string;
  orden: number;
  /** Denominador con el que se calculó: población residente o superficie. */
  normalizacion: Normalizacion;
  /** Texto para rotular la cifra, p. ej. "por 100 mil hab." */
  unidad_tasa: string;
  /**
   * Nombres de las propiedades del GeoJSON que corresponden a este perfil.
   * Vienen del ETL en lugar de construirse con plantillas en el cliente, para
   * que un cambio de nomenclatura no rompa el mapa en silencio.
   */
  campo_indice: string;
  campo_estrato: string;
  campo_incidentes: string;
  campo_tasa: string;
  campo_muestra_baja: string;
  campo_percentil: string;
  delitos: string[];
  resumen_estratos: Partial<Record<ClaveEstrato, number>>;
}

export interface Fuente {
  clave: string;
  nombre: string;
  institucion: string;
  url: string;
  cadencia: string;
  notas: string;
}

export interface CoberturaEmpate {
  incidentes_totales: number;
  incidentes_ubicados: number;
  porcentaje_ubicado: number;
  incidentes_sin_colonia_en_fuente: number;
  incidentes_sin_poligono: number;
  nombres_unicos: number;
  nombres_empatados: number;
  metodos_de_empate: Record<string, number>;
  principales_sin_poligono: {
    municipio: string;
    colonia: string;
    incidentes: number;
  }[];
}

export interface Meta {
  generado_en: string;
  metodo_version: string;
  periodo: {
    inicio: string;
    fin: string;
    meses: number;
    etiqueta: string;
  };
  advertencia_principal: string;
  municipios: { clave: string; nombre: string }[];
  unidad_analisis: {
    tipo: string;
    total: number;
    fuente_poligonos: string;
  };
  perfiles: Perfil[];
  estratos: { clave: ClaveEstrato; percentil_hasta: number }[];
  metodologia: {
    descripcion: string;
    umbral_muestra_baja: {
      poblacion_minima: number;
      incidentes_minimos: number;
      nota: string;
    };
    pesos_severidad: Record<string, number>;
  };
  cobertura_empate: CoberturaEmpate;
  fuentes: Fuente[];
}

/**
 * Propiedades de cada colonia en el GeoJSON.
 *
 * Las métricas por perfil llegan con nombre dinámico (`idx_general`,
 * `est_peaton`, …), así que se declara un índice abierto y se accede a través
 * de los `campo_*` del perfil.
 */
export interface PropiedadesColonia {
  clave: string;
  nombre: string;
  municipio_clave: string;
  poblacion: number | null;
  area_km2: number;
  [metricaPorPerfil: string]: string | number | boolean | null;
}
