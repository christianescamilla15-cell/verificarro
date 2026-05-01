import { useState } from 'react'
import { X, Lock, AlertTriangle, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api.js'

/**
 * Modal de desbloqueo. Recibe `report_id` y abre Mercado Pago.
 *
 * Pide email (para mandar el reporte) y opcional URL del anuncio
 * (para que el unlock incluya scrape de ML + análisis fotos + precio
 * comparado). Si no pegan URL, el unlock entrega el detalle de
 * REPUVE pero NO precio justo ni fotos IA.
 */
export default function PaywallModal({ reportId, onClose }) {
  const [email, setEmail] = useState('')
  const [listingUrl, setListingUrl] = useState('')
  const [tier, setTier] = useState('basic')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleUnlock(e) {
    e.preventDefault()
    setError(null)
    if (!email || !email.includes('@')) {
      setError('Necesitamos tu email para mandarte el reporte.')
      return
    }
    setLoading(true)
    const res = await api.post('/api/payments/checkout', {
      report_id: reportId,
      payer_email: email,
      listing_url: listingUrl || null,
      tier,
      title_hint: listingUrl ? extractTitleHint(listingUrl) : null,
    })
    setLoading(false)
    if (!res.ok) {
      setError(res.error || 'No pudimos iniciar el pago. Intenta de nuevo.')
      return
    }
    window.location.href = res.data.init_point
  }

  return (
    <div className="vin-scanner-overlay" role="dialog" aria-modal="true">
      <div className="vin-scanner paywall-modal">
        <div className="vin-scanner-header">
          <h2>
            <Lock size={20} style={{ verticalAlign: '-3px', marginRight: 6, color: 'var(--accent-text)' }} />
            Desbloquear reporte completo
          </h2>
          <button onClick={onClose} className="close-btn" aria-label="Cerrar">
            <X size={22} />
          </button>
        </div>

        <form onSubmit={handleUnlock} className="paywall-form">
          <label>
            Email (te mandamos el reporte aquí)
            <input
              type="email" required
              placeholder="tu@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>

          <label>
            URL del anuncio en Mercado Libre <span className="muted">(opcional)</span>
            <input
              type="url"
              placeholder="https://auto.mercadolibre.com.mx/..."
              value={listingUrl}
              onChange={(e) => setListingUrl(e.target.value)}
            />
            <small className="muted">
              Sin URL: REPUVE detallado + escaneo de VIN físico. Con URL:
              además precio justo, análisis de fotos con IA, y banderas en
              la descripción.
            </small>
          </label>

          <div className="tier-select">
            <label className={`tier ${tier === 'basic' ? 'active' : ''}`}>
              <input
                type="radio" name="tier" value="basic"
                checked={tier === 'basic'}
                onChange={() => setTier('basic')}
              />
              <div>
                <strong>Básico — $49 MXN</strong>
                <small>Reporte completo + escaneo VIN</small>
              </div>
            </label>
            <label className={`tier ${tier === 'premium' ? 'active' : ''}`}>
              <input
                type="radio" name="tier" value="premium"
                checked={tier === 'premium'}
                onChange={() => setTier('premium')}
              />
              <div>
                <strong>Premium — $99 MXN</strong>
                <small>Básico + soporte por WhatsApp</small>
              </div>
            </label>
          </div>

          <button type="submit" className="primary big" disabled={loading}>
            <Lock size={18} />
            {loading ? 'Iniciando pago…' : 'Pagar y desbloquear'}
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
        </form>
      </div>
    </div>
  )
}

function extractTitleHint(url) {
  const match = url.match(/MLM-?\d+-([a-z0-9-]+)/i)
  if (!match) return null
  return match[1].replace(/-/g, ' ').slice(0, 60)
}
