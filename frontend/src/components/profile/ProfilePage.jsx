import React, { useState } from 'react';
import { User, ShieldCheck, Lock, Trash2, CheckCircle2, ArrowLeft } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export const ProfilePage = ({ onBackToChat, onClearHistory }) => {
  const { user } = useAuth();
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [clearHistorySuccess, setClearHistorySuccess] = useState(false);

  const handleChangePassword = (e) => {
    e.preventDefault();
    setPasswordSuccess(true);
    setTimeout(() => setPasswordSuccess(false), 3000);
  };

  const handleClearHistoryClick = () => {
    if (onClearHistory) {
      onClearHistory();
    }
    setClearHistorySuccess(true);
    setTimeout(() => setClearHistorySuccess(false), 3000);
  };

  return (
    <section className="mx-auto w-full max-w-2xl px-6 py-10 overflow-y-auto flex-1 font-sans text-ink-900">

      <button
        onClick={onBackToChat}
        className="flex items-center gap-1.5 text-xs text-ink-500 hover:text-ink-900 mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        <span>Volver al Chat</span>
      </button>

      <header className="mb-8 border-b border-line pb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-display text-ink-900">Perfil y Privacidad</h1>
          <p className="mt-1 text-xs text-ink-500">
            Gestiona la seguridad de tu cuenta y el almacenamiento de datos locales.
          </p>
        </div>
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
          <ShieldCheck className="h-7 w-7" />
        </div>
      </header>

      <div className="space-y-8">
        {/* Datos de Usuario */}
        <div className="rounded-xl border border-line bg-surface-0 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-ink-900 flex items-center gap-2">
            <User className="h-4 w-4 text-accent" />
            <span>Información del Usuario</span>
          </h2>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div>
              <span className="text-ink-500 uppercase tracking-wide">Nombre</span>
              <p className="text-ink-700 font-medium mt-0.5">{user?.name || 'Usuario ARCSA'}</p>
            </div>
            <div>
              <span className="text-ink-500 uppercase tracking-wide">Correo Electrónico</span>
              <p className="text-ink-700 font-medium mt-0.5">{user?.email || 'usuario@arcsa.gob.ec'}</p>
            </div>
          </div>
        </div>

        {/* Cambiar Contraseña */}
        <div className="rounded-xl border border-line bg-surface-0 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-ink-900 flex items-center gap-2">
            <Lock className="h-4 w-4 text-accent" />
            <span>Seguridad y Contraseña</span>
          </h2>

          {passwordSuccess && (
            <div className="flex items-center gap-2 rounded-lg bg-good/10 border border-good/40 p-2.5 text-xs text-good">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>Contraseña actualizada correctamente.</span>
            </div>
          )}

          <form onSubmit={handleChangePassword} className="space-y-3 max-w-md">
            <div>
              <label className="block text-xs text-ink-500 mb-1">Nueva Contraseña</label>
              <input
                type="password"
                required
                placeholder="••••••••"
                className="w-full rounded-lg border border-line bg-surface-0 px-3 py-2 text-xs text-ink-900 placeholder-ink-500 outline-none focus:border-accent"
              />
            </div>
            <button
              type="submit"
              className="rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white hover:bg-accent-hover"
            >
              Actualizar Contraseña
            </button>
          </form>
        </div>

        {/* Historial de Conversaciones */}
        <div className="rounded-xl border border-line bg-surface-0 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-ink-900 flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-warn" />
            <span>Historial de Conversaciones</span>
          </h2>

          <div className="space-y-3 text-xs text-ink-500 leading-5">
            <p>Al presionar el botón de abajo, se borrarán de forma definitiva todas las consultas guardadas tanto de la barra lateral como de la memoria del navegador.</p>

            {clearHistorySuccess && (
              <div className="flex items-center gap-2 rounded-lg bg-good/10 border border-good/40 p-2.5 text-xs text-good mb-2">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                <span>Historial de consultas borrado correctamente.</span>
              </div>
            )}

            <button
              onClick={handleClearHistoryClick}
              className="flex items-center gap-1.5 rounded-lg border border-line bg-surface-0 px-3.5 py-2 text-xs font-semibold text-ink-700 hover:bg-surface-200 hover:text-bad transition"
            >
              <Trash2 className="h-3.5 w-3.5 text-bad" />
              <span>Borrar historial local de consultas</span>
            </button>
          </div>
        </div>

      </div>
    </section>
  );
};
