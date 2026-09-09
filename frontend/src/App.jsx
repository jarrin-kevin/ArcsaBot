import React, { useState, useEffect } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginForm } from './components/auth/LoginForm';
import { ForgotPassword } from './components/auth/ForgotPassword';
import { Sidebar } from './components/chat/Sidebar';
import { ChatWindow } from './components/chat/ChatWindow';
import { MessageInput } from './components/chat/MessageInput';
import { Error401Banner } from './components/chat/Error401Banner';
import { DeleteConfirmModal } from './components/chat/DeleteConfirmModal';
import { RenameModal } from './components/chat/RenameModal';
import { MobileDrawer } from './components/chat/MobileDrawer';
import { RagSourcesDrawer } from './components/chat/RagSourcesDrawer';
import { FeedbackModal } from './components/chat/FeedbackModal';
import { ProfilePage } from './components/profile/ProfilePage';
import { HelpQuiz } from './components/help/HelpQuiz';
import { useChat } from './hooks/useChat';
import { Loader2, Menu, ShieldCheck } from 'lucide-react';

const Dashboard = () => {
  const [currentView, setCurrentView] = useState('chat'); // 'chat' | 'profile' | 'help'
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [feedbackModalInfo, setFeedbackModalInfo] = useState(null);
  const [prefilledInputText, setPrefilledInputText] = useState('');

  const {
    conversations,
    activeId,
    messages,
    loading,
    errorDetails,
    searchQuery,
    setSearchQuery,
    pinnedIds,
    togglePinConversation,
    renameModalId,
    setRenameModalId,
    renameConversation,
    deleteModalId,
    createNewChat,
    selectConversation,
    requestDeleteConversation,
    confirmDeleteConversation,
    cancelDeleteConversation,
    clearLocalHistory,
    sendMessage,
    stopResponse,
    activeSources,
    setActiveSources,
    handleFeedback
  } = useChat();

  const chatToRename = conversations.find(c => c.id === renameModalId);

  const handleLaunchHelpQuery = (queryText) => {
    setCurrentView('chat');
    sendMessage(queryText);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-surface-100 font-sans text-ink-900 antialiased">
      {/* Sidebar Fijo en Escritorio */}
      <aside className="hidden w-64 shrink-0 border-r border-line bg-surface-0 lg:flex lg:flex-col">
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          selectConversation={selectConversation}
          requestDeleteConversation={requestDeleteConversation}
          createNewChat={createNewChat}
          currentView={currentView}
          setCurrentView={setCurrentView}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          pinnedIds={pinnedIds}
          togglePinConversation={togglePinConversation}
          setRenameModalId={setRenameModalId}
        />
      </aside>

      {/* Drawer Móvil */}
      <MobileDrawer
        isOpen={mobileDrawerOpen}
        onClose={() => setMobileDrawerOpen(false)}
        conversations={conversations}
        activeId={activeId}
        selectConversation={selectConversation}
        requestDeleteConversation={requestDeleteConversation}
        createNewChat={createNewChat}
        currentView={currentView}
        setCurrentView={setCurrentView}
      />

      {/* Contenido Principal */}
      <main className="flex min-w-0 flex-1 flex-col h-full bg-surface-0 relative">
        {/* Encabezado Móvil (< lg) */}
        <header className="flex items-center justify-between border-b border-line bg-surface-0 px-4 py-3 lg:hidden shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileDrawerOpen(true)}
              aria-label="Abrir menú"
              className="text-ink-700 hover:text-ink-900 p-1"
            >
              <Menu className="h-5 w-5" />
            </button>

            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded bg-ink-900 text-accent">
                <ShieldCheck className="h-4 w-4" />
              </div>
              <span className="text-sm font-semibold font-display text-ink-900">Arcsa</span>
            </div>
          </div>
        </header>

        {/* Muestra ÚNICA de Alerta Superior */}
        {errorDetails && currentView === 'chat' ? (
          <Error401Banner
            errorDetails={errorDetails}
            onRetry={() => {
              const lastMessage = messages[messages.length - 1];
              const lastMessageText = lastMessage?.content || (lastMessage?.parts && lastMessage.parts[0]?.text) || '';
              sendMessage(lastMessageText);
            }}
          />
        ) : null}

        {/* Renderizado de Vistas */}
        {currentView === 'profile' ? (
          <ProfilePage
            onBackToChat={() => setCurrentView('chat')}
            onClearHistory={clearLocalHistory}
          />
        ) : currentView === 'help' ? (
          <HelpQuiz
            onBackToChat={() => setCurrentView('chat')}
            onStartQuery={handleLaunchHelpQuery}
          />
        ) : (
          <>
            <ChatWindow
              messages={messages}
              loading={loading}
              onSendMessage={sendMessage}
              onStopResponse={stopResponse}
              onOpenSources={(sources) => setActiveSources(sources)}
              onOpenFeedback={(msgId, type) => setFeedbackModalInfo({ msgId, type })}
              onRephraseQuery={(prevText) => setPrefilledInputText(prevText ? `Por favor amplía o especifica la normativa para: ${prevText}` : '')}
            />
            <MessageInput
              onSendMessage={sendMessage}
              loading={loading}
              prefilledText={prefilledInputText}
              setPrefilledText={setPrefilledInputText}
            />
          </>
        )}
      </main>

      {/* Drawer de Fuentes RAG */}
      <RagSourcesDrawer
        sources={activeSources}
        onClose={() => setActiveSources(null)}
      />

      {/* Modal de Calificación Feedback */}
      <FeedbackModal
        isOpen={Boolean(feedbackModalInfo)}
        type={feedbackModalInfo?.type}
        onClose={() => setFeedbackModalInfo(null)}
        onSubmit={(type, reason) => {
          if (feedbackModalInfo) {
            handleFeedback(feedbackModalInfo.msgId, type, reason);
          }
        }}
      />

      {/* Modal de Renombrar Consulta */}
      <RenameModal
        isOpen={Boolean(renameModalId)}
        currentTitle={chatToRename?.title || ''}
        onClose={() => setRenameModalId(null)}
        onSave={(newTitle) => renameConversation(renameModalId, newTitle)}
      />

      {/* Modal de Confirmación de Eliminación */}
      <DeleteConfirmModal
        isOpen={Boolean(deleteModalId)}
        onCancel={cancelDeleteConversation}
        onConfirm={confirmDeleteConversation}
      />
    </div>
  );
};

const AuthGate = () => {
  const { user, loading } = useAuth();
  const [authState, setAuthState] = useState('login');

  // authState vive en este componente, que nunca se desmonta entre login y
  // logout: sin este reset, un logout heredaría cualquier pantalla auxiliar
  // (p.ej. "forgot") en la que el usuario haya quedado antes de autenticarse,
  // en vez de ir siempre directo a login en un solo click.
  useEffect(() => {
    if (!user) {
      setAuthState('login');
    }
  }, [user]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-100">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="animate-spin text-ink-700" size={36} />
          <p className="text-xs text-ink-500 font-medium">Cargando tu asistente…</p>
        </div>
      </div>
    );
  }

  if (!user) {
    if (authState === 'forgot') {
      return <ForgotPassword onBackToLogin={() => setAuthState('login')} />;
    }
    // No hay un paso de "verificar tu correo" real: chatbot/auth.py crea la
    // cuenta y entrega la sesión en el mismo POST /api/auth/signup, sin
    // ningún flag de verificación ni envío de email. Antes había acá una
    // pantalla EmailVerification que afirmaba "hemos enviado un enlace de
    // confirmación" sin que nunca se enviara nada (mock heredado del
    // sistema 100% client-side previo) — se quitó para no mentirle al
    // usuario sobre un correo que jamás existió.
    return <LoginForm onForgotPassword={() => setAuthState('forgot')} />;
  }

  return <Dashboard />;
};

function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}

export default App;
