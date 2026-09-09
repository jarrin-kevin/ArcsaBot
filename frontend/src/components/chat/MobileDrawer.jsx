import React from 'react';
import { X } from 'lucide-react';
import { Sidebar } from './Sidebar';

export const MobileDrawer = ({
  isOpen,
  onClose,
  conversations,
  activeId,
  selectConversation,
  requestDeleteConversation,
  createNewChat,
  currentView,
  setCurrentView
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      {/* Overlay traslúcido */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />

      {/* Panel deslizante */}
      <div className="fixed inset-y-0 left-0 w-72 max-w-[80vw] bg-surface-0 shadow-sm flex flex-col z-10 animate-in slide-in-from-left duration-200">
        <button
          onClick={onClose}
          className="absolute right-3 top-4 text-ink-500 hover:text-ink-900 p-1 rounded-lg z-20"
          aria-label="Cerrar menú"
        >
          <X className="h-5 w-5" />
        </button>

        <Sidebar
          conversations={conversations}
          activeId={activeId}
          selectConversation={(id) => {
            selectConversation(id);
            onClose();
          }}
          requestDeleteConversation={requestDeleteConversation}
          createNewChat={() => {
            createNewChat();
            onClose();
          }}
          currentView={currentView}
          setCurrentView={(view) => {
            setCurrentView(view);
            onClose();
          }}
        />
      </div>
    </div>
  );
};
