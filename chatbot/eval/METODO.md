# Método de evaluación

Este documento describe el protocolo de evaluación aplicado al chatbot RAG del proyecto, con el detalle suficiente para que un tercero pueda reproducirlo. Todos los datos citados provienen de los artefactos reales generados en las fases previas del plan de evaluación: `chatbot/eval/golden_set.json`, `chatbot/eval/traces.jsonl`, `chatbot/eval/ragas_resumen.json`, `chatbot/eval/ragas_resultados.json` y `chatbot/eval/exactitud_cita.json`, además del código fuente que los produjo (`chatbot/eval/run_eval.py`, `chatbot/eval/ragas_eval.py`) y del código de producción (`chatbot/main.py`).

## 1. Criterio de construcción del conjunto de evaluación

El conjunto de evaluación (*golden set*, `chatbot/eval/golden_set.json`) se construye a partir de una lectura directa del corpus real ya indexado por el sistema: `chatbot/data/vector_docstore.json` (el índice vectorial serializado) y `chatbot/data/normativa/` (317 archivos JSON, uno por documento normativo de ARCSA, identificados por `file_id`, p. ej. `arcsa_10854.json`).

Para cada caso respondible (ejes *producto*, *tramite*, *establecimiento* y *codigo*), el procedimiento es:

1. Se localiza un fragmento real dentro del corpus indexado (documento + artículo/sección).
2. El campo `contexto_referencia` de `golden_set.json` se transcribe **verbatim** como subcadena real de ese fragmento del corpus (no es una paráfrasis ni un resumen; es el texto tal como está indexado, incluyendo saltos de línea y, en algunos casos, ruido propio de la extracción del PDF original — ver sección de limitaciones).
3. La fuente esperada (`fuente_esperada.file_id`, `fuente_esperada.articulo`, `fuente_esperada.documento`) se deriva directamente de los metadatos reales de ese mismo fragmento en el corpus indexado (`file_id` del archivo en `chatbot/data/normativa/`, número/fragmento de artículo y título del documento tal como aparecen en `vector_docstore.json`).
4. Se redacta una consulta en lenguaje natural cuya respuesta correcta depende de ese fragmento.

Los 8 casos del eje *fuera_de_cobertura* se construyen con el criterio opuesto: son preguntas deliberadamente ajenas al dominio o al alcance geográfico/regulatorio del corpus (por ejemplo, trámites ante COFEPRIS o la FDA, una receta de cocina, o preguntas genéricas sin relación con normativa sanitaria ecuatoriana). Para estos casos `fuente_esperada` y `contexto_referencia` son `null` **por diseño**: no existe fragmento del corpus que responda correctamente a la pregunta, de modo que no hay "verdad de referencia" que transcribir.

La distribución resultante (documentada también en `chatbot/eval/ANEXO_C.md`) es 60 % de consultas respondibles (ejes *producto*, *tramite*, *establecimiento*), 20 % de consultas de *código normativo* (la consulta cita explícitamente una resolución por su código, p. ej. "Según la Resolución ARCSA-DE-2022-016-AKRG...") y 20 % de consultas *fuera de cobertura*.

**Descartes**: en el repositorio no sobrevive un script ni un registro de la fase de construcción del conjunto (fase 1) — `chatbot/eval/` solo conserva `run_eval.py` (fase 2, ejecución del pipeline) y `ragas_eval.py` (fase 3, evaluación RAGAS). No se registraron descartes documentados en esta corrida: no hay ningún archivo, log o comentario en el repositorio que liste candidatos descartados durante la construcción del golden set. Este hecho se declara explícitamente en vez de inferir o inventar un proceso de descarte que no está documentado.

## 2. Composición final del conjunto

El conjunto final tiene 40 casos (`chatbot/eval/golden_set.json`), con 8 casos por eje:

| Eje | IDs | N |
|---|---|---|
| producto | q001–q008 | 8 |
| tramite | q009–q016 | 8 |
| establecimiento | q017–q024 | 8 |
| codigo | q025–q032 | 8 |
| fuera_de_cobertura | q033–q040 | 8 |
| **Total** | | **40** |

De estos 40 casos, 32 tienen `contexto_referencia != null` (los cuatro ejes respondibles) y 8 tienen `contexto_referencia = null` (fuera_de_cobertura), tal como confirma `ragas_resumen.json` (`n_casos_con_contexto_referencia: 32`, `n_casos_fuera_de_cobertura_excluidos_de_context_metrics: 8`).

## 3. Definición operativa de las métricas y configuración exacta

### 3.1 Métricas RAGAS

Versiones instaladas en el entorno del proyecto (`./.venv/Scripts/python.exe -m pip show ragas langchain-openai`):

- `ragas` versión **0.4.3**
- `langchain-openai` versión **1.6.1**

Las cuatro métricas se calculan con `chatbot/eval/ragas_eval.py`, usando las clases de `ragas.metrics`:

- **Faithfulness** (`Faithfulness`): mide si las afirmaciones contenidas en la respuesta generada pueden inferirse a partir de los contextos efectivamente recuperados (consistencia factual de la respuesta respecto de la evidencia recuperada, con independencia de si esa evidencia era la correcta para la pregunta). No requiere `reference`. Se calcula sobre los 40 casos.
- **Answer Relevancy** (`ResponseRelevancy`): mide qué tan pertinente es la respuesta generada respecto de la pregunta original. RAGAS la calcula generando preguntas sintéticas a partir de la respuesta y comparando, por similitud de embeddings, esas preguntas generadas contra la pregunta original. No requiere `reference`. Se calcula sobre los 40 casos.
- **Context Precision** (`LLMContextPrecisionWithReference`): mide si los fragmentos recuperados que son relevantes para responder la pregunta (juzgado por el LLM contra el `reference`) están mejor rankeados entre los contextos recuperados. Requiere `reference`; se calcula solo sobre los 32 casos con `contexto_referencia != null`.
- **Context Recall** (`LLMContextRecall`): mide, juzgado por el LLM, en qué medida la información necesaria presente en el `reference` está cubierta por los contextos efectivamente recuperados. Requiere `reference`; se calcula solo sobre los 32 casos con `contexto_referencia != null`.

Los 8 casos de `fuera_de_cobertura` se excluyen explícitamente de Context Precision y Context Recall porque no existe `reference` (no está bien definido calcular precisión/recall de recuperación contra una referencia inexistente por diseño). Esta decisión está documentada tanto en el docstring de `ragas_eval.py` como en el campo `metodologia.decision_exclusion` de `ragas_resumen.json`.

Configuración exacta empleada (`chatbot/eval/ragas_eval.py`):

- `JUDGE_MODEL = "gpt-5.5"`, instanciado como `ChatOpenAI(model=JUDGE_MODEL)` y envuelto en `LangchainLLMWrapper(chat, bypass_temperature=True)`. El flag `bypass_temperature=True` es necesario porque `gpt-5.5` (igual que la familia o1/o3/gpt-5 de OpenAI) rechaza cualquier `temperature` distinto de 1; sin ese flag, RAGAS pisa el `temperature` con su valor interno por defecto y las cuatro métricas fallan con un error 400 de la API.
- `EMBEDDING_MODEL = "text-embedding-3-small"`, usado por `OpenAIEmbeddings` para Answer Relevancy.
- Concurrencia máxima: 5 llamadas simultáneas (`MAX_CONCURRENCY = 5`).
- Timeout por llamada: 240 segundos.
- Reintentos: hasta 2 reintentos con backoff de 10 y 30 segundos ante un fallo real de RAGAS (timeout, error de parseo del juez, etc.). Si el fallo persiste tras agotar los reintentos, se registra el texto del error real en `ragas_resultados.json` (campo `errors.<metrica>`) y ese caso se excluye del promedio de esa métrica — nunca se promedia como si fuera 0. En esta corrida, `ragas_resumen.json` reporta `n_fallos_ragas: 0` para las cuatro métricas, tanto a nivel global como por eje.
- Desviación estándar: muestral (`statistics.stdev`, ddof = 1); indefinida (`null`) cuando n < 2.

### 3.2 Exactitud de cita

`chatbot/eval/exactitud_cita.json` evalúa 5 criterios sobre las fuentes citadas por el sistema en una muestra de 24 de los 32 casos respondibles/código (120 fuentes evaluadas en total, 5 fuentes por caso). Los 8 casos `fuera_de_cobertura` quedan fuera de este análisis porque no citan fuentes reales.

Los 5 criterios y su método:

1. **Documento existe** (`criterio_1_documento_existe`) — método **automatizado**: verifica que el documento/`file_id` citado por el sistema exista realmente en el corpus indexado.
2. **El fragmento respalda la afirmación** (`criterio_2_fragmento_respalda_afirmacion`) — método **asistido por LLM** (juez `gpt-5.5`): evalúa si el texto del fragmento citado efectivamente sustenta la afirmación que la respuesta generada le atribuye.
3. **Ubicación precisa** (`criterio_3_ubicacion_precisa`) — método **automatizado**: compara el artículo/sección citado en la traza contra el valor real de `metadata.articulo_numero` en el docstore para ese fragmento. No aplica (`N/A`) a fuentes del corpus `tutorial`, que no tienen concepto de artículo.
4. **Norma vigente** (`criterio_4_norma_vigente`) — método **automatizado**: lee directamente el campo `metadata.vigente` del fragmento citado. No aplica (`N/A`) a fuentes del corpus `tutorial` que carecen de ese campo.
5. **La disposición aplica al caso** (`criterio_5_disposicion_aplica_al_caso`) — método **asistido por LLM** (juez `gpt-5.5`): evalúa si la disposición normativa citada es realmente pertinente para la consulta concreta formulada, más allá de que el fragmento exista y esté correctamente ubicado.

Los criterios 2 y 5 usan el mismo modelo juez que RAGAS (`gpt-5.5`); `exactitud_cita.json` no registra fallos del juez LLM en esta corrida (`llm_failures: []`).

Muestreo (`exactitud_cita.json`, campo `metodologia_muestreo`): se tomaron los primeros 6 de los 8 IDs de cada uno de los 4 ejes elegibles (producto, tramite, establecimiento, codigo), en el orden en que aparecen en `golden_set.json`/`traces.jsonl` — selección **determinista, no aleatoria**, para preservar la reproducibilidad y mantener la muestra balanceada entre ejes, acotando el volumen de llamadas al juez LLM (~240 llamadas para 120 fuentes × 2 criterios evaluados por LLM) a un tamaño manejable dentro del rango de 20-30 casos solicitado. Los IDs excluidos de este sub-muestreo (no del golden set completo, solo de esta evaluación de citas) son: q007, q008, q015, q016, q023, q024, q031, q032.

## 4. Modelo generador y modelo evaluador

**Modelo generador**: `gemini-3.5-flash-lite`, instanciado en `chatbot/main.py` (`llm = GoogleGenAI(model="gemini-3.5-flash-lite", api_key=GEMINI_API_KEY)`). Es el mismo modelo que corre en producción; no se modificó para esta evaluación. Las trazas de `chatbot/eval/traces.jsonl` se generaron llamando directamente a las funciones reales de `chatbot/main.py` (`retrieve_chunks`, `_build_grounded_prompt`, `_build_source_citation`, `_is_low_confidence`, `llm.complete`) contra el pipeline RAG real (Pinecone + Gemini), sin mocks.

**Modelo evaluador (juez)**: `gpt-5.5`, fijado en el código como alias mediante `JUDGE_MODEL = "gpt-5.5"` y usado a través de `ChatOpenAI(model=JUDGE_MODEL)` (`chatbot/eval/ragas_eval.py`). Ninguno de los artefactos versionados en `chatbot/eval/` (`ragas_resumen.json`, `ragas_resultados.json`, `exactitud_cita.json`) registra el `system_fingerprint`/snapshot con fecha del modelo juez efectivamente usado en cada corrida — solo el alias. Como dato aparte, durante la verificación previa del cableado evaluador (una llamada de prueba puntual, no versionada en el repo, antes de correr las Fases 3 y 4) la API resolvió el alias `gpt-5.5` al snapshot `gpt-5.5-2026-04-23` (visible en `response_metadata.model_name` de esa respuesta); OpenAI no garantiza que ese mismo snapshot se mantenga fijo en corridas futuras del alias, por lo que este dato se reporta como una observación puntual y no como una propiedad estable documentada por el proveedor.

**Modelo de embeddings usado por RAGAS para Answer Relevancy**: `text-embedding-3-small` (`ragas_resumen.json`, campo `metodologia.modelo_embeddings_answer_relevancy`; coincide con `EMBEDDING_MODEL` en `ragas_eval.py`). Este es un modelo de embeddings distinto del modelo de embeddings de recuperación que usa el pipeline de producción para poblar el índice vectorial (`models/gemini-embedding-001`, según comentario en `chatbot/main.py`); ambos cumplen roles distintos y no deben confundirse.

## 5. LIMITACIONES DEL MÉTODO

- **Evaluación asistida por modelo, no validación experta**: los criterios 2 (el fragmento respalda la afirmación) y 5 (la disposición aplica al caso) de Exactitud de Cita son evaluaciones asistidas por un modelo de lenguaje (`gpt-5.5`), no una validación realizada por un experto regulatorio del dominio sanitario ecuatoriano. `exactitud_cita.json` lo declara explícitamente en su propio campo `criterio_2_y_5_disclaimer: "evaluacion asistida, no validacion experta"`.

- **El criterio 4 (vigencia) no es informativo en esta versión**: según `exactitud_cita.json` (campo `aclaracion_criterio_4`), sobre el total de 9506 entradas de `vector_docstore.json`, el campo `metadata.vigente`, cuando está presente, tiene un único valor posible: `{True: 9117}`. Además, 389 entradas no tienen el campo `vigente` en absoluto (mayormente del corpus `tutorial`), y `chatbot/main.py._build_source_citation` usa `metadata.get('vigente', True)`, es decir que también trata esas entradas como "Vigente" por defecto cuando el campo falta. En la práctica, con los datos y el código actuales, **ninguna cita puede resultar "no vigente"**: el 100 % (o cercano) de cumplimiento de este criterio es una constante estructural del sistema y del corpus, no un mérito real de la respuesta evaluada. No debe reportarse como una fortaleza del sistema.

- **Tamaño e inferencia estadística**: el conjunto de 40 casos es una muestra dirigida y estratificada por eje (8 casos por cada uno de los 5 ejes), construida deliberadamente para cubrir categorías específicas de consulta — no es una muestra aleatoria extraída de tráfico real de usuarios. Este diseño no permite generalizar con confianza estadística los resultados obtenidos (medias, medianas, proporciones de cumplimiento) al universo completo de consultas posibles de usuarios reales, ni calcular intervalos de confianza con una interpretación poblacional válida. Los resultados deben leerse como una evaluación diagnóstica sobre las categorías representadas en el golden set, no como una medición de desempeño esperado en producción con tráfico real.

- **La corrección post-evaluación (`_filter_citable_sources()`) no fue re-validada empíricamente con el conjunto completo**: después de cerrar esta evaluación (tag `tfe-evaluacion`, commit `25b9642`) se implementó en `chatbot/main.py` un filtro que descarta, de las fuentes citadas, cualquier chunk cuya `distance` individual no alcance `SIMILARITY_THRESHOLD = 0.70` (ver `chatbot/eval/RESULTADOS.md`, Sección 8, para el detalle completo). Deliberadamente **no se re-ejecutaron las Fases 3 y 4 sobre los 40 casos con el fix aplicado**. Esto es una decisión explícita, no un descuido: cruzando los veredictos de criterio_2/criterio_5 de `exactitud_cita.json` contra las distancias reales de `traces.jsonl`, las fuentes relevantes (n=35) tienen distance promedio 0.7668 (rango 0.7250–0.8461) y las no relevantes (n=85) tienen distance promedio 0.7584 (rango 0.7243–0.8203) — una diferencia de medias de solo 0.0084 y solapamiento casi total entre ambas distribuciones. Además, ninguno de los 32 casos en dominio del golden set tiene, en su top-5, un chunk por debajo de 0.70. Es decir, el conjunto de fuentes citadas en los 32 casos respondibles ya evaluados en las Secciones 3 y 4 de `RESULTADOS.md` es idéntico con o sin el fix, por lo que una re-ejecución completa no puede producir un resultado distinto al ya documentado, y su único efecto habría sido consumir de nuevo presupuesto real de la API de OpenAI (la corrida de Fases 3 y 4 documentada costó ≈$11 reales) sin generar información nueva.

## 6. Separación de proveedores generador/evaluador

La evaluación automática emplea como modelo juez un modelo de un proveedor distinto al del generador. Esta separación entre el modelo que produce las respuestas y el que las evalúa elimina el sesgo de auto-preferencia que se produce cuando ambos roles recaen sobre el mismo modelo, y constituye la práctica recomendada en la literatura sobre evaluación asistida por modelos de lenguaje. La validación de los veredictos automáticos contra juicio de un experto regulatorio del dominio sanitario queda fuera del alcance de este trabajo y se recoge como línea de trabajo futuro.

## 7. Líneas de trabajo futuro

- Validación de los veredictos del evaluador automático (gpt-5.5) contra el juicio de un experto regulatorio del dominio sanitario ecuatoriano.
- Ampliar el conjunto anotado más allá de los 40 casos actuales, incorporando una muestra aleatoria de tráfico real de usuarios (además de la muestra dirigida por eje ya existente), para poder sostener inferencias estadísticas con mayor validez poblacional.
- Corregir el ruido de extracción de PDF presente en el corpus indexado: por ejemplo, el fragmento correspondiente a `arcsa_15697` (entre otros documentos que comparten el mismo texto, como `arcsa_14867`, `arcsa_14456`, `arcsa_13112` y `arcsa_11666`) tiene el carácter inicial "R" recortado ("epresentantes técnicos de plantas procesadoras de alimentos deben contar con..." en vez de "Representantes técnicos..."), tal como quedó registrado verbatim en `contexto_referencia` del caso q015 de `golden_set.json` y confirmado en el propio corpus (`chatbot/data/normativa/arcsa_15697.json` y `chatbot/data/vector_docstore.json`).
- Investigar por qué 2 de los 8 casos del eje `fuera_de_cobertura` (q035 y q036, según `chatbot/eval/traces.jsonl`, campo `is_low_confidence`) no fueron marcados como de baja confianza por el sistema pese a tratarse de preguntas fuera del dominio (registro sanitario ante COFEPRIS en México y requisitos de la FDA de EE. UU., respectivamente), a diferencia de los otros 6 casos del mismo eje que sí se marcaron correctamente.
- Extender la evaluación de Exactitud de Cita a los 8 casos restantes del pool elegible (q007, q008, q015, q016, q023, q024, q031, q032), que quedaron fuera de la muestra de 24 casos analizada en esta corrida.
- Implementar un mecanismo de juicio de contenido por fragmento en vez de (o además de) un umbral de similitud de embeddings: el análisis del punto de limitaciones sobre `_filter_citable_sources()` (Sección 5 de este documento) y de la Sección 8 de `RESULTADOS.md` muestra que las fuentes relevantes y no relevantes del golden set ocupan casi la misma banda de distance (0.7243–0.8461), por lo que ningún ajuste de `SIMILARITY_THRESHOLD` puede separarlas. Un reranker entrenado para relevancia fina, o un juez LLM que evalúe cada fragmento individualmente contra la afirmación que va a respaldar antes de decidir si se cita, son los candidatos naturales para resolver el problema de sobre-citación medido en los criterios 2 y 5 de la Sección 3 de `RESULTADOS.md`.
  **Priorización frente a otras mejoras de recuperación**: se prioriza el reranking/juicio por fragmento por sobre una eventual migración a recuperación híbrida (denso + BM25). La recuperación densa actual ya trae el fragmento correcto dentro del top-5 en los 32 casos en dominio del golden set (ninguno cae por debajo de `SIMILARITY_THRESHOLD`); el problema medido no es que falte traer el fragmento correcto, sino que, una vez traído junto con otros cuatro fragmentos temáticamente parecidos, no hay ningún mecanismo que decida cuál de los cinco citar. Recuperación híbrida atacaría un problema distinto (mejorar qué entra al top-5), no el que estos datos evidencian; queda como mejora complementaria, no como prioridad inmediata.
- Si se retoma la evaluación asistida por LLM (por ejemplo, para validar el reranker o juez de citación por fragmento del punto anterior), usar `gpt-5.4-mini` en vez de `gpt-5.5` como modelo evaluador: sobre los mismos volúmenes de tokens de la Fase 3 ya documentados (626,132 de entrada + 150,532 de salida), el costo habría sido de ≈$1.15 con `gpt-5.4-mini` frente a los ≈$7.65 reales pagados con `gpt-5.5` para ese mismo tramo (precios verificados: `gpt-5.5` $5/$30 por millón de tokens entrada/salida, `gpt-5.4-mini` $0.75/$4.50 por millón).
