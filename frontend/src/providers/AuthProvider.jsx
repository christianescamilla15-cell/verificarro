import { useCallback, useEffect, useState } from 'react'
import { AuthContext } from '../hooks/useAuth.js'
import { api, clearToken, getToken } from '../lib/api.js'

/**
 * Provider que centraliza el state de auth y lo expone vía AuthContext.
 *
 * Montado en main.jsx alrededor de <App>. Los consumers usan `useAuth()`
 * en lugar de hacer su propio fetch — un solo `/api/auth/me` por boot,
 * compartido por Header + Dashboard + AuthVerify.
 */
export default function AuthProvider({ children }) {
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

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
