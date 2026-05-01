import { useState } from 'react'
import { api } from '../lib/api.js'

export default function Landing() {
  const [url, setUrl] = useState('')
  const [plate, setPlate] = useState('')
  const [email, setEmail] = useState('')
  const [tier, setTier] = useState('basic')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    const res = await api.post('/api/payments/checkout', {
      listing_url: url || null,
      plate: plate || null,
      payer_email: email || null,
      tier,
      title_hint: url ? extractTitleHint(url) : null,
    })
    setLoading(false)
    if (!res.ok) {
      setError(res.error || 'No pudimos iniciar el pago. Intenta de nuevo.')
      return
    }
    // Redirect a Mercado Pago
    window.location.href = res.data.init_point
  }

  return (
    <main>
      {/* Hero */}
      <section className="hero">
        <h1>Checa tu auto antes de soltar el cash</h1>
        <p className="tagline">
          REPUVE · precio justo · análisis de fotos con IA · detecta clonación de placa
        </p>
        <p className="subtag">
          El único verificador en México que escanea el VIN del auto físico desde tu celular.
        </p>

        <form onSubmit={handleSubmit} className="checkout-form">
          <label>
            URL del anuncio (Mercado Libre Motors)
            <input
              type="url" required
              placeholder="https://auto.mercadolibre.com.mx/..."
              value={url} onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          <label>
            Placa o NIV (opcional, para REPUVE)
            <input
              type="text" maxLength={20}
              placeholder="ABC-123-D"
              value={plate} onChange={(e) => setPlate(e.target.value.toUpperCase())}
            />
          </label>
          <label>
            Email (te mandamos el reporte aquí)
            <input
              type="email"
              placeholder="tu@email.com"
              value={email} onChange={(e) => setEmail(e.target.value)}
            />
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

          <button type="submit" className="primary big" disabled={loading || !url}>
            {loading ? 'Iniciando pago…' : 'Verificar este auto'}
          </button>
          {error && <div className="error">⚠️ {error}</div>}
          <p className="micro-trust">
            Pago seguro vía Mercado Pago. Acepta tarjeta, OXXO, SPEI.
          </p>
        </form>
      </section>

      {/* Cómo funciona */}
      <section className="how-it-works">
        <h2>¿Cómo funciona?</h2>
        <div className="steps">
          <div className="step">
            <div className="step-num">1</div>
            <h3>Pega la URL del anuncio</h3>
            <p>De Mercado Libre Motors. Si lo viste en Facebook Marketplace, captura los datos manualmente.</p>
          </div>
          <div className="step">
            <div className="step-num">2</div>
            <h3>Recibes tu reporte en 30 segundos</h3>
            <p>REPUVE, precio justo, análisis de fotos con IA, red flags de descripción y vendedor.</p>
          </div>
          <div className="step">
            <div className="step-num">3</div>
            <h3>Antes de pagar, escanea el VIN</h3>
            <p>Cuando vayas a ver el auto, escanea el VIN físico con la cámara. Si no coincide con el anuncio, te avisamos.</p>
          </div>
        </div>
      </section>

      {/* Casos de uso */}
      <section className="use-cases">
        <h2>Casos reales que detectamos</h2>
        <div className="use-case-grid">
          <div className="use-case">
            <h3>🚨 Placa clonada</h3>
            <p>Auto robado con placa duplicada de uno legítimo. REPUVE sale "limpio" pero el VIN físico es de otra marca/año. Verificarro lo detecta antes de pagar.</p>
          </div>
          <div className="use-case">
            <h3>💸 Auto sobrepuesto</h3>
            <p>Vendedor pide $30% más que el precio justo del mercado. Comparamos contra 50 listings similares en ML Motors.</p>
          </div>
          <div className="use-case">
            <h3>📸 Fotos manipuladas</h3>
            <p>Cofre con tono distinto al resto, paneles desalineados, óxido oculto. Claude visión las analiza y reporta.</p>
          </div>
          <div className="use-case">
            <h3>📝 Descripción sospechosa</h3>
            <p>"Estoy en el extranjero, deposita primero". Detectamos 21 patrones lingüísticos de estafa-clásica.</p>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="faq">
        <h2>Preguntas frecuentes</h2>

        <details>
          <summary>¿Cuánto tarda el reporte?</summary>
          <p>~30 segundos después del pago. Te llega al email y aparece en tu cuenta si te registraste.</p>
        </details>

        <details>
          <summary>¿Sustituye una revisión mecánica?</summary>
          <p>No. Verificarro detecta fraudes documentales y de fotos antes de que veas el auto. La revisión mecánica sigue siendo necesaria — pídele al vendedor que te acompañe a tu mecánico de confianza.</p>
        </details>

        <details>
          <summary>¿Por qué REPUVE me pide consultar manualmente?</summary>
          <p>El portal de gob.mx tiene reCaptcha de Google que bloquea consultas automáticas. Te damos un link y un campo para que pegues el resultado en 30 segundos.</p>
        </details>

        <details>
          <summary>¿Cómo escaneo el VIN?</summary>
          <p>Después de comprar el reporte, abre el link en tu celular. Cuando vayas a ver el auto, da clic en "Escanear VIN", apunta la cámara al tablero (visible por el parabrisas) o al marco de la puerta del chofer. Te decimos si coincide con el anuncio.</p>
        </details>

        <details>
          <summary>¿Cobran si el auto resulta robado?</summary>
          <p>Sí — el reporte se cobra al momento del pago. Pero descubrir que es robado vale los $49 MXN comparado con perder $150,000+ MXN.</p>
        </details>

        <details>
          <summary>¿Funciona para autos en Facebook Marketplace?</summary>
          <p>Sí, pero como FB Marketplace requiere login para ver anuncios, te pedimos pegar manualmente título, precio, año, kms y subir las fotos.</p>
        </details>
      </section>

      <footer className="footer">
        <small>
          Verificarro v0.1 · MVP · Hecho en México 🇲🇽 · Reportes informativos,
          no sustituyen revisión mecánica profesional.
        </small>
      </footer>
    </main>
  )
}


function extractTitleHint(url) {
  // Intenta sacar make-model del slug del URL ML para que aparezca en MP checkout
  const match = url.match(/MLM-\d+-([a-z0-9-]+)/i)
  if (!match) return null
  return match[1].replace(/-/g, ' ').slice(0, 60)
}
