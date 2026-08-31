import React, { useState } from 'react';
import { Mail, ArrowLeft, CheckCircle2, AlertTriangle, KeyRound } from 'lucide-react';

export const ForgotPassword = ({ onBackToLogin }) => {
  const [email, setEmail] = useState('');
  const [step, setStep] = useState('request'); // 'request' | 'sent' | 'reset' | 'expired'
  const [newPassword, setNewPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleRequestSubmit = (e) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      setStep('sent');
    }, 1000);
  };

  const handleResetSubmit = (e) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      onBackToLogin();
    }, 1000);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#121314] px-4 font-sans text-zinc-100">
      <div className="w-full max-w-md bg-[#202124] border border-[#303136] rounded-2xl shadow-2xl p-8">
        
        <button
          onClick={onBackToLogin}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-100 mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Volver al inicio de sesión</span>
        </button>

        {step === 'request' && (
          <>
            <div className="mb-6 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#1E3A6D]/50 text-[#2F6FED] border border-[#2F6FED]/30">
                <KeyRound className="h-6 w-6" />
              </div>
              <h2 className="text-xl font-bold text-zinc-100">Recuperar Contraseña</h2>
              <p className="text-xs text-zinc-400 mt-1">
                Ingresa tu correo registrado y te enviaremos un enlace oficial de restablecimiento.
              </p>
            </div>

            <form onSubmit={handleRequestSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wide text-zinc-400 mb-1.5">
                  Correo Electrónico
                </label>
                <div className="relative">
                  <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="usuario@arcsa.gob.ec"
                    className="w-full rounded-xl border border-[#303136] bg-[#1C1D20] pl-10 pr-4 py-3 text-sm text-zinc-100 outline-none focus:border-[#2F6FED]"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading || !email}
                className="w-full rounded-xl bg-[#2F6FED] py-3 text-sm font-semibold text-white hover:bg-[#255CC7] disabled:opacity-50 transition"
              >
                {loading ? 'Enviando enlace…' : 'Enviar Enlace de Recuperación'}
              </button>
            </form>
          </>
        )}

        {step === 'sent' && (
          <div className="text-center py-4 space-y-4">
            <CheckCircle2 className="mx-auto h-12 w-12 text-green-500 animate-pulse" />
            <h2 className="text-lg font-bold text-zinc-100">Correo Enviado</h2>
            <p className="text-xs text-zinc-400 leading-5">
              Hemos enviado las instrucciones para restablecer tu contraseña a <strong className="text-zinc-200">{email}</strong>.
            </p>
            <div className="pt-4 flex flex-col gap-2">
              <button
                onClick={() => setStep('reset')}
                className="w-full rounded-xl bg-[#2F6FED] py-2.5 text-xs font-semibold text-white hover:bg-[#255CC7]"
              >
                Simular clic en enlace recibido
              </button>
              <button
                onClick={() => setStep('expired')}
                className="text-xs text-zinc-500 hover:underline"
              >
                Probar estado "Enlace Expirado"
              </button>
            </div>
          </div>
        )}

        {step === 'reset' && (
          <>
            <div className="mb-6 text-center">
              <h2 className="text-xl font-bold text-zinc-100">Nueva Contraseña</h2>
              <p className="text-xs text-zinc-400 mt-1">Crea una nueva contraseña segura para tu cuenta ARCSA.</p>
            </div>

            <form onSubmit={handleResetSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wide text-zinc-400 mb-1.5">
                  Nueva Contraseña
                </label>
                <input
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-[#303136] bg-[#1C1D20] px-4 py-3 text-sm text-zinc-100 outline-none focus:border-[#2F6FED]"
                />
              </div>

              <button
                type="submit"
                disabled={loading || !newPassword}
                className="w-full rounded-xl bg-[#2F6FED] py-3 text-sm font-semibold text-white hover:bg-[#255CC7] transition"
              >
                {loading ? 'Guardando…' : 'Restablecer Contraseña'}
              </button>
            </form>
          </>
        )}

        {step === 'expired' && (
          <div className="text-center py-4 space-y-4">
            <AlertTriangle className="mx-auto h-12 w-12 text-amber-500" />
            <h2 className="text-lg font-bold text-zinc-100">Enlace Expirado</h2>
            <p className="text-xs text-zinc-400 leading-5">
              El enlace de recuperación ha caducado por motivos de seguridad (validez máxima de 15 minutos).
            </p>
            <button
              onClick={() => setStep('request')}
              className="w-full rounded-xl bg-[#2F6FED] py-2.5 text-xs font-semibold text-white hover:bg-[#255CC7]"
            >
              Solicitar Nuevo Enlace
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
