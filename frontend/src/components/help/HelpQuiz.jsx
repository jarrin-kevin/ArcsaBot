import React, { useState } from 'react';
import { HelpCircle, ArrowLeft, KeyRound, ShieldAlert, Cpu, Sparkles, BookOpen } from 'lucide-react';

export const HelpQuiz = ({ onBackToChat }) => {
  const [openIndex, setOpenIndex] = useState(null);

  const faqs = [
    {
      id: 1,
      icon: <Sparkles className="h-4 w-4 text-[#2F6FED]" />,
      question: '¿Qué es el Asistente Virtual ARCSA?',
      answer: 'Es una herramienta de asistencia conversacional inteligente diseñada para facilitar la búsqueda y comprensión de la normativa sanitaria, trámites, permisos de funcionamiento y registros de la Agencia Nacional de Regulación, Control y Vigilancia Sanitaria (ARCSA) de Ecuador.'
    },
    {
      id: 2,
      icon: <Cpu className="h-4 w-4 text-[#2F6FED]" />,
      question: '¿Cómo funciona la tecnología RAG (Generación Aumentada)?',
      answer: 'Cuando realizas una consulta, el sistema busca fragmentos de información relevantes directamente en nuestra base de datos de reglamentos y resoluciones oficiales de ARCSA (Fase de Recuperación). Luego, le entrega estos textos a la Inteligencia Artificial para redactar una respuesta precisa basada únicamente en evidencia documental verificada.'
    },
    {
      id: 3,
      icon: <KeyRound className="h-4 w-4 text-amber-400" />,
      question: '¿Cómo conecto mi API Key y qué tan segura está?',
      answer: 'Ve a la sección de "Configuración" desde el menú lateral e ingresa la API Key de tu proveedor preferido (como OpenRouter). Por motivos de seguridad y confidencialidad, tu clave se almacena de forma efímera en la memoria activa del navegador (React State). Esto significa que nunca se envía a servidores externos y se borrará automáticamente al cerrar la pestaña o sesión.'
    },
    {
      id: 4,
      icon: <BookOpen className="h-4 w-4 text-[#2F6FED]" />,
      question: '¿Cómo obtengo una API Key de OpenRouter?',
      answer: 'Para obtener tu clave de acceso:\n1. Regístrate en https://openrouter.ai/\n2. Ve a la sección "Keys" (Claves) en tu perfil.\n3. Presiona "+ Create Key", asígnale un nombre y copia la clave generada (empieza por "sk-or-...").\n4. Asegúrate de contar con créditos activos en tu cuenta de OpenRouter para poder realizar consultas.'
    },
    {
      id: 5,
      icon: <ShieldAlert className="h-4 w-4 text-[#2F6FED]" />,
      question: '¿Qué significa el estado "Sin evidencia suficiente"?',
      answer: 'Indica que el algoritmo RAG no encontró un nivel de coincidencia documental confiable en la normativa para responder a tu pregunta. En estos casos, te sugerimos reformular la consulta especificando el tipo de producto (alimentos, cosméticos, dispositivos médicos, etc.) o utilizar los enlaces directos a los portales oficiales de ARCSA.'
    }
  ];

  const toggleFaq = (index) => {
    setOpenIndex(openIndex === index ? null : index);
  };

  return (
    <section className="mx-auto w-full max-w-2xl px-6 py-10 overflow-y-auto flex-1 font-sans text-zinc-100">
      
      <button
        onClick={onBackToChat}
        className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-100 mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        <span>Volver al Chat</span>
      </button>

      <header className="mb-8 border-b border-[#303136] pb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100 flex items-center gap-2">
            <HelpCircle className="h-6 w-6 text-[#2F6FED]" />
            <span>Centro de Ayuda y FAQ</span>
          </h1>
          <p className="mt-2 text-xs text-zinc-400">
            Preguntas frecuentes sobre el funcionamiento del aplicativo, uso de API Keys, seguridad y la tecnología de búsqueda del asistente.
          </p>
        </div>
      </header>

      {/* Lista de Preguntas Frecuentes */}
      <div className="space-y-3.5">
        {faqs.map((faq, index) => {
          const isOpen = openIndex === index;
          return (
            <div
              key={faq.id}
              className="rounded-xl border border-[#303136] bg-[#202124] overflow-hidden transition duration-150"
            >
              <button
                onClick={() => toggleFaq(index)}
                className="w-full flex items-center justify-between p-4 text-left focus:outline-none"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#1E3A6D]/40 text-[#2F6FED]">
                    {faq.icon}
                  </div>
                  <span className="font-semibold text-xs leading-5 text-zinc-100 md:text-sm">
                    {faq.question}
                  </span>
                </div>
                <span className="text-zinc-400 ml-4 font-bold text-lg select-none">
                  {isOpen ? '−' : '+'}
                </span>
              </button>

              {isOpen && (
                <div className="px-4 pb-4 pt-1 text-xs leading-6 text-zinc-300 border-t border-[#303136]/50 whitespace-pre-line">
                  {faq.answer}
                </div>
              )}
            </div>
          );
        })}
      </div>

    </section>
  );
};
