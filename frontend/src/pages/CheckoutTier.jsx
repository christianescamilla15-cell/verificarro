import { useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { Lock, ShieldCheck, AlertTriangle, ArrowLeft, Crown, Building2 } from 'lucide-react'
import { api } from '../lib/api.js'

/**
 * Checkout B2B para tiers `search` y `dealer`. Distinto al PaywallModal
 * porque NO requiere `report_id` previo — son passes mensuales que se
 * compran sin haber escaneado nada antes.
 */
const TIER_CONFIG = {
  search: {
    icon: <Crown size={28} />,
    name: 'Búsqueda activa',
    price: 199,
    cap: '50 reportes / mes',
    description: 'Hasta 50 reportes en 30 días + WhatsApp prioritario.',
  },
  dealer: {
    icon: <Building2 size={28} />,
    name: 'Dealer / Lotero',
    price: 1499,
    cap: '500 reportes / mes',
    description: 'Hasta 500 reportes en 30 días + API + multi-usuario + onboarding.',
  },
}

export default function CheckoutTier() {
  const [params] = useSearchParams()
  const tier = params.get('tier') || 'search'
  const config = TIER_CONFIG[tier] || TIER_CONFIG.search
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    if (!email || !email.includes('@')) {
      setError('Necesitamos tu email para mandar la confirmación del plan.')
      return
    }
    setLoading(true)
    const res = await api.post('/api/payments/checkout', {
      tier,
      payer_email: email,
      title_hint: `${config.name} (${config.cap})`,
    })
    setLoading(false)
    if (!res.ok) {
      setError(res.error || 'No pudimos iniciar el pago. Intenta de nuevo.')
      return
    }
    window.location.href = res.data.init_point
  }

  return (
    <main className="report-view">
      <Link to="/precios" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)', marginBottom: 16 }}>
        <ArrowLeft size={16} /> Ver todos los planes
      </Link>

      <div className="auth-card" style={{ maxWidth: 560 }}>
        <div className="tier-header">
          <div className="tier-icon">{config.icon}</div>
          <div>
            <h1 style={{ margin: 0 }}>{config.name}</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              {config.description}
            </p>
          </div>
        </div>

        <div className="tier-summary">
          <div>
            <span className="muted small">Mensualidad</span>
            <div style={{ fontSize: 'var(--fs-2xl)', fontWeight: 'var(--fw-bold)', color: 'var(--accent-text)' }}>
              ${config.price.toLocaleString('es-MX')} MXN
            </div>
          </div>
          <div>
            <span className="muted small">Incluye</span>
            <div style={{ fontWeight: 'var(--fw-semibold)' }}>{config.cap}</div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="paywall-form" style={{ marginTop: 16 }}>
          <label>
            Tu nombre
            <input
              type="text"
              placeholder="Christian Hernández"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Email (recibes instrucciones de activación)
            <input
              type="email" required
              placeholder="tu@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            WhatsApp (para activarte el plan + soporte)
            <input
              type="tel"
              placeholder="55 1234 5678"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </label>

          <button type="submit" className="primary big" disabled={loading}>
            <Lock size={18} />
            {loading ? 'Iniciando pago…' : `Pagar $${config.price.toLocaleString('es-MX')} MXN`}
          </button>

          {error && (
            <div className="error">
              <AlertTriangle size={16} /> {error}
            </div>
          )}
          <p className="micro-trust">
            <ShieldCheck size={12} />
            Pago seguro vía Mercado Pago · Tarjeta, OXXO, SPEI
          </p>
          <p className="muted small" style={{ textAlign: 'center', marginTop: 12 }}>
            Una vez confirmado el pago, te activamos el plan en menos de 1 hora
            hábil y te llega un email con tus credenciales + tutorial.
          </p>
        </form>
      </div>
    </main>
  )
}
