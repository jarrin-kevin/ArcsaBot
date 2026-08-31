import React, { useEffect, useRef } from 'react';

export const DeleteConfirmModal = ({ isOpen, onCancel, onConfirm }) => {
  const cancelButtonRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      cancelButtonRef.current?.focus();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      onCancel();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-xs transition-opacity"
      onKeyDown={handleKeyDown}
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-dialog-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl border border-[#303136] bg-[#202124] p-6 shadow-2xl animate-in fade-in zoom-in duration-150"
      >
        <h2 id="delete-dialog-title" className="text-lg font-semibold text-zinc-100">
          ¿Eliminar consulta?
        </h2>

        <p className="mt-2 text-sm leading-6 text-zinc-400">
          ¿Estás seguro de eliminar esta consulta? Esta acción no se puede deshacer.
        </p>

        <div className="mt-6 flex justify-end gap-3">
          <button
            ref={cancelButtonRef}
            onClick={onCancel}
            className="rounded-lg border border-[#303136] px-4 py-2 text-sm font-medium text-zinc-200 hover:bg-[#2A2C31] focus:outline-none focus:ring-1 focus:ring-[#2F6FED]"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            className="rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white hover:bg-red-600 focus:outline-none focus:ring-1 focus:ring-red-400"
          >
            Eliminar
          </button>
        </div>
      </div>
    </div>
  );
};
