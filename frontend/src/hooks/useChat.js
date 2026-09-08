import { useSyncExternalStore, useRef, useCallback } from 'react';
import { globalChatStore } from '../services/transport/ChatStore';

/**
 * useChat.js
 * React Hook para conectar los componentes gráficos con el ChatStore.
 * Utiliza `useSyncExternalStore` para suscripciones eficientes sin re-renders pesados
 * y `useRef` para retener referencias estables de callbacks evitando stale closures.
 */
export const useChat = () => {
  const storeSnapshot = useSyncExternalStore(
    useCallback((listener) => globalChatStore.subscribe(listener), []),
    useCallback(() => globalChatStore.getSnapshot(), [])
  );

  // useRef para mantener callbacks siempre frescos sin re-suscribir
  const callbacksRef = useRef({});
  callbacksRef.current = {
    activeId: storeSnapshot.activeId
  };

  return {
    ...storeSnapshot,
    setSearchQuery: (q) => globalChatStore.setSearchQuery(q),
    setRenameModalId: (id) => globalChatStore.setRenameModalId(id),
    setActiveSources: (s) => globalChatStore.setActiveSources(s),
    createNewChat: () => globalChatStore.createNewChat(),
    selectConversation: (id) => globalChatStore.selectConversation(id),
    togglePinConversation: (id, e) => globalChatStore.togglePinConversation(id, e),
    renameConversation: (id, title) => globalChatStore.renameConversation(id, title),
    requestDeleteConversation: (id, e) => globalChatStore.requestDeleteConversation(id, e),
    cancelDeleteConversation: () => globalChatStore.cancelDeleteConversation(),
    confirmDeleteConversation: () => globalChatStore.confirmDeleteConversation(),
    clearLocalHistory: () => globalChatStore.clearLocalHistory(),
    stopResponse: () => globalChatStore.stopResponse(),
    handleFeedback: (msgId, type, reason) => globalChatStore.handleFeedback(msgId, type, reason),
    sendMessage: (text) => globalChatStore.sendMessage(text)
  };
};
