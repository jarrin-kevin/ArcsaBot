import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

export const Error401Banner = ({ errorDetails, onRetry }) => {
  if (!errorDetails) return null;

  const { code, message } = errorDetails;

  let title = 'Error de Conexión';
  let desc = message || 'Ocurrió un problema con el servicio de IA.';
  let buttonLabel = 'Reintentar';
  let buttonIcon = <RefreshCw className="h-3.5 w-3.5" />;
  let actionFn = onRetry;

  if (code === 'INVALID_KEY') {
    title = 'Error de autenticación con el proveedor de IA';
    desc = 'El servidor no pudo autenticarse con el proveedor de IA. Contacta al administrador.';
  } else if (code === 'QUOTA_EXCEEDED') {
    title = 'Sin créditos / Cuota agotada';
    desc = 'La cuenta del proveedor de IA configurada en el servidor se ha quedado sin saldo o créditos.';
    buttonLabel = 'Reintentar más tarde';
  } else if (code === 'RATE_LIMIT') {
    title = 'Límite de solicitudes (Rate Limit 429)';
    desc = 'Se enviaron demasiadas peticiones seguidas. Espera unos segundos.';
    buttonLabel = 'Reintentar en unos segundos';
  } else if (code === 'NETWORK_ERROR') {
    title = 'Error de Red / Servidor';
    desc = 'No se pudo establecer conexión con el backend del chatbot.';
    buttonLabel = 'Reintentar';
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pt-4 shrink-0">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-bad/40 bg-bad/10 p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-bad shrink-0 mt-0.5" />
          <div>
            <h2 className="text-sm font-semibold text-bad">{title}</h2>
            <p className="mt-0.5 text-xs text-ink-700">{desc}</p>
          </div>
        </div>

        <button
          onClick={actionFn}
          className="flex items-center gap-1.5 rounded-lg bg-bad px-3.5 py-2 text-xs font-medium text-white transition hover:bg-bad/90 shrink-0 shadow-sm"
        >
          {buttonIcon}
          <span>{buttonLabel}</span>
        </button>
      </div>
    </div>
  );
};
