import { useCallback, useEffect, useState } from 'react'
import { api, clearToken, getToken } from '../lib/api.js'

/**
 * Hook de auth: lee JWT del localStorage, hace fetch a /me al montar
 * y expone {user, loading, logout, refresh}.
 *
 * Si no hay token o el token es inválido, user queda en null.
 */
export function useAuth() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    setLoading(true)
    const res = await api.get('/api/auth/me')
    if (res.ok) {
      setUser(res.data)
    } else {
      clearToken()
      setUser(null)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    if (getToken()) {
      await api.post('/api/auth/logout')
    }
    clearToken()
    setUser(null)
  }, [])

  return { user, loading, logout, refresh }
}
