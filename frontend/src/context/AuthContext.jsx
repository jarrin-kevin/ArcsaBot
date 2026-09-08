import React, { createContext, useState, useContext, useEffect } from 'react';
import { globalChatStore } from '../services/transport/ChatStore';

const AuthContext = createContext(null);

// Misma base URL y convención que ya usan frontend/src/services/api.js y
// frontend/src/services/transport/HttpChatTransport.js para hablar con el
// backend real (chatbot/main.py, que incluye chatbot/auth.py como router).
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';

// El resto de la app (Sidebar.jsx, ProfilePage.jsx) espera `user.name` además
// de `user.email` — el backend sólo devuelve {id, email}, así que se deriva
// `name` acá mismo, igual que hacía el mock antes.
const toStoredUser = (backendUser) => ({
  ...backendUser,
  name: backendUser.email.split('@')[0],
});

const readErrorMessage = async (response, fallback) => {
  try {
    const data = await response.json();
    return data.error || fallback;
  } catch {
    return fallback;
  }
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Si hay una sesión guardada (token + user en localStorage), se valida
    // contra el backend antes de asumir que sigue viva: un token puede haber
    // expirado (7 días) entre visitas.
    const validateStoredSession = async () => {
      const token = localStorage.getItem('chat_token');
      const storedUser = localStorage.getItem('chat_user');

      if (!token || !storedUser) {
        setLoading(false);
        return;
      }

      try {
        const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (!response.ok) {
          throw new Error('Sesión inválida o expirada');
        }

        const data = await response.json();
        setUser(toStoredUser(data.user));
      } catch (error) {
        console.error('Error al validar la sesión guardada:', error);
        localStorage.removeItem('chat_user');
        localStorage.removeItem('chat_token');
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    validateStoredSession();
  }, []);

  const login = async (email, password) => {
    const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Credenciales inválidas.'));
    }

    const { user: backendUser, token } = await response.json();
    const userData = toStoredUser(backendUser);
    setUser(userData);
    localStorage.setItem('chat_user', JSON.stringify(userData));
    localStorage.setItem('chat_token', token);
    // El historial de chat (ChatStore.js) es un singleton que ya se
    // inicializó antes de este login; hay que avisarle que ahora hay un
    // usuario (y un token) distintos para que cargue SU historial real.
    globalChatStore.resetForAuthChange();
    return userData;
  };

  const signup = async (email, password) => {
    const response = await fetch(`${API_BASE_URL}/api/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Error al registrar usuario. Introduce datos válidos.'));
    }

    const { user: backendUser, token } = await response.json();
    const userData = toStoredUser(backendUser);
    setUser(userData);
    localStorage.setItem('chat_user', JSON.stringify(userData));
    localStorage.setItem('chat_token', token);
    globalChatStore.resetForAuthChange();
    return userData;
  };

  const logout = () => {
    // POST /api/auth/logout es un no-op del lado servidor (no hay lista de
    // revocación de tokens, ver chatbot/auth.py); igual se llama para dejar
    // el punto de extensión listo, pero el estado real se limpia acá.
    fetch(`${API_BASE_URL}/api/auth/logout`, { method: 'POST' }).catch(() => {});
    setUser(null);
    localStorage.removeItem('chat_user');
    localStorage.removeItem('chat_token');
    // Limpia el historial del usuario saliente de la memoria del store para
    // que no quede visible si otro usuario inicia sesión en la misma pestaña.
    globalChatStore.resetForAuthChange();
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth debe usarse dentro de un AuthProvider');
  }
  return context;
};
