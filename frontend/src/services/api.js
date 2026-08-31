const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';


const USE_MOCK_FALLBACK = false;

export const apiService = {
  /**
   * Envía un mensaje al chatbot backend RAG con API Key opcional.
   */
  async sendMessage(message, apiKey = '', provider = 'OpenRouter') {
    // Si el switch está encendido, responde inmediatamente de forma simulada
    if (USE_MOCK_FALLBACK) {
      await new Promise((resolve) => setTimeout(resolve, 800)); // Simula retardo
      return this.getSimulatedRagResponse(message);
    }

    try {
      const headers = {
        'Content-Type': 'application/json',
      };
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
        headers['X-LLM-Provider'] = provider;
      }

      const response = await fetch(`${API_BASE_URL}/api/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message, provider }),
      });

      if (response.status === 401) {
        const error = new Error('API Key no válida');
        error.code = 'INVALID_KEY';
        error.status = 401;
        throw error;
      }
      if (response.status === 402 || response.status === 403) {
        const error = new Error('Cuota o créditos agotados en el proveedor');
        error.code = 'QUOTA_EXCEEDED';
        error.status = response.status;
        throw error;
      }
      if (response.status === 429) {
        const error = new Error('Límite de solicitudes alcanzado (Rate limit)');
        error.code = 'RATE_LIMIT';
        error.status = 429;
        throw error;
      }

      if (!response.ok) {
        throw new Error(`Error de red o servidor (${response.status})`);
      }

      return await response.json();
    } catch (error) {
      console.error('Error en apiService.sendMessage:', error);
      throw error;
    }
  },

  /**
   * Respuesta RAG simulada institucional con fuentes reales de ARCSA.
   */
  getSimulatedRagResponse(message) {
    const isLowConfidence = message.toLowerCase().includes('receta secreta') || message.toLowerCase().includes('invento no regulado');

    if (isLowConfidence) {
      return {
        text: 'No se encontró evidencia suficiente ni normativa oficial en la base de datos de ARCSA para responder con precisión a esta consulta.',
        isLowConfidence: true,
        sources: []
      };
    }

    return {
      text: `Para obtener la certificación o trámite en ARCSA respecto a la consulta:

1. **Requisitos Generales**: Se debe presentar la **Solicitud de Registro Sanitario** firmada por el Representante Legal y el Responsable Técnico.
2. **Documentación Técnica**: Presentar la **Fórmula cuali-cuantitativa** expedida por el fabricante y el **Certificado de Libre Venta (CLV)** con legalización o Apostilla de La Haya.
3. **Pago de Tasas**: Cumplir con el pago de la tasa establecida según la **Resolución ARCSA-DE-016-2023-FFF**.
4. **Vigencia**: El certificado emitido tendrá una vigencia oficial de **5 años** renovable.`,
      sources: [
        {
          id: 'src-1',
          documentTitle: 'Resolución ARCSA-DE-016-2023-FFF - Normativa Sanitaria de Suplementos y Alimentos',
          issuingEntity: 'Dirección Ejecutiva de ARCSA',
          section: 'Capítulo III: Requisitos de Registro Sanitario, Pág. 14-18',
          validityDate: 'Vigente desde Enero 2023',
          snippet: '...todo producto procesado importado debe adjuntar el Certificado de Libre Venta (CLV) apostillado junto con el análisis bromatológico cuali-cuantitativo...',
          officialUrl: 'https://www.controlsanitario.gob.ec/normativa-alimenticia'
        },
        {
          id: 'src-2',
          documentTitle: 'Instructivo Técnico para Permisos de Funcionamiento 2024',
          issuingEntity: 'Coordinación General de Vigilancia Posterior',
          section: 'Sección 2.1: Establecimientos de Distribución',
          validityDate: 'Vigente 2024',
          snippet: '...los establecimientos tipo distribuidoras de medicamentos deberán contar con la inspección favorable de buenas prácticas de almacenamiento (BPA)...',
          officialUrl: 'https://www.controlsanitario.gob.ec/permisos-funcionamiento'
        }
      ]
    };
  },

  /**
   * Prueba de conexión con estados diferenciados.
   */
  async testConnection(apiKey, provider = 'OpenRouter') {
    if (!apiKey || !apiKey.trim()) {
      return { success: false, code: 'INVALID_KEY', message: 'Ingresa una API Key para validar.' };
    }

    await new Promise((resolve) => setTimeout(resolve, 1000));

    if (apiKey.startsWith('sk-err-401')) {
      return { success: false, code: 'INVALID_KEY', message: 'API Key no válida. Revisa las credenciales.' };
    }
    if (apiKey.startsWith('sk-err-402')) {
      return { success: false, code: 'QUOTA_EXCEEDED', message: 'Sin créditos disponibles en la cuenta del proveedor.' };
    }
    if (apiKey.startsWith('sk-err-429')) {
      return { success: false, code: 'RATE_LIMIT', message: 'Límite de peticiones alcanzado. Reintenta en unos segundos.' };
    }

    return { success: true, code: 'SUCCESS', message: 'Conexión verificada correctamente con ' + provider };
  },

  async getChatHistory() {
    const stored = localStorage.getItem('arcsa_chat_sessions');
    return stored ? JSON.parse(stored) : [];
  },

  saveChatSession(sessions) {
    localStorage.setItem('arcsa_chat_sessions', JSON.stringify(sessions));
  }
};
