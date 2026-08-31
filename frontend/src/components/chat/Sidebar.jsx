import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  Zap,
  Plus,
  MessageSquare,
  Search,
  MoreVertical,
  Pin,
  Edit3,
  Trash2,
  Settings,
  HelpCircle,
  LogOut,
  User,
  ShieldCheck,
  AlertTriangle
} from 'lucide-react';

export const Sidebar = ({
  conversations,
  activeId,
  selectConversation,
  requestDeleteConversation,
  createNewChat,
  currentView,
  setCurrentView,
  apiKey,
  searchQuery,
  setSearchQuery,
  pinnedIds,
  togglePinConversation,
  setRenameModalId
}) => {
  const { user, logout } = useAuth();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [activeMenuId, setActiveMenuId] = useState(null);

  // Filtrar conversaciones por búsqueda
  const filtered = conversations.filter(c =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Agrupación por Hoy / Esta semana / Anteriores
  const today = new Date().toDateString();
  const groupConversations = (items) => {
    const pinned = [];
    const todayList = [];
    const earlierList = [];

    items.forEach(item => {
      if (pinnedIds.includes(item.id)) {
        pinned.push(item);
      } else {
        const itemDate = new Date(item.timestamp || Date.now()).toDateString();
        if (itemDate === today) {
          todayList.push(item);
        } else {
          earlierList.push(item);
        }
      }
    });

    return { pinned, todayList, earlierList };
  };

  const { pinned, todayList, earlierList } = groupConversations(filtered);

  return (
    <div className="flex h-full flex-col bg-[#17181B] text-zinc-200 select-none">
      
      {/* Header Institucional */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-[#303136]/50 shrink-0">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#1E3A6D]/40 text-[#2F6FED]">
          <Zap className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-base font-semibold leading-5 text-zinc-100">Arcsa</p>
          <p className="text-xs text-zinc-500">Asistente Virtual</p>
        </div>
      </div>

      {/* Botón Principal + Nueva Consulta */}
      <div className="px-3 pt-4 shrink-0">
        <button
          onClick={() => {
            createNewChat();
            if (setCurrentView) setCurrentView('chat');
          }}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#2F6FED] px-4 py-3 text-sm font-medium text-white transition hover:bg-[#255CC7] active:scale-98 shadow-md"
        >
          <Plus className="h-4 w-4" />
          <span>Nueva Consulta</span>
        </button>
      </div>

      {/* Buscador de Historial */}
      <div className="px-3 pt-3 shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Buscar consulta..."
            className="w-full rounded-lg border border-[#303136] bg-[#1C1D20] pl-8 pr-3 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-500 outline-none focus:border-[#2F6FED]"
          />
        </div>
      </div>

      {/* Lista de Conversaciones por Agrupación */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {filtered.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-500 space-y-2">
            <p>No se encontraron consultas.</p>
            <button
              onClick={createNewChat}
              className="text-[#2F6FED] hover:underline font-medium"
            >
              Crear Nueva Consulta
            </button>
          </div>
        ) : (
          <>
            {/* Fijadas */}
            {pinned.length > 0 && (
              <div className="space-y-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 flex items-center gap-1">
                  <Pin className="h-3 w-3 text-amber-500" />
                  <span>Fijadas</span>
                </p>
                {pinned.map(chat => renderChatItem(chat))}
              </div>
            )}

            {/* Hoy */}
            {todayList.length > 0 && (
              <div className="space-y-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  Hoy
                </p>
                {todayList.map(chat => renderChatItem(chat))}
              </div>
            )}

            {/* Anteriores */}
            {earlierList.length > 0 && (
              <div className="space-y-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  Anteriores
                </p>
                {earlierList.map(chat => renderChatItem(chat))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer del Sidebar */}
      <div className="mt-auto border-t border-[#303136] p-3 shrink-0 relative">
        
        {/* Links de Navegación */}
        <nav className="mb-2 space-y-1">
          <button
            onClick={() => setCurrentView && setCurrentView('settings')}
            className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs font-medium transition ${
              currentView === 'settings'
                ? 'bg-[#2A2C31] text-[#2F6FED]'
                : 'text-zinc-300 hover:bg-[#2A2C31] hover:text-zinc-100'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <Settings className="h-4 w-4" />
              <span>Configuración</span>
            </div>
            {!apiKey && (
              <span className="flex items-center gap-1 rounded bg-[#3A2B16] px-1.5 py-0.5 text-[10px] font-semibold text-amber-400 border border-[#785316]">
                <AlertTriangle className="h-3 w-3" />
                <span>API Key pendiente</span>
              </span>
            )}
          </button>

          <button
            onClick={() => setCurrentView && setCurrentView('help')}
            className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium transition ${
              currentView === 'help'
                ? 'bg-[#2A2C31] text-[#2F6FED]'
                : 'text-zinc-400 hover:bg-[#2A2C31] hover:text-zinc-100'
            }`}
          >
            <HelpCircle className="h-4 w-4" />
            <span>Ayuda / Diagnóstico</span>
          </button>
        </nav>

        {/* Tarjeta de Usuario */}
        <div className="relative">
          <div
            onClick={() => setUserMenuOpen(!userMenuOpen)}
            className="flex items-center gap-3 rounded-xl px-2.5 py-2 hover:bg-[#2A2C31] transition cursor-pointer border border-transparent hover:border-[#303136]"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#1E3A6D] text-xs font-bold text-[#2F6FED] border border-[#2F6FED]/30">
              {user?.name ? user.name.slice(0, 2).toUpperCase() : 'UA'}
            </div>
            <span className="min-w-0 flex-1 truncate text-xs font-medium text-zinc-200">
              {user?.name || 'Usuario ARCSA'}
            </span>
          </div>

          {/* Menú Desplegable de Usuario */}
          {userMenuOpen && (
            <div
              className="absolute bottom-12 left-0 right-0 z-30 rounded-xl border border-[#303136] bg-[#202124] p-1.5 shadow-2xl space-y-0.5 text-xs animate-in slide-in-from-bottom-2 duration-150"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                onClick={() => {
                  if (setCurrentView) setCurrentView('profile');
                  setUserMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-zinc-300 hover:bg-[#2A2C31] hover:text-zinc-100"
              >
                <User className="h-3.5 w-3.5 text-[#2F6FED]" />
                <span>Perfil y Privacidad</span>
              </button>

              <button
                onClick={() => {
                  if (setCurrentView) setCurrentView('settings');
                  setUserMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-zinc-300 hover:bg-[#2A2C31] hover:text-zinc-100"
              >
                <Settings className="h-3.5 w-3.5 text-[#2F6FED]" />
                <span>Configuración</span>
              </button>

              <button
                onClick={() => {
                  if (setCurrentView) setCurrentView('help');
                  setUserMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-zinc-300 hover:bg-[#2A2C31] hover:text-zinc-100"
              >
                <HelpCircle className="h-3.5 w-3.5 text-[#2F6FED]" />
                <span>Ayuda / Diagnóstico</span>
              </button>

              <div className="border-t border-[#303136] my-1" />

              <button
                onClick={() => {
                  setUserMenuOpen(false);
                  logout();
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-zinc-400 hover:bg-[#3A1B1B] hover:text-red-400 transition"
              >
                <LogOut className="h-3.5 w-3.5 text-zinc-400 group-hover:text-red-400" />
                <span>Cerrar sesión</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  function renderChatItem(chat) {
    const isActive = chat.id === activeId && currentView === 'chat';
    const isPinned = pinnedIds.includes(chat.id);

    return (
      <div
        key={chat.id}
        onClick={() => {
          selectConversation(chat.id);
          if (setCurrentView) setCurrentView('chat');
        }}
        className={`group relative flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-xs cursor-pointer transition ${
          isActive
            ? 'bg-[#1E3A6D]/30 border-l-2 border-[#2F6FED] text-zinc-100 font-medium pl-2.5'
            : 'text-zinc-400 hover:bg-[#2A2C31] hover:text-zinc-200'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <MessageSquare
            className={`h-3.5 w-3.5 shrink-0 ${
              isActive ? 'text-[#2F6FED]' : 'text-zinc-500'
            }`}
          />
          <span className="truncate">{chat.title || 'Nueva Consulta'}</span>
        </div>

        <div className="relative shrink-0">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setActiveMenuId(activeMenuId === chat.id ? null : chat.id);
            }}
            className="opacity-0 group-hover:opacity-100 p-1 text-zinc-500 hover:text-zinc-200 rounded hover:bg-[#1C1D20]"
          >
            <MoreVertical className="h-3.5 w-3.5" />
          </button>

          {activeMenuId === chat.id && (
            <div
              className="absolute right-0 top-6 z-40 w-36 rounded-lg border border-[#303136] bg-[#202124] p-1 shadow-xl text-xs space-y-0.5 animate-in fade-in duration-100"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                onClick={() => {
                  togglePinConversation(chat.id);
                  setActiveMenuId(null);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-zinc-300 hover:bg-[#2A2C31]"
              >
                <Pin className="h-3 w-3 text-amber-500" />
                <span>{isPinned ? 'Desfijar' : 'Fijar'}</span>
              </button>

              <button
                onClick={() => {
                  setRenameModalId(chat.id);
                  setActiveMenuId(null);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-zinc-300 hover:bg-[#2A2C31]"
              >
                <Edit3 className="h-3 w-3 text-[#2F6FED]" />
                <span>Renombrar</span>
              </button>

              <button
                onClick={(e) => {
                  setActiveMenuId(null);
                  requestDeleteConversation(chat.id, e);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-red-400 hover:bg-[#3A1B1B]"
              >
                <Trash2 className="h-3 w-3" />
                <span>Eliminar</span>
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }
};
