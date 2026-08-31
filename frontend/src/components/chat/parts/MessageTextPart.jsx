import React from 'react';

/**
 * MessageTextPart.jsx
 * Sub-componente especializado para renderizar texto formateado en Markdown.
 */
export const MessageTextPart = ({ text, isError }) => {
  if (!text) return null;

  const parts = text.split(/(\*\*.*?\*\*)/g);
  const formattedContent = parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold text-zinc-100">{part.slice(2, -2)}</strong>;
    }
    return part;
  });

  return (
    <div
      className={`rounded-xl border p-4 text-sm leading-6 ${
        isError
          ? 'border-red-900/60 bg-[#3A1B1B] text-red-200'
          : 'border-[#303136] bg-[#202124]/40 text-zinc-300'
      }`}
    >
      <p className="whitespace-pre-line">{formattedContent}</p>
    </div>
  );
};
