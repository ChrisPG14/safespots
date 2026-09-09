"""Normalización y empate de nombres de colonia.

Este módulo resuelve el problema más caro del proyecto. La incidencia
delictiva del IIEG identifica la colonia por NOMBRE, escrito por capturistas
distintos a lo largo de cinco años y lleno de abreviaturas
("JARDS. DEL BOSQUE"). Los polígonos la identifican con otro nombre, más
formal ("Jardines del Bosque"). Sin un empate confiable no hay mapa.

Estrategia, de más a menos confiable:

  1. Normalizar y expandir abreviaturas; empatar exacto.
  2. Empatar contra los nombres alternativos que el propio padrón declara
     entre paréntesis: "Villaseñor (Santa Teresita)" son dos nombres del
     mismo lugar.
  3. Empatar con los tokens ordenados, para nombres escritos al revés.
  4. Empatar difuso DENTRO del mismo municipio, con umbral alto y guardas.
  5. Lo que no empata se reporta para revisión humana. Nunca se adivina:
     asignar incidentes a la colonia equivocada es peor que no asignarlos,
     porque el error queda invisible en el mapa.

El municipio SIEMPRE acota la búsqueda. Hay decenas de "Las Flores" en la
ZMG y compararlas entre municipios distintos produce empates falsos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process

# ---------------------------------------------------------------------------
# Abreviaturas observadas en los datos reales del IIEG
# ---------------------------------------------------------------------------
# Esta tabla no es teórica: cada entrada salió de inspeccionar los nombres que
# no empataban, ordenados por número de incidentes.
ABREVIATURAS: dict[str, str] = {
    # Tipos de asentamiento que a veces se escriben y a veces no
    "FRACC": "",
    "FRAC": "",
    "COL": "",
    "COLONIA": "",
    "BARRIO": "",
    "CJTO": "CONJUNTO",
    "CTO": "CONJUNTO",
    "RES": "RESIDENCIAL",
    "RESID": "RESIDENCIAL",
    "INFON": "INFONAVIT",
    "UHAB": "UNIDAD HABITACIONAL",
    "HAB": "HABITACIONAL",
    "CD": "CIUDAD",
    "EJ": "EJIDO",
    "PBLO": "PUEBLO",
    "RCHO": "RANCHO",
    "PQUE": "PARQUE",
    # Sustantivos frecuentes
    "JARDS": "JARDINES",
    "JARD": "JARDINES",
    "JDNES": "JARDINES",
    "HDA": "HACIENDA",
    "HDAS": "HACIENDAS",
    "STA": "SANTA",
    "STO": "SANTO",
    "SN": "SAN",
    "GPE": "GUADALUPE",
    "GDL": "GUADALAJARA",
    "VDA": "VILLA",
    "VLLA": "VILLA",
    "LOMS": "LOMAS",
    "MIRAD": "MIRADOR",
    "PRAD": "PRADOS",
    "ARB": "ARBOLEDAS",
    "BOSQ": "BOSQUES",
    "PTO": "PUERTO",
    "SRA": "SIERRA",
    "MPIO": "MUNICIPIO",
    "AMPL": "AMPLIACION",
    "AMP": "AMPLIACION",
    "PROL": "PROLONGACION",
    "SECC": "SECCION",
    "SEC": "SECCION",
    "SECT": "SECTOR",
    "DELEG": "DELEGACION",
    "AGR": "AGRICOLA",
    "IND": "INDUSTRIAL",
    # Puntos cardinales
    "OTE": "ORIENTE",
    "PTE": "PONIENTE",
    "NTE": "NORTE",
    # Nombres propios abreviados: aparecen muchísimo en colonias con nombre
    # de personaje histórico.
    "FCO": "FRANCISCO",
    "FRCO": "FRANCISCO",
    "MA": "MARIA",
    "JZ": "JUAREZ",
    "HDGO": "HIDALGO",
    "CIRCUN": "CIRCUNVALACION",
    "CIRC": "CIRCUNVALACION",
    "RNDA": "RONDA",
    "PZA": "PLAZA",
    "AV": "AVENIDA",
    "CAM": "CAMINO",
    "MIGL": "MIGUEL",
    "ANT": "ANTONIO",
    "SRIA": "SECRETARIA",
    "INT": "INTERIOR",
    "PDTE": "PRESIDENTE",
    "GRAL": "GENERAL",
    # Títulos que no identifican el lugar
    "LIC": "",
    "DR": "",
    "ING": "",
    "PROF": "",
}

# Números romanos a arábigos. "JALISCO SECC. I" y "Jalisco 1a Sección" son la
# misma colonia; sin esta conversión no empatan.
ROMANOS: dict[str, str] = {
    "I": "1", "II": "2", "III": "3", "IV": "4", "V": "5",
    "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10",
    "XI": "11", "XII": "12", "XIII": "13", "XIV": "14", "XV": "15",
}

# Artículos y preposiciones que no aportan a la identidad de la colonia.
#
# Ojo: "A" NO va aquí a propósito. En estos datos una "A" suelta casi siempre
# es el marcador de sección ("Loma Dorada Delegación A") y eliminarla haría
# indistinguibles la sección A y la B, que es justo el empate falso que más
# daño hace.
VACIAS: frozenset[str] = frozenset({"DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "EN"})

# Palabras que describen CÓMO se subdivide una colonia, no cuál es. El padrón
# de Tonalá escribe "Loma Dorada Delegación A" donde la fuente delictiva
# escribe "LOMA DORADA SECC. A": el sustantivo cambia pero el lugar es el
# mismo, así que se descarta y se compara lo que queda ("LOMA DORADA A").
#
# Descartarlas es seguro únicamente porque la guarda de `compatibles` exige
# que el número y la letra de sección coincidan.
ESTRUCTURALES: frozenset[str] = frozenset(
    {"SECCION", "DELEGACION", "ETAPA", "SECTOR", "FRACCION", "MANZANA", "SUPERMANZANA"}
)

# "CAB. MUN. TONALA" = cabecera municipal, el centro histórico. Se maneja
# aparte porque es frecuente y de mucho peso: son miles de incidentes.
_RE_CABECERA = re.compile(r"^CAB(?:ECERA)?\.?\s*MUN(?:ICIPAL)?\.?\s*(.*)$")

# Nombre alternativo que el padrón declara entre paréntesis.
_RE_PARENTESIS = re.compile(r"^(?P<antes>[^(]*)\((?P<dentro>[^)]*)\)(?P<despues>.*)$")


def quitar_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def es_cabecera(nombre: str) -> bool:
    """¿El nombre se refiere a la cabecera municipal?"""
    return bool(_RE_CABECERA.match(quitar_acentos(str(nombre)).upper().strip()))


def _vacio(texto: str) -> bool:
    return not texto.strip() or texto.strip().upper() in {
        "N.D.", "ND", "N.D", "NAN", "NONE", "SIN NOMBRE", "NO ESPECIFICADO",
    }


def normalizar(
    nombre: str | None,
    quitar_vacias: bool = False,
    quitar_estructurales: bool = False,
) -> str:
    """Lleva un nombre de colonia a una forma canónica comparable.

    Mayúsculas, sin acentos, sin puntuación, abreviaturas expandidas y
    romanos convertidos a dígitos.
    """
    if nombre is None or _vacio(str(nombre)):
        return ""

    texto = quitar_acentos(str(nombre)).upper()

    # "CAB. MUN. X" -> "X CENTRO", que es como el padrón suele nombrar al
    # centro histórico.
    m = _RE_CABECERA.match(texto.strip())
    if m:
        texto = f"{m.group(1)} CENTRO"

    # La puntuación se vuelve espacio para que "JARDS." y "JARDS" colapsen al
    # mismo token.
    texto = re.sub(r"[^A-Z0-9Ñ]+", " ", texto)

    salida: list[str] = []
    for token in texto.split():
        if token in ABREVIATURAS:
            expandido = ABREVIATURAS[token]
            if expandido:
                salida.extend(expandido.split())
            continue
        if token in ROMANOS:
            salida.append(ROMANOS[token])
            continue
        salida.append(token)

    if quitar_estructurales:
        salida = [t for t in salida if t not in ESTRUCTURALES]
    if quitar_vacias:
        salida = [t for t in salida if t not in VACIAS]

    return " ".join(salida).strip()


def clave_comparacion(nombre: str | None) -> str:
    """Forma reducida que se usa para el empate difuso."""
    return normalizar(nombre, quitar_vacias=True, quitar_estructurales=True)


def clave_ordenada(nombre: str | None) -> str:
    """Clave con los tokens ordenados alfabéticamente.

    Hace que "Lomas de Independencia" e "Independencia Lomas" —el mismo lugar
    escrito al revés— produzcan la misma clave.
    """
    return " ".join(sorted(clave_comparacion(nombre).split()))


def variantes(nombre: str | None) -> list[str]:
    """Formas alternativas de un nombre, en orden de preferencia.

    Cubre dos casos reales:

    * Nombres alternativos entre paréntesis. El padrón escribe
      "Villaseñor (Santa Teresita)" y la fuente delictiva usa a veces uno y a
      veces el otro. Ambos son claves válidas del mismo polígono.
    * Cabeceras municipales. "CAB. MUN. EL SALTO" puede aparecer en el padrón
      como "El Salto Centro" o simplemente como "Centro", así que se prueban
      las dos.
    """
    if nombre is None or _vacio(str(nombre)):
        return []

    crudo = quitar_acentos(str(nombre)).upper().strip()
    formas: list[str] = []

    m = _RE_PARENTESIS.match(crudo)
    if m:
        antes = m.group("antes").strip()
        dentro = m.group("dentro").strip()
        despues = m.group("despues").strip()
        # El nombre principal primero, luego el alterno. Un alterno puede
        # traer varias opciones separadas por "Y/O" o por coma.
        formas.append(f"{antes} {despues}".strip())
        # El nombre completo sin los paréntesis también cuenta: la fuente
        # escribe "LOMA DORADA EJIDAL" donde el padrón tiene
        # "Loma Dorada (Ejidal)", es decir el paréntesis no es un alias sino
        # parte del nombre.
        formas.append(f"{antes} {dentro} {despues}".strip())
        for pieza in re.split(r"\s*(?:Y/O|,|/)\s*", dentro):
            if pieza.strip():
                formas.append(pieza.strip())
    else:
        formas.append(crudo)

    if es_cabecera(crudo):
        # Además de "<municipio> CENTRO", probar "CENTRO" a secas.
        formas.append("CENTRO")

    # Deduplicar conservando el orden.
    vistas: set[str] = set()
    ordenadas: list[str] = []
    for f in formas:
        if f and f not in vistas:
            vistas.add(f)
            ordenadas.append(f)
    return ordenadas


# ---------------------------------------------------------------------------
# Guardas contra empates falsos
# ---------------------------------------------------------------------------
# Palabras que ubican la colonia dentro de un conjunto mayor. Si dos nombres
# difieren en una de estas son lugares DISTINTOS aunque el resto coincida:
# "Los Gavilanes Oriente" y "Los Gavilanes Poniente" están en lados opuestos.
_CARDINALES: frozenset[str] = frozenset(
    {"ORIENTE", "PONIENTE", "NORTE", "SUR", "CENTRO", "ALTA", "BAJA"}
)

_RE_DIGITOS = re.compile(r"\d+")

# Pares que el algoritmo confunde y que son lugares distintos. Cada entrada
# se agregó tras revisar a mano los empates difusos de mayor peso.
#
# Mantener esta lista es trabajo legítimo del proyecto: ningún umbral de
# similitud distingue "La Nopalera" de "La Nogalera", que difieren en una
# letra y son una colonia y una zona industrial completamente distintas.
EXCEPCIONES: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"NOPALERA", "NOGALERA"}),
        frozenset({"SANTA ANITA", "SANTA RITA"}),
        frozenset({"SAN MARTIN", "SAN MARCOS"}),
        frozenset({"LOMA BONITA", "LOMA LINDA"}),
    }
)


def _digitos(texto: str) -> frozenset[str]:
    """Números presentes en el nombre, sin importar cómo estén pegados.

    Se extraen con expresión regular y no por token porque el padrón escribe
    "Providencia 4a Sección" y la fuente "PROVIDENCIA SECC. IV": tras
    normalizar quedan "4A" y "4", que como token no coinciden pero como
    número sí.
    """
    return frozenset(_RE_DIGITOS.findall(texto))


def _letras_seccion(texto: str) -> frozenset[str]:
    """Tokens de una sola letra, que en estos datos marcan la sección.

    Es la guarda que permite descartar la palabra "Sección" sin riesgo:
    "Loma Dorada A" y "Loma Dorada B" quedan textualmente casi idénticas y
    solo esta comparación las separa.
    """
    return frozenset(t for t in texto.split() if len(t) == 1 and t.isalpha())


def compatibles(consulta: str, candidato: str, max_dif_tokens: int = 1) -> bool:
    """¿Pueden dos nombres normalizados referirse al mismo lugar?

    Filtro previo al puntaje de similitud: rechaza lo que la similitud
    textual no sabe rechazar.
    """
    tokens_a, tokens_b = consulta.split(), candidato.split()

    # Diferencia de longitud: sin esta guarda, "Loma" absorbe "Loma Dorada",
    # "Loma Bonita" y "Loma del Zalate". Ese error concentraba 2,935
    # incidentes en una colonia que tenía 18.
    if abs(len(tokens_a) - len(tokens_b)) > max_dif_tokens:
        return False

    a, b = set(tokens_a), set(tokens_b)
    if (a & _CARDINALES) != (b & _CARDINALES):
        return False
    if _digitos(consulta) != _digitos(candidato):
        return False
    if _letras_seccion(consulta) != _letras_seccion(candidato):
        return False
    if frozenset({consulta, candidato}) in EXCEPCIONES:
        return False

    return True


@dataclass
class Empate:
    """Resultado de intentar empatar un nombre contra el padrón."""

    nombre_origen: str
    clave_destino: str | None
    nombre_destino: str | None
    metodo: str  # exacto | alterno | ordenado | difuso | sin_empate
    puntaje: float  # 100 en los no difusos

    @property
    def resuelto(self) -> bool:
        return self.clave_destino is not None


class EmparejadorColonias:
    """Empata nombres de colonia contra el padrón de polígonos de un municipio.

    Se construye un emparejador por municipio. El municipio no es un detalle:
    acotar la búsqueda es lo que evita confundir "Las Flores" de Tonalá con
    "Las Flores" de Zapopan.
    """

    # 82 sobre 100 con token_sort_ratio. Calibrado midiendo cobertura contra
    # los datos reales y revisando A MANO los empates difusos que arrastran
    # más de 250 incidentes: a 82 los seis casos de mayor peso son correctos
    # ("Rojas Ladrón de Guevara" -> "Ladrón de Guevara", "Providencia Secc.
    # IV" -> "Providencia 4a Sección", "La Micaelita" -> "La Micailita").
    #
    # NO usar token_set_ratio: devuelve 100 cuando los tokens de un nombre
    # son subconjunto del otro, así que "La Loma" empataba con "Loma Dorada
    # Delegación A/B/C/D", "Loma del Zalate" y "Loma Linda". Tampoco WRatio:
    # incluye partial_ratio y sufre la misma patología, dando 90 a esos pares.
    UMBRAL_DIFUSO = 82.0

    def __init__(self, padron: dict[str, str]) -> None:
        """`padron` mapea clave de colonia -> nombre oficial."""
        self.padron = padron
        self._exactos: dict[str, str] = {}
        self._ordenados: dict[str, str] = {}
        self._difusos: dict[str, str] = {}
        # Nombres alternativos declarados por el padrón entre paréntesis. Van
        # en un índice aparte, con menor prioridad que los nombres
        # principales, para que un alterno nunca le gane a un nombre oficial.
        self._alternos: dict[str, str] = {}

        for clave, nombre in padron.items():
            formas = variantes(nombre)
            for i, forma in enumerate(formas):
                exacto = normalizar(forma)
                comparacion = clave_comparacion(forma)
                ordenado = clave_ordenada(forma)

                destino_exacto = self._exactos if i == 0 else self._alternos
                if exacto:
                    # setdefault y no asignación directa: si dos colonias
                    # normalizan igual conservamos la primera en lugar de
                    # resolver la ambigüedad al azar según el orden de lectura
                    # del shapefile.
                    destino_exacto.setdefault(exacto, clave)
                if comparacion:
                    destino_exacto.setdefault(comparacion, clave)
                    self._difusos.setdefault(comparacion, clave)
                if ordenado:
                    self._ordenados.setdefault(ordenado, clave)

    def _resultado(self, nombre: str, clave: str, metodo: str, puntaje: float) -> Empate:
        return Empate(nombre, clave, self.padron[clave], metodo, puntaje)

    def empatar(self, nombre: str) -> Empate:
        formas = variantes(nombre)
        if not formas:
            return Empate(nombre, None, None, "sin_empate", 0.0)

        # 1) exacto sobre el nombre principal
        for forma in formas:
            for clave_texto in (normalizar(forma), clave_comparacion(forma)):
                if clave_texto and (clave := self._exactos.get(clave_texto)) is not None:
                    return self._resultado(nombre, clave, "exacto", 100.0)

        # 2) exacto sobre los nombres alternativos del padrón
        for forma in formas:
            for clave_texto in (normalizar(forma), clave_comparacion(forma)):
                if clave_texto and (clave := self._alternos.get(clave_texto)) is not None:
                    return self._resultado(nombre, clave, "alterno", 100.0)

        # 3) tokens ordenados
        for forma in formas:
            ordenado = clave_ordenada(forma)
            if ordenado and (clave := self._ordenados.get(ordenado)) is not None:
                return self._resultado(nombre, clave, "ordenado", 100.0)

        # 4) difuso con guardas
        if not self._difusos:
            return Empate(nombre, None, None, "sin_empate", 0.0)

        for forma in formas:
            consulta = clave_comparacion(forma)
            if not consulta:
                continue
            # Se piden varios candidatos y no solo el mejor: el de mayor
            # puntaje puede quedar descartado por las guardas y el siguiente
            # sí ser válido.
            candidatos = process.extract(
                consulta,
                self._difusos.keys(),
                scorer=fuzz.token_sort_ratio,
                score_cutoff=self.UMBRAL_DIFUSO,
                limit=8,
            )
            for texto, puntaje, _ in candidatos:
                if compatibles(consulta, texto):
                    return self._resultado(
                        nombre, self._difusos[texto], "difuso", float(puntaje)
                    )

        return Empate(nombre, None, None, "sin_empate", 0.0)
