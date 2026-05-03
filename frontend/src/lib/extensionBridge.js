/**
 * Bridge para comunicar el page script de Verificarro con la Chrome
 * extension `verificarro-helper`.
 *
 * El page no puede ver `chrome.*` APIs — el content script
 * `verificarro_bridge.js` de la extension es el intermediario y
 * habla con el page via `window.postMessage`.
 *
 * Protocolo:
 *
 *   page  -> ext : { source: "verificarro-page",      type, requestId, payload }
 *   ext   -> page: { source: "verificarro-extension", type, requestId, ...    }
 *
 * Tipos:
 *   - PING / PONG               handshake bidireccional
 *   - READY                     anuncio del content script al cargar
 *   - SCAN_REPUVE / RESULT      pide consulta REPUVE y recibe el resultado
 */

const HANDSHAKE_TIMEOUT_MS = 800
const SCAN_TIMEOUT_MS = 70_000

let cachedAvailability = null

function generateRequestId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `vfr-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function isExtensionMessage(event, expectedType, requestId) {
  if (event.source !== window) return false
  const data = event.data
  if (!data || data.source !== 'verificarro-extension') return false
  if (expectedType && data.type !== expectedType) return false
  if (requestId && data.requestId !== requestId) return false
  return true
}

/**
 * Detecta si la extension esta instalada via PING/PONG. Cachea el
 * resultado en memoria — la extension no se instala/desinstala dentro
 * de la misma sesion del page.
 *
 * Devuelve `false` despues de `HANDSHAKE_TIMEOUT_MS` si nadie responde.
 */
export async function isExtensionAvailable({ force = false } = {}) {
  if (!force && cachedAvailability !== null) return cachedAvailability

  cachedAvailability = await new Promise((resolve) => {
    const requestId = generateRequestId()
    const handler = (event) => {
      if (!isExtensionMessage(event, 'PONG', requestId)) return
      window.removeEventListener('message', handler)
      resolve(true)
    }
    window.addEventListener('message', handler)
    window.postMessage(
      { source: 'verificarro-page', type: 'PING', requestId },
      window.location.origin,
    )
    setTimeout(() => {
      window.removeEventListener('message', handler)
      resolve(false)
    }, HANDSHAKE_TIMEOUT_MS)
  })

  return cachedAvailability
}

/**
 * Pide a la extension que abra REPUVE, capture el resultado y lo
 * mande al backend Verificarro para parsing.
 *
 * @param {object} params
 * @param {string} [params.plate]     Placa MX (5-7 alfanum)
 * @param {string} [params.vin]       NIV/VIN (17 alfanum)
 * @param {string} [params.token]     JWT del user (Authorization Bearer)
 * @param {string} params.apiBase     Base URL del backend (https://...)
 * @returns {Promise<object>}         RepuveResult-like:
 *   { queried, plate, vin, is_stolen, has_legal_status, raw_status, error }
 */
export function scanRepuveViaExtension({ plate, vin, token, apiBase }) {
  if (!plate && !vin) {
    return Promise.reject(new Error('Falta placa o NIV'))
  }
  if (!apiBase) {
    return Promise.reject(new Error('apiBase requerido'))
  }

  return new Promise((resolve, reject) => {
    const requestId = generateRequestId()
    let settled = false

    const cleanup = () => {
      window.removeEventListener('message', handler)
    }

    const finish = (fn, value) => {
      if (settled) return
      settled = true
      cleanup()
      fn(value)
    }

    const handler = (event) => {
      if (!isExtensionMessage(event, 'SCAN_REPUVE_RESULT', requestId)) return
      const response = event.data.response || {}
      if (response.ok) {
        finish(resolve, response.result)
      } else {
        finish(reject, new Error(response.error || 'Extension scan fallo'))
      }
    }

    window.addEventListener('message', handler)
    window.postMessage(
      {
        source: 'verificarro-page',
        type: 'SCAN_REPUVE',
        requestId,
        payload: { plate, vin, token, apiBase },
      },
      window.location.origin,
    )

    setTimeout(() => {
      finish(reject, new Error('Extension scan timeout'))
    }, SCAN_TIMEOUT_MS)
  })
}

/** Util para tests — borra el cache de detect. */
export function _resetAvailabilityCache() {
  cachedAvailability = null
}
