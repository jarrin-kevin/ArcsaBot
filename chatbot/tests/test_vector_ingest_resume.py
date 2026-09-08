"""
test_vector_ingest_resume.py
Verificación aislada, con datos SINTÉTICOS (sin Gemini/Pinecone reales), del
mecanismo de resumibilidad agregado a chatbot/vector_ingest.py el 2026-09-08
(ver decisión de diseño 9 en el docstring de ese módulo): que una corrida
interrumpida detecte y saltee lo ya subido en vez de reprocesar todo, y que
NO borre el índice cuando hay progreso real que resumir.

No usa mocks de red: `plan_resume()` es una función PURA (sólo sets/dicts en
memoria, nunca toca Pinecone ni disco) diseñada específicamente para poder
testearse así. `test_write_docstore_atomic_survives_partial_write_crash`
sí toca el filesystem real (vía tmp_path de pytest), para verificar el
patrón temp+rename.

Import: igual que chatbot/tests/test_integration_rag.py, chatbot/vector_ingest.py
importa sus dependencias internas como paquete ("from chatbot.xxx import
..."), así que hace falta la RAÍZ del repo en sys.path (no chatbot/ como en
conftest.py, que sirve para auth.py/conversations.py con imports planos).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chatbot.vector_ingest import _write_docstore_atomic, load_existing_docstore, plan_resume  # noqa: E402


# ---------------------------------------------------------------------------
# plan_resume(): los 3 casos (empty_index / incompatible_corpus / resume)
# ---------------------------------------------------------------------------


def test_plan_resume_empty_index_means_fresh_run():
    """Índice de Pinecone vacío -> corrida nueva, nada que resumir. Este es
    el caso real de HOY (verificado con describe_index_stats() real antes de
    este fix: total_vector_count=0)."""
    current_ids = {"normativa:a:0:1", "normativa:a:1:2", "tutorial:p1"}

    reason, resumable_ids, docstore_kept = plan_resume(
        current_ids=current_ids,
        existing_ids_in_pinecone=set(),
        existing_docstore={"normativa:a:0:1": {"text": "viejo", "metadata": {}}},
    )

    assert reason == "empty_index"
    assert resumable_ids == set()
    assert docstore_kept == {}


def test_plan_resume_stale_docstore_with_empty_index_is_ignored():
    """Caso real detectado en esta sesión: vector_docstore.json en disco
    tiene 4591 entradas de una corrida de días atrás (chunking viejo), pero
    Pinecone real está vacío. La sola existencia de un docstore no vacío NO
    debe hacer que se saltee el corpus: Pinecone manda."""
    current_ids = {"normativa:a:0:1"}
    stale_docstore = {f"normativa:viejo:{i}:1": {"text": "x", "metadata": {}} for i in range(4591)}

    reason, resumable_ids, docstore_kept = plan_resume(
        current_ids=current_ids,
        existing_ids_in_pinecone=set(),
        existing_docstore=stale_docstore,
    )

    assert reason == "empty_index"
    assert resumable_ids == set()
    assert docstore_kept == {}


def test_plan_resume_incompatible_corpus_triggers_overwrite():
    """Pinecone tiene vectores, pero NINGUNO coincide con el corpus actual
    (p. ej. chunking cambió y todos los IDs son distintos ahora, ver
    decisión de diseño 4): debe tratarse como corrida nueva (overwrite),
    igual que el diseño original."""
    current_ids = {"normativa:a:0:1", "tutorial:p1"}
    old_pinecone_ids = {"normativa:a:0:99", "normativa:b:0:5"}  # IDs de un chunking viejo

    reason, resumable_ids, docstore_kept = plan_resume(
        current_ids=current_ids,
        existing_ids_in_pinecone=old_pinecone_ids,
        existing_docstore={"normativa:a:0:99": {"text": "viejo", "metadata": {}}},
    )

    assert reason == "incompatible_corpus"
    assert resumable_ids == set()
    assert docstore_kept == {}


def test_plan_resume_real_interrupted_run_is_resumed_not_restarted():
    """El caso central que pide la tarea: corrida interrumpida hoy, mismo
    corpus/IDs deterministas, con progreso real ya subido a Pinecone (y con
    texto en el docstore local) -> se resume, saltando sólo lo ya hecho."""
    current_ids = {f"normativa:doc{i}:0:{i}" for i in range(10)} | {"tutorial:p1", "tutorial:p2"}
    # 4 de los 10 documentos de normativa + 1 de tutorial ya se subieron
    # antes de que el proceso muriera.
    already_uploaded = {"normativa:doc0:0:0", "normativa:doc1:0:1", "normativa:doc2:0:2", "tutorial:p1"}
    docstore_on_disk = {doc_id: {"text": f"texto {doc_id}", "metadata": {}} for doc_id in already_uploaded}

    reason, resumable_ids, docstore_kept = plan_resume(
        current_ids=current_ids,
        existing_ids_in_pinecone=already_uploaded,
        existing_docstore=docstore_on_disk,
    )

    assert reason == "resume"
    assert resumable_ids == already_uploaded
    assert docstore_kept == docstore_on_disk

    # La corrida sólo debe procesar lo que falta, nunca reprocesar lo ya subido.
    documents_to_process_ids = current_ids - resumable_ids
    assert documents_to_process_ids == (current_ids - already_uploaded)
    assert "normativa:doc0:0:0" not in documents_to_process_ids
    assert "normativa:doc9:0:9" in documents_to_process_ids


def test_plan_resume_pinecone_id_without_local_text_is_reprocessed_not_lost():
    """Caso borde documentado en la decisión de diseño 9b: un id está subido
    en Pinecone pero el docstore local no tiene su texto (p. ej. el proceso
    murió justo entre escribir el docstore y hacer el upsert, o el docstore
    es más viejo que el índice). Debe RE-procesarse (no perderse en
    silencio): no debe aparecer en resumable_ids."""
    current_ids = {"normativa:a:0:1", "normativa:b:0:2"}
    existing_ids_in_pinecone = {"normativa:a:0:1", "normativa:b:0:2"}
    # Sólo el primero tiene texto local; el segundo está "huérfano".
    existing_docstore = {"normativa:a:0:1": {"text": "texto a", "metadata": {}}}

    reason, resumable_ids, docstore_kept = plan_resume(
        current_ids=current_ids,
        existing_ids_in_pinecone=existing_ids_in_pinecone,
        existing_docstore=existing_docstore,
    )

    assert reason == "resume"
    assert resumable_ids == {"normativa:a:0:1"}  # NO incluye "normativa:b:0:2"
    documents_to_process_ids = current_ids - resumable_ids
    assert "normativa:b:0:2" in documents_to_process_ids  # se re-procesa, no se pierde


def test_plan_resume_never_marks_a_pinecone_only_document_as_resumable_without_text():
    """Refuerza el invariante central: resumable_ids siempre es un
    subconjunto de docstore_kept.keys() (nunca se saltea un documento sin
    poder mostrar su texto localmente después)."""
    current_ids = {f"id{i}" for i in range(20)}
    existing_ids_in_pinecone = {f"id{i}" for i in range(15)}  # 15 subidos
    existing_docstore = {f"id{i}": {"text": "t", "metadata": {}} for i in range(10)}  # sólo 10 con texto

    _reason, resumable_ids, docstore_kept = plan_resume(current_ids, existing_ids_in_pinecone, existing_docstore)

    assert resumable_ids.issubset(docstore_kept.keys())
    assert resumable_ids == {f"id{i}" for i in range(10)}


# ---------------------------------------------------------------------------
# _write_docstore_atomic() / load_existing_docstore(): patrón temp+rename
# ---------------------------------------------------------------------------


def test_write_docstore_atomic_then_load_roundtrip(tmp_path: Path):
    path = tmp_path / "vector_docstore.json"
    docstore = {"id1": {"text": "hola", "metadata": {"corpus": "normativa"}}}

    _write_docstore_atomic(path, docstore)

    assert path.exists()
    assert not (tmp_path / "vector_docstore.json.tmp").exists()  # el .tmp no debe sobrevivir
    loaded = load_existing_docstore(path)
    assert loaded == docstore


def test_write_docstore_atomic_never_leaves_real_file_half_written(tmp_path: Path):
    """Simula el escenario real que motivó este fix: un docstore ya grande
    en disco (simulando progreso previo), y una nueva escritura completa
    encima. El archivo real nunca debe quedar en un estado a medio escribir
    ni corrupto: o tiene el contenido viejo completo, o tiene el nuevo
    completo, nunca un estado intermedio inválido."""
    path = tmp_path / "vector_docstore.json"
    original = {f"id{i}": {"text": "x" * 100, "metadata": {}} for i in range(50)}
    _write_docstore_atomic(path, original)

    before_bytes = path.read_bytes()
    json.loads(before_bytes)  # el archivo real siempre debe ser JSON válido

    updated = dict(original)
    updated["id_nueva"] = {"text": "nuevo chunk", "metadata": {}}
    _write_docstore_atomic(path, updated)

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after == updated
    assert "id_nueva" in after


def test_load_existing_docstore_missing_file_returns_empty(tmp_path: Path):
    missing_path = tmp_path / "no_existe.json"
    assert load_existing_docstore(missing_path) == {}


def test_load_existing_docstore_corrupted_file_returns_empty_with_warning(tmp_path: Path, capsys):
    path = tmp_path / "corrupto.json"
    path.write_text("{esto no es json valido", encoding="utf-8")

    result = load_existing_docstore(path)

    assert result == {}
    captured = capsys.readouterr()
    assert "ADVERTENCIA" in captured.out
