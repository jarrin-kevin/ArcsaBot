import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp } from 'lucide-react';

export const MessageInput = ({ onSendMessage, loading, prefilledText, setPrefilledText }) => {
  const [text, setText] = useState('');
  const textareaRef = useRef(null);

  useEffect(() => {
    if (prefilledText) {
      setText(prefilledText);
      textareaRef.current?.focus();
      if (setPrefilledText) setPrefilledText('');
    }
  }, [prefilledText, setPrefilledText]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [text]);

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    if (!text.trim() || loading) return;
    onSendMessage(text);
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="border-t border-line bg-surface-0 px-4 pb-4 pt-3 shrink-0">
      <div className="mx-auto max-w-4xl">
        <form onSubmit={handleSubmit} className="relative">
          <div className="flex items-end gap-2 border border-line bg-surface-0 p-2 focus-within:border-accent transition-colors">
            <textarea
              ref={textareaRef}
              rows={1}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Pregunta lo que no sepas sobre normativas y trámites del ARCSA..."
              disabled={loading}
              className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-3 py-2 text-sm text-ink-900 outline-none placeholder:text-ink-500 disabled:opacity-50"
            />

            <button
              type="submit"
              disabled={!text.trim() || loading}
              aria-label="Enviar consulta"
              className="flex h-9 w-9 shrink-0 items-center justify-center bg-accent text-white transition hover:bg-accent-hover active:scale-95 disabled:cursor-not-allowed disabled:bg-surface-200 disabled:text-ink-500 disabled:scale-100"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          </div>
        </form>

        <p className="mt-2 text-center text-[11px] text-ink-500">
          La información generada por IA puede contener errores. Verifica siempre la normativa y los trámites en fuentes oficiales de ARCSA.
        </p>
      </div>
    </div>
  );
};
