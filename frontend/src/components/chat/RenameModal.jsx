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
      <div className="w-full max-w-sm rounded-xl border border-[#303136] bg-[#202124] p-5 shadow-2xl animate-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between border-b border-[#303136] pb-3 mb-4">
          <div className="flex items-center gap-2">
            <Edit3 className="h-4 w-4 text-[#2F6FED]" />
            <h3 className="text-sm font-semibold text-zinc-100">Renombrar Consulta</h3>
          </div>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100 p-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-zinc-400 mb-1.5">
              Título de la consulta
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ej. Registro de suplementos 2024"
              className="w-full rounded-lg border border-[#303136] bg-[#1C1D20] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-[#2F6FED]"
              autoFocus
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#303136] px-3.5 py-2 text-xs font-medium text-zinc-300 hover:bg-[#2A2C31]"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={!title.trim()}
              className="rounded-lg bg-[#2F6FED] px-4 py-2 text-xs font-semibold text-white hover:bg-[#255CC7] disabled:opacity-50"
            >
              Guardar Título
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
