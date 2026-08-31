/**
 * uiMessages.js
 * Modelado de datos e helpers para mensajes estructurados por partes.
 * Inspirado en el diseño de partes de Vercel AI SDK.
 */

/**
 * Crea un objeto de mensaje normalizado estructurado por partes.
 */
export function createUIMessage({
  id = Date.now().toString(),
  role = 'user',
  parts = [],
  status = 'sent',
  metadata = {},
  timestamp = new Date().toISOString()
}) {
  return {
    id,
    role,
    status, // 'sending' | 'sent' | 'error'
    parts,
    metadata,
    timestamp
  };
}

/**
 * Helper para crear una parte de texto.
 */
export function createTextPart(text = '') {
  return {
    type: 'text',
    text
  };
}

/**
 * Helper para crear una parte de fuentes RAG.
 */
export function createSourcesPart(sources = []) {
  return {
    type: 'sources',
    sources
  };
}

/**
 * Helper para crear una parte de razonamiento (pensamiento del modelo).
 */
export function createReasoningPart(text = '') {
  return {
    type: 'reasoning',
    text
  };
}

/**
 * Normaliza un objeto de respuesta de API para convertirlo en partes de UI.
 */
export function responseToUIMessageParts(response) {
  const parts = [];

  if (response.text) {
    parts.push(createTextPart(response.text));
  }

  if (response.sources && response.sources.length > 0) {
    parts.push(createSourcesPart(response.sources));
  }

  return parts;
}
