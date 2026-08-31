"""
Módulo de parsing/chunking jerárquico para Normativas ARCSA.

Convierte el texto crudo de una Normativa en chunks a nivel de Artículo,
que es la unidad de fragmentación definida en CONTEXT.md: un Artículo
contiene sus Numerales y Literales, y una obligación con sus excepciones
nunca debe quedar dividida entre dos chunks. Por eso NO se separan los
Numerales/Literales en chunks propios: viajan dentro del texto completo
de su Artículo.

Este módulo es solo la etapa de parsing. No hace embeddings ni llamadas
a un vector store (eso pertenece a otro workstream).
"""

import re


# Patrón que reconoce los encabezados de Artículo usados en la
# normativa ecuatoriana. Cubre variantes comunes:
#   "Art. 12.-", "Artículo 12.-", "ARTÍCULO 12.-", con o sin tildes,
#   y con número seguido opcionalmente de un sufijo alfabético
#   (p. ej. "Art. 12-A.-" para artículos "innumerados"/agregados).
#
# Grupos capturados:
#   1) número de artículo (dígitos)
#   2) sufijo opcional (letra, ej. "A" en "12-A")
ARTICULO_HEADER_PATTERN = re.compile(
    r"(?im)^\s*(?:art(?:í|i)culo|art)\.?\s+(\d+)\s*(?:[-.]?\s*([A-Za-z]))?\s*\.?-\s*",
)


def parse_normativa(text: str, source_name: str) -> list[dict]:
    """
    Divide el texto crudo de una Normativa en chunks a nivel de Artículo.

    Cada chunk conserva el texto completo del Artículo (incluyendo sus
    Numerales y Literales anidados, sin separarlos) porque una obligación
    y sus excepciones deben permanecer dentro de los límites del mismo
    Artículo (ver CONTEXT.md).

    Args:
        text: texto crudo de la Normativa (ya extraído del documento fuente).
        source_name: nombre del documento fuente (para trazabilidad).

    Returns:
        Lista de diccionarios, uno por Artículo encontrado, con las claves:
            - "articulo_numero": identificador del artículo (str), p. ej. "12" o "12-A"
            - "texto": texto completo del artículo (incluye Numerales/Literales)
            - "source": nombre del documento fuente
            - "vigente": bool, True por defecto (ver ADR 0004: una Tutorial que
              cita este artículo puede marcarse luego como "Cita Desactualizada"
              si este campo pasa a False, sin borrar nada)
    """
    matches = list(ARTICULO_HEADER_PATTERN.finditer(text))

    if not matches:
        print(
            f"[ADVERTENCIA] No se encontraron encabezados de Artículo en '{source_name}'. "
            "Verifica el formato del documento fuente."
        )
        return []

    chunks = []
    for i, match in enumerate(matches):
        numero = match.group(1)
        sufijo = match.group(2)
        articulo_numero = f"{numero}-{sufijo.upper()}" if sufijo else numero

        # El texto del artículo va desde el inicio de este encabezado
        # hasta el inicio del siguiente encabezado (o el final del texto).
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        articulo_texto = text[start:end].strip()

        chunks.append(
            {
                "articulo_numero": articulo_numero,
                "texto": articulo_texto,
                "source": source_name,
                "vigente": True,
            }
        )

    print(f"[INFO] Se extrajeron {len(chunks)} artículo(s) de '{source_name}'.")
    return chunks


def to_documents(chunks: list[dict]):
    """
    Envuelve cada chunk de parse_normativa en un llama_index.core.Document,
    dejando los campos (articulo_numero, source, vigente) como metadata.

    Esta función es un paso delgado de adaptación hacia LlamaIndex; el
    parsing puro (parse_normativa) no depende de LlamaIndex.

    Args:
        chunks: lista de diccionarios producidos por parse_normativa.

    Returns:
        Lista de instancias de llama_index.core.Document.
    """
    from llama_index.core import Document

    documents = []
    for chunk in chunks:
        documents.append(
            Document(
                text=chunk["texto"],
                metadata={
                    "articulo_numero": chunk["articulo_numero"],
                    "source": chunk["source"],
                    "vigente": chunk["vigente"],
                },
            )
        )
    return documents


if __name__ == "__main__":
    # NOTA: el texto de ejemplo a continuación es un PLACEHOLDER ficticio
    # para ilustrar el uso del módulo. NO es contenido real de ARCSA.
    texto_ejemplo = """
Art. 1.- [texto de ejemplo] Toda persona que solicite el trámite X deberá
presentar los siguientes requisitos:
1. Requisito de ejemplo uno.
2. Requisito de ejemplo dos.
   a) Literal de ejemplo dentro del numeral 2.
   b) Otro literal de ejemplo.

Art. 2.- [texto de ejemplo] Se exceptúa de lo dispuesto en el artículo
anterior a los casos de ejemplo previstos en el numeral 3 de este mismo
artículo.
3. Excepción de ejemplo aplicable únicamente a este artículo.

Art. 3-A.- [texto de ejemplo] Artículo innumerado de ejemplo, agregado
mediante una reforma ficticia posterior.
"""

    print("Ejecutando ejemplo ilustrativo con texto PLACEHOLDER (no es texto real de ARCSA)...")
    resultado = parse_normativa(texto_ejemplo, source_name="normativa_ejemplo_placeholder.txt")
    for chunk in resultado:
        print("-" * 60)
        print(f"Artículo: {chunk['articulo_numero']}")
        print(f"Vigente: {chunk['vigente']}")
        print(f"Texto:\n{chunk['texto']}")
