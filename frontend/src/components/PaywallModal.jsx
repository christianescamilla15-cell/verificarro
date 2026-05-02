import { useRef, useState } from 'react'
import { X, Lock, AlertTriangle, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api.js'
import { useModalA11y } from '../hooks/useModalA11y.js'
import WhatsAppButton from './WhatsAppButton.jsx'

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
  const [invoiceNumber, setInvoiceNumber] = useState('')
  const [tier, setTier] = useState('basic')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const modalRef = useRef(null)

  // MOD-028: ESC cierra, focus trap intra-modal, restaura focus al
  // elemento que abrió el modal cuando cierra.
  useModalA11y(modalRef, onClose)

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
      invoice_number: invoiceNumber.trim() || null,
      tier,
      title_hint: listingUrl ? extractTitleHint(listingUrl) : null,
    })
    setLoading(false)
    if (!res.ok) {
      setError(res.error || 'No pudimos iniciar el pago. Intenta de nuevo.')
      return
    }
    // Guardamos el polling_token (MOD-005) en localStorage antes del
    // redirect a MP. Cuando MP devuelva al user a /checkout/success
    // con ?external_reference=X, el polling lee el token desde localStorage.
    try {
      localStorage.setItem(
        `verificarro_polling_${res.data.external_reference}`,
        res.data.polling_token,
      )
    } catch { /* localStorage en modo privado puede fallar — ignorable */ }
    window.location.href = res.data.init_point
  }

  return (
    <div className="vin-scanner-overlay" role="dialog" aria-modal="true" aria-labelledby="paywall-modal-title">
      <div className="vin-scanner paywall-modal" ref={modalRef}>
        <div className="vin-scanner-header">
          <h2 id="paywall-modal-title">
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

          <label>
            Folio de la factura del auto <span className="muted">(opcional)</span>
            <input
              type="text"
              maxLength={64}
              placeholder="UUID CFDI o número de folio"
              value={invoiceNumber}
              onChange={(e) => setInvoiceNumber(e.target.value)}
            />
            <small className="muted">
              Si el vendedor ya te lo dio, lo incluimos en el reporte como
              instrucción para que valides que la factura física coincida.
              Próximamente: validación automática contra SAT.
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

          {tier === 'premium' && (
            <div className="paywall-wa-hint">
              <p className="muted small" style={{ textAlign: 'center', marginBottom: 'var(--space-2)' }}>
                Premium incluye soporte directo:
              </p>
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <WhatsAppButton variant="inline" reportId={reportId} label="Vista previa del soporte WA" />
              </div>
            </div>
          )}
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
