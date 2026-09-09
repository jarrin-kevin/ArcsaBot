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
        className="w-full max-w-md rounded-xl border border-line bg-surface-0 p-6 shadow-sm animate-in fade-in zoom-in duration-150"
      >
        <h2 id="delete-dialog-title" className="text-lg font-semibold font-display text-ink-900">
          ¿Eliminar consulta?
        </h2>

        <p className="mt-2 text-sm leading-6 text-ink-500">
          ¿Estás seguro de eliminar esta consulta? Esta acción no se puede deshacer.
        </p>

        <div className="mt-6 flex justify-end gap-3">
          <button
            ref={cancelButtonRef}
            onClick={onCancel}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink-700 hover:bg-surface-200 focus:outline-none focus:ring-1 focus:ring-accent"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            className="rounded-lg bg-bad px-4 py-2 text-sm font-medium text-white hover:bg-bad/90 focus:outline-none focus:ring-1 focus:ring-bad"
          >
            Eliminar
          </button>
        </div>
      </div>
    </div>
  );
};
