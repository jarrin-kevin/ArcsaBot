import React, { useState, useEffect } from 'react';
import { X, Edit3 } from 'lucide-react';

export const RenameModal = ({ isOpen, currentTitle, onClose, onSave }) => {
  const [title, setTitle] = useState(currentTitle || '');

  useEffect(() => {
    setTitle(currentTitle || '');
  }, [currentTitle]);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (title.trim()) {
      onSave(title.trim());
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-xs">
      <div className="w-full max-w-sm rounded-xl border border-line bg-surface-0 p-5 shadow-sm animate-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between border-b border-line pb-3 mb-4">
          <div className="flex items-center gap-2">
            <Edit3 className="h-4 w-4 text-accent" />
            <h3 className="text-sm font-semibold text-ink-900">Renombrar Consulta</h3>
          </div>
          <button onClick={onClose} className="text-ink-500 hover:text-ink-900 p-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-ink-700 mb-1.5">
              Título de la consulta
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ej. Registro de suplementos 2024"
              className="w-full rounded-lg border border-line bg-surface-0 px-3 py-2 text-sm text-ink-900 placeholder-ink-500 outline-none focus:border-accent"
              autoFocus
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-line px-3.5 py-2 text-xs font-medium text-ink-700 hover:bg-surface-200"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={!title.trim()}
              className="rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            >
              Guardar Título
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
