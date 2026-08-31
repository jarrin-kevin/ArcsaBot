import React, { createContext, useState, useContext, useEffect } from 'react';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user session exists in localStorage (mock auth)
    const storedUser = localStorage.getItem('chat_user');
    if (storedUser) {
      setUser(JSON.parse(storedUser));
    }
    setLoading(false);
  }, []);

  const login = async (email, password) => {
    // Mock login delay
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (email && password.length >= 6) {
          const userData = { email, name: email.split('@')[0] };
          setUser(userData);
          localStorage.setItem('chat_user', JSON.stringify(userData));
          resolve(userData);
        } else {
          reject(new Error('Credenciales inválidas o contraseña muy corta (min 6 caracteres).'));
        }
      }, 800);
    });
  };

  const signup = async (email, password) => {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (email && password.length >= 6) {
          const userData = { email, name: email.split('@')[0] };
          setUser(userData);
          localStorage.setItem('chat_user', JSON.stringify(userData));
          resolve(userData);
        } else {
          reject(new Error('Error al registrar usuario. Introduce datos válidos.'));
        }
      }, 800);
    });
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem('chat_user');
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
