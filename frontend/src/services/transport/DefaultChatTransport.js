import { HttpChatTransport } from './HttpChatTransport';

/**
 * DefaultChatTransport.js
 * Decodificador de respuestas de chat.
 * Procesa la respuesta HTTP y soporta:
 * - Modo de simulador local (USE_MOCK_FALLBACK)
 * - Decodificación de JSON o streams de eventos NDJSON
 */
export class DefaultChatTransport extends HttpChatTransport {
  constructor(options = {}) {
    super(options);
    this.useMockFallback = options.useMockFallback || false;
  }

  async sendMessages(options) {
    if (this.useMockFallback) {
      await new Promise((resolve) => setTimeout(resolve, 800));
      const lastMessage = options.messages[options.messages.length - 1];
      const promptText = lastMessage ? (lastMessage.content || (lastMessage.parts && lastMessage.parts[0]?.text) || '') : '';
      return this.getSimulatedRagResponse(promptText);
    }

    return await super.sendMessages(options);
  }

  async processResponseStream(response) {
    const contentType = response.headers.get('content-type');

    // Si es un stream de eventos o ndjson
    if (contentType && (contentType.includes('text/event-stream') || contentType.includes('application/x-ndjson'))) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullText = '';
      let sources = [];
      let isLowConfidence = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        fullText += chunk;
      }

      return {
        text: fullText,
        sources,
        isLowConfidence
      };
    }

    // Respuesta JSON estándar
    return await response.json();
  }

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
  }
}
