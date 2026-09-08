"""
Carga real de datos hacia Pinecone.

Este es el paso final que deja el pipeline de RAG realmente consultable:
toma los chunks ya preparados de los dos corpus (Normativa + Tutorial),
genera embeddings reales con la Gemini API y los sube al índice de Pinecone
(`chatbot.vector_store.PINECONE_INDEX_NAME`) mediante `index.upsert()`.

Reutiliza (sin modificar) chatbot/vector_store.py, chatbot/ingestion.py y
chatbot/tutorial_ingestion.py. Pensado para poder volver a correrse más
adelante (p. ej. cuando se agreguen chunks nuevos): si el índice de Pinecone
está vacío, o si tiene contenido de un corpus/chunking incompatible con la
corrida actual, borra TODO el contenido existente del índice
(`index.delete(delete_all=True)`) y sube el corpus completo de cero, en vez
de hacer un upsert incremental "ciego" sobre IDs deterministas (ver decisión
de diseño 4 más abajo — el motivo por el que se prefiere overwrite total a
upsert incremental en ese caso). Pero si detecta progreso REAL de una
corrida anterior interrumpida del mismo corpus (ver decisión de diseño 9),
NO borra nada: retoma sólo con los documentos faltantes, subiendo a Pinecone
y persistiendo el docstore local de forma incremental (lote por lote, no al
final) para que una interrupción nunca vuelva a costar la corrida completa.

Modo de uso (desde la raíz del repositorio, con las dependencias de
chatbot/requirements.txt instaladas):

    python -m chatbot.vector_ingest

DECISIONES DE DISEÑO IMPORTANTES
---------------------------------

1. Modelo de embeddings: este script usa `configure_embeddings()` de
   vector_store.py como única fuente de verdad para el modelo de embeddings.
   Apunta a `models/gemini-embedding-001` con `output_dimensionality=768`
   (el antiguo `models/text-embedding-004` ya no existe para esta cuenta de
   la Gemini API: devolvía 404 NOT_FOUND, verificado llamando a
   `client.models.list()`, que sólo expone `gemini-embedding-001`,
   `gemini-embedding-2` y `gemini-embedding-2-preview` con soporte de
   embedContent). El índice de Pinecone se crea con dimension=768 para
   calzar con eso (ver `get_vector_store()` en vector_store.py). Este script
   ya NO instancia su propio `GoogleGenAIEmbedding` en paralelo; sólo ajusta
   `embed_batch_size` sobre la instancia devuelta por `configure_embeddings()`
   para mantener el tamaño de lote EMBED_BATCH_SIZE=10 (bajado de 25 el
   2026-09-08, ver decisión de diseño 8 más abajo) usado en el paso 3.

2. Normalización: al pedir `output_dimensionality=768` (truncado tipo
   Matryoshka), gemini-embedding-001 NO devuelve vectores unitarios (norma
   ~0.58 medida empíricamente contra la API real, no 1.0). El índice de
   Pinecone usa `metric="cosine"`, que ya normaliza internamente para el
   cálculo de similitud, pero este script sigue normalizando cada embedding
   a norma 1 con `normalize_embedding()` de vector_store.py (misma función
   que usa main.py para las consultas) para mantener consistencia end-to-end
   con el resto del pipeline.

3. Almacenamiento de texto: Pinecone sólo guarda id + embedding + metadata
   pequeña, nunca el texto completo del chunk (los valores de metadata tienen
   límite de tamaño, ~40KB por vector, y de todas formas no tiene sentido
   duplicar ahí un texto ya grande). Para poder mostrar resultados legibles en
   la consulta de prueba (paso 5) y para que el chatbot pueda resolver los
   IDs devueltos por el índice a texto real más adelante, este script guarda
   un docstore local (chatbot/data/vector_docstore.json: id -> {text,
   metadata}) además de subir los embeddings a Pinecone. La metadata que sí
   se sube a Pinecone se limita a campos cortos (corpus, articulo_numero,
   vigente) para poder filtrar consultas en el futuro sin acercarse a ese
   límite.

4. IDs deterministas + overwrite total (no upsert incremental): los IDs son
   estables ("normativa:<file_id>:<index_in_file>:<articulo_numero>" y
   "tutorial:<page_id>"), pero build_normativa_documents()/
   build_tutorial_documents() no soportan ingesta parcial — cada corrida
   reprocesa el corpus completo desde cero. Si un reprocesamiento cambia la
   cantidad de chunks de un archivo, el "index_in_file" de muchos documentos
   cambia, generando IDs "nuevos" que en la práctica son el mismo documento.
   Con un upsert incremental (sin borrar antes), esos IDs viejos nunca se
   reemplazan: se acumulan datapoints huérfanos indefinidamente. Esto ya pasó
   una vez con Vertex AI Vector Search (9016 vectores reales en el índice vs
   4595 esperados, dos corridas completas acumuladas sin pisarse) y se
   corrigió forzando un overwrite total. Con Pinecone, el equivalente directo
   es borrar todo el índice (`index.delete(delete_all=True)`) antes de subir
   el corpus completo de la corrida actual — más simple que el mecanismo de
   Vertex y sin el riesgo de duplicación por diseño.

5. Por qué Pinecone y no Vertex AI Vector Search: ver
   docs/adr/0002-vertex-ai-vector-search.md para la decisión original, y la
   memoria del proyecto para el motivo del cambio (se deshabilitó la
   facturación del proyecto GCP por costo, dejando Vertex AI Vector Search
   inoperativo con 403 BILLING_DISABLED). Pinecone es una única API directa:
   sin bucket de staging, sin cuenta de servicio de GCP, sin batch job
   asíncrono — el upsert es una llamada de API que queda consultable casi de
   inmediato, no hace falta sondear sincronización de una réplica desplegada.

6. Manejo de 429/rate-limit en embed_documents() (fix del 2026-09-08): la
   primera corrida real murió a mitad de camino (1725/4649 documentos, 37%)
   sin cuota diaria de Gemini para embed_content, por dos causas confirmadas
   con el log real de esa corrida:
     a) Amplificación de reintentos: cuando un lote de 25 fallaba por
        CUALQUIER motivo (incluido un simple 429), el código caía al
        fallback documento por documento (hasta 26 requests en vez de 1).
        De los 55 errores 429 del log, 17 citaban explícitamente la cuota
        DIARIA (quotaId "EmbedContentRequestsPerDayPerUserPerProjectPerModel
        -FreeTier", límite 1000/día) y 2 la cuota por minuto (límite
        100/min) — fragmentar un lote que sólo chocó con rate-limit no
        arregla nada y sólo quema cuota diaria más rápido.
     b) Pacing insuficiente: BATCH_PACING_SECONDS=0.3 permitía hasta
        ~200 requests/minuto, por encima del límite real de 100/min.
   El fix: _is_rate_limit_error()/_quota_violation_period() clasifican la
   excepción real de la librería instalada (google-genai 2.20.0:
   google.genai.errors.ClientError con .code==429 para cualquier 4xx; el
   quotaId real del 429 capturado en el log distingue "PerDay" de
   "PerMinute" dentro de error.details). _embed_with_retry() reintenta el
   MISMO lote completo (nunca fragmentado) ante un 429 de cuota por minuto,
   con backoff (usando el retryDelay real que sugiere Google cuando está
   presente), hasta RATE_LIMIT_BATCH_MAX_RETRIES veces; ante cuota DIARIA
   confirmada, o reintentos de minuto agotados, aborta la corrida entera con
   EmbeddingQuotaAbortError en vez de seguir insistiendo en vano. El
   fallback documento por documento se mantiene, pero sólo se alcanza para
   errores que NO son 429 (errores reales de contenido de un documento
   puntual). El pacing fijo se reemplaza por _RateLimiter, una ventana
   deslizante real que nunca deja pasar más de EMBED_RATE_LIMIT_MAX_REQUESTS
   requests en EMBED_RATE_LIMIT_WINDOW_SECONDS segundos.

7. Chunks de Normativa sin Artículo + red de seguridad de tamaño genérica
   (fix del 2026-09-08, mismo día que el punto 6): antes de este fix, todo
   documento de Normativa sin encabezado de Artículo se guardaba como UN
   chunk con el texto COMPLETO (hasta 1 339 954 caracteres en el caso real
   más extremo), muy por encima del límite real de 2048 tokens de
   gemini-embedding-001 — ver la investigación completa y la calibración
   empírica contra la API real de tokens en chatbot/normativa_extraction.py
   (sección "LIMITACIÓN DE DISEÑO" del docstring del módulo, y
   _fallback_size_based_chunks/_resplit_oversized_chunk). Esos documentos
   NUNCA llegaron a embeberse antes de este fix. Al preparar la corrida
   real completa se encontró que el corpus de Tutorial tiene el mismo
   problema por otra causa (páginas HTML largas sin trocear por tamaño,
   hasta 122 086 caracteres): ver enforce_max_safe_chunk_size() más abajo,
   aplicada a AMBOS corpus justo antes de embed_documents() como red de
   seguridad final, reutilizando split_text_into_windows() de
   normativa_extraction.py en vez de duplicar esa lógica.

8. EMBED_BATCH_SIZE bajado de 25 a 10 + límite de tokens/minuto agregado al
   rate limiter (fix del 2026-09-08): el mismo día en que se vinculó
   facturación real a la cuenta de Gemini, un lote real de 25 documentos de
   normativa (los primeros 25 devueltos por build_normativa_documents(),
   30 280 tokens medidos con `google.genai.Client().models.count_tokens`,
   mismo método ya usado en normativa_extraction.py) falló con
   429 RESOURCE_EXHAUSTED genérico (sin "quotaId" ni "retryDelay" en
   error.details, a diferencia de los 429 de la corrida anterior descrita
   en la decisión 6, que sí traían quotaId) pese a que la cuota de
   REQUESTS/minuto (EMBED_RATE_LIMIT_MAX_REQUESTS=90) nunca se acercó a
   violarse. Esto es consistente con reportes públicos de cuentas recién
   vinculadas a facturación cuyo límite de TOKENS/minuto para embed_content
   tarda en subir de nivel.

   Diagnóstico incremental el mismo día, contra la API real, un intento por
   tamaño (sin reintentos): un lote real de 5 documentos (6560 tokens) y
   uno de 10 documentos (13 304 tokens) tuvieron éxito; un lote real de 15
   documentos (20 214 tokens), disparado unos segundos después de los dos
   anteriores, falló con el mismo 429 genérico. No se siguió subiendo a 20
   ni se bajó a probar de a 1 en loop: 10 es el tamaño real confirmado que
   funcionó, no un máximo teórico rebuscado a propósito.

   Con lotes más chicos hacen falta muchos más (≈9500/10 en vez de
   ≈9500/25), y el límite de REQUESTS/minuto ya no alcanza para mantenerse
   dentro del límite de TOKENS/minuto recién confirmado (90 lotes de 10 en
   una ventana de 60s serían ~90×1200 ≈ 108 000 tokens, muy por encima de lo
   que ya falló hoy). Por eso _RateLimiter ahora también rastrea tokens
   estimados (no sólo cantidad de requests) en la misma ventana deslizante,
   con EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS fijado en 18 000 — por debajo de
   los 20 214 tokens del lote que falló y con margen bajo los ~19 864
   tokens acumulados de los dos lotes exitosos disparados casi juntos ese
   mismo día — usando CHARS_PER_TOKEN_CONSERVATIVE (calibrado sobre la
   misma medición real de 101 552 caracteres / 30 280 tokens de los primeros
   25 documentos, redondeado hacia abajo para sobreestimar tokens en vez de
   subestimarlos). El límite de requests/minuto (EMBED_RATE_LIMIT_MAX_REQUESTS)
   se mantiene sin cambios: con el nuevo límite de tokens, en la práctica es
   el límite de tokens el que termina espaciando las llamadas, no el de
   requests.

9. Subida y docstore incrementales + resumibilidad real (fix del
   2026-09-08, mismo día que los puntos 6-8): el diseño original de este
   script generaba los embeddings de los ~9506 documentos del corpus
   COMPLETO en memoria, y recién al final (a) escribía
   chatbot/data/vector_docstore.json con un único `json.dump()`, y (b)
   borraba y volvía a subir el índice de Pinecone completo. Con una corrida
   real estimada en ~16 horas (EMBED_BATCH_SIZE=10 +
   EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS=18000/60s, ver puntos 6-8), esto es un
   riesgo real de pérdida total de progreso, no teórico: un proceso
   background de esta misma corrida murió sin explicación clara tras varias
   horas (con sólo ~30-40/9506 documentos embebidos en memoria, nunca
   persistidos) el mismo día en que se escribe este comentario, obligando a
   reiniciar de cero.

   El fix tiene tres partes:

   a) Subida incremental a Pinecone: `process_documents()` (antes
      `embed_documents()` + `upload_embeddings()` por separado) sube cada
      lote de EMBED_BATCH_SIZE=10 documentos a Pinecone con `index.upsert()`
      INMEDIATAMENTE después de generar su embedding, en vez de acumular
      los ~9506 embeddings en memoria y subir todo al final. Esto también
      vuelve innecesario un tamaño de lote de upsert separado
      (UPSERT_BATCH_SIZE): 10 vectores de 768 floats (~30KB con metadata)
      están muy por debajo de cualquier límite de payload de Pinecone.

   b) Docstore incremental y a prueba de cortes: `_write_docstore_atomic()`
      escribe el docstore COMPLETO (no sólo el lote nuevo: el diccionario en
      memoria ya incluye todo lo acumulado) a un archivo temporal
      (`vector_docstore.json.tmp`) y lo reemplaza sobre el archivo real con
      `os.replace()` — atómico en Windows y POSIX cuando origen y destino
      están en el mismo volumen (lo están: mismo directorio). Si el proceso
      se corta a mitad de un `json.dump()`, sólo el `.tmp` queda a medio
      escribir; `vector_docstore.json` real nunca pasa por un estado
      corrupto a medio escribir, porque `os.replace()` sólo ocurre después
      de que el `.tmp` ya se cerró (con `flush()` + `fsync()` antes del
      `close()` implícito del `with`) completo y válido.

      Orden elegido DENTRO de cada lote (importa para qué falla peor si el
      proceso muere a mitad de un lote): se escribe el docstore primero y
      recién después se hace el upsert a Pinecone. Si el proceso muere entre
      medio, el peor caso es un lote re-embebido y re-subido de más al
      reanudar (upsert es idempotente sobre el mismo id, así que no genera
      duplicados) — nunca el caso inverso (un vector ya en Pinecone sin
      texto local, que dejaría ese chunk permanentemente sin texto legible
      para retrieve_chunks()/run_test_query()).

   c) Resumibilidad real al arrancar `main()`: ANTES de decidir si hace
      falta `clear_index()`, se listan los IDs REALMENTE presentes en el
      índice de Pinecone (`list_uploaded_ids()`, vía `index.list()`
      paginado — sólo IDs, sin values/metadata) y se cruzan con los IDs del
      corpus que esta corrida está por procesar. Pinecone (no el docstore
      local) es la fuente de verdad de "qué ya se subió": el docstore local
      puede corresponder a una corrida vieja con chunking/IDs distintos —
      comprobado empíricamente el mismo día: el archivo real en disco tenía
      4591 entradas de una corrida de días atrás (anterior a los fixes de
      chunking de los puntos 6-7), mientras el índice real de Pinecone
      estaba en 0 vectores. Confiar en la sola existencia del docstore
      hubiera hecho saltear por error el corpus completo.

      `plan_resume()` (función pura, sin tocar Pinecone/disco, para poder
      testearla con datos sintéticos sin mocks) decide entre tres casos:
        - Índice vacío -> corrida nueva: `clear_index()` (no-op si ya está
          vacío) y se procesa el corpus completo.
        - Índice con contenido pero SIN ningún id en común con el corpus
          actual -> los datos del índice son de un corpus/chunking
          incompatible (ver decisión 4): `clear_index()` igual, overwrite
          total, se procesa el corpus completo.
        - Índice con ids en común con el corpus actual -> resume real: NO
          se llama a `clear_index()` (borraría progreso real ya subido); se
          procesa sólo el subconjunto de documentos cuyo id NO está ya
          subido en Pinecone Y con texto ya presente en el docstore local
          cargado (un id subido en Pinecone pero sin texto local, caso
          borde que no debería darse con el orden descrito en (b), se
          re-procesa en vez de darse por perdido: upsert es idempotente).

10. EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS subido de 18 000 a 26 000 (2026-09-08,
    más tarde el mismo día que los puntos 6-9): el 18 000 de la decisión 8
    era una calibración EMPÍRICA (prueba y error) hecha sin conocer el
    límite oficial real. Ese mismo día se confirmó contra el panel OFICIAL
    de límites de Google para esta cuenta/proyecto
    (https://aistudio.google.com/rate-limit, con captura de pantalla real)
    que "Gemini Embedding 1" en Nivel gratuito tiene TPM=30 000, RPM=100,
    RPD=1000 — la facturación de este proyecto seguía sin vincularse (panel
    en "Nivel gratuito"), así que se sigue diseñando contra estos límites
    exactos. Se subió el tope a 26 000 (13.3% de margen bajo el oficial, ver
    el comentario junto a la constante para el detalle completo) en vez de
    dejarlo en 18 000 (dejaba rendimiento real sin usar) o pegarlo a 30 000
    (sin margen). Una simulación offline del `_RateLimiter` real contra los
    951 lotes reales de esta corrida confirmó dos cosas: (a) el tiempo total
    restante baja de ~9.7h a ~8.0h con el nuevo tope, una mejora real pero
    NO proporcional al aumento (ver el comentario de la constante — depende
    de qué fracción del corpus ya viene en lotes cercanos al máximo posible
    por MAX_SAFE_CHUNK_CHARS), y (b) EMBED_RATE_LIMIT_MAX_REQUESTS (90/60s)
    nunca termina siendo el límite que manda en la práctica con ningún tope
    de tokens probado entre 18 000 y 28 000: el límite de TOKENS sigue
    siendo el que impone el ritmo real. La estimación de "~16 horas" de la
    decisión 9 también resultó ser una sobreestimación ingenua (60s fijos
    por lote × 951 lotes): la misma simulación, calibrada contra el tiempo
    real observado de la corrida en curso (2100s reales para los primeros
    36 lotes vs 2100s simulados, con tope 18 000 — coincidencia exacta), da
    ~10.3h reales para el corpus completo con el tope viejo, no ~16h.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.genai.errors import ClientError

from chatbot.ingestion import to_documents as normativa_to_documents
from chatbot.link_validation import REPORT_PATH as LINK_VALIDATION_REPORT_PATH
from chatbot.link_validation import load_broken_urls, strip_broken_links_from_text
from chatbot.normativa_extraction import MAX_SAFE_CHUNK_CHARS, split_text_into_windows
from chatbot.tutorial_ingestion import run_pipeline as run_tutorial_pipeline
from chatbot.tutorial_ingestion import to_documents as tutorial_to_documents
from chatbot.vector_store import EMBED_DIMENSIONS, configure_embeddings, get_vector_store, normalize_embedding

load_dotenv()

# --------------------------------------------------------------------------
# Rutas y constantes
# --------------------------------------------------------------------------

CHATBOT_DIR = Path(__file__).resolve().parent
NORMATIVA_DIR = CHATBOT_DIR / "data" / "normativa"
DOCSTORE_PATH = CHATBOT_DIR / "data" / "vector_docstore.json"

# Tamaño de lote para las llamadas a la Gemini API. Bajado de 25 a 10 el
# 2026-09-08 (ver decisión de diseño 8 en el docstring del módulo): tras
# vincular facturación real, un lote real de 25 documentos (~30 280 tokens
# medidos con count_tokens) empezó a fallar con 429 RESOURCE_EXHAUSTED
# genérico por un límite de TOKENS/minuto todavía bajo (no por cantidad de
# requests). Diagnóstico incremental contra la API real el mismo día: un
# lote real de 10 documentos (13 304 tokens) funcionó, uno de 15 (20 214
# tokens) falló. 10 es el tamaño real confirmado ese día, no un máximo
# teórico. Cada llamada a embed_model.get_text_embedding_batch(texts) con
# len(texts) <= EMBED_BATCH_SIZE dispara EXACTAMENTE una request HTTP real a
# embed_content (confirmado leyendo llama_index/core/base/embeddings/base.py::
# get_text_embedding_batch(): sólo "flushea" el buffer cuando llega a
# embed_batch_size). GoogleGenAIEmbedding ya envuelve esa request con su
# propio reintento por tenacity (retries=3, retry_min_seconds=1,
# retry_max_seconds=60, sólo sobre códigos [429, 502, 503, 504]) antes de
# devolver el control acá: para cuando process_documents() ve la excepción, la
# librería ya agotó esos 3 intentos cortos (~3s totales) sin éxito.
#
# SUBIDO de 10 a 25 el 2026-09-08 (más tarde el mismo día, tras confirmar
# Nivel 1 real con facturación vinculada — ver el comentario junto a
# EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS más abajo para la fuente): 25 documentos
# ya se había medido ese mismo día en 30 280 tokens reales (con
# count_tokens), y esa llamada en su momento NO falló por ningún límite de
# tamaño de request de la API de Gemini (batchEmbedContents no tiene un
# límite documentado de cantidad de textos por llamada relevante acá) —
# falló únicamente por el TPM=30 000 del free tier de ese momento, que ya no
# aplica. Con el nuevo tope de tokens/minuto, un lote de 25 (~30-38k tokens
# estimados en el peor caso, ver MAX_SAFE_CHUNK_CHARS) consume sólo ~4-5% del
# presupuesto por minuto, dejando margen enorme. Volver a 25 (en vez de saltar
# a un valor mayor como 50) reduce la cantidad de requests reales en ~2.3x
# frente a 10 (menos overhead de red y menos rescrituras completas del
# docstore, ver decisión 9b) sin agrandar demasiado el "blast radius" de un
# lote que falle por un error real de contenido (no-429), que cae al
# fallback documento por documento. El THROUGHPUT real del corpus lo sigue
# imponiendo el tope de TOKENS/minuto, no el tamaño de lote en sí (ver abajo):
# agrandar el lote reduce la cantidad de requests, no acelera el ritmo de
# tokens/minuto más allá de lo que ya permite EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS.
# Payload de upsert a Pinecone verificado con un vector real fetcheado del
# índice: ~11.4KB por vector (768 floats + metadata como JSON), muy por
# debajo de cualquier límite de payload de Pinecone incluso con 25-50
# vectores por lote (~285-570KB).
EMBED_BATCH_SIZE = 25

# Limitador de tasa real (ver decisión de diseño 6 más arriba): nunca se
# dispara una request si ya hubo EMBED_RATE_LIMIT_MAX_REQUESTS en los
# últimos EMBED_RATE_LIMIT_WINDOW_SECONDS segundos. El máximo se fijó
# originalmente en 90 (no 100, el límite real del free tier de Gemini para
# embed_content) como margen de seguridad frente a jitter de reloj/latencia
# de red.
#
# SUBIDO de 90 a 2500 el 2026-09-08 (más tarde el mismo día, Nivel 1
# confirmado — ver EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS más abajo para la
# fuente/evidencia): el panel oficial confirma RPM=3000 en Nivel 1 (antes
# 100 en el free tier, 30x más). Se recalculó si REQUESTS o TOKENS es el
# límite que realmente manda ahora: con EMBED_BATCH_SIZE=25 y el tope de
# tokens nuevo, los lotes "pesados" del corpus (normativa, ~1200-1500
# tokens/documento) siguen estando acotados por TOKENS, no por requests
# (∼22-28 lotes/min posibles bajo el tope de tokens, muy por debajo de
# cualquier tope de requests razonable). PERO el camino de fallback
# documento-por-documento (_embed_with_retry con tokens de UN solo documento,
# ver process_documents()) puede disparar muchos más requests/minuto que
# eso si los documentos son chicos (p. ej. chunks cortos de Tutorial, ~100-300
# tokens): con el tope de tokens nuevo, ese camino podría acercarse o superar
# el viejo tope de 90 requests/min sin violar ningún límite real de tokens,
# volviendo el límite de requests (90) artificialmente restrictivo. Se sube a
# 2500 (16.7% de margen bajo los 3000 oficiales, mismo criterio de margen que
# el tope de tokens de abajo) para que ese camino no quede innecesariamente
# limitado ahora que la cuota real lo permite.
EMBED_RATE_LIMIT_MAX_REQUESTS = 2500
EMBED_RATE_LIMIT_WINDOW_SECONDS = 60.0

# Límite de TOKENS/minuto (nuevo el 2026-09-08, ver decisión de diseño 8):
# EMBED_RATE_LIMIT_MAX_REQUESTS por sí solo ya no alcanza para mantenerse
# bajo el límite real de tokens/minuto de una cuenta recién facturada (90
# lotes de 10 documentos en 60s serían ~108 000 tokens, muy por encima de lo
# que ya falló hoy). Se fijó inicialmente en 18 000 por CALIBRACIÓN EMPÍRICA
# (prueba y error, sin conocer el límite oficial real): por debajo de los
# 20 214 tokens del lote real que falló ese mismo día, con margen bajo los
# ~19 864 tokens acumulados de los dos lotes reales que sí funcionaron (5 y
# 10 documentos, disparados casi juntos).
#
# ACTUALIZADO el 2026-09-08 (más tarde el mismo día) a 26 000, fuente: panel
# OFICIAL de límites de Google para este proyecto/cuenta
# (https://aistudio.google.com/rate-limit), confirmado con captura de
# pantalla real — no una suposición ni una recalibración empírica más. Ese
# panel muestra, para "Gemini Embedding 1" en Nivel gratuito: TPM (tokens
# por minuto) = 30 000, RPM = 100, RPD = 1000. La facturación de este
# proyecto NO logró vincularse todavía (el panel sigue mostrando "Nivel
# gratuito"), así que se sigue diseñando contra estos límites exactos del
# free tier, no contra los límites (mayores) de una cuenta facturada.
#
# ACTUALIZADO OTRA VEZ el 2026-09-08 (más tarde ese mismo día) a 850 000,
# fuente: panel OFICIAL de límites de Google (https://aistudio.google.com/
# rate-limit) confirmado por el usuario tras vincular facturación real de
# verdad: el proyecto pasó de "Nivel gratuito" a "Nivel 1", con TPM=1 000 000,
# RPM=3000, RPD=ilimitado para "Gemini Embedding 1" (33x más TPM, 30x más RPM
# que el free tier). 850 000 (15% de margen bajo el 1 000 000 oficial) se
# eligió en vez de pegarse al límite oficial por el margen adicional ya
# documentado más abajo (CHARS_PER_TOKEN_CONSERVATIVE sobreestima tokens a
# propósito) y para absorber jitter de reloj/latencia de red en la ventana
# deslizante del rate limiter.
#
# NOTA IMPORTANTE sobre una segunda actualización propuesta el mismo día,
# RECHAZADA tras verificación: horas después de confirmar "Nivel 1" se
# recibió un reporte (vía un canal de coordinación entre agentes, sin
# posibilidad de verificación directa de mi parte sobre el panel real) de
# que la cuenta ya estaría en "Nivel 2" con TPM=5 000 000, apenas minutos
# después de vincular facturación por primera vez. Se verificó contra la
# documentación oficial de Google (https://ai.google.dev/gemini-api/docs/
# rate-limits) antes de aplicar ese cambio, y se decidió NO aplicarlo, por
# dos motivos concretos:
#   1) Los requisitos documentados para Nivel 2 son "$100 de gasto + 3 días
#      desde el primer pago exitoso" (Nivel 3 pide $1000 + 30 días). Vincular
#      facturación por primera vez no genera de inmediato un pago exitoso de
#      $100 ni 3 días transcurridos; alcanzar Nivel 2 en minutos contradice
#      la política documentada, sin importar qué muestre una captura de
#      pantalla relatada de segunda mano.
#   2) El número "5 000 000" SÍ aparece en la documentación oficial de
#      Google, pero como el límite de "Batch enqueued tokens" de Nivel 2 de
#      la Batch API — una cuota completamente distinta al TPM síncrono de
#      embed_content que usa este script (get_text_embedding_batch nunca usa
#      la Batch API). Es un número real pero mal aplicado a este contexto,
#      no una confirmación válida de un TPM síncrono más alto.
# Por estos dos motivos verificables, este script se queda calibrado contra
# Nivel 1 (850 000) hasta que haya evidencia verificable de otra cosa (p. ej.
# un 429 real que indique que incluso 850 000 es demasiado, o pasados los 3
# días/gasto mínimo documentado para Nivel 2 de verdad).
#
# Simulación/cálculo real contra el nuevo tope (2026-09-08): con
# EMBED_BATCH_SIZE=25 y ~1200-1500 tokens/documento promedio (normativa, la
# mayoría del corpus), un lote pesado ronda ~30-38k tokens estimados; a
# 850 000 tokens/min eso permite ~22-28 lotes/min (550-700 documentos/min)
# incluso para los lotes más pesados del corpus — un salto real de ~30x
# frente al ritmo observado bajo el tope viejo de 26 000 (~2 lotes de 10/min
# ≈ 22 documentos/min). Con esto, EMBED_RATE_LIMIT_MAX_REQUESTS (2500/60s)
# no llega a ser el límite que manda para los lotes normales de tamaño 25,
# pero sí protege el camino de fallback documento-por-documento con
# documentos chicos (ver comentario junto a esa constante).
#
# Este valor reemplaza al 26 000 anterior porque ese número estaba calibrado
# contra el free tier (TPM oficial=30 000), ya no vigente para este
# proyecto/cuenta tras vincular facturación real.
EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS = 850000
CHARS_PER_TOKEN_CONSERVATIVE = 3.0


def _estimate_tokens(text: str) -> int:
    """Estimación conservadora (sobreestimada a propósito) de tokens a
    partir de caracteres, ver EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS arriba para
    la calibración real usada."""
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN_CONSERVATIVE))

# Reintento de LOTE COMPLETO ante un 429 de rate-limit por minuto (ver
# decisión de diseño 6): cuántas veces se reintenta el mismo lote/documento
# antes de darse por vencido, y el backoff a usar cuando Google no sugiere
# un retryDelay explícito en el propio error.
RATE_LIMIT_BATCH_MAX_RETRIES = 5
RATE_LIMIT_BACKOFF_INITIAL_SECONDS = 5.0
RATE_LIMIT_BACKOFF_MAX_SECONDS = 90.0

# NOTA (2026-09-08, ver decisión de diseño 9a): ya no hace falta un tamaño de
# lote de upsert separado de EMBED_BATCH_SIZE. Antes se acumulaban TODOS los
# embeddings del corpus antes de subir, así que hacía falta trocear ese upload
# gigante en lotes de 100 para no pasarse del límite de payload de Pinecone
# (~2MB por request). Ahora cada lote de EMBED_BATCH_SIZE=10 documentos (~30KB
# con metadata, muy por debajo de ese límite) se sube a Pinecone apenas se
# genera su embedding (process_documents()), así que el lote de embedding YA
# es el lote de upsert.

# Metadata subida a Pinecone junto con cada vector (campos cortos para poder
# filtrar en el futuro, ver decisión de diseño 3 — el texto completo NO va
# acá, sólo al docstore local).
METADATA_TEXT_MAX_LEN = 128

# Pregunta de prueba en español, relevante al dominio (ARCSA/trámites).
TEST_QUERY = (
    "¿Qué requisitos debo cumplir para la Notificación Sanitaria Obligatoria "
    "de un dispositivo médico a través de la Ventanilla Única Ecuatoriana?"
)
TEST_QUERY_TOP_K = 5


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def _batched(items: list[Any], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _write_docstore_atomic(path: Path, docstore: dict[str, dict]) -> None:
    """Escribe el docstore COMPLETO de forma atómica (ver decisión de diseño
    9b): vuelca a un archivo temporal en el mismo directorio
    (`<path>.tmp`), fuerza flush+fsync, y recién después lo reemplaza sobre
    el destino final con `os.replace()` — atómico en Windows y POSIX cuando
    origen y destino están en el mismo volumen (lo están: mismo directorio).

    Si el proceso se corta a mitad de este `json.dump()`, sólo el `.tmp`
    queda a medio escribir; el archivo real en `path` nunca pasa por un
    estado corrupto a medio escribir, porque `os.replace()` recién ocurre
    después de que el `.tmp` ya quedó completo y cerrado."""
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(docstore, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def load_existing_docstore(path: Path) -> dict[str, dict]:
    """Carga el docstore existente en disco de forma tolerante a fallos (ver
    decisión de diseño 9c): si el archivo no existe, está vacío, o quedó
    corrupto (p. ej. de una corrida MUY vieja anterior al fix de escritura
    atómica del punto (b)), se trata como vacío en vez de tirar abajo toda
    la corrida. `plan_resume()` es quien decide qué parte de este contenido
    es realmente reutilizable."""
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, OSError) as error:
        print(f"[ADVERTENCIA] No se pudo leer el docstore existente en '{path}' ({error}); se trata como vacío.")
        return {}


# --------------------------------------------------------------------------
# Paso 1-2: cargar los dos corpus y convertirlos a Document con id estable
# --------------------------------------------------------------------------


def load_normativa_chunks(data_dir: Path) -> list[dict]:
    """
    Aplana todos los chatbot/data/normativa/*.json en una sola lista de
    chunks (cada archivo trae varios chunks bajo la clave "chunks").

    Se le agregan las claves internas "_file_id" (tomada del "file_id" del
    archivo fuente) y "_index_in_file" (posición del chunk dentro de ese
    archivo) a cada chunk, para poder construir un id determinista más
    abajo; ingestion.to_documents() ignora las claves que no reconoce, así
    que esto no rompe su contrato.

    "_index_in_file" hace falta porque "articulo_numero" NO es único dentro
    de un mismo archivo: verificado que 20 de los 296 archivos (192 chunks)
    tienen numeración de Artículo repetida (p. ej. un PDF que concatena dos
    resoluciones, cada una reiniciando su "Art. 1, Art. 2..."). Usar sólo
    file_id+articulo_numero como id produciría colisiones silenciosas.
    """
    chunks: list[dict] = []
    files = sorted(data_dir.glob("*.json"))
    for path in files:
        with path.open(encoding="utf-8") as f:
            record = json.load(f)
        file_id = record.get("file_id") or path.stem
        for index_in_file, chunk in enumerate(record.get("chunks", [])):
            enriched = dict(chunk)
            enriched["_file_id"] = file_id
            enriched["_index_in_file"] = index_in_file
            chunks.append(enriched)

    print(f"[INFO] Normativa: {len(files)} archivos, {len(chunks)} chunks cargados desde '{data_dir}'.")
    return chunks


def build_normativa_documents() -> list:
    chunks = load_normativa_chunks(NORMATIVA_DIR)
    documents = normativa_to_documents(chunks)

    for chunk, document in zip(chunks, documents, strict=True):
        document.id_ = f"normativa:{chunk['_file_id']}:{chunk['_index_in_file']}:{chunk['articulo_numero']}"
        document.metadata["corpus"] = "normativa"
        document.metadata["file_id"] = chunk["_file_id"]

    return documents


def build_tutorial_documents() -> list:
    print("[INFO] Tutorial: regenerando chunks vía tutorial_ingestion.run_pipeline() (no se persisten en disco).")
    chunks = run_tutorial_pipeline()
    documents = tutorial_to_documents(chunks)

    # Limpieza de enlaces ya confirmados rotos ("broken"/"timeout") antes de
    # embeber: el LLM recibe el texto de estos chunks tal cual en el prompt
    # (chatbot/main.py::_build_grounded_prompt) y los reproduce si están
    # presentes, incluidos los muertos. Se usa el reporte de
    # link_validation.py más reciente en disco; si no existe, no rompe esta
    # corrida (ver load_broken_urls()), sólo deja el corpus sin limpiar.
    broken_urls = load_broken_urls()
    if broken_urls:
        cleaned_chunks = 0
        cleaned_links = 0
        for document in documents:
            new_text, removed = strip_broken_links_from_text(document.text, broken_urls)
            if removed:
                document.set_content(new_text)
                cleaned_chunks += 1
                cleaned_links += removed
        print(
            f"[INFO] Limpieza de enlaces rotos del corpus Tutorial: {cleaned_links} "
            f"enlace(s) roto(s) eliminado(s) en {cleaned_chunks}/{len(documents)} "
            f"chunk(s) (según '{LINK_VALIDATION_REPORT_PATH}')."
        )

    for chunk, document in zip(chunks, documents, strict=True):
        page_id = chunk.get("id") or document.id_
        document.id_ = f"tutorial:{page_id}"
        document.metadata["corpus"] = "tutorial"

    return documents


def enforce_max_safe_chunk_size(documents: list, corpus_label: str) -> list:
    """
    Red de seguridad de tamaño GENÉRICA aplicada a CUALQUIER Document antes
    de llegar a process_documents() — sin importar de qué corpus venga.

    POR QUÉ EXISTE (fix del 2026-09-08, mismo día que el fix de chunking de
    Normativa en chatbot/normativa_extraction.py): ese fix resolvió el caso
    de los documentos de Normativa sin Artículo que se guardaban como un
    único chunk gigante ("DOCUMENTO_COMPLETO"). Al preparar la corrida real
    completa se encontró que el corpus de TUTORIAL (chatbot/
    tutorial_ingestion.py, que este script reutiliza sin modificar) tiene el
    MISMO problema de fondo por una razón distinta: 32 de sus 252 chunks
    reales superan los 7000 caracteres, hasta 122 086 caracteres en una sola
    página — tutorial_ingestion.py trocea por página HTML, no por tamaño, así
    que una página larga sin cortes internos queda como un chunk único.

    Verificado empíricamente contra la API real de embeddings
    (embed_model.get_text_embedding_batch) que un texto muy grande en una
    sola llamada puede devolver un 429 (RESOURCE_EXHAUSTED) SIN el campo
    "quotaId" que _quota_violation_period() usa para distinguir cuota
    diaria/por minuto de un rate-limit real y transitorio. Sin esta función,
    ese 429 llegaría a _embed_with_retry() clasificado como "cuota
    desconocida", reintentaría el MISMO lote completo (con el mismo
    documento gigante adentro) hasta agotar RATE_LIMIT_BATCH_MAX_RETRIES, y
    terminaría abortando LA CORRIDA ENTERA vía EmbeddingQuotaAbortError — un
    solo chunk de tamaño excesivo tumbaría el resto de una corrida que, para
    ese punto, ya podría llevar cientos de lotes embebidos con éxito.

    Por eso, antes de que CUALQUIER documento llegue a process_documents(),
    se aplica el mismo criterio de tamaño ya calibrado empíricamente en
    chatbot/normativa_extraction.py (MAX_SAFE_CHUNK_CHARS,
    split_text_into_windows: sliding window con solapamiento, sin cortar
    palabras) — se reutiliza esa función en vez de duplicar la lógica,
    porque el límite real de la API de embeddings es el mismo sin importar
    el corpus de origen. Para el resto del corpus (Normativa ya troceada en
    origen, y la mayoría de las páginas de Tutorial) esta función es un
    no-op. El id de cada parte usa el sufijo ":PARTE_<i>_DE_<n>" sobre el id
    determinista ya asignado (p. ej. "tutorial:<page_id>:PARTE_2_DE_5"),
    consistente con el mismo sufijo que usa
    normativa_extraction._resplit_oversized_chunk para Artículos genuinos
    demasiado grandes.
    """
    result: list = []
    split_count = 0
    for document in documents:
        text = document.text
        if len(text) <= MAX_SAFE_CHUNK_CHARS:
            result.append(document)
            continue

        windows = split_text_into_windows(text)
        total = len(windows)
        split_count += 1
        base_id = document.id_
        for i, window_text in enumerate(windows, start=1):
            part = deepcopy(document)
            part.set_content(window_text)
            part.id_ = f"{base_id}:PARTE_{i}_DE_{total}"
            result.append(part)

    if split_count:
        print(
            f"[ADVERTENCIA] Corpus '{corpus_label}': {split_count} documento(s) superaban "
            f"MAX_SAFE_CHUNK_CHARS ({MAX_SAFE_CHUNK_CHARS} caracteres) y se dividieron en "
            f"{len(result) - (len(documents) - split_count)} parte(s) más chicas antes de "
            "embeber (ver enforce_max_safe_chunk_size)."
        )
    return result


# --------------------------------------------------------------------------
# Paso 3: generar embeddings reales, con aislamiento de fallos por documento
# --------------------------------------------------------------------------


class _RateLimiter:
    """Ventana deslizante real: garantiza que nunca se disparen más de
    `max_requests` llamadas NI más de `max_tokens` tokens (estimados, ver
    _estimate_tokens) en cualquier ventana de `window_seconds` segundos
    consecutivos. `wait_for_slot(tokens)` debe llamarse inmediatamente antes
    de cada request HTTP real a embed_content (tanto en el camino de lote
    como en el fallback documento por documento) — a diferencia de un
    time.sleep() fijo entre lotes, esto acota el ritmo real en cualquier
    ventana, no sólo el promedio.

    El límite de tokens se agregó el 2026-09-08 (ver decisión de diseño 8 en
    el docstring del módulo): el límite de requests por sí solo no alcanza
    para mantenerse bajo un límite de tokens/minuto todavía bajo en una
    cuenta recién facturada; `max_tokens=None` desactiva ese chequeo (para
    no romper otros usos de esta clase que no lo necesiten)."""

    def __init__(self, max_requests: int, window_seconds: float, max_tokens: int | None = None) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tokens = max_tokens
        self._entries: deque[tuple[float, int]] = deque()  # (timestamp, tokens)

    def _drop_expired(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] >= self.window_seconds:
            self._entries.popleft()

    def wait_for_slot(self, tokens: int = 0) -> None:
        while True:
            now = time.monotonic()
            self._drop_expired(now)

            over_requests = len(self._entries) >= self.max_requests
            tokens_in_window = sum(t for _, t in self._entries)
            over_tokens = (
                self.max_tokens is not None
                and bool(self._entries)
                and tokens_in_window + tokens > self.max_tokens
            )
            if not over_requests and not over_tokens:
                break

            sleep_seconds = self.window_seconds - (now - self._entries[0][0])
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        self._entries.append((time.monotonic(), tokens))


_embed_rate_limiter = _RateLimiter(
    EMBED_RATE_LIMIT_MAX_REQUESTS,
    EMBED_RATE_LIMIT_WINDOW_SECONDS,
    max_tokens=EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS,
)


class EmbeddingQuotaAbortError(RuntimeError):
    """Se lanza para cortar process_documents() ante un 429 de Gemini que no
    tiene sentido seguir reintentando dentro de la misma corrida: cuota
    DIARIA confirmada agotada, o cuota por minuto que sigue fallando después
    de agotar RATE_LIMIT_BATCH_MAX_RETRIES reintentos del lote/documento
    completo."""


def _is_rate_limit_error(error: BaseException) -> bool:
    """True si `error` es un 429 real de la API de Gemini.

    Verificado contra la librería realmente instalada (google-genai 2.20.0,
    .venv/Lib/site-packages/google/genai/errors.py): APIError.raise_error()
    clasifica cualquier status 4xx como `ClientError` (subclase de
    `APIError`), con `.code` = status HTTP entero y `.details` = el JSON
    crudo de la respuesta de error. No se asume el nombre de la excepción:
    se confirmó leyendo el código fuente instalado y contra un 429 real
    capturado en el log de la corrida anterior.
    """
    return isinstance(error, ClientError) and getattr(error, "code", None) == 429


def _quota_violation_period(error: BaseException) -> str | None:
    """Distingue si el 429 viola la cuota DIARIA o la de POR MINUTO.

    Inspecciona el campo real "quotaId" que Gemini incluye en el detalle
    QuotaFailure del cuerpo del error (confirmado contra un 429 real
    capturado en el log de la corrida anterior: quotaId
    "EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier" para
    el límite por minuto, con "...PerDay..." para el límite diario). Se
    busca por substring sobre la representación en texto de `error.details`
    porque es un dict anidado sin esquema tipado fijo (details de un
    ClientError es JSON arbitrario devuelto por el servidor).

    Returns: "day", "minute" o None si no se pudo determinar.
    """
    details_text = str(getattr(error, "details", "") or "")
    if "PerDay" in details_text:
        return "day"
    if "PerMinute" in details_text:
        return "minute"
    return None


def _retry_delay_seconds(error: BaseException) -> float | None:
    """Extrae el retryDelay sugerido por Google (p. ej. "48s") del detalle
    RetryInfo del 429, si está presente (confirmado presente en el 429 real
    capturado en el log de la corrida anterior). Devuelve None si no está,
    para que el llamador use su propio backoff exponencial."""
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return None
    nested = details.get("error")
    if not isinstance(nested, dict):
        return None
    for item in nested.get("details") or []:
        if isinstance(item, dict) and str(item.get("@type", "")).endswith("RetryInfo"):
            match = re.match(r"([\d.]+)s", str(item.get("retryDelay", "")))
            if match:
                return float(match.group(1))
    return None


def _embed_with_retry(embed_call, label: str, tokens: int = 0):
    """Ejecuta `embed_call()` (una llamada real a get_text_embedding_batch)
    respetando el rate limiter (`tokens` es la estimación conservadora de
    _estimate_tokens para el/los texto(s) de esta llamada, usada por el
    límite de tokens/minuto agregado el 2026-09-08), reintentando la MISMA
    llamada completa ante un 429 de rate-limit (nunca fragmentándola más),
    con backoff (usa el retryDelay real que sugiere Google cuando está
    presente, si no un backoff exponencial propio). Aborta con
    EmbeddingQuotaAbortError si el 429 es de cuota DIARIA, o si se agotan
    los reintentos de un 429 de cuota por minuto. Cualquier excepción que NO
    sea un 429 se re-lanza tal cual para que el llamador decida (aislar
    documento por documento, o registrar como fallo puntual de
    contenido)."""
    rate_limit_attempt = 0
    while True:
        _embed_rate_limiter.wait_for_slot(tokens)
        try:
            return embed_call()
        except Exception as error:  # noqa: BLE001 - se clasifica abajo
            if not _is_rate_limit_error(error):
                raise

            quota_period = _quota_violation_period(error)
            if quota_period == "day":
                raise EmbeddingQuotaAbortError(
                    f"Cuota DIARIA de Gemini para embed_content agotada en {label}. Esperar dentro de "
                    "esta misma corrida no sirve: la cuota diaria no resetea hasta el próximo ciclo de "
                    f"24hs de Google. Detalle real: {error}"
                ) from error

            rate_limit_attempt += 1
            if rate_limit_attempt > RATE_LIMIT_BATCH_MAX_RETRIES:
                raise EmbeddingQuotaAbortError(
                    f"{label}: se agotaron los {RATE_LIMIT_BATCH_MAX_RETRIES} reintentos completos ante "
                    f"un 429 de rate-limit (cuota={quota_period or 'desconocida'}) sin recuperarse. "
                    f"Detalle real: {error}"
                ) from error

            wait_seconds = _retry_delay_seconds(error)
            if wait_seconds is not None:
                wait_seconds += 2.0  # margen de seguridad sobre lo que sugiere Google
            else:
                wait_seconds = min(
                    RATE_LIMIT_BACKOFF_INITIAL_SECONDS * (2 ** (rate_limit_attempt - 1)),
                    RATE_LIMIT_BACKOFF_MAX_SECONDS,
                )
            print(
                f"[ADVERTENCIA] {label}: 429 rate-limit (cuota={quota_period or 'desconocida'}); "
                f"reintento {rate_limit_attempt}/{RATE_LIMIT_BATCH_MAX_RETRIES} de la llamada completa "
                f"en {wait_seconds:.0f}s..."
            )
            time.sleep(wait_seconds)


def process_documents(
    embed_model,
    index,
    documents: list,
    docstore: dict[str, dict],
) -> tuple[int, list[dict]]:
    """
    Genera embeddings para `documents` en lotes de EMBED_BATCH_SIZE y sube
    cada lote a Pinecone + persiste el docstore local de forma INCREMENTAL,
    inmediatamente después de generar el embedding de ESE lote (ver decisión
    de diseño 9a/9b) — a diferencia del `embed_documents()` original, que
    devolvía todos los embeddings al llamador para recién subirlos/guardarlos
    al final de main().

    `docstore` se recibe y se MUTA in-place (ya viene con las entradas
    resumidas de una corrida anterior, si las hay — ver plan_resume() en
    main()): cada lote agrega sus entradas nuevas y vuelve a persistir el
    diccionario completo con `_write_docstore_atomic()`.

    Orden dentro de cada lote (ver decisión 9b para el motivo): primero se
    persiste el docstore, después se hace el upsert a Pinecone. Un 429 de
    rate-limit en un lote se reintenta con backoff sobre el MISMO LOTE
    COMPLETO vía _embed_with_retry() (nunca fragmentado documento por
    documento): un 429 no indica ningún problema de contenido, así que
    fragmentarlo sólo multiplicaría requests desperdiciadas contra una
    cuota ya ajustada (ver decisión de diseño 6 en el docstring del módulo).
    Si el 429 indica que la cuota violada es la DIARIA, o si se agotan los
    reintentos de un 429 de cuota por minuto, se aborta la corrida entera
    (EmbeddingQuotaAbortError) en vez de seguir insistiendo en vano — todo
    lo subido en lotes ANTERIORES a ese punto ya quedó persistido de forma
    incremental, así que no se pierde.

    El fallback documento por documento (para aislar el/los chunk(s)
    problemático(s)) se mantiene, pero SOLO se alcanza para excepciones que
    NO son un 429 (p. ej. un texto que excede el límite de tokens de un
    documento puntual).

    Returns:
        (uploaded_count, failures) donde uploaded_count es la cantidad total
        de vectores subidos a Pinecone en esta llamada, y failures es una
        lista de {"id", "corpus", "source", "error"}.

    Raises:
        EmbeddingQuotaAbortError: cuota diaria confirmada agotada, o cuota
        por minuto que no se recupera después de agotar los reintentos.
    """
    failures: list[dict] = []
    uploaded_total = 0

    # Los documentos con texto vacío no se pueden embeber de forma útil.
    embeddable = [d for d in documents if d.text and d.text.strip()]
    skipped_empty = len(documents) - len(embeddable)
    if skipped_empty:
        print(f"[ADVERTENCIA] {skipped_empty} documento(s) con texto vacío se omiten del embedding.")

    total = len(embeddable)
    done = 0
    batches = list(_batched(embeddable, EMBED_BATCH_SIZE))
    print(
        f"[INFO] Generando embeddings reales para {total} documentos en {len(batches)} lotes de hasta "
        f"{EMBED_BATCH_SIZE} (subida a Pinecone y persistencia del docstore INMEDIATAS tras cada lote, "
        "ver decisión de diseño 9)..."
    )

    for batch_idx, batch in enumerate(batches, start=1):
        texts = [d.text for d in batch]
        vectors: list[list[float]] | None = None
        try:
            vectors = _embed_with_retry(
                lambda texts=texts: embed_model.get_text_embedding_batch(texts),
                label=f"lote {batch_idx}/{len(batches)}",
                tokens=sum(_estimate_tokens(t) for t in texts),
            )
        except EmbeddingQuotaAbortError:
            # Cuota diaria agotada, o reintentos de rate-limit agotados: no
            # tiene sentido seguir, hay que abortar la corrida (ver main()),
            # nunca tratarlo como "error real de contenido" ni caer al
            # fallback documento por documento de abajo. Todo lo subido en
            # lotes anteriores a este ya está persistido (ver docstring).
            raise
        except Exception as batch_error:  # noqa: BLE001 - error real de contenido, no un 429
            print(
                f"[ADVERTENCIA] Lote {batch_idx}/{len(batches)} falló completo (no es un 429: "
                f"{batch_error}); reintentando documento por documento para aislar el/los chunk(s) "
                "problemático(s)."
            )

        # (documento, vector_normalizado) del lote actual únicamente — nunca
        # se acumula esto entre lotes, a diferencia del embeddings/failures
        # del diseño anterior.
        batch_results: list[tuple[Any, list[float]]] = []
        if vectors is not None:
            for document, vector in zip(batch, vectors, strict=True):
                batch_results.append((document, normalize_embedding(vector)))
        else:
            for document in batch:
                try:
                    vector = _embed_with_retry(
                        lambda document=document: embed_model.get_text_embedding_batch([document.text])[0],
                        label=f"documento {document.id_!r}",
                        tokens=_estimate_tokens(document.text),
                    )
                    batch_results.append((document, normalize_embedding(vector)))
                except EmbeddingQuotaAbortError:
                    raise
                except Exception as doc_error:  # noqa: BLE001
                    failures.append(
                        {
                            "id": document.id_,
                            "corpus": document.metadata.get("corpus"),
                            "source": document.metadata.get("source") or document.metadata.get("source_url"),
                            "error": str(doc_error),
                        }
                    )

        if batch_results:
            # 1) Docstore primero (ver decisión 9b: orden elegido para que,
            #    si el proceso muere entre medio, el peor caso sea "re-hacer
            #    este lote al reanudar" y nunca "vector en Pinecone sin
            #    texto local").
            for document, _vector in batch_results:
                docstore[document.id_] = {"text": document.text, "metadata": document.metadata}
            _write_docstore_atomic(DOCSTORE_PATH, docstore)

            # 2) Upsert del mismo lote a Pinecone.
            vectors_payload = [
                {"id": document.id_, "values": vector, "metadata": build_metadata(document)}
                for document, vector in batch_results
            ]
            index.upsert(vectors=vectors_payload)
            uploaded_total += len(vectors_payload)

        done += len(batch)
        print(
            f"[INFO]   ... {done}/{total} documentos procesados, {uploaded_total} vector(es) subidos a "
            f"Pinecone hasta ahora (lote {batch_idx}/{len(batches)})."
        )

    print(
        f"[INFO] Proceso incremental terminado: {uploaded_total} subidos OK, {len(failures)} fallidos, "
        f"{skipped_empty} omitidos por texto vacío."
    )
    return uploaded_total, failures


# --------------------------------------------------------------------------
# Paso 4: resumibilidad real (ver decisión de diseño 9c) + overwrite total
# del índice de Pinecone para una corrida nueva / incompatible
# --------------------------------------------------------------------------


def build_metadata(document) -> dict[str, Any]:
    """Metadata corta y filtrable; el texto completo NO va aquí (ver decisión de diseño 3)."""
    corpus = str(document.metadata.get("corpus", "desconocido"))
    metadata: dict[str, Any] = {"corpus": corpus}

    if corpus == "normativa":
        metadata["vigente"] = bool(document.metadata.get("vigente", True))
        articulo = str(document.metadata.get("articulo_numero", ""))[:METADATA_TEXT_MAX_LEN]
        if articulo:
            metadata["articulo_numero"] = articulo

    return metadata


def clear_index(index) -> None:
    """Borra TODO el contenido existente del índice antes de subir el corpus
    completo de esta corrida (ver decisión de diseño 4: overwrite total en
    vez de upsert incremental, para no acumular datapoints huérfanos)."""
    stats_before = index.describe_index_stats()
    count_before = stats_before.get("total_vector_count", 0)
    if count_before == 0:
        print("[INFO] El índice ya está vacío; no hace falta borrar nada.")
        return

    print(f"[INFO] Borrando los {count_before} vectores existentes del índice antes del overwrite total...")
    index.delete(delete_all=True)

    # delete_all() es async del lado de Pinecone; esperamos a que el conteo
    # confirme el borrado real antes de seguir (evidencia real, no una espera fija).
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if index.describe_index_stats().get("total_vector_count", 0) == 0:
            print("[INFO] Índice confirmado vacío.")
            return
        time.sleep(2)
    print("[ADVERTENCIA] No se pudo confirmar que el índice quedó vacío dentro del timeout; se sigue igual.")


def list_uploaded_ids(index) -> set[str]:
    """Enumera TODOS los IDs de vectores realmente presentes en el índice de
    Pinecone en este momento (ver decisión de diseño 9c): es la fuente de
    verdad real para decidir qué ya se subió, en vez de confiar en la sola
    existencia del docstore local (que puede corresponder a una corrida
    vieja con chunking/IDs distintos — comprobado empíricamente el
    2026-09-08: el docstore real en disco tenía 4591 entradas de una corrida
    de días atrás mientras el índice real estaba en 0 vectores).

    Usa `index.list()` (paginado, sólo trae IDs — nunca values/metadata) en
    vez de `fetch()`, para no pagar el costo de traer vectores/metadata que
    acá no hacen falta."""
    existing: set[str] = set()
    for page in index.list(limit=100):
        for item in page.vectors:
            existing.add(item.id)
    return existing


def plan_resume(
    current_ids: set[str],
    existing_ids_in_pinecone: set[str],
    existing_docstore: dict[str, dict],
) -> tuple[str, set[str], dict[str, dict]]:
    """
    Decide, de forma PURA (sin tocar Pinecone ni disco — para poder
    testearla con datos sintéticos sin mocks, ver chatbot/tests/), si esta
    corrida debe tratarse como nueva/overwrite o como resume real de una
    corrida interrumpida (ver decisión de diseño 9c).

    Args:
        current_ids: IDs de TODOS los documentos que esta corrida está por
            procesar (después de build_*_documents()+enforce_max_safe_chunk_size()).
        existing_ids_in_pinecone: IDs realmente presentes en Pinecone ahora
            mismo (ver list_uploaded_ids()).
        existing_docstore: contenido crudo de vector_docstore.json ya en
            disco al arrancar (ver load_existing_docstore()).

    Returns:
        (reason, resumable_ids, docstore_kept)
        - reason: "empty_index" (índice vacío, corrida nueva),
          "incompatible_corpus" (índice con contenido pero sin ningún id en
          común con el corpus actual: datos de una corrida vieja
          incompatible, ver decisión 4) o "resume" (progreso real
          reutilizable).
        - resumable_ids: subconjunto de current_ids que ya está subido en
          Pinecone Y tiene texto en existing_docstore -> se SALTEA al
          procesar. Vacío salvo en el caso "resume".
        - docstore_kept: subconjunto de existing_docstore a usar como punto
          de partida del docstore de esta corrida (se descarta cualquier
          entrada que no sea parte del progreso real resumible, para no
          arrastrar basura de corpus/corridas viejas). Vacío salvo en el
          caso "resume".
    """
    if not existing_ids_in_pinecone:
        return "empty_index", set(), {}

    overlap = existing_ids_in_pinecone & current_ids
    if not overlap:
        return "incompatible_corpus", set(), {}

    # Sólo se conserva/saltea lo que está en Pinecone Y tiene texto local
    # (ver decisión 9b: un id en Pinecone sin texto local se re-procesa en
    # vez de darse por perdido).
    docstore_kept = {doc_id: entry for doc_id, entry in existing_docstore.items() if doc_id in overlap}
    resumable_ids = overlap & docstore_kept.keys()
    return "resume", resumable_ids, docstore_kept


# --------------------------------------------------------------------------
# Paso 5: consulta de prueba real contra el índice
# --------------------------------------------------------------------------


def run_test_query(embed_model, index, docstore: dict[str, dict]) -> None:
    print(f"\n[INFO] Consulta de prueba: \"{TEST_QUERY}\"")

    query_vector = normalize_embedding(embed_model.get_query_embedding(TEST_QUERY))
    response = index.query(vector=query_vector, top_k=TEST_QUERY_TOP_K, include_metadata=False)
    matches = response.matches if response else []

    if not matches:
        print("[ERROR] La consulta de prueba no devolvió ningún resultado.")
        return

    print(f"[INFO] {len(matches)} resultado(s) devueltos por el índice:\n")
    for rank, match in enumerate(matches, start=1):
        entry = docstore.get(match.id, {})
        text = entry.get("text", "<sin texto local para este id>")
        metadata = entry.get("metadata", {})
        snippet = " ".join(text.split())[:300]
        print(f"  #{rank} id={match.id} score={match.score:.4f}")
        print(f"      corpus={metadata.get('corpus')} fuente={metadata.get('source') or metadata.get('source_url')}")
        print(f"      texto: {snippet}...\n")


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------


def main() -> None:
    # Fuente de verdad para el modelo de embeddings: chatbot/vector_store.py
    # (ver decisión de diseño 1 en el docstring del módulo). Se ajusta
    # embed_batch_size sobre la instancia devuelta para mantener el tamaño
    # de lote EMBED_BATCH_SIZE usado en process_documents().
    embed_model = configure_embeddings()
    embed_model.embed_batch_size = EMBED_BATCH_SIZE

    print("\n=== Paso 1-2: cargando y convirtiendo los dos corpus a Document ===")
    normativa_documents = build_normativa_documents()
    tutorial_documents = build_tutorial_documents()

    # Red de seguridad de tamaño genérica (ver enforce_max_safe_chunk_size):
    # Normativa ya viene troceada de forma segura desde el origen (ver
    # chatbot/normativa_extraction.py), así que esto es un no-op para ese
    # corpus; Tutorial SÍ tiene páginas reales por encima del límite seguro
    # (tutorial_ingestion.py trocea por página, no por tamaño), así que acá
    # SÍ divide antes de que cualquiera de los dos corpus llegue a
    # process_documents().
    normativa_documents = enforce_max_safe_chunk_size(normativa_documents, "normativa")
    tutorial_documents = enforce_max_safe_chunk_size(tutorial_documents, "tutorial")

    all_documents = normativa_documents + tutorial_documents
    print(
        f"[INFO] Total de documentos combinados: {len(all_documents)} "
        f"(normativa={len(normativa_documents)}, tutorial={len(tutorial_documents)})."
    )
    current_ids = {d.id_ for d in all_documents}

    print("\n=== Paso 3: determinando progreso previo real (resumibilidad, ver decisión de diseño 9) ===")
    index = get_vector_store()
    existing_ids_in_pinecone = list_uploaded_ids(index)
    existing_docstore = load_existing_docstore(DOCSTORE_PATH)

    reason, resumable_ids, docstore = plan_resume(current_ids, existing_ids_in_pinecone, existing_docstore)

    if reason == "empty_index":
        print("[INFO] El índice de Pinecone está vacío: corrida nueva, no hay progreso previo que resumir.")
        clear_index(index)
    elif reason == "incompatible_corpus":
        print(
            f"[ADVERTENCIA] El índice tiene {len(existing_ids_in_pinecone)} vector(es) pero NINGUNO "
            "coincide con los IDs del corpus actual (son de una corrida vieja con corpus/chunking "
            "distinto, ver decisión de diseño 4). Se trata como corrida nueva: overwrite total."
        )
        clear_index(index)
    else:  # "resume"
        overlap = existing_ids_in_pinecone & current_ids
        missing_text = overlap - resumable_ids
        if missing_text:
            print(
                f"[ADVERTENCIA] {len(missing_text)} id(s) están subidos en Pinecone pero sin texto en "
                "el docstore local; se re-procesan (re-embeben y re-suben; upsert es idempotente, no "
                "genera duplicados) para no perder el texto local de esos chunks."
            )
        print(
            f"[INFO] Progreso previo real detectado: {len(resumable_ids)}/{len(current_ids)} documentos "
            "del corpus actual ya están subidos en Pinecone (corrida interrumpida anteriormente, mismo "
            "corpus/IDs deterministas). Se SALTEA clear_index() para no perder ese progreso; se sigue "
            "sólo con los documentos faltantes."
        )

    documents_to_process = [d for d in all_documents if d.id_ not in resumable_ids]
    print(
        f"[INFO] Documentos a procesar en esta corrida: {len(documents_to_process)}/{len(all_documents)} "
        f"({len(resumable_ids)} ya subido(s) previamente, se saltean)."
    )

    failures: list[dict] = []
    uploaded = 0
    if not documents_to_process:
        print("[INFO] No hay documentos pendientes: todo el corpus ya estaba subido. No se genera ningún embedding nuevo.")
        if reason == "resume":
            # Caso borde (corpus ya completo al reanudar): process_documents()
            # nunca corre, así que nada reescribe el docstore en disco. Se
            # persiste igual acá el `docstore` ya filtrado por plan_resume()
            # (docstore_kept), para que el archivo en disco no arrastre
            # entradas viejas fuera de `resumable_ids` (ver decisión 9c).
            _write_docstore_atomic(DOCSTORE_PATH, docstore)
    else:
        print("\n=== Paso 4: generando embeddings y subiendo a Pinecone de forma incremental ===")
        try:
            uploaded, failures = process_documents(embed_model, index, documents_to_process, docstore)
        except EmbeddingQuotaAbortError as quota_error:
            print(f"\n[ERROR] {quota_error}")
            print(
                "[ERROR] Corrida abortada. El progreso subido HASTA este punto ya quedó persistido de "
                "forma incremental en Pinecone y en el docstore local (ver decisión de diseño 9): no se "
                "perdió. Para continuar, volvé a correr `python -m chatbot.vector_ingest` más tarde "
                "(cuando la cuota correspondiente de Gemini se recupere) — la próxima corrida detecta "
                "automáticamente lo ya subido y sólo procesa lo que falta."
            )
            sys.exit(1)

        if failures:
            print(f"\n[ADVERTENCIA] {len(failures)} documento(s) no se pudieron embeber:")
            for failure in failures:
                print(f"  - id={failure['id']} corpus={failure['corpus']} fuente={failure['source']}: {failure['error']}")

    fresh_stats = index.describe_index_stats()
    print(f"[INFO] Stats del índice tras esta corrida: {fresh_stats}")

    print("\n=== Paso 5: consulta de prueba real contra el índice ===")
    try:
        run_test_query(embed_model, index, docstore)
    except Exception as e:  # noqa: BLE001 - no queremos perder el resumen final por un fallo aquí
        print(f"[ERROR] La consulta de prueba falló: {e}")

    print("\n=== Resumen final ===")
    print(f"Documentos combinados:    {len(all_documents)}")
    print(f"Ya subidos previamente:   {len(resumable_ids)}")
    print(f"Subidos en esta corrida:  {uploaded}")
    print(f"Fallos de embedding:      {len(failures)}")
    print(f"Total en docstore local:  {len(docstore)}")


if __name__ == "__main__":
    main()
