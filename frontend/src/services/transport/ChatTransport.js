/**
 * ChatTransport.js
 * Interface/Clase base abstracta para el transporte de mensajes de chat.
 * Define la estructura que cualquier transporte de red debe implementar.
 */
export class ChatTransport {
  /**
   * Envia mensajes al endpoint de API y retorna la respuesta.
   * @param {Object} options 
   * @returns {Promise<any>}
   */
  async sendMessages(options) {
    throw new Error('Método sendMessages no implementado.');
  }

  /**
   * Intenta reconectarse a un stream existente.
   * @param {Object} options 
   * @returns {Promise<any>}
   */
  async reconnectToStream(options) {
    throw new Error('Método reconnectToStream no implementado.');
  }
}
