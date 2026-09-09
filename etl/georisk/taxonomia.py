"""Taxonomía canónica de delitos y perfiles de riesgo.

Espejo de lo que siembran las migraciones 0002 y 0003. Existe en Python
porque el ETL debe poder correr y exportar resultados sin una base de datos
levantada, y porque el cálculo del índice necesita los pesos en memoria.

`georisk.cli verificar-taxonomia` compara este módulo contra la base cuando
hay conexión, para que las dos definiciones no se desincronicen en silencio.
Si tocas los pesos aquí, tócalos también en db/migrations/0002_incidencia.sql.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Delito:
    clave: str
    nombre: str
    categoria: str
    peso_severidad: float
    es_violento: bool = False
    afecta_peaton: bool = False
    afecta_vehiculo: bool = False
    afecta_negocio: bool = False
    afecta_vivienda: bool = False


# ---------------------------------------------------------------------------
# Catálogo canónico
# ---------------------------------------------------------------------------
# El peso de severidad es un juicio del proyecto, no un dato de la fuente.
# Se documenta aquí y se cita en el reporte: un índice compuesto sin criterio
# explícito de ponderación no es defendible académicamente.
_DELITOS: tuple[Delito, ...] = (
    Delito("homicidio_doloso", "Homicidio doloso", "vida", 10.0,
           es_violento=True, afecta_peaton=True),
    Delito("feminicidio", "Feminicidio", "vida", 10.0,
           es_violento=True, afecta_peaton=True),
    Delito("parricidio", "Parricidio", "vida", 10.0,
           es_violento=True, afecta_vivienda=True),
    Delito("lesiones_dolosas", "Lesiones dolosas", "integridad", 6.5,
           es_violento=True, afecta_peaton=True),
    Delito("violencia_familiar", "Violencia familiar", "integridad", 6.0,
           es_violento=True, afecta_vivienda=True),
    Delito("homicidio_culposo", "Homicidio culposo", "vida", 6.0,
           afecta_peaton=True, afecta_vehiculo=True),

    Delito("robo_persona", "Robo a persona", "patrimonio", 7.5,
           es_violento=True, afecta_peaton=True),
    Delito("robo_cuentahabientes", "Robo a cuentahabientes", "patrimonio", 7.5,
           es_violento=True, afecta_peaton=True),

    Delito("robo_vehiculo", "Robo de vehículo particular", "patrimonio", 6.5,
           afecta_vehiculo=True),
    Delito("robo_motocicleta", "Robo de motocicleta", "patrimonio", 6.0,
           afecta_vehiculo=True),
    Delito("robo_interior_vehiculo", "Robo al interior de vehículo", "patrimonio", 4.0,
           afecta_vehiculo=True),
    Delito("robo_autopartes", "Robo de autopartes", "patrimonio", 3.0,
           afecta_vehiculo=True),

    Delito("robo_casa_habitacion", "Robo a casa habitación", "patrimonio", 7.0,
           afecta_vivienda=True),
    Delito("robo_negocio", "Robo a negocio", "patrimonio", 6.0,
           afecta_negocio=True),
    Delito("robo_banco", "Robo a banco", "patrimonio", 7.0,
           es_violento=True, afecta_negocio=True),
    Delito("robo_carga_pesada", "Robo a carga pesada", "patrimonio", 5.0,
           afecta_negocio=True),

    # Definidos para la futura integración del SESNSP; sin filas por ahora.
    Delito("violacion", "Violación", "sexual", 9.5,
           es_violento=True, afecta_peaton=True),
    Delito("abuso_sexual", "Abuso sexual", "sexual", 7.5,
           es_violento=True, afecta_peaton=True),
    Delito("secuestro", "Secuestro", "libertad", 10.0,
           es_violento=True, afecta_peaton=True),
    Delito("extorsion", "Extorsión", "libertad", 6.0, afecta_negocio=True),
    Delito("narcomenudeo", "Narcomenudeo", "otros", 4.5),
    Delito("danio_propiedad", "Daño a la propiedad", "patrimonio", 2.5,
           afecta_negocio=True, afecta_vivienda=True),

    Delito("otro", "Otro delito no clasificado", "otros", 1.0),
)

DELITOS: dict[str, Delito] = {d.clave: d for d in _DELITOS}

PESOS: dict[str, float] = {d.clave: d.peso_severidad for d in _DELITOS}


# ---------------------------------------------------------------------------
# Equivalencias del catálogo real del IIEG
# ---------------------------------------------------------------------------
# Verificadas contra el archivo, no supuestas. La fuente duplica categorías
# ("ROBO A BANCO" y "ROBO A BANCOS") y mezcla capitalización
# ("VIOLENCIA FAMILIAR" y "Violencia Familiar"): las claves aquí están en
# mayúsculas y el ETL normaliza antes de buscar.
ALIAS_IIEG: dict[str, str] = {
    "FEMINICIDIO": "feminicidio",
    "HOMICIDIO DOLOSO": "homicidio_doloso",
    "PARRICIDIO": "parricidio",
    "LESIONES DOLOSAS": "lesiones_dolosas",
    "VIOLENCIA FAMILIAR": "violencia_familiar",
    "ROBO A PERSONA": "robo_persona",
    "ROBO A CUENTAHABIENTES": "robo_cuentahabientes",
    "ROBO A VEHICULOS PARTICULARES": "robo_vehiculo",
    "ROBO DE MOTOCICLETA": "robo_motocicleta",
    "ROBO A INT DE VEHICULOS": "robo_interior_vehiculo",
    "ROBO AUTOPARTES": "robo_autopartes",
    "ROBO DE AUTOPARTES": "robo_autopartes",
    "ROBO CASA HABITACION": "robo_casa_habitacion",
    "ROBO A NEGOCIO": "robo_negocio",
    "ROBO A BANCO": "robo_banco",
    "ROBO A BANCOS": "robo_banco",
    "ROBO A CARGA PESADA": "robo_carga_pesada",
}


# ---------------------------------------------------------------------------
# Perfiles de riesgo
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Perfil:
    clave: str
    nombre: str
    descripcion: str
    # Banderas que debe cumplir un delito para entrar al perfil. Se evalúan
    # con OR: basta cumplir una.
    banderas: tuple[str, ...]
    orden: int

    # Denominador con el que se normaliza la incidencia. Es la decisión
    # metodológica más importante del índice.
    #
    #   "poblacion" -> delitos por 100 mil habitantes. Correcto cuando la
    #                  víctima potencial es quien VIVE ahí.
    #   "area"      -> delitos por kilómetro cuadrado. Correcto cuando la
    #                  víctima potencial es quien PASA por ahí.
    #
    # Usar población para todo produce el error clásico de estos mapas: el
    # Centro de Guadalajara tiene 2,585 residentes censados pero cientos de
    # miles de personas circulando, así que dividir entre residentes lo pinta
    # como la zona más peligrosa del planeta. Para un peatón lo relevante es
    # cuántos delitos ocurren en el territorio que va a caminar, no la
    # proporción respecto al padrón de vecinos.
    normalizacion: str = "poblacion"

    # Advertencia que la interfaz DEBE mostrar. Va aquí y no en el frontend
    # para que la limitación viaje junto al dato.
    advertencia: str = ""

    def incluye(self, delito: Delito) -> bool:
        if not self.banderas:
            return True
        return any(getattr(delito, b) for b in self.banderas)

    @property
    def unidad_tasa(self) -> str:
        return "por km²" if self.normalizacion == "area" else "por 100 mil hab."


PERFILES: dict[str, Perfil] = {
    p.clave: p
    for p in (
        Perfil(
            "general", "Riesgo general",
            "Todos los delitos registrados, ponderados por severidad y "
            "normalizados por población residente.",
            (), 1,
            normalizacion="poblacion",
        ),
        Perfil(
            "peaton", "Riesgo peatonal",
            "Delitos contra quien camina en vía pública: robo a persona, "
            "lesiones, homicidio. Medido por concentración territorial, porque "
            "lo que importa a quien transita es cuántos hechos ocurren en la "
            "zona, no la proporción respecto a sus vecinos.",
            ("afecta_peaton",), 2,
            normalizacion="area",
            advertencia=(
                "La fuente no registra la hora del hecho, así que este perfil "
                "NO puede distinguir riesgo diurno de nocturno."
            ),
        ),
        Perfil(
            "vehicular", "Riesgo vehicular",
            "Robo de vehículo, de motocicleta, al interior del vehículo y de "
            "autopartes. Responde si conviene dejar el auto en la calle.",
            ("afecta_vehiculo",), 3,
            normalizacion="area",
        ),
        Perfil(
            "residencial", "Riesgo residencial",
            "Robo a casa habitación y delitos violentos, por 100 mil "
            "habitantes. Insumo del módulo de valuación inmobiliaria: aquí sí "
            "la víctima potencial es quien vive en la colonia.",
            ("afecta_vivienda", "es_violento"), 4,
            normalizacion="poblacion",
        ),
        Perfil(
            "negocio", "Riesgo comercial",
            "Robo a negocio, a banco y a carga pesada, por kilómetro cuadrado. "
            "Para evaluar la ubicación de un local.",
            ("afecta_negocio",), 5,
            normalizacion="area",
        ),
    )
}


def delitos_del_perfil(perfil: str) -> list[str]:
    """Claves de delito que entran en un perfil."""
    p = PERFILES[perfil]
    return sorted(c for c, d in DELITOS.items() if p.incluye(d))
