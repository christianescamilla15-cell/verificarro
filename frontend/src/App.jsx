import { useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || ''

export default function App() {
  const [url, setUrl] = useState('')
  const [plate, setPlate] = useState('')
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      const res = await fetch(`${API_BASE}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url || null,
          plate: plate || null,
          source: 'mercadolibre',
        }),
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail.detail || `Error ${res.status}`)
      }
      setReport(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="hero">
        <h1>Verificarro</h1>
        <p className="tagline">
          Checa tu auto de Marketplace antes de soltar el cash.
        </p>
        <p className="subtag">
          REPUVE · precio justo · análisis de fotos · red flags · en 60 segundos
        </p>
      </header>

      <main className="container">
        <form onSubmit={handleSubmit} className="form">
          <label>
            URL de Mercado Libre Motors
            <input
              type="url"
              placeholder="https://articulo.mercadolibre.com.mx/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          <label>
            Placa o NIV (opcional, para REPUVE)
            <input
              type="text"
              placeholder="ABC-123-D"
              value={plate}
              onChange={(e) => setPlate(e.target.value.toUpperCase())}
              maxLength={20}
            />
          </label>
          <button type="submit" disabled={loading || !url}>
            {loading ? 'Analizando…' : 'Verificar auto'}
          </button>
        </form>

        {error && <div className="error">⚠️ {error}</div>}

        {report && (
          <section className="report">
            <h2>Reporte</h2>
            <div className={`score score-${report.risk_level}`}>
              <span className="score-num">{report.score}</span>
              <span className="score-label">/ 100</span>
            </div>
            <p className="summary">{report.summary}</p>

            <h3>Datos del anuncio</h3>
            <ul>
              <li>
                <strong>{report.listing.title}</strong>
              </li>
              <li>Precio: ${report.listing.price_mxn?.toLocaleString('es-MX')} MXN</li>
              <li>Ubicación: {report.listing.location || '—'}</li>
            </ul>

            <h3>Preguntas para hacerle al vendedor</h3>
            <ol>
              {report.questions_for_seller.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ol>
          </section>
        )}
      </main>

      <footer className="footer">
        <small>
          Verificarro v0.1 · MVP · Hecho en México 🇲🇽 · Reportes informativos,
          no sustituyen revisión mecánica.
        </small>
      </footer>
    </div>
  )
}
