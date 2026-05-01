import { useState } from 'react'
import { api } from '../lib/api.js'

export default function Login() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState(null)

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    const res = await api.post('/api/auth/request-link', { email })
    setLoading(false)
    if (!res.ok) {
      setError(res.error || 'No pudimos mandar el link.')
      return
    }
    setSent(true)
  }

  if (sent) {
    return (
      <div className="auth-card">
        <h1>📧 Revisa tu email</h1>
        <p>Te mandamos un link a <strong>{email}</strong>. Da clic dentro de los próximos 15 minutos. Si no llega, revisa spam.</p>
        <button className="link-button" onClick={() => setSent(false)}>
          ← Cambiar email
        </button>
      </div>
    )
  }

  return (
    <div className="auth-card">
      <h1>Iniciar sesión</h1>
      <p className="muted">Sin contraseña. Te mandamos un link al email para entrar.</p>
      <form onSubmit={submit}>
        <label>
          Tu email
          <input
            type="email" required
            placeholder="tu@email.com"
            value={email} onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <button type="submit" className="primary big" disabled={loading || !email}>
          {loading ? 'Mandando…' : 'Mandarme el link'}
        </button>
        {error && <div className="error">⚠️ {error}</div>}
      </form>
    </div>
  )
}
