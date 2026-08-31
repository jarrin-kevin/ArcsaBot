import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginForm } from './components/auth/LoginForm';
import { ForgotPassword } from './components/auth/ForgotPassword';
import { EmailVerification } from './components/auth/EmailVerification';
import { Sidebar } from './components/chat/Sidebar';
import { ChatWindow } from './components/chat/ChatWindow';
import { MessageInput } from './components/chat/MessageInput';
import { ApiKeyBanner } from './components/chat/ApiKeyBanner';
import { Error401Banner } from './components/chat/Error401Banner';
import { DeleteConfirmModal } from './components/chat/DeleteConfirmModal';
import { RenameModal } from './components/chat/RenameModal';
import { MobileDrawer } from './components/chat/MobileDrawer';
import { RagSourcesDrawer } from './components/chat/RagSourcesDrawer';
import { FeedbackModal } from './components/chat/FeedbackModal';
import { SettingsPage } from './components/settings/SettingsPage';
import { ProfilePage } from './components/profile/ProfilePage';
import { HelpQuiz } from './components/help/HelpQuiz';
import { useChat } from './hooks/useChat';
import { Loader2, Menu, Zap } from 'lucide-react';

const Dashboard = () => {
  const [currentView, setCurrentView] = useState('chat'); // 'chat' | 'settings' | 'profile' | 'help'
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [feedbackModalInfo, setFeedbackModalInfo] = useState(null);
  const [prefilledInputText, setPrefilledInputText] = useState('');

  const {
    conversations,
    activeId,
    messages,
    loading,
    errorDetails,
    apiKey,
    setApiKey,
    provider,
    setProvider,
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
    <div className="flex h-screen w-screen overflow-hidden bg-[#121314] font-sans text-zinc-100 antialiased">
      {/* Sidebar Fijo en Escritorio */}
      <aside className="hidden w-64 shrink-0 border-r border-[#303136] bg-[#17181B] lg:flex lg:flex-col">
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          selectConversation={selectConversation}
          requestDeleteConversation={requestDeleteConversation}
          createNewChat={createNewChat}
          currentView={currentView}
          setCurrentView={setCurrentView}
          apiKey={apiKey}
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
      <main className="flex min-w-0 flex-1 flex-col h-full bg-[#121314] relative">
        {/* Encabezado Móvil (< lg) */}
        <header className="flex items-center justify-between border-b border-[#303136] bg-[#17181B] px-4 py-3 lg:hidden shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileDrawerOpen(true)}
              aria-label="Abrir menú"
              className="text-zinc-300 hover:text-zinc-100 p-1"
            >
              <Menu className="h-5 w-5" />
            </button>

            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#1E3A6D]/50 text-[#2F6FED]">
                <Zap className="h-4 w-4" />
              </div>
              <span className="text-sm font-semibold text-zinc-100">Arcsa</span>
            </div>
          </div>

          <button
            onClick={() => setCurrentView(currentView === 'settings' ? 'chat' : 'settings')}
            className="text-xs text-[#2F6FED] font-medium hover:underline"
          >
            {currentView === 'settings' ? 'Ver Chat' : 'Configuración'}
          </button>
        </header>

        {/* Muestra ÚNICA de Alerta Superior */}
        {errorDetails && currentView === 'chat' ? (
          <Error401Banner
            errorDetails={errorDetails}
            onGoToSettings={() => setCurrentView('settings')}
            onRetry={() => sendMessage(messages[messages.length - 1]?.content || '')}
          />
        ) : !apiKey && currentView === 'chat' ? (
          <ApiKeyBanner onGoToSettings={() => setCurrentView('settings')} />
        ) : null}

        {/* Renderizado de Vistas */}
        {currentView === 'settings' ? (
          <SettingsPage
            apiKey={apiKey}
            setApiKey={setApiKey}
            provider={provider}
            setProvider={setProvider}
            onBackToChat={() => setCurrentView('chat')}
          />
        ) : currentView === 'profile' ? (
          <ProfilePage
            apiKey={apiKey}
            setApiKey={setApiKey}
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
  const [verifyEmail, setVerifyEmail] = useState('');

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#121314]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="animate-spin text-[#2F6FED]" size={36} />
          <p className="text-xs text-zinc-400 font-medium">Cargando tu asistente…</p>
        </div>
      </div>
    );
  }

  if (!user) {
    if (authState === 'forgot') {
      return <ForgotPassword onBackToLogin={() => setAuthState('login')} />;
    }
    if (authState === 'verify') {
      return <EmailVerification email={verifyEmail} onBackToLogin={() => setAuthState('login')} />;
    }
    return (
      <LoginForm
        onForgotPassword={() => setAuthState('forgot')}
        onNeedVerification={(email) => {
          setVerifyEmail(email);
          setAuthState('verify');
        }}
      />
    );
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
