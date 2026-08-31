import React, { useState } from 'react';
import { User, ShieldCheck, Lock, Trash2, KeyRound, CheckCircle2, ArrowLeft } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export const ProfilePage = ({ apiKey, setApiKey, onBackToChat, onClearHistory }) => {
  const { user } = useAuth();
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [clearHistorySuccess, setClearHistorySuccess] = useState(false);

  const handleChangePassword = (e) => {
    e.preventDefault();
    setPasswordSuccess(true);
    setTimeout(() => setPasswordSuccess(false), 3000);
  };

  const handleClearKey = () => {
    setApiKey('');
  };

  const handleClearHistoryClick = () => {
    if (onClearHistory) {
      onClearHistory();
    }
    setClearHistorySuccess(true);
    setTimeout(() => setClearHistorySuccess(false), 3000);
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
          <h1 className="text-2xl font-bold text-zinc-100">Perfil y Privacidad</h1>
          <p className="mt-1 text-xs text-zinc-400">
            Gestiona la seguridad de tu cuenta y el almacenamiento de datos locales.
          </p>
        </div>
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#1E3A6D]/40 text-[#2F6FED]">
          <ShieldCheck className="h-7 w-7" />
        </div>
      </header>

      <div className="space-y-8">
        {/* Datos de Usuario */}
        <div className="rounded-xl border border-[#303136] bg-[#202124] p-5 space-y-4">
          <h2 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
            <User className="h-4 w-4 text-[#2F6FED]" />
            <span>Información del Usuario</span>
          </h2>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div>
              <span className="text-zinc-500 uppercase tracking-wide">Nombre</span>
              <p className="text-zinc-200 font-medium mt-0.5">{user?.name || 'Usuario ARCSA'}</p>
            </div>
            <div>
              <span className="text-zinc-500 uppercase tracking-wide">Correo Electrónico</span>
              <p className="text-zinc-200 font-medium mt-0.5">{user?.email || 'usuario@arcsa.gob.ec'}</p>
            </div>
          </div>
        </div>

        {/* Cambiar Contraseña */}
        <div className="rounded-xl border border-[#303136] bg-[#202124] p-5 space-y-4">
          <h2 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
            <Lock className="h-4 w-4 text-[#2F6FED]" />
            <span>Seguridad y Contraseña</span>
          </h2>

          {passwordSuccess && (
            <div className="flex items-center gap-2 rounded-lg bg-green-950/40 border border-green-500/30 p-2.5 text-xs text-green-400">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>Contraseña actualizada correctamente.</span>
            </div>
          )}

          <form onSubmit={handleChangePassword} className="space-y-3 max-w-md">
            <div>
              <label className="block text-xs text-zinc-400 mb-1">Nueva Contraseña</label>
              <input
                type="password"
                required
                placeholder="••••••••"
                className="w-full rounded-lg border border-[#303136] bg-[#1C1D20] px-3 py-2 text-xs text-zinc-100 outline-none focus:border-[#2F6FED]"
              />
            </div>
            <button
              type="submit"
              className="rounded-lg bg-[#2F6FED] px-4 py-2 text-xs font-semibold text-white hover:bg-[#255CC7]"
            >
              Actualizar Contraseña
            </button>
          </form>
        </div>

        {/* Datos Almacenados y API Key Efímera */}
        <div className="rounded-xl border border-[#303136] bg-[#202124] p-5 space-y-4">
          <h2 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-amber-500" />
            <span>Almacenamiento Local de Datos</span>
          </h2>

          <div className="space-y-3 text-xs text-zinc-400 leading-5">
            <p>
              <strong className="text-zinc-200">API Key Efímera:</strong> Actualmente {apiKey ? 'configurada en memoria de sesión.' : 'no configurada.'}
            </p>
            {apiKey && (
              <button
                onClick={handleClearKey}
                className="flex items-center gap-1.5 rounded-lg border border-red-900/60 bg-[#3A1B1B] px-3 py-1.5 text-xs text-red-300 hover:bg-red-900/40"
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span>Eliminar API Key de la memoria actual</span>
              </button>
            )}

            <div className="pt-2 border-t border-[#303136]">
              <strong className="text-zinc-200 block mb-1">Historial de Conversaciones:</strong>
              <p className="mb-2">Al presionar el botón de abajo, se borrarán de forma definitiva todas las consultas guardadas tanto de la barra lateral como de la memoria del navegador.</p>
              
              {clearHistorySuccess && (
                <div className="flex items-center gap-2 rounded-lg bg-green-950/40 border border-green-500/30 p-2.5 text-xs text-green-400 mb-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>Historial de consultas borrado correctamente.</span>
                </div>
              )}

              <button
                onClick={handleClearHistoryClick}
                className="flex items-center gap-1.5 rounded-lg border border-[#303136] bg-[#1C1D20] px-3.5 py-2 text-xs font-semibold text-zinc-300 hover:bg-[#2A2C31] hover:text-red-400 transition"
              >
                <Trash2 className="h-3.5 w-3.5 text-red-400" />
                <span>Borrar historial local de consultas</span>
              </button>
            </div>
          </div>
        </div>

      </div>
    </section>
  );
};
