"""
run_eval.py
Fase 2 del plan de evaluacion del TFE: corre las 40 consultas de
chatbot/eval/golden_set.json contra el pipeline RAG REAL (Pinecone + Gemini,
el mismo codigo que corre en produccion en chatbot/main.py) y guarda una
traza completa por consulta en chatbot/eval/traces.jsonl (JSON Lines).

No modifica nada bajo chatbot/data/ (fuerza CHATBOT_DB_PATH a un sqlite
temporal en el scratchpad ANTES de importar chatbot.auth, que si no
escribiria en chatbot/data/users.db al importarse). No pega por HTTP: llama
directo a las funciones de chatbot/main.py (retrieve_chunks,
_build_grounded_prompt, _build_source_citation, _is_low_confidence,
llm.complete) para tener control total sobre que capturar, igual que pediria
golpear el endpoint real /api/chat pero sin la latencia/rate-limit de red.

Uso:
    ./.venv/Scripts/python.exe chatbot/eval/run_eval.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
CHATBOT_DIR = EVAL_DIR.parent
GOLDEN_SET_PATH = EVAL_DIR / "golden_set.json"
TRACES_PATH = EVAL_DIR / "traces.jsonl"

# IMPORTANTE: esto tiene que pasar ANTES de importar nada de chatbot/, porque
# chatbot/auth.py llama a _init_db() (que escribe en disco) al nivel de
# modulo, apenas se importa. Sin este override tocaria chatbot/data/users.db
# real. Mismo mecanismo que ya usa la suite de tests del proyecto
# (chatbot/tests/), ver comentario en chatbot/auth.py junto a DB_PATH.
_SCRATCH_DB = Path(
    os.environ.get(
        "RAGEVAL_SCRATCH_DIR",
        r"C:\Users\jarri\AppData\Local\Temp\claude\C--Users-jarri-Desktop-RagChatbot\acaebe96-f13e-4985-b9bd-a582d58dd84f\scratchpad",
    )
) / "eval_users.db"
os.environ["CHATBOT_DB_PATH"] = str(_SCRATCH_DB)

# chatbot/main.py hace imports "planos" (from auth import ...,
# from vector_store import ...), asi que chatbot/ tiene que estar en
# sys.path para poder importar main.py tal cual vive en el repo.
sys.path.insert(0, str(CHATBOT_DIR))

import main as chatbot_main  # noqa: E402  (import despues de setear env/sys.path a proposito)

TOP_K = chatbot_main.TOP_K


# ---------------------------------------------------------------------------
# Reintentos con backoff para llamadas reales a Pinecone/Gemini
# ---------------------------------------------------------------------------

RETRY_DELAYS_SECONDS = [5, 20, 45]  # unos pocos reintentos con backoff creciente
SLEEP_BETWEEN_QUERIES_SECONDS = 1.5  # ser buen vecino de la API real


def _with_retries(fn, *, label: str):
    """Ejecuta fn() con reintentos + backoff. Devuelve (resultado, error_str).
    Si todos los intentos fallan, error_str describe el fallo REAL (no se
    inventa nada); resultado es None en ese caso."""
    last_exc = None
    attempts = len(RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001 - se registra tal cual, no se oculta
            last_exc = exc
            print(
                f"    [WARN] {label}: intento {attempt + 1}/{attempts} fallo: "
                f"{exc!r}"
            )
            if attempt < len(RETRY_DELAYS_SECONDS):
                time.sleep(RETRY_DELAYS_SECONDS[attempt])
    tb = traceback.format_exception_only(type(last_exc), last_exc)
    error_str = f"{label} fallo tras {attempts} intentos: {''.join(tb).strip()}"
    return None, error_str


def process_case(case: dict) -> dict:
    query_id = case["id"]
    consulta = case["consulta"]
    eje = case.get("eje")

    trace: dict = {
        "id": query_id,
        "consulta": consulta,
        "eje": eje,
        "fragmentos_recuperados": [],
        "prompt_construido": None,
        "respuesta_generada": None,
        "fuentes_citadas": [],
        "is_low_confidence": None,
    }

    # 1) Recuperacion de chunks (embedding de la query + busqueda en Pinecone
    #    + resolucion via docstore local), identico a chat() en main.py.
    chunks, retrieval_error = _with_retries(
        lambda: chatbot_main.retrieve_chunks(consulta, top_k=TOP_K),
        label="retrieve_chunks",
    )
    if retrieval_error is not None:
        trace["error"] = retrieval_error
        return trace

    trace["fragmentos_recuperados"] = [
        {
            "id": chunk.get("id"),
            "distance": chunk.get("distance"),
            "text": chunk.get("text", ""),
            "metadata": chunk.get("metadata", {}),
        }
        for chunk in chunks
    ]

    if not chunks:
        # Mismo camino que chat() en main.py cuando no hay chunks: no se
        # llama al LLM, se devuelve el texto fijo de "sin evidencia".
        trace["respuesta_generada"] = chatbot_main.NO_EVIDENCE_TEXT
        trace["fuentes_citadas"] = []
        trace["is_low_confidence"] = True
        return trace

    sources = [
        chatbot_main._build_source_citation(chunk, i)
        for i, chunk in enumerate(chunks, start=1)
    ]
    is_low_confidence = chatbot_main._is_low_confidence(chunks)
    prompt = chatbot_main._build_grounded_prompt(
        consulta, chunks, low_confidence=is_low_confidence
    )

    trace["fuentes_citadas"] = sources
    trace["is_low_confidence"] = is_low_confidence
    trace["prompt_construido"] = prompt

    # 2) Llamada real a Gemini con el prompt "grounded" ya armado.
    def _call_llm():
        response = chatbot_main.llm.complete(prompt)
        return response.text

    answer_text, llm_error = _with_retries(_call_llm, label="llm.complete")
    if llm_error is not None:
        trace["error"] = llm_error
        trace["respuesta_generada"] = None
    else:
        trace["respuesta_generada"] = answer_text

    return trace


def main() -> None:
    with GOLDEN_SET_PATH.open(encoding="utf-8") as f:
        golden_set = json.load(f)

    print(f"Golden set cargado: {len(golden_set)} casos desde {GOLDEN_SET_PATH}")
    print(f"Guardando trazas incrementalmente en {TRACES_PATH}")

    # Se abre en modo 'w' a proposito: esta es una corrida limpia y completa
    # de las 40 consultas (no una reanudacion parcial). Cada linea se escribe
    # y se flushea apenas se procesa esa consulta, para no perder progreso si
    # el proceso se corta a mitad de camino.
    already_done = set()
    if TRACES_PATH.exists():
        # Si ya existe un traces.jsonl de una corrida anterior interrumpida,
        # se reanuda en vez de perder lo ya hecho: se saltan los ids ya
        # presentes y se sigue agregando (append) el resto.
        with TRACES_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    already_done.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        if already_done:
            print(
                f"traces.jsonl ya existe con {len(already_done)} casos; se "
                "reanuda y se agregan solo los que faltan."
            )

    ok_count = 0
    error_count = 0

    with TRACES_PATH.open("a", encoding="utf-8") as out:
        for idx, case in enumerate(golden_set, start=1):
            if case["id"] in already_done:
                print(f"[{idx}/{len(golden_set)}] {case['id']} ya procesado, se salta.")
                continue

            print(f"[{idx}/{len(golden_set)}] Procesando {case['id']} ({case.get('eje')})...")
            trace = process_case(case)

            out.write(json.dumps(trace, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())

            if trace.get("error"):
                error_count += 1
                print(f"    -> ERROR: {trace['error'][:200]}")
            else:
                ok_count += 1
                print(
                    f"    -> OK (isLowConfidence={trace['is_low_confidence']}, "
                    f"{len(trace['fragmentos_recuperados'])} fragmentos)"
                )

            time.sleep(SLEEP_BETWEEN_QUERIES_SECONDS)

    print(f"\nListo. OK={ok_count} ERROR={error_count} de {len(golden_set)} casos.")


if __name__ == "__main__":
    main()
