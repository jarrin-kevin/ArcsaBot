import React from 'react';
import { ShieldAlert, Search, ExternalLink } from 'lucide-react';

/**
 * LowConfidenceBanner.jsx
 * Sub-componente para renderizar la advertencia cuando el RAG no encuentra evidencia en ARCSA.
 */
export const LowConfidenceBanner = ({ officialUrl, userPreviousQuery, onRephraseQuery }) => {
  return (
    <div className="rounded-xl border border-amber-800/60 bg-[#3A2B16] p-4 text-xs leading-6 space-y-3">
      <div className="flex items-start gap-2.5 text-amber-200">
        <ShieldAlert className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <h4 className="font-bold text-sm">Sin evidencia suficiente en normativa ARCSA</h4>
          <p className="text-amber-100/90 mt-1">
            No se encontraron resoluciones ni documentos oficiales verificados en la base RAG para responder a esta consulta con absoluta precisión.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 pt-2 border-t border-[#785316]/50">
        <button
          onClick={() => onRephraseQuery && onRephraseQuery(userPreviousQuery)}
          className="flex items-center gap-1.5 rounded-lg bg-[#2F6FED] px-3 py-1.5 font-semibold text-white hover:bg-[#255CC7] transition"
        >
          <Search className="h-3.5 w-3.5" />
          <span>Reformular consulta</span>
        </button>

        <a
          href={officialUrl || "https://www.controlsanitario.gob.ec/"}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 rounded-lg border border-[#785316] bg-[#202124] px-3 py-1.5 font-medium text-amber-200 hover:bg-[#2A2C31] transition"
        >
          <span>Ver fuentes oficiales ARCSA</span>
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  );
};
