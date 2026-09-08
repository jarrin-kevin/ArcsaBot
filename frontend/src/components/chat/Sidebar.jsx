import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  Plus,
  MessageSquare,
  Search,
  MoreVertical,
  Pin,
  Edit3,
  Trash2,
  HelpCircle,
  LogOut,
  User,
  ShieldCheck
} from 'lucide-react';

export const Sidebar = ({
  conversations,
  activeId,
  selectConversation,
  requestDeleteConversation,
  createNewChat,
  currentView,
  setCurrentView,
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
    <div className="flex h-full flex-col bg-surface-0 text-ink-700 select-none">

      {/* Header Institucional */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-line shrink-0">
        <div className="flex h-8 w-8 items-center justify-center bg-ink-900 text-accent">
          <ShieldCheck className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-base font-semibold font-display leading-5 text-ink-900">Arcsa</p>
          <p className="text-xs text-ink-500">Asistente Virtual</p>
        </div>
      </div>

      {/* Botón Principal + Nueva Consulta */}
      <div className="px-3 pt-4 shrink-0">
        <button
          onClick={() => {
            createNewChat();
            if (setCurrentView) setCurrentView('chat');
          }}
          className="flex w-full items-center justify-center gap-2 bg-accent px-4 py-3 text-sm font-medium text-white transition hover:bg-accent-hover active:scale-98 shadow-sm"
        >
          <Plus className="h-4 w-4" />
          <span>Nueva Consulta</span>
        </button>
      </div>

      {/* Buscador de Historial */}
      <div className="px-3 pt-3 shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-ink-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Buscar consulta..."
            className="w-full border border-line bg-surface-0 pl-8 pr-3 py-1.5 text-xs text-ink-900 placeholder:text-ink-500 outline-none focus:border-accent"
          />
        </div>
      </div>

      {/* Lista de Conversaciones por Agrupación */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {filtered.length === 0 ? (
          <div className="py-8 text-center text-xs text-ink-500 space-y-2">
            <p>No se encontraron consultas.</p>
            <button
              onClick={createNewChat}
              className="text-accent hover:underline font-medium"
            >
              Crear Nueva Consulta
            </button>
          </div>
        ) : (
          <>
            {/* Fijadas */}
            {pinned.length > 0 && (
              <div className="space-y-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-ink-500 flex items-center gap-1">
                  <Pin className="h-3 w-3 text-ink-500" />
                  <span>Fijadas</span>
                </p>
                {pinned.map(chat => renderChatItem(chat))}
              </div>
            )}

            {/* Hoy */}
            {todayList.length > 0 && (
              <div className="space-y-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-ink-500">
                  Hoy
                </p>
                {todayList.map(chat => renderChatItem(chat))}
              </div>
            )}

            {/* Anteriores */}
            {earlierList.length > 0 && (
              <div className="space-y-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-ink-500">
                  Anteriores
                </p>
                {earlierList.map(chat => renderChatItem(chat))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer del Sidebar */}
      <div className="mt-auto border-t border-line p-3 shrink-0 relative">

        {/* Links de Navegación */}
        <nav className="mb-2 space-y-1">
          <button
            onClick={() => setCurrentView && setCurrentView('help')}
            className={`flex w-full items-center gap-2.5 px-3 py-2 text-xs font-medium transition ${
              currentView === 'help'
                ? 'bg-surface-200 text-ink-900'
                : 'text-ink-700 hover:bg-surface-100 hover:text-ink-900'
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
            className="flex items-center gap-3 px-2.5 py-2 hover:bg-surface-100 transition cursor-pointer border border-transparent hover:border-line"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink-900 text-xs font-bold text-accent">
              {user?.name ? user.name.slice(0, 2).toUpperCase() : 'UA'}
            </div>
            <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink-900">
              {user?.name || 'Usuario ARCSA'}
            </span>
          </div>

          {/* Menú Desplegable de Usuario */}
          {userMenuOpen && (
            <div
              className="absolute bottom-12 left-0 right-0 z-30 border border-line bg-surface-0 p-1.5 shadow-lg space-y-0.5 text-xs animate-in slide-in-from-bottom-2 duration-150"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                onClick={() => {
                  if (setCurrentView) setCurrentView('profile');
                  setUserMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-ink-700 hover:bg-surface-100 hover:text-ink-900"
              >
                <User className="h-3.5 w-3.5 text-ink-700" />
                <span>Perfil y Privacidad</span>
              </button>

              <button
                onClick={() => {
                  if (setCurrentView) setCurrentView('help');
                  setUserMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-ink-700 hover:bg-surface-100 hover:text-ink-900"
              >
                <HelpCircle className="h-3.5 w-3.5 text-ink-700" />
                <span>Ayuda / Diagnóstico</span>
              </button>

              <div className="border-t border-line my-1" />

              <button
                onClick={() => {
                  setUserMenuOpen(false);
                  logout();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-ink-500 hover:bg-bad/10 hover:text-bad transition"
              >
                <LogOut className="h-3.5 w-3.5" />
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
        className={`group relative flex items-center justify-between gap-2 px-3 py-2 text-left text-xs cursor-pointer transition ${
          isActive
            ? 'bg-surface-200 text-ink-900 font-semibold'
            : 'text-ink-700 hover:bg-surface-100 hover:text-ink-900'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <MessageSquare
            className={`h-3.5 w-3.5 shrink-0 ${
              isActive ? 'text-ink-900' : 'text-ink-500'
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
            className="opacity-0 group-hover:opacity-100 p-1 text-ink-500 hover:text-ink-900 hover:bg-surface-200"
          >
            <MoreVertical className="h-3.5 w-3.5" />
          </button>

          {activeMenuId === chat.id && (
            <div
              className="absolute right-0 top-6 z-40 w-36 border border-line bg-surface-0 p-1 shadow-lg text-xs space-y-0.5 animate-in fade-in duration-100"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                onClick={() => {
                  togglePinConversation(chat.id);
                  setActiveMenuId(null);
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-ink-700 hover:bg-surface-100"
              >
                <Pin className="h-3 w-3 text-ink-700" />
                <span>{isPinned ? 'Desfijar' : 'Fijar'}</span>
              </button>

              <button
                onClick={() => {
                  setRenameModalId(chat.id);
                  setActiveMenuId(null);
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-ink-700 hover:bg-surface-100"
              >
                <Edit3 className="h-3 w-3 text-ink-700" />
                <span>Renombrar</span>
              </button>

              <button
                onClick={(e) => {
                  setActiveMenuId(null);
                  requestDeleteConversation(chat.id, e);
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-bad hover:bg-bad/10"
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
