import React from 'react';
import { ShieldCheck, Pill, Building2, ClipboardList, AlertTriangle, ArrowRight } from 'lucide-react';

export const SuggestionCards = ({ onSelectSuggestion }) => {
  const suggestions = [
    {
      id: 'meds',
      icon: Pill,
      title: 'Medicamentos libre venta',
      description: '¿Qué medicamentos son de libre venta en Ecuador?',
      prompt: '¿Qué medicamentos son de libre venta en Ecuador?'
    },
    {
      id: 'permisos',
      icon: Building2,
      title: 'Permiso de Funcionamiento',
      description: '¿Cómo obtengo el Permiso de Funcionamiento para mi establecimiento?',
      prompt: '¿Cómo obtengo el Permiso de Funcionamiento para mi establecimiento?'
    },
    {
      id: 'alimentos',
      icon: ClipboardList,
      title: 'Registro de Alimentos',
      description: '¿Cuáles son los requisitos para el Registro Sanitario de alimentos?',
      prompt: '¿Cuáles son los requisitos actuales para obtener el Registro Sanitario de alimentos?'
    },
    {
      id: 'alertas',
      icon: AlertTriangle,
      title: 'Alertas Sanitarias',
      description: 'Consultar alertas sanitarias o productos falsificados recientes.',
      prompt: '¿Cuáles son las últimas alertas sanitarias o productos falsificados reportados por ARCSA?'
    }
  ];

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-8 md:px-6">
      {/* Header institucional */}
      <div className="mb-9 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center bg-ink-900 text-accent shadow-sm">
          <ShieldCheck className="h-7 w-7" />
        </div>
        <h1 className="text-2xl font-bold font-display text-ink-900 tracking-tight">Asistente Virtual ARCSA</h1>
        <p className="text-sm text-ink-500 mt-1.5">
          Consultas de trámites, normativas y registros sanitarios respaldadas por documentación oficial.
        </p>
      </div>

      {/* Grid de sugerencias */}
      <div className="grid gap-3.5 md:grid-cols-2">
        {suggestions.map((card) => {
          const Icon = card.icon;
          return (
            <button
              key={card.id}
              onClick={() => onSelectSuggestion(card.prompt)}
              className="group flex items-start gap-3.5 border border-line bg-surface-0 p-4 text-left transition duration-200 hover:border-accent hover:bg-surface-100 focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center bg-ink-900/10 text-ink-900 border border-ink-900/20 group-hover:bg-ink-900/20 transition-colors">
                <Icon className="h-4.5 w-4.5" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="mb-1 text-sm font-semibold font-display text-ink-900 group-hover:text-accent transition-colors">
                  {card.title}
                </h3>
                <p className="text-xs leading-5 text-ink-500">
                  {card.description}
                </p>
              </div>
              <ArrowRight className="h-4 w-4 shrink-0 text-ink-500 mt-1 opacity-0 -translate-x-1 transition-all group-hover:opacity-100 group-hover:translate-x-0 group-hover:text-accent" />
            </button>
          );
        })}
      </div>
    </div>
  );
};
