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
      <div className="w-full max-w-sm rounded-xl border border-[#303136] bg-[#202124] p-5 shadow-2xl animate-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between border-b border-[#303136] pb-3 mb-4">
          <div className="flex items-center gap-2">
            {type === 'up' ? (
              <ThumbsUp className="h-4 w-4 text-green-500" />
            ) : (
              <ThumbsDown className="h-4 w-4 text-red-400" />
            )}
            <h3 className="text-sm font-semibold text-zinc-100">
              {type === 'up' ? '¿Por qué te sirvió?' : '¿Qué podemos mejorar?'}
            </h3>
          </div>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100 p-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        {submitted ? (
          <div className="py-6 text-center text-sm text-green-400 flex flex-col items-center gap-2">
            <Check className="h-8 w-8 text-green-500 animate-bounce" />
            <span>¡Gracias por ayudarnos a mejorar el asistente!</span>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">
                Motivo (opcional)
              </label>
              <div className="space-y-1.5">
                {options.map((opt, i) => (
                  <label
                    key={i}
                    className={`flex items-center gap-2 rounded-lg border p-2 text-xs cursor-pointer transition ${
                      reason === opt
                        ? 'border-[#2F6FED] bg-[#1E3A6D]/30 text-zinc-100'
                        : 'border-[#303136] bg-[#1C1D20] text-zinc-400 hover:bg-[#2A2C31]'
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
                className="rounded-lg border border-[#303136] px-3 py-1.5 text-xs text-zinc-300 hover:bg-[#2A2C31]"
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="rounded-lg bg-[#2F6FED] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#255CC7]"
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
