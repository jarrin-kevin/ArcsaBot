import { DefaultChatTransport } from './DefaultChatTransport';
import { createUIMessage, createTextPart } from './uiMessages';
import { processUiMessageStream } from './processUiMessageStream';

// TODO: [TEMPORAL - FRONTEND F5] Borrar o reemplazar por llamadas a la API del backend cuando se implemente la base de datos real.
const SESSION_STORAGE_KEY = 'arcsa_chat_sessions_temp';

/**
 * ChatStore.js
 * Controlador de estado agnóstico fuera de React.
 * Aplica patrones Senior Frontend:
 * - Inyección de dependencias para el transporte
 * - Snapshot memoizado para suscripción eficiente en React 18 (useSyncExternalStore)
 */
export class ChatStore {
  constructor(options = {}) {
    this.listeners = new Set();
    this.conversations = [];
    this.activeId = null;
    this.loading = false;
    this.errorDetails = null;
    this.apiKey = '';
    this.provider = 'OpenRouter';
    this.searchQuery = '';
    this.pinnedIds = [];
    this.deleteModalId = null;
    this.renameModalId = null;
    this.activeSources = null;
    this.feedbackState = {};
    this.abortController = null;

    // Inyección de Dependencia: Permite pasar un transporte personalizado o mock para tests
    this.transport = options.transport || new DefaultChatTransport();

    // Cache interno del snapshot para optimización de React 18 useSyncExternalStore
    this._snapshot = null;

    this.init();
    this.updateSnapshot();
  }

  // SUSCRIPCIÓN PARA REACT 18 (useSyncExternalStore)
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Actualiza la referencia del snapshot memoizado solo cuando hay una mutación de estado.
   */
  updateSnapshot() {
    const activeChat = this.conversations.find(c => c.id === this.activeId);
    this._snapshot = {
      conversations: this.conversations,
      activeId: this.activeId,
      messages: activeChat ? activeChat.messages : [],
      loading: this.loading,
      errorDetails: this.errorDetails,
      apiKey: this.apiKey,
      provider: this.provider,
      searchQuery: this.searchQuery,
      pinnedIds: this.pinnedIds,
      deleteModalId: this.deleteModalId,
      renameModalId: this.renameModalId,
      activeSources: this.activeSources,
      feedbackState: this.feedbackState,
    };
  }

  notify() {
    this.updateSnapshot(); // Recrea la referencia del snapshot solo al notificar cambios
    for (const listener of this.listeners) {
      listener();
    }
    this.persistTempSessions();
  }

  /**
   * Retorna la referencia estable del snapshot memoizado.
   * Evita bucles de re-render en React 18.
   */
  getSnapshot() {
    if (!this._snapshot) {
      this.updateSnapshot();
    }
    return this._snapshot;
  }

  // TODO: [TEMPORAL - FRONTEND F5] Reemplazar por llamado al endpoint del backend al iniciar sesión.
  init() {
    try {
      const stored = sessionStorage.getItem(SESSION_STORAGE_KEY);
      if (stored) {
        this.conversations = JSON.parse(stored);
        if (this.conversations.length > 0) {
          this.activeId = this.conversations[0].id;
        } else {
          this.createNewChat();
        }
      } else {
        this.createNewChat();
      }
    } catch (e) {
      console.warn('[ChatStore] Error al cargar sessionStorage temporal:', e);
      this.createNewChat();
    }
  }

  // TODO: [TEMPORAL - FRONTEND F5] Reemplazar por guardado en base de datos mediante el backend.
  persistTempSessions() {
    try {
      if (this.conversations.length > 0) {
        sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(this.conversations));
      }
    } catch (e) {
      console.warn('[ChatStore] Error al guardar en sessionStorage temporal:', e);
    }
  }

  setApiKey(key) {
    this.apiKey = key;
    this.notify();
  }

  setProvider(prov) {
    this.provider = prov;
    this.notify();
  }

  setSearchQuery(query) {
    this.searchQuery = query;
    this.notify();
  }

  setRenameModalId(id) {
    this.renameModalId = id;
    this.notify();
  }

  setActiveSources(sources) {
    this.activeSources = sources;
    this.notify();
  }

  createNewChat() {
    const newChat = {
      id: Date.now().toString(),
      title: `Consulta ${this.conversations.length + 1}`,
      messages: [],
      timestamp: new Date().toISOString()
    };
    this.conversations = [newChat, ...this.conversations];
    this.activeId = newChat.id;
    this.errorDetails = null;
    this.notify();
  }

  selectConversation(id) {
    this.activeId = id;
    this.errorDetails = null;
    this.notify();
  }

  togglePinConversation(id, e) {
    if (e) e.stopPropagation();
    this.pinnedIds = this.pinnedIds.includes(id)
      ? this.pinnedIds.filter(item => item !== id)
      : [...this.pinnedIds, id];
    this.notify();
  }

  renameConversation(id, newTitle) {
    this.conversations = this.conversations.map(c =>
      c.id === id ? { ...c, title: newTitle } : c
    );
    this.renameModalId = null;
    this.notify();
  }

  requestDeleteConversation(id, e) {
    if (e) e.stopPropagation();
    this.deleteModalId = id;
    this.notify();
  }

  cancelDeleteConversation() {
    this.deleteModalId = null;
    this.notify();
  }

  confirmDeleteConversation() {
    if (!this.deleteModalId) return;
    const targetId = this.deleteModalId;
    this.conversations = this.conversations.filter(c => c.id !== targetId);
    this.deleteModalId = null;

    if (this.activeId === targetId) {
      if (this.conversations.length > 0) {
        this.activeId = this.conversations[0].id;
      } else {
        this.createNewChat();
      }
    } else {
      this.notify();
    }
  }

  // TODO: [TEMPORAL - FRONTEND F5] Borrar o adaptar para limpiar historial en backend.
  clearLocalHistory() {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    this.conversations = [];
    this.pinnedIds = [];
    this.createNewChat();
  }

  stopResponse() {
    if (this.abortController) {
      this.abortController.abort();
    }
    this.loading = false;
    this.notify();
  }

  handleFeedback(msgId, type, reason = '') {
    this.feedbackState = {
      ...this.feedbackState,
      [msgId]: { type, reason }
    };
    this.notify();
  }

  async sendMessage(text) {
    if (!text || !text.trim()) return;

    this.errorDetails = null;
    this.loading = true;

    const userMessage = createUIMessage({
      id: Date.now().toString(),
      role: 'user',
      status: 'sent',
      parts: [createTextPart(text)]
    });

    const assistantPlaceholderId = (Date.now() + 1).toString();
    const assistantPlaceholder = createUIMessage({
      id: assistantPlaceholderId,
      role: 'assistant',
      status: 'sending',
      parts: []
    });

    const currentChat = this.conversations.find(c => c.id === this.activeId);
    const existingMessages = currentChat ? currentChat.messages : [];
    const updatedMessages = [...existingMessages, userMessage, assistantPlaceholder];

    const newTitle = existingMessages.length === 0
      ? text.slice(0, 32) + (text.length > 32 ? '...' : '')
      : (currentChat ? currentChat.title : 'Consulta');

    this.conversations = this.conversations.map(chat => {
      if (chat.id === this.activeId) {
        return { ...chat, title: newTitle, messages: updatedMessages };
      }
      return chat;
    });
    this.notify();

    this.abortController = new AbortController();

    try {
      const responseData = await this.transport.sendMessages({
        messages: updatedMessages.filter(m => m.id !== assistantPlaceholderId),
        apiKey: this.apiKey,
        provider: this.provider,
        abortSignal: this.abortController.signal
      });

      const updatedAssistantMessage = processUiMessageStream(assistantPlaceholder, responseData);

      this.conversations = this.conversations.map(chat => {
        if (chat.id === this.activeId) {
          const finalMsgs = chat.messages.map(m =>
            m.id === assistantPlaceholderId ? updatedAssistantMessage : m
          );
          return { ...chat, messages: finalMsgs };
        }
        return chat;
      });
    } catch (err) {
      if (err.name === 'AbortError') {
        console.log('[ChatStore] Consulta cancelada por el usuario.');
      } else {
        console.error('[ChatStore] Error al enviar mensaje:', err);
        const code = err.code || 'NETWORK_ERROR';
        this.errorDetails = {
          code,
          message: err.message || 'No se pudo conectar con el servidor backend.'
        };

        this.conversations = this.conversations.map(chat => {
          if (chat.id === this.activeId) {
            const finalMsgs = chat.messages.map(m =>
              m.id === assistantPlaceholderId
                ? { ...m, status: 'error', parts: [createTextPart('Error al procesar la consulta.')] }
                : m
            );
            return { ...chat, messages: finalMsgs };
          }
          return chat;
        });
      }
    } finally {
      this.loading = false;
      this.abortController = null;
      this.notify();
    }
  }
}

// Instancia única global del store con inyección de dependencia por defecto
export const globalChatStore = new ChatStore();
