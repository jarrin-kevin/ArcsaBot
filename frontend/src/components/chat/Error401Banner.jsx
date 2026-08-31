import React from 'react';
import { AlertCircle, RefreshCw, Edit3, ExternalLink } from 'lucide-react';

export const Error401Banner = ({ errorDetails, onGoToSettings, onRetry }) => {
  if (!errorDetails) return null;

  const { code, message } = errorDetails;

  let title = 'Error de Conexión';
  let desc = message || 'Ocurrió un problema con el servicio de IA.';
  let buttonLabel = 'Ir a Configuración';
  let buttonIcon = <Edit3 className="h-3.5 w-3.5" />;
  let actionFn = onGoToSettings;

  if (code === 'INVALID_KEY') {
    title = 'API Key no válida';
    desc = 'La clave ingresada fue rechazada por el proveedor. Por favor edítala.';
    buttonLabel = 'Editar API Key';
  } else if (code === 'QUOTA_EXCEEDED') {
    title = 'Sin créditos / Cuota agotada';
    desc = 'Tu cuenta en el proveedor de LLM se ha quedado sin saldo o créditos.';
    buttonLabel = 'Revisar proveedor';
    actionFn = () => window.open('https://openrouter.ai/credits', '_blank');
    buttonIcon = <ExternalLink className="h-3.5 w-3.5" />;
  } else if (code === 'RATE_LIMIT') {
    title = 'Límite de solicitudes (Rate Limit 429)';
    desc = 'Se enviaron demasiadas peticiones seguidas. Espera unos segundos.';
    buttonLabel = 'Reintentar en unos segundos';
    buttonIcon = <RefreshCw className="h-3.5 w-3.5" />;
    actionFn = onRetry || onGoToSettings;
  } else if (code === 'NETWORK_ERROR') {
    title = 'Error de Red / Servidor';
    desc = 'No se pudo establecer conexión con el backend del chatbot.';
    buttonLabel = 'Reintentar';
    buttonIcon = <RefreshCw className="h-3.5 w-3.5" />;
    actionFn = onRetry || onGoToSettings;
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pt-4 shrink-0">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-red-900/80 bg-[#3A1B1B] p-4 shadow-lg">
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
          <div>
            <h2 className="text-sm font-semibold text-red-200">{title}</h2>
            <p className="mt-0.5 text-xs text-red-100/80">{desc}</p>
          </div>
        </div>

        <button
          onClick={actionFn}
          className="flex items-center gap-1.5 rounded-lg bg-red-500 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-red-600 shrink-0 shadow-sm"
        >
          {buttonIcon}
          <span>{buttonLabel}</span>
        </button>
      </div>
    </div>
  );
};
