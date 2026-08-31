import React from 'react';

/**
 * MessageReasoningPart.jsx
 * Sub-componente para renderizar bloques de pensamiento/razonamiento interno del modelo.
 */
export const MessageReasoningPart = ({ text }) => {
  if (!text) return null;

  return (
    <div className="rounded-lg border border-indigo-900/40 bg-[#1A1A2E] p-3 text-xs text-indigo-200 leading-5">
      <p className="font-semibold mb-1 text-indigo-400">Pensamiento del modelo:</p>
      <p className="whitespace-pre-line opacity-90">{text}</p>
    </div>
  );
};
