import React from 'react';
import { X, FileText, ExternalLink, ShieldCheck, Calendar, Building2 } from 'lucide-react';

export const RagSourcesDrawer = ({ sources, onClose }) => {
  if (!sources) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-xs">
      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-md border-l border-[#303136] bg-[#17181B] shadow-2xl flex flex-col animate-in slide-in-from-right duration-200">
          
          {/* Header del Panel */}
          <div className="flex items-center justify-between border-b border-[#303136] px-5 py-4">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#1E3A6D]/50 text-[#2F6FED]">
                <ShieldCheck className="h-4 w-4" />
              </div>
              <h2 className="text-base font-semibold text-zinc-100">Fuentes Consultadas</h2>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-[#2A2C31] hover:text-zinc-100 transition-colors"
              aria-label="Cerrar fuentes"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Lista de Fuentes */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {sources.length === 0 ? (
              <div className="py-12 text-center text-sm text-zinc-500">
                No hay fuentes documentales asociadas a esta respuesta.
              </div>
            ) : (
              sources.map((src, index) => (
                <article
                  key={src.id || index}
                  className="rounded-xl border border-[#303136] bg-[#202124] p-4 text-xs leading-5 space-y-3 transition hover:border-[#2F6FED]/50"
                >
                  <div className="flex items-start gap-2 text-zinc-100">
                    <FileText className="h-4 w-4 shrink-0 text-[#2F6FED] mt-0.5" />
                    <h3 className="font-semibold text-sm leading-5">{src.documentTitle}</h3>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-zinc-400 text-[11px] border-y border-[#303136]/60 py-2">
                    <div className="flex items-center gap-1.5">
                      <Building2 className="h-3.5 w-3.5 text-zinc-500" />
                      <span className="truncate">{src.issuingEntity}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Calendar className="h-3.5 w-3.5 text-zinc-500" />
                      <span className="truncate">{src.validityDate}</span>
                    </div>
                  </div>

                  {src.section && (
                    <p className="text-zinc-400">
                      <strong className="text-zinc-300">Ubicación:</strong> {src.section}
                    </p>
                  )}

                  {src.snippet && (
                    <blockquote className="rounded-lg bg-[#1C1D20] p-2.5 text-zinc-300 italic border-l-2 border-[#2F6FED]">
                      "{src.snippet}"
                    </blockquote>
                  )}

                  {src.officialUrl && (
                    <a
                      href={src.officialUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 text-[#2F6FED] hover:underline font-medium pt-1"
                    >
                      <span>Ver fuente oficial en ARCSA</span>
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </article>
              ))
            )}
          </div>

          {/* Footer del Panel */}
          <div className="border-t border-[#303136] bg-[#121314] px-5 py-3 text-center text-xs text-zinc-500">
            Normativa y gacetas oficiales verificadas por ARCSA.
          </div>
        </div>
      </div>
    </div>
  );
};
