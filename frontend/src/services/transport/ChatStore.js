import { DefaultChatTransport } from './DefaultChatTransport';
import { createUIMessage, createTextPart, createSourcesPart, createReasoningPart } from './uiMessages';
import { processUiMessageStream } from './processUiMessageStream';

// Misma base URL y convención que ya usan frontend/src/services/api.js y
// frontend/src/services/transport/HttpChatTransport.js para hablar con el
// backend real (chatbot/main.py). El token de sesión ('chat_token') es el
// mismo que ya persiste frontend/src/context/AuthContext.jsx en localStorage
// tras login/signup.
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';

function getAuthToken() {
  try {
    return localStorage.getItem('chat_token');
  } catch (e) {
    return null;
  }
}

/**
 * Wrapper mínimo de fetch para los endpoints de /api/conversations: agrega
 * el header Authorization cuando hay sesión y normaliza errores HTTP a
 * Error con `.status`, en el mismo espíritu que HttpChatTransport.js.
 */
async function apiRequest(path, options = {}) {
  const token = getAuthToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (!response.ok) {
    let message = `Error de red o servidor (${response.status})`;
    try {
      const data = await response.json();
      if (data && data.error) message = data.error;
    } catch (e) {
      // Cuerpo no-JSON o vacío: se conserva el mensaje genérico de arriba.
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) return null;
  return response.json();
}

/**
 * Convierte el resumen de GET /api/conversations al stub del store.
 * `messages: null` = "aún no cargados" (ver _ensureMessagesLoaded);
 * `messages: []` = "cargados, sin ninguno".
 */
function backendSummaryToConversationStub(c) {
  return {
    id: String(c.id),
    title: c.title,
    messages: null,
    timestamp: c.updatedAt,
    _persisted: true
  };
}

/** Convierte un mensaje del backend (GET .../{id}) a un UIMessage por partes. */
function backendMessageToUiMessage(msg) {
  const parts = [];
  if (msg.content) parts.push(createTextPart(msg.content));
  if (msg.metadata && msg.metadata.reasoning) parts.push(createReasoningPart(msg.metadata.reasoning));
  if (msg.sources && msg.sources.length > 0) parts.push(createSourcesPart(msg.sources));

  return createUIMessage({
    id: String(msg.id),
    role: msg.role,
    status: 'sent',
    parts,
    metadata: msg.metadata || {},
    timestamp: msg.createdAt
  });
}

/**
 * ChatStore.js
 * Controlador de estado agnóstico fuera de React (inyección de dependencias
 * para el transporte + snapshot memoizado para useSyncExternalStore de
 * React 18).
 *
 * Persistencia de historial, atada al usuario logueado:
 * - Con sesión ('chat_token' en localStorage, ver AuthContext): el
 *   historial vive en chatbot/data/users.db vía chatbot/conversations.py.
 *   Un chat nuevo es sólo local hasta el primer mensaje real (ver
 *   _ensurePersistedConversation), para no crear conversaciones vacías.
 * - Sin sesión: se sigue chateando con normalidad pero sólo en memoria
 *   (sin respaldo en localStorage, para no confundirse con el historial
 *   real de un usuario logueado — ver `_persisted`).
 * - Si falla una llamada de persistencia, se loguea un warning pero el
 *   chat sigue funcionando en memoria: la persistencia nunca debe romper
 *   la experiencia de usuario.
 */
export class ChatStore {
  constructor(options = {}) {
    this.listeners = new Set();
    this.conversations = [];
    this.activeId = null;
    this.loading = false;
    this.errorDetails = null;
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
      messages: (activeChat && activeChat.messages) || [],
      loading: this.loading,
      errorDetails: this.errorDetails,
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

  /**
   * Carga inicial: con sesión trae conversaciones reales del backend y
   * precarga la más reciente; sin sesión o si el backend falla, arranca
   * con un chat nuevo en memoria (ver docstring de la clase).
   */
  async init() {
    this.loading = true;
    this.notify();

    if (!getAuthToken()) {
      this.conversations = [];
      this.createNewChat();
      this.loading = false;
      this.notify();
      return;
    }

    try {
      const data = await apiRequest('/api/conversations');
      const list = (data.conversations || []).map(backendSummaryToConversationStub);

      if (list.length > 0) {
        this.conversations = list;
        this.activeId = list[0].id;
        await this._ensureMessagesLoaded(this.activeId);
      } else {
        this.conversations = [];
        this.createNewChat();
      }
    } catch (e) {
      console.warn('[ChatStore] Error al cargar el historial de conversaciones del backend:', e);
      this.conversations = [];
      this.createNewChat();
    } finally {
      this.loading = false;
      this.notify();
    }
  }

  /**
   * Carga perezosa de mensajes de una conversación persistida (sólo la
   * primera vez; luego queda cacheada). No hace nada para chats locales
   * ni para conversaciones ya cargadas.
   */
  async _ensureMessagesLoaded(id) {
    const chat = this.conversations.find(c => c.id === id);
    if (!chat || !chat._persisted || chat.messages !== null) return;

    try {
      const data = await apiRequest(`/api/conversations/${id}`);
      const messages = (data.messages || []).map(backendMessageToUiMessage);
      this.conversations = this.conversations.map(c => (c.id === id ? { ...c, messages } : c));
    } catch (e) {
      console.warn('[ChatStore] Error al cargar los mensajes de la conversación:', e);
      this.conversations = this.conversations.map(c => (c.id === id ? { ...c, messages: [] } : c));
    }
    this.notify();
  }

  /**
   * Crea la conversación activa en el backend si aún no existe (primer
   * mensaje real, ver docstring de la clase). Devuelve el id real, o
   * `null` si no hay sesión o la creación falló (el chat sigue en memoria).
   */
  async _ensurePersistedConversation(title) {
    const chat = this.conversations.find(c => c.id === this.activeId);
    if (!chat) return null;
    if (chat._persisted) return chat.id;
    if (!getAuthToken()) return null;

    try {
      const created = await apiRequest('/api/conversations', {
        method: 'POST',
        body: JSON.stringify({ title })
      });
      const oldId = chat.id;
      const realId = String(created.id);

      this.conversations = this.conversations.map(c =>
        c.id === oldId ? { ...c, id: realId, _persisted: true, timestamp: created.updatedAt } : c
      );
      if (this.activeId === oldId) this.activeId = realId;
      if (this.deleteModalId === oldId) this.deleteModalId = realId;
      if (this.renameModalId === oldId) this.renameModalId = realId;
      this.pinnedIds = this.pinnedIds.map(id => (id === oldId ? realId : id));

      return realId;
    } catch (e) {
      console.warn('[ChatStore] No se pudo crear la conversación en el backend; continúa sólo en memoria.', e);
      return null;
    }
  }

  /** Persiste un mensaje real (nunca placeholders "sending"/"error") en el backend. */
  async _persistMessage(conversationId, uiMessage) {
    if (!conversationId) return;

    try {
      const textPart = uiMessage.parts.find(p => p.type === 'text');
      const sourcesPart = uiMessage.parts.find(p => p.type === 'sources');
      const reasoningPart = uiMessage.parts.find(p => p.type === 'reasoning');

      const metadataToSend = {
        ...(uiMessage.metadata || {}),
        ...(reasoningPart ? { reasoning: reasoningPart.text } : {})
      };

      await apiRequest(`/api/conversations/${conversationId}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          role: uiMessage.role,
          content: textPart ? textPart.text : '',
          sources: sourcesPart ? sourcesPart.sources : null,
          metadata: Object.keys(metadataToSend).length > 0 ? metadataToSend : null
        })
      });
    } catch (e) {
      console.warn('[ChatStore] No se pudo guardar el mensaje en el backend (la conversación sigue en memoria para esta sesión).', e);
    }
  }

  async _deleteConversationRemote(id) {
    try {
      await apiRequest(`/api/conversations/${id}`, { method: 'DELETE' });
    } catch (e) {
      console.warn('[ChatStore] No se pudo borrar la conversación en el backend.', e);
    }
  }

  /**
   * `globalChatStore` es un singleton que sólo lee 'chat_token' una vez, al
   * cargar el módulo. AuthContext.jsx llama a este método tras cada
   * login/signup/logout en caliente para que el store vuelva a resolver el
   * historial con el token actualizado — si no, el historial de un usuario
   * podría seguir visible tras el login de otro en la misma pestaña.
   */
  resetForAuthChange() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    this.conversations = [];
    this.activeId = null;
    this.pinnedIds = [];
    this.deleteModalId = null;
    this.renameModalId = null;
    this.errorDetails = null;
    this.activeSources = null;
    this.feedbackState = {};
    this.loading = false;
    this.init();
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

  /**
   * Crea un chat nuevo sólo en memoria (id temporal `local-...`); recién se
   * persiste en el backend al enviar el primer mensaje real (ver
   * _ensurePersistedConversation), para no crear conversaciones vacías.
   */
  createNewChat() {
    const newChat = {
      id: `local-${Date.now()}`,
      title: `Consulta ${this.conversations.length + 1}`,
      messages: [],
      timestamp: new Date().toISOString(),
      _persisted: false
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
    this._ensureMessagesLoaded(id);
  }

  togglePinConversation(id, e) {
    if (e) e.stopPropagation();
    this.pinnedIds = this.pinnedIds.includes(id)
      ? this.pinnedIds.filter(item => item !== id)
      : [...this.pinnedIds, id];
    this.notify();
  }

  // El renombre sólo se aplica en memoria: no hay endpoint de backend para
  // persistir el título, así que un refresh muestra el título original.
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
    const targetChat = this.conversations.find(c => c.id === targetId);

    this.conversations = this.conversations.filter(c => c.id !== targetId);
    this.deleteModalId = null;

    if (targetChat && targetChat._persisted) {
      this._deleteConversationRemote(targetId);
    }

    if (this.activeId === targetId) {
      if (this.conversations.length > 0) {
        this.activeId = this.conversations[0].id;
        this._ensureMessagesLoaded(this.activeId);
        this.notify();
      } else {
        this.createNewChat(); // ya notifica internamente
      }
    } else {
      this.notify();
    }
  }

  /**
   * Borra todo el historial del usuario actual (backend y memoria) y
   * arranca un chat nuevo. Invocado desde ProfilePage.jsx ("Borrar
   * historial local de consultas").
   */
  async clearLocalHistory() {
    const persistedIds = this.conversations.filter(c => c._persisted).map(c => c.id);

    this.conversations = [];
    this.pinnedIds = [];
    this.createNewChat();

    if (persistedIds.length > 0) {
      try {
        await Promise.all(persistedIds.map(id => apiRequest(`/api/conversations/${id}`, { method: 'DELETE' })));
      } catch (e) {
        console.warn('[ChatStore] Ocurrió un error al borrar el historial completo en el backend.', e);
      }
    }
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
    const existingMessages = (currentChat && currentChat.messages) || [];
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

    // Persistencia real en backend (no-op silencioso sin sesión iniciada o
    // si el backend no responde, ver docstring de la clase).
    const conversationId = await this._ensurePersistedConversation(newTitle);
    await this._persistMessage(conversationId, userMessage);

    this.abortController = new AbortController();

    try {
      const responseData = await this.transport.sendMessages({
        messages: updatedMessages.filter(m => m.id !== assistantPlaceholderId),
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

      await this._persistMessage(conversationId, updatedAssistantMessage);
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
        // El mensaje de error NO se persiste en el backend: sólo se guardan
        // respuestas reales del asistente (ver chatbot/conversations.py).
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
