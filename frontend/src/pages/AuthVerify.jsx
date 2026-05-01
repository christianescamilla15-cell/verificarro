import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, setToken } from '../lib/api.js'
import Spinner from '../components/Spinner.jsx'

export default function AuthVerify() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState(null)

  useEffect(() => {
    const email = params.get('email')
    const token = params.get('token')
    if (!email || !token) {
      setError('Link incompleto — pide uno nuevo desde la página de login.')
      return
    }
    let mounted = true
    api.post('/api/auth/verify', { email, token }).then((res) => {
      if (!mounted) return
      if (!res.ok) {
        setError(res.error || 'Link inválido o expirado.')
        return
      }
      setToken(res.data.access_token)
      // Hard reload para que useAuth re-fetch /me con el token nuevo
      window.location.href = '/'
    })
    return () => { mounted = false }
  }, [params, navigate])

  if (error) {
    return (
      <div className="auth-card">
        <h1>⚠️ {error}</h1>
        <a href="/login" className="primary big">Pedir link nuevo</a>
      </div>
    )
  }
  return <Spinner message="Verificando tu link…" />
}
