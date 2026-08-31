# ARCSA RAG Chatbot

A chatbot that answers questions about ARCSA (Ecuador's health regulatory agency) rules and procedures, grounded in official regulations, reforms, fee schedules, and practical trámite guides.

## Language

### Fuentes y Vigencia

**Normativa Vigente**:
An ARCSA regulation currently in legal effect — the authoritative source for legal facts (requirements, deadlines, fees).
_Avoid_: ley, regla, documento oficial

**Reforma**:
An amendment to a Normativa Vigente. Published irregularly — typically once a year, occasionally immediately.

**Corpus Documental**:
The yearly reference document that consolidates ARCSA's regulations and reforms for a given year. The system's manually-maintained source of truth for what is currently vigente.

**Tutorial**:
A natural-language guide describing how to complete a Trámite. Sourced separately from Normativa Vigente and may cite a Normativa that has since been derogated.
_Avoid_: guía, instructivo (Instructivo is an ARCSA-published document type, distinct from a Tutorial)

**Trámite**:
A regulated procedure a client must complete with ARCSA (e.g. registering a product, paying a fee).

**Vigente / Derogado**:
The status of a piece of Normativa, or of a Tutorial's citation to one — currently in force vs. superseded/repealed.

**Cita Desactualizada**:
A Tutorial's reference to a Normativa that has since been derogated. Flagged rather than removed, so the Tutorial's still-useful procedural steps remain available with a warning instead of disappearing.

### Estructura Normativa

**Artículo**:
The primary legal subdivision of a Normativa. Contains Numerales and Literales; may reference Tablas and Anexos.

**Numeral / Literal**:
Sub-subdivisions of an Artículo. An obligation and its exceptions must stay within the same Artículo's boundaries — never split across a chunk boundary.

### Consultas

**Consulta Multi-paso**:
A user question that can't be answered from a single Artículo and requires assembling information from several linked sources — e.g. a Trámite's form, fee, and deadline may each live in a different Normativa.
