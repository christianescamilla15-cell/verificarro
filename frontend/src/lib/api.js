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

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  const token = getToken()
  const finalHeaders = {
    ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...headers,
  }
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: finalHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    return {
      ok: false,
      status: 0,
      error: 'Sin conexión al servidor',
      detail: err.message,
    }
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
