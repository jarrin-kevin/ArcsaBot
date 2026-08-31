import React, { useState } from 'react';
import { Eye, EyeOff, CheckCircle2, AlertCircle, Loader2, Lock, ExternalLink, ShieldCheck } from 'lucide-react';
import { apiService } from '../../services/api';

export const SettingsPage = ({ apiKey, setApiKey, provider, setProvider, onBackToChat }) => {
  const [keyInput, setKeyInput] = useState(apiKey || '');
  const [selectedProvider, setSelectedProvider] = useState(provider || 'OpenRouter');
  const [showKey, setShowKey] = useState(false);
  const [saveToast, setSaveToast] = useState(null);
  
  // 3 Estados del botón de prueba: 'idle' | 'loading' | 'success' | 'error'
  const [testState, setTestState] = useState('idle');
  const [testMessage, setTestMessage] = useState('');

  const handleSave = (e) => {
    e.preventDefault();
    setApiKey(keyInput.trim());
    setProvider(selectedProvider);
    setSaveToast('Conexión guardada en la sesión activa.');
    setTimeout(() => setSaveToast(null), 3500);
  };

  const handleTestConnection = async () => {
    setTestState('loading');
    setTestMessage('');

    const result = await apiService.testConnection(keyInput || apiKey, selectedProvider);

    if (result.success) {
      setTestState('success');
      setTestMessage('Conexión verificada correctamente');
    } else {
      setTestState('error');
      setTestMessage(result.message || 'Error al conectar con la API.');
    }
  };

  const getProviderLink = () => {
    if (selectedProvider === 'Gemini') return { label: 'Obtener API Key en Google AI Studio ↗', url: 'https://aistudio.google.com/app/apikey' };
    if (selectedProvider === 'OpenAI') return { label: 'Obtener API Key en OpenAI ↗', url: 'https://platform.openai.com/api-keys' };
    return { label: 'Obtener API Key en OpenRouter ↗', url: 'https://openrouter.ai/keys' };
  };

  const providerLink = getProviderLink();

  return (
    <section className="mx-auto w-full max-w-2xl px-6 py-10 overflow-y-auto flex-1 font-sans text-zinc-100">
      <header className="mb-8 border-b border-[#303136] pb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">
            Configuración de Conexión (API Key)
          </h1>
          <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-400 bg-[#3A2B16] border border-[#785316] px-3 py-1.5 rounded-lg w-fit">
            <Lock className="h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span className="font-semibold">Almacenamiento volátil: Tu API Key se mantiene únicamente en memoria en este navegador.</span>
          </div>
        </div>
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#1E3A6D]/40 text-[#2F6FED]">
          <ShieldCheck className="h-7 w-7" />
        </div>
      </header>

      {/* Toast de Éxito al Guardar */}
      {saveToast && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-green-500/40 bg-green-950/50 p-3.5 text-xs font-semibold text-green-300 shadow-md animate-in fade-in duration-150">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-green-400" />
          <span>{saveToast}</span>
        </div>
      )}

      {/* Mensaje de Resultado de Prueba de Conexión */}
      {testState === 'success' && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-green-500/40 bg-green-950/50 p-3.5 text-xs font-semibold text-green-300 shadow-md animate-in fade-in duration-150">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-green-400" />
          <span>{testMessage}</span>
        </div>
      )}

      {testState === 'error' && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-red-500/40 bg-[#3A1B1B] p-3.5 text-xs font-semibold text-red-300 shadow-md animate-in fade-in duration-150">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
          <span>{testMessage}</span>
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-6">
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
            Proveedor LLM
          </label>
          <select
            value={selectedProvider}
            onChange={(e) => {
              setSelectedProvider(e.target.value);
              setTestState('idle');
            }}
            className="h-11 w-full rounded-xl border border-[#303136] bg-[#1C1D20] px-3.5 text-sm text-zinc-100 outline-none focus:border-[#2F6FED] transition-colors"
          >
            <option value="OpenRouter">OpenRouter (Recomendado)</option>
            <option value="Gemini">Google Gemini</option>
            <option value="OpenAI">OpenAI</option>
          </select>
        </div>

        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
            API Key
          </label>
          <div className="relative">
            <input
              type={showKey ? 'text' : 'password'}
              value={keyInput}
              onChange={(e) => {
                setKeyInput(e.target.value);
                setTestState('idle');
              }}
              placeholder="sk-..."
              className="h-11 w-full rounded-xl border border-[#303136] bg-[#1C1D20] pl-3.5 pr-10 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-[#2F6FED] font-mono transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-200 transition-colors"
              title={showKey ? 'Ocultar clave' : 'Mostrar clave'}
            >
              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>

          <p className="text-xs text-zinc-500 pt-1">
            <a
              href={providerLink.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[#2F6FED] hover:underline font-medium"
            >
              <span>{providerLink.label}</span>
              <ExternalLink className="h-3 w-3" />
            </a>
          </p>
        </div>

        {/* Botones de Acción con 3 estados del Botón Probar Conexión */}
        <div className="flex flex-col gap-3 sm:flex-row pt-4">
          <button
            type="submit"
            className="rounded-xl bg-[#2F6FED] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#255CC7] shadow-md"
          >
            Guardar Configuración
          </button>

          <button
            type="button"
            onClick={handleTestConnection}
            disabled={testState === 'loading'}
            className={`flex items-center justify-center gap-2 rounded-xl border px-5 py-3 text-sm font-medium transition ${
              testState === 'success'
                ? 'border-green-500/50 bg-green-950/40 text-green-300'
                : testState === 'error'
                ? 'border-red-500/50 bg-red-950/40 text-red-300'
                : 'border-[#303136] bg-[#202124] text-zinc-200 hover:bg-[#2A2C31]'
            }`}
          >
            {testState === 'loading' && <Loader2 className="h-4 w-4 animate-spin text-[#2F6FED]" />}
            {testState === 'success' && <CheckCircle2 className="h-4 w-4 text-green-400" />}
            {testState === 'error' && <AlertCircle className="h-4 w-4 text-red-400" />}
            <span>
              {testState === 'loading'
                ? 'Probando conexión…'
                : testState === 'success'
                ? 'Conexión verificada'
                : testState === 'error'
                ? 'Error al probar'
                : 'Probar Conexión'}
            </span>
          </button>

          {onBackToChat && (
            <button
              type="button"
              onClick={onBackToChat}
              className="sm:ml-auto text-xs text-zinc-400 hover:text-zinc-100 py-3 px-2"
            >
              Volver al Chat
            </button>
          )}
        </div>
      </form>
    </section>
  );
};
