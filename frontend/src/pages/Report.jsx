import { useState } from 'react'
import { downloadPdf } from '../lib/api.js'
import FindingList from '../components/FindingList.jsx'
import KVTable from '../components/KVTable.jsx'
import ScoreChip from '../components/ScoreChip.jsx'
import VinScanner from '../components/VinScanner.jsx'

export default function ReportView({ reportData }) {
  const r = reportData
  const [vinScannerOpen, setVinScannerOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [vinResult, setVinResult] = useState(r.vin_check || null)

  async function handleDownload() {
    setDownloading(true)
    try {
      const blob = await downloadPdf(r)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `verificarro-${r.listing.year || 'reporte'}-${r.score}.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(`No pudimos descargar el PDF: ${err.message}`)
    }
    setDownloading(false)
  }

  return (
    <main className="report-view">
      <ScoreChip score={r.score} risk={r.risk_level} />
      <p className="report-summary">{r.summary}</p>

      <div className="report-actions">
        <button onClick={handleDownload} disabled={downloading} className="primary">
          {downloading ? 'Generando…' : '📄 Descargar PDF'}
        </button>
        <button onClick={() => setVinScannerOpen(true)} className="primary highlight">
          🔍 Escanear VIN del auto
        </button>
      </div>

      {/* CTA persistente para escanear VIN si no se ha hecho */}
      {!vinResult && (
        <div className="vin-cta">
          <strong>🚨 Antes de pagar:</strong> escanea el VIN físico del auto
          para confirmar que coincide con este anuncio. Detectamos placas
          clonadas en el momento.
        </div>
      )}

      {vinResult && (
        <section className="report-section">
          <h2>Verificación VIN físico</h2>
          <KVTable rows={[
            ['Marca decoded', vinResult.decoded.manufacturer || '—'],
            ['Año decoded', vinResult.decoded.year || '—'],
            ['País', vinResult.decoded.country || '—'],
            ['¿Coincide con anuncio?', vinResult.matches_listing ? '✅ Sí' : '🚨 NO'],
          ]} />
          {vinResult.alerts.length > 0 && (
            <FindingList
              title="Alertas del VIN"
              findings={vinResult.alerts}
              getText={(a) => a.message}
            />
          )}
        </section>
      )}

      <section className="report-section">
        <h2>Datos del anuncio</h2>
        <KVTable rows={[
          ['Título', r.listing.title],
          ['Precio anuncio', r.listing.price_mxn ? `$${r.listing.price_mxn.toLocaleString('es-MX')} MXN` : '—'],
          ['Marca / Modelo', `${r.listing.make} ${r.listing.model}`.trim() || '—'],
          ['Año', r.listing.year || '—'],
          ['Kilómetros', r.listing.kilometers ? `${r.listing.kilometers.toLocaleString('es-MX')} km` : '—'],
          ['Ubicación', r.listing.location],
          ['Vendedor', r.listing.seller_name || '—'],
        ]} />
      </section>

      <section className="report-section">
        <h2>REPUVE (gob.mx)</h2>
        <KVTable rows={[
          ['Estatus',
            r.repuve.is_stolen === true ? '🚨 VEHÍCULO ROBADO'
              : r.repuve.is_stolen === false ? '✅ Sin reportes de robo'
              : (r.repuve.error || 'No consultado')],
          ['Placa', r.repuve.plate],
          ['NIV', r.repuve.vin],
          ['Situación legal',
            r.repuve.has_legal_status === true ? 'Regular'
              : r.repuve.has_legal_status === false ? '⚠️ Irregular'
              : '—'],
        ]} />
      </section>

      <section className="report-section">
        <h2>Precio justo</h2>
        {r.price.fair_price_mxn ? (
          <KVTable rows={[
            ['Mediana del mercado', `$${r.price.fair_price_mxn.toLocaleString('es-MX')} MXN`],
            ['Rango p10–p90',
              r.price.range_low_mxn && r.price.range_high_mxn
                ? `$${r.price.range_low_mxn.toLocaleString('es-MX')} – $${r.price.range_high_mxn.toLocaleString('es-MX')}`
                : '—'],
            ['Delta vs anuncio',
              r.price.delta_pct != null
                ? <span className={`delta ${r.price.delta_pct < -10 ? 'negative' : r.price.delta_pct > 10 ? 'positive' : ''}`}>
                    {r.price.delta_pct >= 0 ? '+' : ''}{r.price.delta_pct.toFixed(1)}%
                  </span>
                : '—'],
            ['Comparables', r.price.comparables_count],
          ]} />
        ) : (
          <p className="muted">No hay comparables suficientes para estimar.</p>
        )}
      </section>

      <FindingList
        title="Banderas en la descripción"
        findings={r.description_findings}
        getText={(f) => f.excerpt}
        emptyText="Descripción limpia, sin patrones de estafa."
      />

      <FindingList
        title="Análisis de fotos con IA"
        findings={r.photo_findings}
        getText={(f) => `Foto #${f.photo_index + 1}: ${f.note}`}
        emptyText="Las fotos se ven normales."
      />

      <FindingList
        title="Banderas del vendedor"
        findings={r.seller_findings}
        getText={(f) => f.note}
        emptyText="Sin banderas en el perfil del vendedor."
      />

      <section className="report-section">
        <h2>Preguntas para hacerle al vendedor</h2>
        <ol className="questions">
          {r.questions_for_seller.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ol>
      </section>

      {vinScannerOpen && (
        <VinScanner
          listing={r.listing}
          repuve={r.repuve}
          onResult={(check) => setVinResult(check)}
          onClose={() => setVinScannerOpen(false)}
        />
      )}
    </main>
  )
}
