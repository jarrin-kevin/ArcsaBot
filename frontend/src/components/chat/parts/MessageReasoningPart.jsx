import React from 'react';

/**
 * MessageReasoningPart.jsx
 * Sub-componente para renderizar bloques de pensamiento/razonamiento interno del modelo.
 */
export const MessageReasoningPart = ({ text }) => {
  if (!text) return null;

  return (
    <div className="border border-line bg-surface-200 p-3 text-xs text-ink-700 leading-5">
      <p className="font-semibold mb-1 text-ink-500">Pensamiento del modelo:</p>
      <p className="whitespace-pre-line opacity-90">{text}</p>
    </div>
  );
};
