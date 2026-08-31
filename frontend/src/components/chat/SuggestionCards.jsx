import React from 'react';
import { Zap } from 'lucide-react';

export const SuggestionCards = ({ onSelectSuggestion }) => {
  const suggestions = [
    {
      id: 'meds',
      title: 'Medicamentos libre venta',
      description: '¿Qué medicamentos son de libre venta en Ecuador?',
      prompt: '¿Qué medicamentos son de libre venta en Ecuador?'
    },
    {
      id: 'permisos',
      title: 'Permiso de Funcionamiento',
      description: '¿Cómo obtengo el Permiso de Funcionamiento para mi establecimiento?',
      prompt: '¿Cómo obtengo el Permiso de Funcionamiento para mi establecimiento?'
    },
    {
      id: 'alimentos',
      title: 'Registro de Alimentos',
      description: '¿Cuáles son los requisitos para el Registro Sanitario de alimentos?',
      prompt: '¿Cuáles son los requisitos actuales para obtener el Registro Sanitario de alimentos?'
    },
    {
      id: 'alertas',
      title: 'Alertas Sanitarias',
      description: 'Consultar alertas sanitarias o productos falsificados recientes.',
      prompt: '¿Cuáles son las últimas alertas sanitarias o productos falsificados reportados por ARCSA?'
    }
  ];

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-8 md:px-6">
      {/* Header institucional */}
      <div className="mb-8 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[#1E3A6D]/40 text-[#2F6FED] border border-[#2F6FED]/30 shadow-inner">
          <Zap className="h-7 w-7" />
        </div>
        <h1 className="text-2xl font-bold text-zinc-100 tracking-tight">Arcsa</h1>
        <p className="text-sm text-zinc-500 mt-1">Asistente virtual de consultas y normativas</p>
      </div>

      {/* Grid de sugerencias */}
      <div className="grid gap-3.5 md:grid-cols-2">
        {suggestions.map((card) => (
          <button
            key={card.id}
            onClick={() => onSelectSuggestion(card.prompt)}
            className="group rounded-xl border border-[#303136] bg-[#202124] p-4 text-left transition duration-200 hover:border-[#2F6FED] hover:bg-[#2A2C31] focus:outline-none focus:ring-1 focus:ring-[#2F6FED]"
          >
            <h3 className="mb-1 text-sm font-semibold text-zinc-100 group-hover:text-[#2F6FED] transition-colors">
              {card.title}
            </h3>
            <p className="text-xs leading-5 text-zinc-400">
              {card.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
};
