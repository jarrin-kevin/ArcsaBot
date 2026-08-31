import React, { useState } from 'react';
import { MailCheck, ArrowLeft, RefreshCw, Edit2 } from 'lucide-react';

export const EmailVerification = ({ email = 'usuario@arcsa.gob.ec', onBackToLogin }) => {
  const [currentEmail, setCurrentEmail] = useState(email);
  const [isEditing, setIsEditing] = useState(false);
  const [resent, setResent] = useState(false);

  const handleResend = () => {
    setResent(true);
    setTimeout(() => setResent(false), 3000);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#121314] px-4 font-sans text-zinc-100">
      <div className="w-full max-w-md bg-[#202124] border border-[#303136] rounded-2xl shadow-2xl p-8 text-center">
        
        <button
          onClick={onBackToLogin}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-100 mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Volver al inicio de sesión</span>
        </button>

        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#1E3A6D]/50 text-[#2F6FED] border border-[#2F6FED]/30">
          <MailCheck className="h-8 w-8" />
        </div>

        <h2 className="text-xl font-bold text-zinc-100 mb-2">Verifica tu Correo Electrónico</h2>
        <p className="text-xs text-zinc-400 leading-5 mb-4">
          Hemos enviado un enlace de confirmación a:
        </p>

        {isEditing ? (
          <div className="flex gap-2 mb-4">
            <input
              type="email"
              value={currentEmail}
              onChange={(e) => setCurrentEmail(e.target.value)}
              className="flex-1 rounded-lg border border-[#303136] bg-[#1C1D20] px-3 py-1.5 text-xs text-zinc-100 outline-none focus:border-[#2F6FED]"
            />
            <button
              onClick={() => setIsEditing(false)}
              className="rounded-lg bg-[#2F6FED] px-3 py-1.5 text-xs font-semibold text-white"
            >
              Guardar
            </button>
          </div>
        ) : (
          <div className="inline-flex items-center gap-2 rounded-lg border border-[#303136] bg-[#1C1D20] px-3 py-1.5 text-xs font-mono text-[#2F6FED] mb-6">
            <span>{currentEmail}</span>
            <button
              onClick={() => setIsEditing(true)}
              className="text-zinc-400 hover:text-zinc-100 p-0.5"
              title="Cambiar correo"
            >
              <Edit2 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        <div className="space-y-3">
          <button
            onClick={handleResend}
            disabled={resent}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-[#202124] border border-[#303136] py-2.5 text-xs font-semibold text-zinc-200 hover:bg-[#2A2C31] transition disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${resent ? 'animate-spin' : ''}`} />
            <span>{resent ? 'Enlace reenviado con éxito' : 'Reenviar enlace de verificación'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
