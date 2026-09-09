# Resultados de la evaluación empírica

Este documento reporta los resultados de la evaluación del chatbot RAG de ARCSA descrita en el plan de evaluación del TFE. Todos los números provienen directamente de los artefactos generados en las Fases 2 a 4 del plan: `golden_set.json`, `traces.jsonl`, `ragas_resumen.json`, `ragas_resultados.json` y `exactitud_cita.json` (todos en `chatbot/eval/`). Ningún valor fue inventado ni redondeado de forma que oculte un resultado bajo; donde el resultado es malo, se reporta como tal y se diagnostica la causa probable.

## 1. Composición del conjunto de evaluación

El conjunto de evaluación (`golden_set.json`) está compuesto por **40 casos**, distribuidos en 5 ejes de 8 casos cada uno:

| Eje | N | IDs | Descripción |
|---|---|---|---|
| `producto` | 8 | q001–q008 | Preguntas sobre qué es o qué cubre un producto regulado (alimentos, medicamentos, cosméticos, dispositivos médicos, etc.) |
| `tramite` | 8 | q009–q016 | Preguntas sobre plazos, requisitos y procedimientos administrativos |
| `establecimiento` | 8 | q017–q024 | Preguntas sobre definiciones, vigencia y obligaciones de establecimientos sujetos a control sanitario |
| `codigo` | 8 | q025–q032 | Preguntas que citan explícitamente el código de una resolución ARCSA y piden su contenido |
| `fuera_de_cobertura` | 8 | q033–q040 | Preguntas fuera del dominio de la base normativa (recetas de cocina, normativa de otros países, IA, criptomonedas, etc.), usadas para medir si el sistema declina responder en vez de alucinar |

Es decir, 32 de los 40 casos (80%) son "respondibles" (tienen `fuente_esperada` y `contexto_referencia` reales en el golden set) y 8 (20%) son deliberadamente no respondibles por diseño, sin ground truth de referencia.

## 2. Métricas RAGAS

Metodología (de `ragas_resumen.json`): juez `gpt-5.5`, embeddings `text-embedding-3-small` para Answer Relevancy, desviación estándar muestral (`ddof=1`). **Context Precision y Context Recall se calcularon solo sobre los 32 casos con `contexto_referencia != null`** (ejes producto/tramite/establecimiento/codigo); los 8 casos `fuera_de_cobertura` se excluyeron explícitamente de esas dos métricas porque la pregunta no tiene respuesta en el corpus por diseño y no existe un ground truth contra el cual medir precisión/recall de contexto. Faithfulness y Answer Relevancy sí se calcularon sobre los 40 casos porque no requieren contexto de referencia. No hubo fallos de RAGAS en ninguna métrica (`n_fallos_ragas: 0` en todos los bloques).

### 2.1 Global

| Métrica | N | Media | Mediana | Desv. estándar |
|---|---|---|---|---|
| Faithfulness | 40 | 0.713 | 0.789 | 0.281 |
| Answer Relevancy | 40 | **0.492** | 0.683 | 0.404 |
| Context Precision | 32 | 0.666 | 0.819 | 0.385 |
| Context Recall | 32 | 0.693 | 1.000 | 0.426 |

Answer Relevancy global es **0.492**, un resultado bajo. La brecha grande entre la media (0.492) y la mediana (0.683), junto con una desviación estándar muy alta (0.404), indica una distribución bimodal: hay un grupo de respuestas con relevancia alta y otro grupo que arrastra la media hacia abajo con valores cercanos a 0. Una parte de ese grupo bajo son los 8 casos `fuera_de_cobertura` (que anotan Answer Relevancy = 0.0 de forma esperada, ver 2.2), pero como se muestra en la Sección 4, también hay casos dentro de los ejes respondibles con Answer Relevancy = 0.0, que sí son fallos reales.

### 2.2 Por eje

| Eje | Faithfulness (media/mediana/σ) | Answer Relevancy (media/mediana/σ) | Context Precision (media/mediana/σ) | Context Recall (media/mediana/σ) |
|---|---|---|---|---|
| `producto` | 0.798 / 0.889 / 0.291 | 0.747 / 0.830 / 0.306 | 0.643 / 0.739 / 0.404 | 0.813 / 1.000 / 0.372 |
| `tramite` | 0.677 / 0.621 / 0.177 | 0.705 / 0.831 / 0.298 | 0.666 / 0.798 / 0.392 | 0.604 / 0.750 / 0.454 |
| `establecimiento` | **0.415** / 0.408 / 0.307 | 0.483 / 0.581 / 0.355 | 0.851 / 1.000 / 0.350 | 0.688 / 1.000 / 0.458 |
| `codigo` | 0.770 / 0.817 / 0.202 | 0.526 / 0.743 / 0.443 | 0.503 / 0.569 / 0.385 | 0.667 / 1.000 / 0.471 |
| `fuera_de_cobertura` | 0.907 / 1.000 / 0.177 | **0.000** / 0.000 / 0.000 | n/a (excluido) | n/a (excluido) |

Dos lecturas importantes de esta tabla:

- **`establecimiento` es el eje con peor Faithfulness (0.415)**, muy por debajo del resto. Es también el eje del peor caso individual del conjunto completo (q018, Sección 4).
- **Answer Relevancy = 0.000 en `fuera_de_cobertura` no es un fallo del sistema, es el comportamiento correcto.** Cuando el sistema declina responder ("no tengo información suficiente...") ante una pregunta sin respuesta en el corpus, esa respuesta es —por construcción de la métrica RAGAS— poco "relevante" respecto de la pregunta original, porque no la responde. Faithfulness alto (0.907) en ese mismo eje confirma que el sistema no alucina contenido no sustentado al declinar. Este patrón se retoma en la Sección 4 para no contar como "fallo" lo que en realidad es una negativa correcta.

## 3. Exactitud de Cita

Evaluado sobre una muestra de **24 de los 32 casos respondibles** (6 primeros IDs de cada uno de los 4 ejes elegibles, selección determinista documentada en `exactitud_cita.json.resumen.metodologia_muestreo`, para acotar el volumen de llamadas al juez LLM), cubriendo **120 fuentes citadas** en total. Juez: `gpt-5.5`. Los 8 casos `fuera_de_cobertura` quedaron fuera de la muestra porque no citan fuentes reales.

| Criterio | Cumplimiento | Cumple / Evaluados |
|---|---|---|
| 1. El documento citado existe en el docstore | **100.0%** | 120 / 120 |
| 2. El fragmento citado respalda la afirmación hecha | **34.2%** | 41 / 120 |
| 3. La ubicación (artículo/sección) citada es precisa | **100.0%** | 115 / 115 |
| 4. La norma citada está vigente | **100.0%** | 115 / 115 (ver aclaración abajo — no informativo) |
| 5. La disposición citada aplica realmente al caso consultado | **45.0%** | 54 / 120 |

(Criterios 3 y 4 excluyen las fuentes de tipo `tutorial`, que no tienen concepto de artículo ni campo `vigente` en su metadata, y las fuentes que ya fallaron el criterio 1; por eso su base es 115 y no 120.)

**El criterio 2 (34.2%) y el criterio 5 (45.0%) son los hallazgos más importantes de esta sección y no deben suavizarse**: en más de 6 de cada 10 fuentes citadas, el fragmento recuperado no respalda literalmente la afirmación que el sistema le atribuye, y en más de la mitad de los casos la disposición citada no es la que realmente aplica a la pregunta hecha. Esto es consistente con el patrón de recuperación deficiente diagnosticado en la Sección 4: el sistema cita 5 fuentes por respuesta casi siempre (mecanismo de citación fijo, no condicionado a relevancia real), y cuando la recuperación trae contenido tangencial, esas fuentes igual se citan aunque no aporten evidencia real a la afirmación. (Nota de metodología del propio archivo: `criterio_2_y_5_disclaimer: "evaluacion asistida, no validacion experta"`.)

### Aclaración sobre el criterio 4 (norma vigente): 100% no es una fortaleza real

El texto completo de `exactitud_cita.json.resumen.aclaracion_criterio_4` explica por qué este 100% no tiene valor informativo sobre el mérito de las respuestas evaluadas:

> Sobre el corpus `normativa` completo (9506 entradas totales en `vector_docstore.json`), el campo `metadata.vigente`, cuando está presente, tiene **un solo valor distinto: `{True: 9117}`**. Además hay **389 entradas sin el campo `vigente` en absoluto** (mayormente corpus `tutorial`), y `chatbot/main.py._build_source_citation` usa `metadata.get('vigente', True)`: el sistema también las trata como "Vigente" por defecto cuando el campo falta. En la práctica, **ninguna cita puede dar "no vigente" con los datos y el código actuales**: el resultado de este criterio es 100% (o cercano) por diseño/constante del sistema, no por mérito de la respuesta evaluada.

En otras palabras: el criterio 4 mide una propiedad que el corpus y el código hacen matemáticamente imposible de fallar, no una capacidad real del sistema de distinguir normativa vigente de derogada. No se presenta como fortaleza en este informe.

## 4. Los tres peores casos

**Criterio usado**: se promediaron las métricas RAGAS aplicables de cada caso (Faithfulness, Answer Relevancy y, cuando aplica, Context Precision/Recall) sobre las 32 preguntas de los ejes respondibles (`producto`/`tramite`/`establecimiento`/`codigo`), usando `ragas_resultados.json`. **Se excluyó deliberadamente el eje `fuera_de_cobertura` de esta selección**: un Answer Relevancy de 0.0 ahí es la respuesta correcta esperada (negarse a responder), no un fallo — incluirlo habría contaminado el ranking de "peores casos" con negativas correctas. Dentro de los 32 casos respondibles, los tres de menor promedio combinado fueron q018, q007 y q012 (q028 quedó empatado con q012 en 0.208; se prioriza q012 en el análisis porque expone además un problema de consistencia del corpus que se documenta abajo).

### Caso q018 (el peor del conjunto completo, promedio RAGAS 0.104)

- **Consulta**: "¿Cómo define la normativa de permiso de funcionamiento sanitario el término 'establecimiento'?"
- **Métricas**: Faithfulness 0.417, Answer Relevancy 0.0, Context Precision 0.0, Context Recall 0.0
- **Qué salió mal**: la fuente esperada en el golden set es el Art. 3 (Parte 4 de 7) de la Resolución ARCSA-DE-2023-001-AKRG, que sí contiene la definición literal de "Establecimiento". La recuperación (top-5, `traces.jsonl`) trajo 4 fragmentos del documento correcto (`arcsa_10854`) pero de los artículos 4, 26, 13 y 27 —ninguno es la definición—, más un fragmento de otro documento (`arcsa_14960`). El artículo con la definición nunca fue recuperado. El sistema, correctamente, declinó responder ("No tengo información suficiente... el contexto proporcionado no contiene una definición explícita").
- **Diagnóstico técnico**: falla de **recuperación**, no de generación. El artículo 3 de esta resolución está fragmentado en 7 partes en el docstore (`3_PARTE_1_DE_7` ... `3_PARTE_7_DE_7`); es plausible que esta fragmentación diluya la señal semántica de cada parte individual frente a artículos operativos más "densos" en vocabulario de la consulta (todos mencionan "establecimientos sujetos a control y vigilancia sanitaria"), bajando su ranking por similitud. La generación se comportó bien (no alucinó una definición inexistente en su contexto), lo cual confirma que el cuello de botella está en la recuperación/chunking, no en el LLM.

### Caso q007 (promedio RAGAS 0.208)

- **Consulta**: "¿Qué tipos de productos están cubiertos por el certificado de Buenas Prácticas de Almacenamiento, Distribución y Transporte (BPADT) que otorga ARCSA?"
- **Métricas**: Faithfulness 0.833, Answer Relevancy 0.0, Context Precision 0.0, Context Recall 0.0
- **Qué salió mal**: la fuente esperada es el Art. 1 de la Resolución ARCSA-DE-002-2020-LDCL, que enumera explícitamente los productos cubiertos (medicamentos, gases medicinales, productos biológicos, dispositivos médicos, etc.). La recuperación trajo el documento correcto pero el **Art. 100** (qué debe constar en el certificado, no qué productos cubre), más 3 fragmentos de páginas `tutorial` genéricas y 1 de un instructivo distinto. A diferencia de q018, el sistema **no declinó**: construyó una respuesta a partir de ese contenido tangencial, citando el Art. 100 y una página de definición genérica, sin nunca dar la lista real de productos.
- **Diagnóstico técnico**: falla mixta. Hay un componente de **recuperación** (el artículo correcto —Art. 1— no entró en el top-5, aunque el documento sí), y un componente de **generación**: en vez de reconocer que el contexto no contenía la lista pedida (como sí hizo en q018), el modelo produjo una respuesta que suena fundamentada (cita artículo y resolución específicos) pero no responde la pregunta real. Este patrón —confianza aparente sobre evidencia tangencial— es más riesgoso que una negativa honesta, porque un usuario podría no notar que la respuesta no cubre lo preguntado. Nota: q007 no forma parte de la muestra de 24 casos de Exactitud de Cita, por lo que no hay veredictos de criterio 2/5 del juez LLM para este caso específico; el diagnóstico aquí se basa en comparar directamente la traza contra `fuente_esperada` del golden set.

### Caso q012 (promedio RAGAS 0.208)

- **Consulta**: "¿Qué certificación de calidad pueden presentar temporalmente los fabricantes nacionales de dispositivos médicos mientras obtienen la certificación ISO 13485?"
- **Métricas**: Faithfulness 0.833, Answer Relevancy 0.0, Context Precision 0.0, Context Recall 0.0
- **Qué salió mal**: la fuente esperada (`arcsa_12504`, Fragmento 5 de 26) indica que se puede presentar temporalmente el certificado **ISO 9001**. Ninguno de los 5 fragmentos recuperados proviene de ese documento; en cambio, la recuperación trajo el Art. 14 de otra resolución (`arcsa_11927`) que regula la **misma disposición transitoria pero en una versión distinta**: exige directamente el certificado ISO 13485 (sin mencionar ISO 9001 como alternativa temporal), además de otros 3 artículos de documentos relacionados pero no coincidentes. El sistema, de nuevo, declinó correctamente responder sobre la alternativa ISO 9001 porque no estaba en su contexto.
- **Diagnóstico técnico**: falla de **recuperación**, agravada por un problema de **calidad del corpus**: coexisten en el docstore al menos dos versiones/redacciones de la misma disposición transitoria (una que exige solo ISO 13485, otra —la esperada— que permite ISO 9001 como puente temporal) en documentos distintos, sin metadato de versión/vigencia relativa que le permita al sistema de recuperación o generación preferir la más reciente o la más específica. El embedding trajo la versión semánticamente más genérica en vez de la más específica y actualizada. La generación, otra vez, se comportó de forma calibrada (no inventó la mención a ISO 9001), pero el resultado final para el usuario es una respuesta incompleta sobre un trámite real.

**Patrón agregado de los tres casos**: en dos de tres (q018, q012) el sistema se comportó de forma segura ante evidencia insuficiente (declinó en vez de alucinar), lo cual es deseable; el problema de fondo en los tres es de **recuperación** —documento correcto pero artículo equivocado (q018, q007), o documento equivocado por versión duplicada de la norma (q012)— no de umbral de confianza mal calibrado ni de alucinación pura del LLM.

## 5. Dos casos completos: el mejor y el peor del conjunto

Ambos casos seleccionados (q010 como mejor, q018 como peor) pertenecen a la muestra de 24 casos evaluados para Exactitud de Cita, por lo que se presentan con los 5 fragmentos recuperados, la respuesta completa, las fuentes citadas y el veredicto de los 5 criterios de la rúbrica para cada una de sus 5 fuentes.

### 5.1 Mejor caso: q010 (promedio RAGAS 0.957 — el más alto de los 40 casos)

**Consulta**: "¿En qué plazo debe el Organismo de Inspección Acreditado (OIA) entregar al usuario los resultados de una inspección de certificación de Buenas Prácticas de Manufactura (BPM)?"

**Métricas RAGAS**: Faithfulness 1.000, Answer Relevancy 0.829, Context Precision ≈1.000 (0.9999999999), Context Recall 1.000.

**Los 5 fragmentos recuperados** (similitud reportada como `distance`, en escala Pinecone donde más alto = más similar):

| # | Documento (file_id) | Artículo | Distance |
|---|---|---|---|
| 1 | `arcsa_11650` — IE-B.3.1.3.1-B.P.M-01-01_Direct. para los OIA con fines de Cert. BPM v5 | FRAGMENTO_4_DE_17 | 0.7683 |
| 2 | `arcsa_11375` — IE-B.3.2.3-BPADT-02 (Directrices OIA para BPADT) | FRAGMENTO_4_DE_14 | 0.7497 |
| 3 | `arcsa_11650` — IE-B.3.1.3.1-B.P.M-01-01 | FRAGMENTO_5_DE_17 | 0.7483 |
| 4 | `arcsa_14441` — IE-B.3.4.2-LF-01_BPM Lab. Farma. V5.0 | FRAGMENTO_14_DE_293 | 0.7466 |
| 5 | `arcsa_13953` — Res. ARCSA-DE-2025-001-DASP (BPM laboratorios farmacéuticos) | FRAGMENTO_16_DE_328 | 0.7463 |

**Respuesta generada (completa)**:

> Con base en el documento *[Fuente 1: IE-B.3.1.3.1-B.P.M-01-01_Direct. para los OIA con fines de Cert. BPM v5 - Artículo FRAGMENTO_4_DE_17]*, sección "3.3. DE LAS INSPECCIONES", literal b), los resultados de las inspecciones de certificación de Buenas Prácticas de Manufactura (sean favorables o no favorables) deben ser entregados al usuario en el término de **diez (10) días laborales**.

**Fuentes citadas**: las 5 mismas de la tabla anterior (mecanismo de citación fijo: cita las 5 fuentes recuperadas, no solo la usada en el texto).

**Veredictos de Exactitud de Cita (5 criterios × 5 fuentes)**:

| Fuente | C1 Existe | C2 Respalda | C3 Ubicación precisa | C4 Vigente | C5 Aplica al caso |
|---|---|---|---|---|---|
| 1 (`arcsa_11650`, FRAGMENTO_4_DE_17) | Sí | Sí | Sí | Sí | Sí |
| 2 (`arcsa_11375`, FRAGMENTO_4_DE_14) | Sí | No (regula BPADT, no BPM; plazo distinto: 15 días) | Sí | Sí | No |
| 3 (`arcsa_11650`, FRAGMENTO_5_DE_17) | Sí | No (no menciona el plazo de 10 días ni entrega al usuario) | Sí | Sí | No |
| 4 (`arcsa_14441`, FRAGMENTO_14_DE_293) | Sí | No (no menciona al OIA; plazo distinto: 15 días) | Sí | Sí | Sí (parcial — mismo trámite general BPM) |
| 5 (`arcsa_13953`, FRAGMENTO_16_DE_328) | Sí | No (comité auditor, no OIA; plazo distinto: 15 días) | Sí | Sí | No |

**Diagnóstico de por qué salió bien**: la Fuente 1 —la única efectivamente citada en el texto de la respuesta— es exactamente el artículo esperado por el golden set (`arcsa_11650`, FRAGMENTO_4_DE_17) y respalda literalmente la afirmación (los "diez (10) días laborales"). El sistema identificó correctamente cuál de las 5 fuentes recuperadas era la relevante y construyó la respuesta solo a partir de ella, sin mezclar el plazo de 10 días con los plazos de 15 días que aparecen en las otras 4 fuentes (que regulan trámites similares pero distintos: BPADT y BPM de laboratorios farmacéuticos, no BPM de plantas procesadoras de alimentos). Esto muestra que cuando el artículo correcto sí es recuperado, tanto la generación como la atribución de la cita funcionan con precisión, incluso en presencia de "distractores" muy similares temáticamente (mismo tipo de trámite, plazos numéricamente distintos).

### 5.2 Peor caso: q018 (promedio RAGAS 0.104 — el más bajo de los 40 casos)

**Consulta**: "¿Cómo define la normativa de permiso de funcionamiento sanitario el término 'establecimiento'?"

**Métricas RAGAS**: Faithfulness 0.417, Answer Relevancy 0.0, Context Precision 0.0, Context Recall 0.0.

**Los 5 fragmentos recuperados**:

| # | Documento (file_id) | Artículo | Distance |
|---|---|---|---|
| 1 | `arcsa_10854` — Res. ARCSA-DE-2023-001-AKRG (permiso de funcionamiento sanitario) | 4 | 0.7615 |
| 2 | `arcsa_10854` | 26 | 0.7384 |
| 3 | `arcsa_10854` | 13 | 0.7336 |
| 4 | `arcsa_10854` | 27 | 0.7308 |
| 5 | `arcsa_14960` — IE-B.3.4.1-PF-01 (Descriptivo de establecimientos) | FRAGMENTO_9_DE_50 | 0.7300 |

Ninguno de los 5 es el artículo esperado (Art. 3, Parte 4 de 7, del mismo documento `arcsa_10854`), que contiene la definición literal: *"Establecimiento.- Lugar en el cual se ejerce una actividad comercial, industrial, sanitaria, entre otros; pudiendo ser un local, casa o edificio."*

**Respuesta generada (completa)**:

> No tengo información suficiente en la base normativa de ARCSA para responder esto con precisión, ya que el contexto proporcionado no contiene una definición explícita o textual del término "establecimiento".
>
> El CONTEXTO menciona que el permiso de funcionamiento se otorga a los "establecimientos sujetos a control y vigilancia sanitaria" (según el Artículo 4 de la *Resolución ARCSA-DE-2023-001-AKRG*), e incluye listados de categorías (como establecimientos farmacéuticos, restaurantes, servicios de catering, entre otros en la *Resolución ARCSA-DE-2023-001-AKRG* y el instructivo *IE-B.3.4.1-PF-01*), pero no define conceptualmente la palabra "establecimiento".

**Fuentes citadas**: las 5 mismas de la tabla anterior.

**Veredictos de Exactitud de Cita (5 criterios × 5 fuentes)**:

| Fuente | C1 Existe | C2 Respalda | C3 Ubicación precisa | C4 Vigente | C5 Aplica al caso |
|---|---|---|---|---|---|
| 1 (Art. 4) | Sí | Sí (respalda lo que sí se afirma: que el permiso se otorga a estos establecimientos) | Sí | Sí | No (no define "establecimiento") |
| 2 (Art. 26) | Sí | No | Sí | Sí | No |
| 3 (Art. 13) | Sí | No | Sí | Sí | No |
| 4 (Art. 27) | Sí | No | Sí | Sí | No |
| 5 (FRAGMENTO_9_DE_50) | Sí | Sí (respalda las categorías mencionadas, no una definición general) | Sí | Sí | No |

**Diagnóstico de por qué salió mal**: este es el caso más claro del conjunto de una **falla pura de recuperación por chunking**. El documento correcto sí fue recuperado en 4 de los 5 fragmentos (`arcsa_10854`), pero el artículo con la definición (Art. 3, fragmentado en 7 partes) nunca apareció en el top-5, desplazado por artículos operativos (4, 26, 13, 27) que comparten vocabulario superficial con la consulta ("establecimientos sujetos a control y vigilancia sanitaria") sin contener la definición pedida. A diferencia de q007, aquí la generación se comportó de forma ejemplarmente calibrada: reconoció explícitamente que no tenía la definición y no fabricó una. El costo de esa honestidad se refleja en RAGAS (Answer Relevancy y Context Recall en 0, porque no se recuperó ni se usó el contexto de referencia real) y en Faithfulness parcial (0.417, porque el poco que afirma sobre el Art. 4 es correcto pero la respuesta global admite no responder la pregunta). Es el mismo síntoma que en q012: la fragmentación de artículos largos en partes (aquí, 7 partes de un artículo de definiciones) parece perjudicar sistemáticamente la recuperación de esas partes frente a artículos completos y más "temáticamente densos".

## 6. Limitaciones del propio método de evaluación

- **Tamaño del conjunto (40 casos, 8 por eje)**: es un conjunto suficiente para detectar patrones y órdenes de magnitud (p. ej., que Answer Relevancy global es bajo, o que `establecimiento` tiene el peor Faithfulness), pero **no permite sostener generalizaciones estadísticas robustas por eje** (8 observaciones por eje producen intervalos de confianza muy anchos) ni afirmar que la tasa de acierto medida es representativa del universo completo de preguntas posibles sobre el corpus normativo de ARCSA (que cubre decenas de resoluciones e instructivos). Tres casos concentrados en un solo eje (como en la Sección 4) ya bastan para mover sustancialmente el promedio de ese eje.
- **El juez es un modelo de lenguaje (gpt-5.5), no un experto regulatorio humano**: tanto las métricas RAGAS como los criterios 2 y 5 de Exactitud de Cita dependen de que un LLM juzgue si un fragmento "respalda" una afirmación o si una disposición "aplica" a un caso. El propio archivo `exactitud_cita.json` lo declara explícitamente (`criterio_2_y_5_disclaimer: "evaluacion asistida, no validacion experta"`). Un abogado o especialista en regulación sanitaria podría matizar o revertir algunos veredictos límite, especialmente en el criterio 5 (aplicabilidad), que requiere juicio sobre alcance normativo.
- **Context Precision y Context Recall no están definidos para el eje `fuera_de_cobertura`** (8 de 40 casos, 20% del conjunto): al no existir `contexto_referencia`, esas 2 de las 4 métricas RAGAS simplemente no se calculan para ese 20% del conjunto, por lo que las medias globales de esas dos métricas (0.666 y 0.693) están calculadas sobre un subconjunto de 32 casos, no sobre los 40.
- **El criterio 4 de Exactitud de Cita no mide lo que aparenta medir** (ver Sección 3): su 100% de cumplimiento es una consecuencia matemática de que el corpus solo contiene el valor `vigente=True` (o ausencia del campo, tratada como `True` por defecto en el código), no evidencia de que el sistema verifique correctamente vigencia normativa. Esta es una limitación del método de evaluación (el criterio no puede fallar con los datos actuales) más que del sistema evaluado.
- **Ruido de extracción observable directamente en las trazas**: en varios fragmentos recuperados (visibles en `traces.jsonl`, p. ej. en los casos q010 y q018 documentados en la Sección 5) aparecen bloques de encabezado/pie de página del PDF original (nombre de la agencia, código de documento, versión, número de página, aviso de "copia no controlada") intercalados en medio del texto normativo, cortando oraciones y listas de incisos. Esto es consistente con el riesgo ya documentado en `docs/adr/0003-self-hosted-ocr.md` sobre la fidelidad de la extracción de PDFs escaneados (uso de Tesseract OCR) y con la fragmentación de artículos largos en múltiples partes numeradas (`_PARTE_N_DE_M`, `FRAGMENTO_N_DE_M`), que la Sección 4 identifica como un factor que perjudica la recuperación de las partes específicas donde vive la respuesta correcta.
- **Selección determinista, no aleatoria, de la muestra de Exactitud de Cita**: los 24 casos evaluados para Exactitud de Cita son los primeros 6 IDs de cada eje elegible (documentado en `exactitud_cita.json.resumen.metodologia_muestreo`), no una muestra aleatoria. Esto favorece la reproducibilidad pero introduce el riesgo de que los IDs no seleccionados (los últimos 2 de cada eje: q007-q008, q015-q016, q023-q024, q031-q032) tengan un comportamiento sistemáticamente distinto no capturado en los porcentajes de la Sección 3.

## 7. Consumo aproximado de la evaluación

**Fase 3 (RAGAS)** — datos exactos, capturados por el callback de LangChain (`get_openai_callback`) sobre el modelo juez `gpt-5.5`, reportados en `ragas_resumen.json.costo_fase3`:

| Métrica | Valor |
|---|---|
| Llamadas exitosas al juez LLM | 312 |
| Tokens de prompt | 626,132 |
| Tokens de prompt cacheados | 5,888 |
| Tokens de completion | 150,532 |
| Tokens de razonamiento (reasoning) | 79,208 |
| **Tokens totales** | **776,664** |
| Tiempo transcurrido | 604.5 s (~10.1 min) |

Esta cifra no incluye las llamadas al modelo de embeddings (`text-embedding-3-small`) que usa Answer Relevancy internamente; el propio archivo aclara que ese costo es marginal y que LangChain no lo agrega a este contador.

**Fase 4 (Exactitud de Cita)** — **no se registró telemetría exacta de tokens ni de llamadas** para esta fase; `exactitud_cita.json` no contiene un bloque de costos equivalente al `costo_fase3` de RAGAS. La única cifra disponible es una estimación declarada en el propio texto de metodología del archivo (`resumen.metodologia_muestreo`): el tamaño de la muestra (24 de 32 casos elegibles, 120 fuentes) se fijó explícitamente para "acotar el volumen de llamadas al juez LLM (**~240 llamadas** para 120 fuentes x 2 criterios-LLM)" dentro de un rango manejable. Esta cifra de ~240 es una estimación de diseño documentada en el archivo, no una medición posterior; no se puede reportar un conteo de tokens real para esta fase porque no fue instrumentado.
