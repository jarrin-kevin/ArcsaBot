import React from 'react';
import { X, ExternalLink, ShieldCheck, Calendar, Building2, MapPin, Quote } from 'lucide-react';

export const RagSourcesDrawer = ({ sources, onClose }) => {
  if (!sources) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-ink-900/50 backdrop-blur-xs">
      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-xl border-l border-line bg-surface-0 shadow-2xl flex flex-col animate-in slide-in-from-right duration-200">

          {/* Header del Panel */}
          <div className="flex items-start justify-between gap-4 border-b border-line bg-surface-0 px-6 py-5 shrink-0">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center bg-ink-900 text-accent">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold font-display text-ink-900">Fuentes Consultadas</h2>
                <p className="mt-0.5 text-xs text-ink-500">
                  {sources.length > 0
                    ? `${sources.length} ${sources.length === 1 ? 'documento oficial verificado' : 'documentos oficiales verificados'}`
                    : 'Verificación documental ARCSA'}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="shrink-0 p-1.5 text-ink-500 hover:bg-surface-100 hover:text-ink-900 transition-colors"
              aria-label="Cerrar fuentes"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Lista de Fuentes */}
          <div className="flex-1 overflow-y-auto p-6 space-y-5">
            {sources.length === 0 ? (
              <div className="py-12 text-center text-sm text-ink-500">
                No hay fuentes documentales asociadas a esta respuesta.
              </div>
            ) : (
              sources.map((src, index) => (
                <article
                  key={src.id || index}
                  className="border border-line bg-surface-0 shadow-sm text-xs leading-5 transition hover:border-accent/50 overflow-hidden"
                >
                  {/* Encabezado numerado de la fuente */}
                  <div className="flex items-start gap-3 px-5 pt-4">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink-900 text-surface-0 text-xs font-bold">
                      {index + 1}
                    </div>
                    <div className="min-w-0">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-accent mb-0.5">
                        Fuente {index + 1}
                      </p>
                      <h3 className="font-display font-bold text-sm leading-5 text-ink-900 break-words">
                        {src.documentTitle}
                      </h3>
                      <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-good/15 text-good mt-1.5">
                        Vigencia no verificada
                      </span>
                    </div>
                  </div>

                  {/* Metadatos: entidad y vigencia (sin truncar) */}
                  <div className="mx-5 mt-3 space-y-2 bg-surface-100 border border-line/70 px-3.5 py-3 text-[11px] text-ink-500">
                    <div className="flex items-start gap-2">
                      <Building2 className="h-3.5 w-3.5 text-ink-500 mt-0.5 shrink-0" />
                      <span className="break-words">{src.issuingEntity}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Calendar className="h-3.5 w-3.5 text-ink-500 shrink-0" />
                      <span className="break-words">{src.validityStatus}</span>
                    </div>
                    {src.section && (
                      <div className="flex items-start gap-2 pt-1.5 border-t border-line/70">
                        <MapPin className="h-3.5 w-3.5 text-ink-500 mt-0.5 shrink-0" />
                        <span className="break-words">
                          <strong className="text-ink-700 font-semibold">Ubicación:</strong> {src.section}
                        </span>
                      </div>
                    )}
                  </div>

                  {src.snippet && (
                    <blockquote className="mx-5 mt-3 flex gap-2 bg-surface-100 p-3 text-ink-700 italic border-l-2 border-accent">
                      <Quote className="h-3.5 w-3.5 shrink-0 text-accent/60 mt-0.5" />
                      <span>{src.snippet}</span>
                    </blockquote>
                  )}

                  {src.officialUrl && (
                    <div className="px-5 pb-4 pt-3">
                      <a
                        href={src.officialUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 text-accent hover:underline font-medium"
                      >
                        <span>Ver fuente oficial en ARCSA</span>
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    </div>
                  )}
                </article>
              ))
            )}
          </div>

          {/* Footer del Panel */}
          <div className="border-t border-line bg-surface-100 px-5 py-3 text-center text-xs text-ink-500 shrink-0">
            Normativa y gacetas oficiales verificadas por ARCSA.
          </div>
        </div>
      </div>
    </div>
  );
};
