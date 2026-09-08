import { ChatTransport } from './ChatTransport';

/**
 * HttpChatTransport.js
 * Implementación de transporte HTTP con soporte para:
 * - Credentials: 'include' (Preparado para cookies de sesión de backend futuro)
 * - AbortSignal para cancelación de respuesta
 * - Reintentos automáticos con retraso exponencial (Exponential Backoff Retries)
 */
export class HttpChatTransport extends ChatTransport {
  constructor(options = {}) {
    super();
    this.api = options.api || (import.meta.env.VITE_API_URL || 'http://localhost:8001');
    this.maxRetries = options.maxRetries || 3;
    this.baseDelayMs = options.baseDelayMs || 1000;
  }

  /**
   * Ejecuta una petición HTTP POST con reintentos automáticos en caso de errores de red o rate limit (429).
   */
  async sendMessages({ messages, abortSignal, customBody = {} }) {
    const endpoint = `${this.api}/api/chat`;

    const headers = {
      'Content-Type': 'application/json',
    };

    const lastMessage = messages[messages.length - 1];
    const userPrompt = lastMessage ? (lastMessage.content || (lastMessage.parts && lastMessage.parts[0]?.text) || '') : '';

    const body = JSON.stringify({
      message: userPrompt,
      messages,
      ...customBody
    });

    let attempt = 0;
    while (attempt < this.maxRetries) {
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers,
          body,
          credentials: 'include', // Preparado para cookies de sesión futuras
          signal: abortSignal,
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

        // Si es 429 (Rate limit) o 503 (Servicio no disponible), reintentar si quedan intentos
        if ((response.status === 429 || response.status === 503) && attempt < this.maxRetries - 1) {
          attempt++;
          const delay = this.baseDelayMs * Math.pow(2, attempt - 1);
          console.warn(`[HttpChatTransport] Reintento ${attempt}/${this.maxRetries} tras error ${response.status}. Esperando ${delay}ms...`);
          await new Promise((res) => setTimeout(res, delay));
          continue;
        }

        if (!response.ok) {
          throw new Error(`Error de red o servidor (${response.status})`);
        }

        return await this.processResponseStream(response);
      } catch (error) {
        if (error.name === 'AbortError') {
          throw error; // La cancelación del usuario no debe reintentarse
        }
        
        if (attempt < this.maxRetries - 1 && (!error.status || error.status === 429)) {
          attempt++;
          const delay = this.baseDelayMs * Math.pow(2, attempt - 1);
          console.warn(`[HttpChatTransport] Reintento ${attempt}/${this.maxRetries} tras fallo de red. Esperando ${delay}ms...`);
          await new Promise((res) => setTimeout(res, delay));
          continue;
        }

        throw error;
      }
    }
  }

  /**
   * Método a sobreescribir por subclases para procesar la respuesta.
   */
  async processResponseStream(response) {
    return await response.json();
  }
}
