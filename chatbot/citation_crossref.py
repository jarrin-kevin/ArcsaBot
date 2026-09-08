"""
Cruce entre las citas a Normativa detectadas en el corpus de Tutorial
(chatbot/tutorial_ingestion.py) y el Corpus Documental real de Normativa
Vigente (chatbot/data/normativa/*.json).

Objetivo (ver CONTEXT.md y docs/adr/0004-flag-dont-drop-outdated-tutorial-
citations.md): para cada cita a Normativa que aparece en una página de
Tutorial (p. ej. "ARCSA-DE-2021-016-AKRG", "Acuerdo Ministerial Nº 705",
"Decisión 833"), determinar si esa Normativa existe en el Corpus Documental
actual. Las citas que NO aparecen en el corpus son candidatas a "Cita
Desactualizada": pueden apuntar a una Normativa derogada, superada por una
reforma con otro código, o simplemente todavía no incorporada al corpus.
Este módulo NO distingue esos tres casos ni concluye que el Tutorial esté
equivocado: solo produce la bandera "no_encontrada_en_corpus" para que una
persona la revise (ADR 0004: "flag, don't drop/assume", aplicado aquí a
nivel de cita individual).

Estrategia de matching (ver limitaciones honestas en el reporte final del
trabajo, no solo aquí):
  - El campo "source" de un chunk de Normativa es el título del documento
    (nombre de archivo original sin extensión), no un campo de código
    estructurado. Los títulos reales SÍ suelen embeber el código de la
    Normativa (p. ej. "Resolución_ARCSA-DE-002-2020-LDCL Buenas Prácticas
    de..."), así que el cruce se hace extrayendo ese código del título con
    el mismo tipo de patrón que ya usa tutorial_ingestion.py para
    extraerlo del cuerpo del Tutorial, y comparando identificadores
    normalizados (no substrings crudos) entre ambos lados.
  - Resolución ARCSA-DE-*: se compara el código completo (letras, dígitos y
    guiones) ignorando espacios en blanco, porque el scrape del Tutorial
    introduce a veces un espacio accidental dentro del código (defecto ya
    documentado en tutorial_ingestion.py, p. ej. "ARCSA-DE-2021- 008-AKRG").
  - Acuerdo Ministerial: se compara solo el número (ignorando "N°/No./Nº" y
    ceros a la izquierda), y el año si ambos lados lo traen.
  - Decisión CAN: se compara solo el número, tolerando además la variante
    mal escrita "DESICION" que aparece en el corpus real.

Este módulo NO modifica tutorial_ingestion.py, ingestion.py,
normativa_extraction.py, vector_store.py, main.py ni vector_ingest.py: solo
importa run_pipeline() de tutorial_ingestion (igual que ya hace
vector_ingest.py). No hace embeddings ni llamadas a un vector store.

Modo de uso (desde la raíz del repositorio):

    python -m chatbot.citation_crossref
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from chatbot.tutorial_ingestion import run_pipeline as run_tutorial_pipeline

# --------------------------------------------------------------------------
# Rutas por defecto.
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
NORMATIVA_DIR = BASE_DIR / "data" / "normativa"
OUTPUT_PATH = BASE_DIR / "data" / "citation_crossref_report.json"


# --------------------------------------------------------------------------
# Clasificación y normalización de una cita ya extraída por
# tutorial_ingestion.py (el string de la cita, no el texto completo).
# --------------------------------------------------------------------------

_ARCSA_DE_PREFIX_PATTERN = re.compile(r"^ARCSA-DE-", re.IGNORECASE)

# OJO: este patrón se corre sobre el título ORIGINAL de la Normativa (con
# sus espacios intactos), nunca sobre una versión con todo el whitespace
# ya eliminado. Un título real es prosa ("...LDCL Buenas Prácticas de
# Almacenamiento..."), y si se le quita el espacio antes de aplicar el
# regex, el cuantificador ávido "[A-Z]{2,6}" del sufijo se come letras de
# la palabra siguiente (p. ej. "LDCL" + "Buenas" -> "LDCLBU"), produciendo
# un código incorrecto y un falso negativo. El "(?![A-Za-z])" es una
# segunda barrera para el caso (no visto en el corpus real, pero posible)
# de un título sin separador entre el código y la palabra siguiente.
_ARCSA_DE_CODE_PATTERN = re.compile(
    r"ARCSA-DE-\d{2,4}-\s?\d{2,4}-\s?[A-Z]{2,6}(?![A-Za-z])",
    re.IGNORECASE,
)

# Mismo espíritu que _ACUERDO_MINISTERIAL_PATTERN de tutorial_ingestion.py,
# pero con el número/año capturados en grupos para poder comparar solo el
# identificador (no el string completo, que varía en "N°/No./Nº").
_ACUERDO_NUM_PATTERN = re.compile(
    r"Acuerdo\s+Ministerial\s+(?:N[°ºo]\.?\s*)?(\d{1,6})(?:-(\d{4}))?",
    re.IGNORECASE,
)

# Incluye la variante mal escrita "DESICION" encontrada en el título real
# "DESICION 826_Notificación Sanitaria Obligatoria..." del Corpus
# Documental: un ejemplo concreto de que un matching por substring de texto
# (en vez de por número normalizado) habría fallado en encontrar ese
# documento aunque la Decisión sí está en el corpus.
_DECISION_NUM_PATTERN = re.compile(
    r"(?:Decisi[oó]n(?:es)?|DESICION)\s+(\d{1,5})",
    re.IGNORECASE,
)


def _strip_ws_upper(text: str) -> str:
    """Quita todo whitespace y pasa a mayúsculas.

    Se usa para comparar códigos ARCSA-DE tolerando el espacio accidental
    que el scrape a veces introduce dentro del código (ver docstring del
    módulo y comentarios de tutorial_ingestion.py sobre este defecto).
    """
    return re.sub(r"\s+", "", text).upper()


AcuerdoKey = tuple  # (numero: int, anio: Optional[str])


def classify_citation(citation: str):
    """
    Clasifica una cita ya extraída (string tal como la devuelve
    parse_tutorial()) y devuelve (tipo, identificador_normalizado).

    tipo es uno de "resolucion_arcsa", "acuerdo_ministerial", "decision_can",
    o None si la cita no calzó ningún patrón conocido (no debería ocurrir en
    la práctica, porque las citas ya vienen filtradas por los patrones de
    tutorial_ingestion.py, pero se maneja por robustez en vez de asumirlo).
    """
    stripped = citation.strip()

    if _ARCSA_DE_PREFIX_PATTERN.match(stripped):
        return "resolucion_arcsa", _strip_ws_upper(stripped)

    match = _ACUERDO_NUM_PATTERN.search(stripped)
    if match:
        numero = int(match.group(1))
        anio = match.group(2)
        return "acuerdo_ministerial", (numero, anio)

    match = _DECISION_NUM_PATTERN.search(stripped)
    if match:
        return "decision_can", int(match.group(1))

    return None, None


# --------------------------------------------------------------------------
# Carga del Corpus Documental real y construcción de su índice de
# identificadores (a partir del título "source" de cada chunk).
# --------------------------------------------------------------------------

def load_normativa_sources(normativa_dir: Path = NORMATIVA_DIR) -> list[str]:
    """
    Carga el título ("source") de cada chunk de Normativa Vigente,
    deduplicado.

    Se cruza contra el título del documento (no contra el texto de cada
    Artículo): la cita del Tutorial identifica una Normativa completa
    (una Resolución, un Acuerdo Ministerial, una Decisión CAN), no un
    Artículo específico dentro de ella, y el título es el único campo
    donde el código de la Normativa aparece de forma reconocible.
    """
    sources: set[str] = set()
    for path in sorted(normativa_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        for chunk in data.get("chunks", []):
            source = chunk.get("source")
            if source:
                sources.add(source)
    return sorted(sources)


def build_normativa_index(sources: list[str]):
    """
    Construye tres índices (uno por tipo de cita) que mapean un
    identificador normalizado hacia la lista de títulos de Normativa donde
    aparece ese identificador.

    Un título puede alimentar más de una entrada si menciona más de un
    identificador (p. ej. un título de Reforma que menciona tanto su propio
    código como el código que reforma), y un identificador puede recibir
    más de un título si más de un documento lo menciona (p. ej. una
    Decisión modificatoria que menciona la Decisión original en su título).
    """
    resolucion_index: dict[str, list[str]] = defaultdict(list)
    acuerdo_index: dict[AcuerdoKey, list[str]] = defaultdict(list)
    decision_index: dict[int, list[str]] = defaultdict(list)

    for source in sources:
        # Se busca sobre el título tal cual (ver docstring del patrón):
        # solo se normaliza (quitar whitespace, mayúsculas) el fragmento ya
        # extraído, para usarlo como llave del índice.
        for match in _ARCSA_DE_CODE_PATTERN.finditer(source):
            code = _strip_ws_upper(match.group(0))
            resolucion_index[code].append(source)

        for match in _ACUERDO_NUM_PATTERN.finditer(source):
            key = (int(match.group(1)), match.group(2))
            acuerdo_index[key].append(source)

        for match in _DECISION_NUM_PATTERN.finditer(source):
            decision_index[int(match.group(1))].append(source)

    return resolucion_index, acuerdo_index, decision_index


def _lookup_acuerdo(
    acuerdo_index: dict[AcuerdoKey, list[str]], numero: int, anio: Optional[str]
) -> list[str]:
    """
    Busca un Acuerdo Ministerial por número, tolerando que uno de los dos
    lados (cita del Tutorial vs. título de Normativa) no traiga año.

    Si AMBOS lados traen año, deben coincidir: dos Acuerdos Ministeriales
    distintos podrían compartir número de secuencia en años distintos, y
    ahí sí el año es la única señal que los distingue.
    """
    matches: list[str] = []
    for (idx_numero, idx_anio), titles in acuerdo_index.items():
        if idx_numero != numero:
            continue
        if anio is not None and idx_anio is not None and anio != idx_anio:
            continue
        matches.extend(titles)
    return matches


def find_matches(
    citation: str,
    resolucion_index: dict[str, list[str]],
    acuerdo_index: dict[AcuerdoKey, list[str]],
    decision_index: dict[int, list[str]],
) -> list[str]:
    """Devuelve la lista (puede ser vacía) de títulos de Normativa que calzan con esta cita."""
    tipo, identificador = classify_citation(citation)
    if tipo == "resolucion_arcsa":
        return list(resolucion_index.get(identificador, []))
    if tipo == "acuerdo_ministerial":
        numero, anio = identificador
        return _lookup_acuerdo(acuerdo_index, numero, anio)
    if tipo == "decision_can":
        return list(decision_index.get(identificador, []))
    return []


# --------------------------------------------------------------------------
# Orquestación del cruce completo.
# --------------------------------------------------------------------------

def build_crossref(tutorial_chunks: list[dict], normativa_sources: list[str]):
    """
    Cruza cada cita única del Tutorial contra el índice de Normativa y las
    separa en matched (encontrada_en_corpus) y unmatched
    (no_encontrada_en_corpus, candidata a Cita Desactualizada).

    Returns:
        (matched, unmatched):
          matched: dict cita -> lista de títulos de Normativa coincidentes.
          unmatched: dict cita -> lista de páginas de Tutorial que la citan
            (cada página con "title" y "source_url"), para que una persona
            pueda ir directo a revisarla.
    """
    resolucion_index, acuerdo_index, decision_index = build_normativa_index(normativa_sources)

    citation_to_pages: dict[str, list[dict]] = defaultdict(list)
    for chunk in tutorial_chunks:
        for citation in chunk.get("normativa_citations", []):
            citation_to_pages[citation].append(
                {"title": chunk.get("title"), "source_url": chunk.get("source_url")}
            )

    matched: dict[str, list[str]] = {}
    unmatched: dict[str, list[dict]] = {}

    for citation, pages in citation_to_pages.items():
        matches = find_matches(citation, resolucion_index, acuerdo_index, decision_index)
        if matches:
            matched[citation] = sorted(set(matches))
            continue

        # Dedup de páginas por (title, source_url): normativa_citations ya
        # viene deduplicado dentro de una misma página, pero si la misma
        # página apareciera más de una vez en el corpus no queremos
        # duplicarla en el reporte.
        seen: set[tuple] = set()
        unique_pages: list[dict] = []
        for page in pages:
            key = (page["title"], page["source_url"])
            if key not in seen:
                seen.add(key)
                unique_pages.append(page)
        unmatched[citation] = unique_pages

    return matched, unmatched


def write_report(
    matched: dict[str, list[str]],
    unmatched: dict[str, list[dict]],
    tutorial_chunk_count: int,
    normativa_source_count: int,
    output_path: Path = OUTPUT_PATH,
) -> dict:
    total = len(matched) + len(unmatched)
    report = {
        "resumen": {
            "total_citas_unicas": total,
            "encontradas_en_corpus": len(matched),
            "no_encontradas_en_corpus": len(unmatched),
            "paginas_tutorial_analizadas": tutorial_chunk_count,
            "documentos_normativa_analizados": normativa_source_count,
        },
        "citas_no_encontradas": [
            {"cita": citation, "paginas_tutorial": pages}
            for citation, pages in sorted(unmatched.items())
        ],
        "citas_encontradas": [
            {"cita": citation, "documentos_normativa_coincidentes": titles}
            for citation, titles in sorted(matched.items())
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Reporte de cruce escrito en '{output_path}'.")

    return report


def main() -> dict:
    print("[INFO] Ejecutando pipeline de Tutorial (chatbot/tutorial_ingestion.py)...")
    tutorial_chunks = run_tutorial_pipeline()

    print(f"[INFO] Cargando títulos de Normativa desde '{NORMATIVA_DIR}'...")
    normativa_sources = load_normativa_sources()
    print(f"[INFO] {len(normativa_sources)} documentos de Normativa indexados (por título único).")

    matched, unmatched = build_crossref(tutorial_chunks, normativa_sources)

    total = len(matched) + len(unmatched)
    print(f"[INFO] Citas únicas de Normativa encontradas en el Tutorial: {total}")
    print(f"       - encontrada_en_corpus: {len(matched)}")
    print(f"       - no_encontrada_en_corpus (candidata a Cita Desactualizada): {len(unmatched)}")

    return write_report(matched, unmatched, len(tutorial_chunks), len(normativa_sources))


if __name__ == "__main__":
    main()
