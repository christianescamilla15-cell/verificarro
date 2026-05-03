/**
 * Fetch wrapper centralizado.
 *
 * - Base URL desde VITE_API_BASE (vacío en dev → usa proxy de vite.config.js)
 * - Auto-attach JWT bearer header desde localStorage si existe
 * - Errores HTTP se traducen a { ok: false, error, status, detail }
 */

const API_BASE = import.meta.env.VITE_API_BASE || ''
const TOKEN_KEY = 'verificarro_jwt'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// Render Starter duerme el container tras 15min sin trafico. El primer
// request despues de eso tarda 30-60s en despertar el server. Browsers
// mobile cortan fetch sin response a los ~30s y el user ve "Sin conexion
// al servidor" cuando en realidad solo necesitamos esperar el cold start.
// Damos 90s de margen para POSTs que envian imagen y 30s para GETs.
const REQUEST_TIMEOUT_MS = 90_000

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  const token = getToken()
  const finalHeaders = {
    ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...headers,
  }
  // AbortController para no depender del default del browser (que
  // varia: Chrome desktop 300s, Chrome mobile 30-60s, Safari mobile 60s)
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: finalHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
  } catch (err) {
    const isAbort = err.name === 'AbortError'
    return {
      ok: false,
      status: 0,
      error: isAbort
        ? `Servidor tardó más de ${REQUEST_TIMEOUT_MS / 1000}s en responder. ` +
          'Si es la primera consulta del día, el servidor estaba "dormido" — ' +
          'reintenta y la siguiente debería ser rápida.'
        : 'Sin conexión al servidor',
      detail: err.message,
    }
  } finally {
    clearTimeout(timeoutId)
  }

  // Parseo defensivo: algunos endpoints (PDF) no devuelven JSON
  const contentType = response.headers.get('content-type') || ''
  let payload = null
  if (contentType.includes('application/json')) {
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      error: payload?.detail || `Error ${response.status}`,
      detail: payload,
    }
  }

  return { ok: true, status: response.status, data: payload, response }
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body }),
}

/**
 * Wake-up del backend Render. Render Starter duerme el container tras
 * 15min sin trafico. El primer request real (con imagen) puede tardar
 * 30-60s; este ping liviano (GET /health, ~1KB) lo despierta y queda
 * caliente para cuando el user dispare el scan real ~10-30s despues.
 *
 * Fire-and-forget: no bloquea el render, no espera respuesta. Si falla
 * (red caida, dominio mal) NO afecta nada — el siguiente request lo
 * reintentaria y mostraria su propio error.
 *
 * Llamar UNA vez al montar la app raiz.
 */
export function warmupBackend() {
  if (!API_BASE) return // dev local con proxy de vite, no necesita warm-up
  // No usamos `request()` para evitar contar este ping en cualquier
  // metric global de errores. Fetch directo, signal con timeout corto
  // (5s) — si en 5s no respondio el container esta dormido y el user
  // tendra que esperar el cold start completo en su primer request real.
  const controller = new AbortController()
  setTimeout(() => controller.abort(), 5_000)
  fetch(`${API_BASE}/health`, { signal: controller.signal })
    .catch(() => {
      // Silencioso: warm-up es best-effort
    })
}

/** Helper específico: descargar PDF como Blob. */
export async function downloadPdf(report) {
  const token = getToken()
  const res = await fetch(`${API_BASE}/api/analyze/pdf`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(report),
  })
  if (!res.ok) {
    throw new Error(`PDF download falló: ${res.status}`)
  }
  return res.blob()
}
