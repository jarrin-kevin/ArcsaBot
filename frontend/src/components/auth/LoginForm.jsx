import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { Mail, Lock, Loader2, ArrowRight, Zap } from 'lucide-react';

export const LoginForm = ({ onForgotPassword, onNeedVerification }) => {
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
        await signup(email, password);
        if (onNeedVerification) {
          onNeedVerification(email);
        }
      }
    } catch (err) {
      setError(err.message || 'Ocurrió un error. Inténtalo de nuevo.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#121314] px-4 font-sans text-zinc-100">
      <div className="w-full max-w-md bg-[#202124] border border-[#303136] rounded-2xl shadow-2xl p-8">
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 bg-[#1E3A6D]/50 border border-[#2F6FED]/30 rounded-2xl flex items-center justify-center text-[#2F6FED] shadow-lg mb-4">
            <Zap className="h-8 w-8" />
          </div>
          <h2 className="text-2xl font-bold text-zinc-100">
            {isLogin ? 'Asistente Virtual ARCSA' : 'Crear Cuenta'}
          </h2>
          <p className="text-zinc-400 text-xs mt-2 text-center">
            {isLogin 
              ? 'Inicia sesión para consultar trámites, normativas y registros sanitarios.' 
              : 'Regístrate para acceder al asistente de consultas regulatorias.'}
          </p>
        </div>

        {error && (
          <div className="bg-[#3A1B1B] border border-red-900/60 text-red-200 text-xs rounded-xl p-3.5 mb-6">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-zinc-300 text-xs font-semibold uppercase tracking-wide mb-1.5" htmlFor="email">
              Correo Electrónico
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-zinc-500">
                <Mail size={18} />
              </span>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="usuario@arcsa.gob.ec"
                className="w-full bg-[#1C1D20] border border-[#303136] text-zinc-100 placeholder-zinc-500 rounded-xl pl-10 pr-4 py-3 text-sm focus:outline-none focus:border-[#2F6FED] transition-colors"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-zinc-300 text-xs font-semibold uppercase tracking-wide" htmlFor="password">
                Contraseña
              </label>
              {isLogin && onForgotPassword && (
                <button
                  type="button"
                  onClick={onForgotPassword}
                  className="text-xs text-[#2F6FED] hover:underline"
                >
                  ¿Olvidaste tu contraseña?
                </button>
              )}
            </div>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-zinc-500">
                <Lock size={18} />
              </span>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-[#1C1D20] border border-[#303136] text-zinc-100 placeholder-zinc-500 rounded-xl pl-10 pr-4 py-3 text-sm focus:outline-none focus:border-[#2F6FED] transition-colors"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#2F6FED] hover:bg-[#255CC7] text-white font-medium py-3 px-4 rounded-xl shadow-md transition-all flex items-center justify-center gap-2 mt-6 active:scale-98 disabled:opacity-50 text-sm"
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

        <div className="mt-8 text-center border-t border-[#303136] pt-6">
          <p className="text-zinc-400 text-xs">
            {isLogin ? '¿No tienes cuenta?' : '¿Ya tienes una cuenta?'}
            <button
              onClick={() => setIsLogin(!isLogin)}
              className="text-[#2F6FED] hover:underline ml-1.5 font-medium transition-colors"
            >
              {isLogin ? 'Regístrate aquí' : 'Inicia sesión'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
};
