import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { Mail, Lock, Loader2, ArrowRight, ShieldCheck } from 'lucide-react';

export const LoginForm = ({ onForgotPassword }) => {
  const { login, signup } = useAuth();
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (isLogin) {
        await login(email, password);
      } else {
        // signup() ya deja al usuario logueado (chatbot/auth.py entrega la
        // sesión en el mismo POST /api/auth/signup, sin verificación de
        // correo) — no hay ningún paso adicional que disparar acá.
        await signup(email, password);
      }
    } catch (err) {
      setError(err.message || 'Ocurrió un error. Inténtalo de nuevo.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-100 px-4 font-sans text-ink-900">
      <div className="w-full max-w-md bg-surface-0 border border-line shadow-sm p-8">
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 bg-ink-900 flex items-center justify-center text-accent shadow-sm mb-4">
            <ShieldCheck className="h-8 w-8" />
          </div>
          <h2 className="text-2xl font-bold font-display text-ink-900">
            {isLogin ? 'Asistente Virtual ARCSA' : 'Crear Cuenta'}
          </h2>
          <p className="text-ink-500 text-xs mt-2 text-center">
            {isLogin
              ? 'Inicia sesión para consultar trámites, normativas y registros sanitarios.'
              : 'Regístrate para acceder al asistente de consultas regulatorias.'}
          </p>
        </div>

        {error && (
          <div className="bg-bad/10 border border-bad/40 text-bad text-xs p-3.5 mb-6">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-ink-700 text-xs font-semibold uppercase tracking-wide mb-1.5" htmlFor="email">
              Correo Electrónico
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-ink-500">
                <Mail size={18} />
              </span>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="usuario@arcsa.gob.ec"
                className="w-full bg-surface-0 border border-line text-ink-900 placeholder-ink-500 pl-10 pr-4 py-3 text-sm focus:outline-none focus:border-accent transition-colors"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-ink-700 text-xs font-semibold uppercase tracking-wide" htmlFor="password">
                Contraseña
              </label>
              {isLogin && onForgotPassword && (
                <button
                  type="button"
                  onClick={onForgotPassword}
                  className="text-xs text-accent hover:underline"
                >
                  ¿Olvidaste tu contraseña?
                </button>
              )}
            </div>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-ink-500">
                <Lock size={18} />
              </span>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-surface-0 border border-line text-ink-900 placeholder-ink-500 pl-10 pr-4 py-3 text-sm focus:outline-none focus:border-accent transition-colors"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-accent hover:bg-accent-hover text-white font-medium py-3 px-4 shadow-sm transition-all flex items-center justify-center gap-2 mt-6 active:scale-98 disabled:opacity-50 text-sm"
          >
            {loading ? (
              <Loader2 className="animate-spin" size={20} />
            ) : (
              <>
                <span>{isLogin ? 'Iniciar Sesión' : 'Registrarse'}</span>
                <ArrowRight size={18} />
              </>
            )}
          </button>
        </form>

        <div className="mt-8 text-center border-t border-line pt-6">
          <p className="text-ink-500 text-xs">
            {isLogin ? '¿No tienes cuenta?' : '¿Ya tienes una cuenta?'}
            <button
              onClick={() => {
                setIsLogin(!isLogin);
                setError('');
              }}
              className="text-accent hover:underline ml-1.5 font-medium transition-colors"
            >
              {isLogin ? 'Regístrate aquí' : 'Inicia sesión'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
};
