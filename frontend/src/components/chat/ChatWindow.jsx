import React, { useEffect, useRef, useState } from 'react';
import { Zap, Loader2, Copy, Check, FileText, RotateCcw, ThumbsUp, ThumbsDown, Square } from 'lucide-react';
import { SuggestionCards } from './SuggestionCards';
import { MessageTextPart } from './parts/MessageTextPart';
import { MessageReasoningPart } from './parts/MessageReasoningPart';
import { LowConfidenceBanner } from './parts/LowConfidenceBanner';

export const ChatWindow = ({
  messages,
  loading,
  onSendMessage,
  onStopResponse,
  onOpenSources,
  onOpenFeedback,
  onRephraseQuery
}) => {
  const bottomRef = useRef(null);
  const [copiedId, setCopiedId] = useState(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleCopy = (id, text) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const defaultFollowUpChips = [
    { label: 'Tasas de registro', query: '¿Cuáles son las tasas de registro vigentes en ARCSA?' },
    { label: 'Permisos de funcionamiento', query: '¿Qué requisitos necesito para renovar el permiso de funcionamiento?' },
    { label: 'Vigilancia y control', query: '¿Cómo funciona el proceso de vigilancia y control posterior del ARCSA?' },
    { label: 'Normativa técnica', query: '¿Dónde puedo consultar la normativa técnica ecuatoriana sobre alimentos y medicamentos?' }
  ];

  if (!messages || messages.length === 0) {
    return <SuggestionCards onSelectSuggestion={onSendMessage} />;
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 space-y-6 bg-[#121314] font-sans">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        {messages.map((message, index) => {
          const isBot = message.role === 'assistant';
          const isLastMessage = index === messages.length - 1;
          const isSending = message.status === 'sending';
          const isError = message.status === 'error' || message.isError;
          const isLowConfidence = message.metadata?.isLowConfidence || message.isLowConfidence;

          let messageText = message.content || '';
          let sourcesList = message.sources || [];
          let reasoningText = '';

          if (message.parts && message.parts.length > 0) {
            message.parts.forEach(part => {
              if (part.type === 'text') messageText += (messageText ? '\n' : '') + part.text;
              if (part.type === 'reasoning') reasoningText += (reasoningText ? '\n' : '') + part.text;
              if (part.type === 'sources' && part.sources) sourcesList = part.sources;
            });
          }

          const chipsToDisplay = (message.relatedQueries && message.relatedQueries.length > 0)
            ? message.relatedQueries
            : defaultFollowUpChips;

          const previousUserMessage = messages[index - 1];
          const userPreviousQuery = previousUserMessage
            ? (previousUserMessage.content || (previousUserMessage.parts && previousUserMessage.parts[0]?.text) || '')
            : '';

          if (isBot) {
            return (
              <article
                key={message.id || index}
                className={`max-w-3xl space-y-3 animate-in fade-in duration-150 ${
                  isSending ? 'opacity-70' : 'opacity-100'
                }`}
              >
                {/* Header Asistente ARCSA */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#1E3A6D]/50 text-[#2F6FED] border border-[#2F6FED]/30">
                      <Zap className="h-3.5 w-3.5" />
                    </div>
                    <span className="text-xs font-semibold text-zinc-200">Asistente ARCSA</span>
                    {isSending && (
                      <span className="text-[10px] bg-[#1E3A6D]/40 text-[#2F6FED] px-2 py-0.5 rounded-full border border-[#2F6FED]/20 animate-pulse">
                        Enviando...
                      </span>
                    )}
                  </div>

                  {/* Acciones del mensaje */}
                  {!isError && !isSending && (
                    <div className="flex items-center gap-1 text-xs text-zinc-400">
                      <button
                        onClick={() => handleCopy(message.id, messageText)}
                        className="flex items-center gap-1 px-2 py-1 rounded hover:bg-[#202124] hover:text-zinc-200 transition"
                        title="Copiar respuesta"
                      >
                        {copiedId === message.id ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
                        <span>{copiedId === message.id ? 'Copiado' : 'Copiar'}</span>
                      </button>

                      {sourcesList && sourcesList.length > 0 && (
                        <button
                          onClick={() => onOpenSources(sourcesList)}
                          className="flex items-center gap-1 px-2 py-1 rounded bg-[#1E3A6D]/30 border border-[#2F6FED]/40 text-[#2F6FED] hover:bg-[#1E3A6D]/60 transition"
                        >
                          <FileText className="h-3.5 w-3.5" />
                          <span className="font-semibold">Ver fuentes ({sourcesList.length})</span>
                        </button>
                      )}

                      <button
                        onClick={() => onSendMessage(userPreviousQuery || messageText)}
                        className="flex items-center gap-1 px-2 py-1 rounded hover:bg-[#202124] hover:text-zinc-200 transition"
                        title="Regenerar respuesta"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        <span>Regenerar</span>
                      </button>

                      <button
                        onClick={() => onOpenFeedback(message.id, 'up')}
                        className="p-1 rounded hover:bg-[#202124] hover:text-green-400 transition"
                        title="Útil"
                      >
                        <ThumbsUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => onOpenFeedback(message.id, 'down')}
                        className="p-1 rounded hover:bg-[#202124] hover:text-red-400 transition"
                        title="No útil"
                      >
                        <ThumbsDown className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>

                {/* Sub-componente de Razonamiento */}
                <MessageReasoningPart text={reasoningText} />

                {/* Sub-componente de Baja Confianza o Texto Normal */}
                {isLowConfidence ? (
                  <LowConfidenceBanner
                    officialUrl={message.metadata?.officialUrl || message.officialUrl}
                    userPreviousQuery={userPreviousQuery}
                    onRephraseQuery={onRephraseQuery}
                  />
                ) : (
                  <MessageTextPart text={messageText} isError={isError} />
                )}

                {/* Chips de seguimiento */}
                {isLastMessage && !loading && !isError && !isSending && (
                  <div className="pt-2">
                    <p className="mb-2 text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">
                      Consultas relacionadas:
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {chipsToDisplay.map((chip, idx) => (
                        <button
                          key={idx}
                          onClick={() => onSendMessage(chip.query || chip.label)}
                          className="rounded-lg border border-[#303136] bg-[#202124] px-3 py-1.5 text-xs text-zinc-300 transition hover:border-[#2F6FED] hover:bg-[#2A2C31] hover:text-zinc-100"
                        >
                          {chip.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </article>
            );
          }

          {/* Mensaje del Usuario */}
          return (
            <div key={message.id || index} className="flex justify-end animate-in fade-in duration-150">
              <div className="ml-auto max-w-[80%] rounded-xl border border-[#303136] bg-[#202124] px-4 py-3 text-sm leading-6 text-zinc-100 shadow-sm">
                <MessageTextPart text={messageText} isError={false} />
              </div>
            </div>
          );
        })}

        {/* Indicador de Carga con Botón Detener Respuesta */}
        {loading && (
          <article className="max-w-3xl space-y-2">
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#1E3A6D]/50 text-[#2F6FED]">
                <Zap className="h-3.5 w-3.5" />
              </div>
              <span className="text-xs font-semibold text-zinc-200">Asistente ARCSA</span>
            </div>

            <div className="flex items-center justify-between gap-3 rounded-xl border border-[#303136] bg-[#1C1D20] px-4 py-3 text-xs text-zinc-400">
              <div className="flex items-center gap-2.5">
                <Loader2 className="h-4 w-4 animate-spin text-[#2F6FED]" />
                <span>La IA está procesando tu consulta...</span>
              </div>

              {onStopResponse && (
                <button
                  onClick={onStopResponse}
                  className="flex items-center gap-1 rounded border border-[#303136] bg-[#202124] px-2.5 py-1 text-xs font-medium text-zinc-300 hover:bg-[#2A2C31] hover:text-red-400 transition"
                >
                  <Square className="h-3 w-3 fill-current text-red-400" />
                  <span>Detener respuesta</span>
                </button>
              )}
            </div>
          </article>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
};
