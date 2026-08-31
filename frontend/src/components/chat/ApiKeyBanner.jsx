import React from 'react';
import { KeyRound } from 'lucide-react';

export const ApiKeyBanner = ({ onGoToSettings }) => {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#785316] bg-[#3A2B16] px-5 py-3 shrink-0 shadow-md">
      <div className="flex items-center gap-3 text-amber-100 min-w-0">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30">
          <KeyRound className="h-4 w-4" />
        </div>
        <div className="text-xs">
          <p className="font-bold text-amber-200">Configura tu conexión para comenzar</p>
          <p className="text-amber-100/80">
            Ingresa la API Key de tu proveedor LLM en Configuración para activar las respuestas del asistente.
          </p>
        </div>
      </div>

      <button
        onClick={onGoToSettings}
        className="rounded-lg bg-[#2F6FED] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#255CC7] shrink-0 shadow-sm"
      >
        Configurar API Key
      </button>
    </div>
  );
};
