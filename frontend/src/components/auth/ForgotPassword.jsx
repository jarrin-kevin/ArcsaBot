import React, { useState } from 'react';
import { Mail, ArrowLeft, AlertTriangle, KeyRound } from 'lucide-react';

// El backend real (chatbot/auth.py) no expone recuperación de contraseña ni
// envío de emails, así que este paso muestra un mensaje honesto en vez de
// simular un "correo enviado" que nunca ocurre.
export const ForgotPassword = ({ onBackToLogin }) => {
  const [email, setEmail] = useState('');
  const [step, setStep] = useState('request'); // 'request' | 'unavailable'
  const [loading, setLoading] = useState(false);

  const handleRequestSubmit = (e) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      setStep('unavailable');
    }, 500);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-100 px-4 font-sans text-ink-900">
      <div className="w-full max-w-md bg-surface-0 border border-line rounded-2xl shadow-sm p-8">

        <button
          onClick={onBackToLogin}
          className="flex items-center gap-1.5 text-xs text-ink-500 hover:text-ink-900 mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Volver al inicio de sesión</span>
        </button>

        {step === 'request' && (
          <>
            <div className="mb-6 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent border border-accent/30">
                <KeyRound className="h-6 w-6" />
              </div>
              <h2 className="text-xl font-bold font-display text-ink-900">Recuperar Contraseña</h2>
              <p className="text-xs text-ink-500 mt-1">
                Ingresa tu correo registrado para continuar.
              </p>
            </div>

            <form onSubmit={handleRequestSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wide text-ink-700 mb-1.5">
                  Correo Electrónico
                </label>
                <div className="relative">
                  <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-500" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="usuario@arcsa.gob.ec"
                    className="w-full rounded-xl border border-line bg-surface-0 pl-10 pr-4 py-3 text-sm text-ink-900 placeholder-ink-500 outline-none focus:border-accent"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading || !email}
                className="w-full rounded-xl bg-accent py-3 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 transition"
              >
                {loading ? 'Verificando…' : 'Continuar'}
              </button>
            </form>
          </>
        )}

        {step === 'unavailable' && (
          <div className="text-center py-4 space-y-4">
            <AlertTriangle className="mx-auto h-12 w-12 text-warn" />
            <h2 className="text-lg font-bold font-display text-ink-900">Función no disponible todavía</h2>
            <p className="text-xs text-ink-500 leading-5">
              La recuperación automática de contraseña no está implementada todavía. No se envió ningún correo.
              Por favor contactá al administrador del sistema para restablecer tu contraseña.
            </p>
            <button
              onClick={onBackToLogin}
              className="w-full rounded-xl bg-accent py-2.5 text-xs font-medium text-white hover:bg-accent-hover"
            >
              Volver al inicio de sesión
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
