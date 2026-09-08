import React from 'react';

/**
 * MessageTextPart.jsx
 * Sub-componente especializado para renderizar texto formateado en Markdown ligero.
 * Soporta: **negrita**, listas con "- "/"* " y listas ordenadas tipo "a." / "1.",
 * preservando saltos de línea para el resto del contenido.
 */

// Convierte segmentos "**negrita**" dentro de una línea de texto en nodos React.
const renderInlineFormatting = (line, keyPrefix) => {
  const parts = line.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={`${keyPrefix}-${i}`} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <React.Fragment key={`${keyPrefix}-${i}`}>{part}</React.Fragment>;
  });
};

const BULLET_RE = /^[*-]\s+(.*)/;
const LETTERED_RE = /^([a-zA-Z])[.)]\s+(.*)/;
const NUMBERED_RE = /^(\d+)[.)]\s+(.*)/;

export const MessageTextPart = ({ text, isError, bare }) => {
  if (!text) return null;

  const lines = text.split('\n');

  // Agrupa líneas consecutivas del mismo tipo (viñeta) en un solo <ul>.
  const blocks = [];
  let currentList = null;

  lines.forEach((rawLine, idx) => {
    const bulletMatch = rawLine.match(BULLET_RE);
    const letteredMatch = rawLine.match(LETTERED_RE);
    const numberedMatch = rawLine.match(NUMBERED_RE);

    if (bulletMatch) {
      if (!currentList || currentList.type !== 'bullet') {
        currentList = { type: 'bullet', items: [] };
        blocks.push(currentList);
      }
      currentList.items.push({ key: idx, marker: null, content: bulletMatch[1] });
    } else if (letteredMatch) {
      if (!currentList || currentList.type !== 'lettered') {
        currentList = { type: 'lettered', items: [] };
        blocks.push(currentList);
      }
      currentList.items.push({ key: idx, marker: `${letteredMatch[1]}.`, content: letteredMatch[2] });
    } else if (numberedMatch) {
      if (!currentList || currentList.type !== 'numbered') {
        currentList = { type: 'numbered', items: [] };
        blocks.push(currentList);
      }
      currentList.items.push({ key: idx, marker: `${numberedMatch[1]}.`, content: numberedMatch[2] });
    } else {
      currentList = null;
      if (rawLine.trim() === '') {
        blocks.push({ type: 'spacer', key: idx });
      } else {
        blocks.push({ type: 'text', key: idx, content: rawLine });
      }
    }
  });

  const content = (
    <>
      {blocks.map((block, blockIdx) => {
        if (block.type === 'spacer') return null;

        if (block.type === 'text') {
          return (
            <p key={blockIdx} className="whitespace-pre-line">
              {renderInlineFormatting(block.content, `t-${blockIdx}`)}
            </p>
          );
        }

        if (block.type === 'bullet') {
          return (
            <ul key={blockIdx} className="space-y-1.5 pl-1">
              {block.items.map((item) => (
                <li key={item.key} className="flex gap-2.5 pl-1">
                  <span className={`mt-2 h-1 w-1 shrink-0 rounded-full ${isError ? 'bg-bad' : 'bg-ink-700'}`} />
                  <span>{renderInlineFormatting(item.content, `b-${item.key}`)}</span>
                </li>
              ))}
            </ul>
          );
        }

        // 'lettered' y 'numbered' comparten el mismo layout de lista ordenada
        return (
          <ul key={blockIdx} className="space-y-1.5">
            {block.items.map((item) => (
              <li key={item.key} className="flex gap-2.5">
                <span className={`shrink-0 font-semibold ${isError ? 'text-bad' : 'text-ink-700'}`}>
                  {item.marker}
                </span>
                <span>{renderInlineFormatting(item.content, `l-${item.key}`)}</span>
              </li>
            ))}
          </ul>
        );
      })}
    </>
  );

  if (bare) {
    return <div className="space-y-2.5 text-sm leading-6">{content}</div>;
  }

  return (
    <div
      className={`border p-4 text-sm leading-6 space-y-2.5 ${
        isError
          ? 'border-bad/40 bg-bad/10 text-bad'
          : 'border-line bg-surface-100 text-ink-900 shadow-sm'
      }`}
    >
      {content}
    </div>
  );
};
