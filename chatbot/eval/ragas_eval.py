"""
ragas_eval.py
Fase 3 del plan de evaluacion del TFE: mide con RAGAS, usando gpt-5.5 como LLM
juez, 4 metricas sobre los 40 casos de chatbot/eval/golden_set.json cruzados
con chatbot/eval/traces.jsonl (trazas reales ya ejecutadas contra el pipeline
en produccion):

  - Context Precision  (recuperacion: pregunta + contextos recuperados + ref.)
  - Context Recall     (recuperacion: pregunta + contextos recuperados + ref.)
  - Faithfulness       (generacion:   pregunta + respuesta + contextos)
  - Answer Relevancy   (generacion:   pregunta + respuesta)

Decision metodologica (documentada tal como pide el plan de evaluacion):
  Los 8 casos con eje=fuera_de_cobertura tienen contexto_referencia=null en
  el golden set: no existe un fragmento normativo "correcto" contra el cual
  comparar lo recuperado, porque la pregunta no tiene respuesta en el corpus
  por diseno. Context Precision y Context Recall no tienen una definicion
  bien formada sin ese ground truth, asi que esos 8 casos se EXCLUYEN del
  calculo de esas dos metricas (ver funcion `build_cases`, campo
  `has_reference`). Si se hubieran incluido, el score dependeria de un
  "reference" ausente/artificial y el numero resultante no significaria nada
  interpretable.

  Faithfulness y Answer Relevancy, en cambio, no requieren contexto de
  referencia (evaluan la respuesta generada contra lo que efectivamente se
  recupero, no contra si lo recuperado era lo correcto), asi que SI se
  calculan para los 40 casos, incluidos los 8 fuera_de_cobertura. Esto es
  util precisamente para esos casos: permite chequear si el pipeline es
  "fiel" a evidencia irrelevante (p.ej. si alucina una respuesta igual, o si
  correctamente se abstiene/marca baja confianza en vez de inventar).

Fallos reales de RAGAS (timeout, error de parseo del juez, etc.) se
REGISTRAN explicitamente por caso y por metrica (campo "error" != null en
ragas_resultados.json) y se EXCLUYEN del promedio agregado, pero el conteo
de fallos se reporta siempre junto con cada media/mediana/desvio en
ragas_resumen.json — nunca se ocultan ni se promedian como si fueran 0.

No toca nada bajo chatbot/data/: solo lee golden_set.json y traces.jsonl, y
solo escribe en chatbot/eval/ (ragas_resultados.json y ragas_resumen.json).

Uso:
    ./.venv/Scripts/python.exe chatbot/eval/ragas_eval.py
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
import traceback
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
CHATBOT_DIR = EVAL_DIR.parent
REPO_ROOT = CHATBOT_DIR.parent

GOLDEN_SET_PATH = EVAL_DIR / "golden_set.json"
TRACES_PATH = EVAL_DIR / "traces.jsonl"
RESULTADOS_PATH = EVAL_DIR / "ragas_resultados.json"
RESUMEN_PATH = EVAL_DIR / "ragas_resumen.json"

JUDGE_MODEL = "gpt-5.5"
EMBEDDING_MODEL = "text-embedding-3-small"

MAX_CONCURRENCY = 5
PER_CALL_TIMEOUT_SECONDS = 240.0
RETRY_DELAYS_SECONDS = [10, 30]  # 2 reintentos con backoff antes de registrar fallo real

METRIC_NAMES = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
GENERATION_METRICS = ["faithfulness", "answer_relevancy"]
RETRIEVAL_METRICS = ["context_precision", "context_recall"]


# ---------------------------------------------------------------------------
# Carga de datos y cruce por id
# ---------------------------------------------------------------------------


def load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY no esta seteada tras cargar .env desde "
            f"{REPO_ROOT / '.env'}. No se puede correr RAGAS sin credenciales."
        )


def build_cases() -> list[dict[str, Any]]:
    golden = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    traces_by_id: dict[str, dict[str, Any]] = {}
    with TRACES_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            traces_by_id[t["id"]] = t

    golden_ids = {g["id"] for g in golden}
    trace_ids = set(traces_by_id)
    if golden_ids != trace_ids:
        raise RuntimeError(
            "golden_set.json y traces.jsonl no tienen el mismo conjunto de "
            f"ids. Solo en golden: {golden_ids - trace_ids}. Solo en "
            f"traces: {trace_ids - golden_ids}."
        )

    cases = []
    for g in golden:
        qid = g["id"]
        t = traces_by_id[qid]
        if t.get("error"):
            # Fallo real del pipeline en Fase 2 (no de RAGAS): no hay
            # respuesta/contextos utilizables. Se registra como caso
            # excluido en vez de inventar datos.
            cases.append(
                {
                    "id": qid,
                    "eje": g["eje"],
                    "has_reference": g["contexto_referencia"] is not None,
                    "pipeline_error": t["error"],
                    "sample": None,
                }
            )
            continue

        retrieved_contexts = [c["text"] for c in t.get("fragmentos_recuperados", [])]
        cases.append(
            {
                "id": qid,
                "eje": g["eje"],
                "has_reference": g["contexto_referencia"] is not None,
                "pipeline_error": None,
                "user_input": g["consulta"],
                "response": t.get("respuesta_generada") or "",
                "retrieved_contexts": retrieved_contexts,
                "reference": g["contexto_referencia"],
            }
        )
    return cases


# ---------------------------------------------------------------------------
# Ejecucion de metricas RAGAS, caso por caso, con reintentos y registro de
# fallos reales (nunca se omiten silenciosamente).
# ---------------------------------------------------------------------------


async def score_one(metric, sample, *, label: str) -> tuple[float | None, str | None]:
    """Corre una metrica sobre una muestra con reintentos acotados.
    Devuelve (score, None) si tuvo exito, o (None, error_str) si fallo tras
    agotar los reintentos. error_str describe el fallo REAL, no se inventa."""
    attempts = len(RETRY_DELAYS_SECONDS) + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            score = await metric.single_turn_ascore(sample, timeout=PER_CALL_TIMEOUT_SECONDS)
            return float(score), None
        except Exception as exc:  # noqa: BLE001 - se registra tal cual, no se oculta
            last_exc = exc
            print(f"    [WARN] {label}: intento {attempt + 1}/{attempts} fallo: {exc!r}")
            if attempt < len(RETRY_DELAYS_SECONDS):
                await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
    tb = traceback.format_exception_only(type(last_exc), last_exc)
    error_str = f"{label} fallo tras {attempts} intentos: {''.join(tb).strip()}"
    return None, error_str


async def run_all(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas.dataset_schema import SingleTurnSample
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    chat = ChatOpenAI(model=JUDGE_MODEL)
    embed = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    # bypass_temperature=True: gpt-5.5 (como la familia o1/o3/gpt-5 de
    # OpenAI) rechaza cualquier temperature != 1 ("Unsupported value:
    # 'temperature' does not support 0.3 with this model"). Sin este flag,
    # LangchainLLMWrapper pisa el temperature del ChatOpenAI con su default
    # interno (0.3/0.01 segun la metrica) y las 4 metricas fallan 100% de
    # las veces con un 400 de la API de OpenAI. Verificado en un smoke test
    # de 1 caso antes de correr las 40 preguntas completas.
    ragas_llm = LangchainLLMWrapper(chat, bypass_temperature=True)
    ragas_embed = LangchainEmbeddingsWrapper(embed)

    metrics = {
        "faithfulness": Faithfulness(llm=ragas_llm),
        "answer_relevancy": ResponseRelevancy(llm=ragas_llm, embeddings=ragas_embed),
        "context_precision": LLMContextPrecisionWithReference(llm=ragas_llm),
        "context_recall": LLMContextRecall(llm=ragas_llm),
    }

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results: dict[str, dict[str, Any]] = {}
    for c in cases:
        results[c["id"]] = {
            "id": c["id"],
            "eje": c["eje"],
            "excluido_context_metrics": not c["has_reference"],
            "pipeline_error": c["pipeline_error"],
            "faithfulness": None,
            "answer_relevancy": None,
            "context_precision": None,
            "context_recall": None,
            "errors": {m: None for m in METRIC_NAMES},
        }
        if c["pipeline_error"] is not None:
            for m in METRIC_NAMES:
                results[c["id"]]["errors"][m] = f"caso excluido: fallo del pipeline en Fase 2 ({c['pipeline_error'][:200]})"

    async def worker(case: dict[str, Any], metric_name: str) -> None:
        async with semaphore:
            sample_kwargs = dict(
                user_input=case["user_input"],
                response=case["response"],
                retrieved_contexts=case["retrieved_contexts"],
            )
            if metric_name in RETRIEVAL_METRICS:
                sample_kwargs["reference"] = case["reference"]
            sample = SingleTurnSample(**sample_kwargs)

            label = f"{case['id']}/{metric_name}"
            print(f"  -> corriendo {label}...")
            score, error = await score_one(metrics[metric_name], sample, label=label)
            results[case["id"]][metric_name] = score
            results[case["id"]]["errors"][metric_name] = error
            status = "OK" if error is None else "FALLO"
            print(f"  <- {label}: {status} score={score}")

    tasks = []
    for c in cases:
        if c["pipeline_error"] is not None:
            continue
        for m in GENERATION_METRICS:
            tasks.append(worker(c, m))
        if c["has_reference"]:
            for m in RETRIEVAL_METRICS:
                tasks.append(worker(c, m))

    print(f"Total de evaluaciones (caso, metrica) a correr: {len(tasks)}")

    from langchain_community.callbacks import get_openai_callback

    t0 = time.time()
    with get_openai_callback() as cb:
        await asyncio.gather(*tasks)
    elapsed = time.time() - t0

    cost_info = {
        "modelo_juez": JUDGE_MODEL,
        "prompt_tokens_juez_llm": cb.prompt_tokens,
        "prompt_tokens_cached_juez_llm": cb.prompt_tokens_cached,
        "completion_tokens_juez_llm": cb.completion_tokens,
        "reasoning_tokens_juez_llm": cb.reasoning_tokens,
        "total_tokens_juez_llm": cb.total_tokens,
        "llamadas_exitosas_juez_llm": cb.successful_requests,
        "elapsed_seconds": round(elapsed, 1),
        "nota": (
            "El contador de tokens/llamadas es el que reporta el callback "
            "de LangChain (get_openai_callback) sobre TODAS las llamadas "
            "reales hechas al modelo juez (gpt-5.5) durante esta corrida, "
            "incluyendo reintentos. NO incluye las llamadas de embeddings "
            f"({EMBEDDING_MODEL}) que usa Answer Relevancy para comparar "
            "preguntas generadas contra la pregunta original: ese costo es "
            "marginal (modelo de embeddings, no de razonamiento) y "
            "LangChain no lo agrega a este mismo contador."
        ),
    }

    return list(results.values()), cost_info


# ---------------------------------------------------------------------------
# Agregacion: media, mediana, desvio estandar (muestral), global y por eje.
# Los fallos reales y las exclusiones metodologicas se cuentan explicitamente
# y NUNCA se promedian como 0 ni se ocultan.
# ---------------------------------------------------------------------------


def summarize_values(values: list[float]) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"n": 0, "media": None, "mediana": None, "desv_std": None}
    return {
        "n": n,
        "media": statistics.fmean(values),
        "mediana": statistics.median(values),
        # Desvio estandar MUESTRAL (n-1). Con n=1 no esta definido.
        "desv_std": statistics.stdev(values) if n >= 2 else None,
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    ejes = sorted({r["eje"] for r in results})

    def metric_summary(rows: list[dict[str, Any]], metric: str, *, applicable: bool) -> dict[str, Any]:
        if not applicable:
            return {"aplicable": False, "motivo": "excluido: eje fuera_de_cobertura no tiene contexto_referencia"}
        # Para context_precision/context_recall, filtrar los casos ya
        # excluidos (fuera_de_cobertura, sin contexto_referencia) antes de
        # contar intentos/fallos; para faithfulness/answer_relevancy se usan
        # todos los casos de "rows" (no requieren contexto_referencia).
        if metric in RETRIEVAL_METRICS:
            attempted = [r for r in rows if not r["excluido_context_metrics"]]
        else:
            attempted = list(rows)

        n_pipeline_excluded = sum(1 for r in attempted if r["pipeline_error"] is not None)
        n_attempted_ragas = len(attempted) - n_pipeline_excluded
        values = [r[metric] for r in attempted if r[metric] is not None]
        n_ragas_failed = n_attempted_ragas - len(values)
        summary = summarize_values(values)
        summary["aplicable"] = True
        summary["n_casos_totales"] = len(attempted)
        summary["n_excluidos_por_fallo_pipeline_fase2"] = n_pipeline_excluded
        summary["n_intentados_con_ragas"] = n_attempted_ragas
        summary["n_fallos_ragas"] = n_ragas_failed
        if n_ragas_failed > 0:
            summary["ids_con_fallo_ragas"] = [
                r["id"] for r in attempted if r["pipeline_error"] is None and r[metric] is None
            ]
        return summary

    out: dict[str, Any] = {"global": {}, "por_eje": {}}
    for metric in METRIC_NAMES:
        applicable_global = metric in GENERATION_METRICS or any(not r["excluido_context_metrics"] for r in results)
        out["global"][metric] = metric_summary(results, metric, applicable=applicable_global)

    for eje in ejes:
        rows = [r for r in results if r["eje"] == eje]
        eje_summary = {}
        for metric in METRIC_NAMES:
            applicable = metric in GENERATION_METRICS or any(not r["excluido_context_metrics"] for r in rows)
            eje_summary[metric] = metric_summary(rows, metric, applicable=applicable)
        out["por_eje"][eje] = eje_summary

    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    load_env()
    cases = build_cases()
    n_with_ref = sum(1 for c in cases if c["has_reference"])
    n_without_ref = len(cases) - n_with_ref
    print(f"Casos cargados: {len(cases)} (con contexto_referencia: {n_with_ref}, sin (fuera_de_cobertura): {n_without_ref})")

    results, cost_info = asyncio.run(run_all(cases))
    results.sort(key=lambda r: r["id"])

    RESULTADOS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Resultados crudos por caso guardados en {RESULTADOS_PATH}")

    aggregated = aggregate(results)
    resumen = {
        "metodologia": {
            "modelo_juez": JUDGE_MODEL,
            "modelo_embeddings_answer_relevancy": EMBEDDING_MODEL,
            "n_casos_total": len(results),
            "n_casos_con_contexto_referencia": n_with_ref,
            "n_casos_fuera_de_cobertura_excluidos_de_context_metrics": n_without_ref,
            "decision_exclusion": (
                "Context Precision y Context Recall se calculan solo sobre "
                "los 32 casos con contexto_referencia != null (ejes "
                "producto/tramite/establecimiento/codigo). Los 8 casos "
                "fuera_de_cobertura no tienen ground truth de referencia "
                "(la pregunta no tiene respuesta en el corpus por diseno), "
                "asi que esas 2 metricas no estan bien definidas para ellos "
                "y se excluyen explicitamente. Faithfulness y Answer "
                "Relevancy SI se calculan sobre los 40 casos, incluidos los "
                "8 fuera_de_cobertura, porque no requieren contexto de "
                "referencia: evaluan si la respuesta es fiel/relevante "
                "respecto de lo efectivamente recuperado, sea o no ese "
                "contexto pertinente a la pregunta."
            ),
            "desviacion_estandar": "muestral (ddof=1, statistics.stdev). Indefinida (null) cuando n<2.",
            "manejo_de_fallos": (
                "Un fallo real de RAGAS para un caso puntual (timeout, "
                "error de parseo del juez, etc.) se reintenta hasta 2 veces "
                "con backoff; si persiste, se registra explicitamente en "
                "ragas_resultados.json (campo errors.<metrica> con el texto "
                "del error real) y se EXCLUYE del promedio de esa metrica, "
                "pero el conteo de fallos (n_fallos_ragas) y los ids "
                "afectados (ids_con_fallo_ragas) se reportan siempre junto "
                "a cada media/mediana/desvio. Nunca se promedian como si "
                "fueran 0 ni se omiten sin declararlo."
            ),
        },
        **aggregated,
        "costo_fase3": cost_info,
    }
    RESUMEN_PATH.write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Resumen agregado guardado en {RESUMEN_PATH}")


if __name__ == "__main__":
    main()
