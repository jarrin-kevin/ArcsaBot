import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, X, Check } from 'lucide-react';

export const FeedbackModal = ({ isOpen, type, onClose, onSubmit }) => {
  const [reason, setReason] = useState('');
  const [submitted, setSubmitted] = useState(false);

  if (!isOpen) return null;

  const options = [
    'Información desactualizada',
    'No responde la consulta',
    'Faltan fuentes oficiales',
    'Texto confuso o impreciso',
    'Otro'
  ];

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(type, reason);
    setSubmitted(true);
    setTimeout(() => {
      setSubmitted(false);
      setReason('');
      onClose();
    }, 1500);
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-xs">
      <div className="w-full max-w-sm rounded-xl border border-line bg-surface-0 p-5 shadow-sm animate-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between border-b border-line pb-3 mb-4">
          <div className="flex items-center gap-2">
            {type === 'up' ? (
              <ThumbsUp className="h-4 w-4 text-good" />
            ) : (
              <ThumbsDown className="h-4 w-4 text-bad" />
            )}
            <h3 className="text-sm font-semibold text-ink-900">
              {type === 'up' ? '¿Por qué te sirvió?' : '¿Qué podemos mejorar?'}
            </h3>
          </div>
          <button onClick={onClose} className="text-ink-500 hover:text-ink-900 p-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        {submitted ? (
          <div className="py-6 text-center text-sm text-good flex flex-col items-center gap-2">
            <Check className="h-8 w-8 text-good animate-bounce" />
            <span>¡Gracias por ayudarnos a mejorar el asistente!</span>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-ink-700 uppercase tracking-wide">
                Motivo (opcional)
              </label>
              <div className="space-y-1.5">
                {options.map((opt, i) => (
                  <label
                    key={i}
                    className={`flex items-center gap-2 rounded-lg border p-2 text-xs cursor-pointer transition ${
                      reason === opt
                        ? 'border-accent bg-accent/10 text-ink-900'
                        : 'border-line bg-surface-0 text-ink-500 hover:bg-surface-200'
                    }`}
                  >
                    <input
                      type="radio"
                      name="reason"
                      value={opt}
                      checked={reason === opt}
                      onChange={(e) => setReason(e.target.value)}
                      className="hidden"
                    />
                    <span>{opt}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink-700 hover:bg-surface-200"
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="rounded-lg bg-accent px-3.5 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
              >
                Enviar Feedback
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
