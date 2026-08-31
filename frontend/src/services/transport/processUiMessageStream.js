import { createTextPart, createSourcesPart, createReasoningPart } from './uiMessages';

/**
 * processUiMessageStream.js
 * Procesa atómicamente la respuesta y actualiza las partes del mensaje del asistente.
 */
export function processUiMessageStream(assistantMessage, responseData) {
  const updatedParts = [];

  if (responseData.text) {
    updatedParts.push(createTextPart(responseData.text));
  }

  if (responseData.reasoning) {
    updatedParts.push(createReasoningPart(responseData.reasoning));
  }

  if (responseData.sources && responseData.sources.length > 0) {
    updatedParts.push(createSourcesPart(responseData.sources));
  }

  return {
    ...assistantMessage,
    status: 'sent',
    parts: updatedParts,
    metadata: {
      ...assistantMessage.metadata,
      isLowConfidence: responseData.isLowConfidence || false,
      officialUrl: responseData.officialUrl || null
    }
  };
}
