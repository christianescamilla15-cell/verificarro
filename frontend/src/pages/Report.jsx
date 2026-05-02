import { useState } from 'react'
import { ExternalLink, Factory, Globe, FileText } from 'lucide-react'
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

      {/* MOD-031: disclaimer prominente en cada reporte. Cumple
          requisitos de Términos y Condiciones (limitación de
          responsabilidad) y reduce riesgo de reclamos por
          "información incorrecta". */}
      <aside className="report-disclaimer" role="note">
        <strong>Importante</strong>: Verificarro proporciona
        información de fuentes públicas (REPUVE, NHTSA, SAT) y análisis
        del anuncio. NO garantizamos exactitud absoluta — REPUVE puede
        estar desactualizado, fotos pueden ser modificadas, descripciones
        pueden tener errores. La decisión de compra y el riesgo de la
        transacción son responsabilidad del usuario. Recomendamos
        siempre verificar el auto en persona y con un mecánico de
        confianza antes de pagar. Ver{' '}
        <a href="/terminos" target="_blank" rel="noreferrer">Términos y Condiciones</a>.
      </aside>

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
            ['País (WMI)', vinResult.decoded.country || '—'],
            ['¿Coincide con anuncio?', vinResult.matches_listing ? '✅ Sí' : '🚨 NO'],
          ]} />

          {vinResult.decoded.nhtsa_found && (
            <div className="nhtsa-block">
              <h3>
                <Factory size={18} style={{ verticalAlign: '-3px', marginRight: 6, color: 'var(--accent-text)' }} />
                NHTSA vPIC (datos oficiales fabricante)
              </h3>
              <KVTable rows={[
                ['Make oficial', vinResult.decoded.nhtsa_make || '—'],
                ['Model oficial', vinResult.decoded.nhtsa_model || '—'],
                ['Año modelo NHTSA', vinResult.decoded.nhtsa_model_year || '—'],
                ['Carrocería', vinResult.decoded.nhtsa_body_class || '—'],
                ['Trim', vinResult.decoded.nhtsa_trim || '—'],
                ['Cilindros', vinResult.decoded.nhtsa_engine_cylinders || '—'],
                ['Desplazamiento (L)', vinResult.decoded.nhtsa_engine_displacement_l || '—'],
                ['Combustible', vinResult.decoded.nhtsa_fuel_type || '—'],
                ['Transmisión', vinResult.decoded.nhtsa_transmission || '—'],
                ['Tracción', vinResult.decoded.nhtsa_drive_type || '—'],
                ['Puertas', vinResult.decoded.nhtsa_doors || '—'],
                ['Planta de fabricación', [
                  vinResult.decoded.nhtsa_plant_city,
                  vinResult.decoded.nhtsa_plant_country,
                ].filter(Boolean).join(', ') || '—'],
              ]} />
            </div>
          )}

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

      {r.exif_findings && r.exif_findings.length > 0 && (
        <FindingList
          title="Forensia EXIF (metadata de las fotos)"
          findings={r.exif_findings}
          getText={(f) => `Foto #${f.photo_index + 1}: ${f.note}`}
          emptyText="Sin findings en metadata de fotos."
        />
      )}

      <FindingList
        title="Banderas del vendedor"
        findings={r.seller_findings}
        getText={(f) => f.note}
        emptyText="Sin banderas en el perfil del vendedor."
      />

      {r.cross_listings && r.cross_listings.length > 0 && (
        <section className="report-section cross-listings">
          <h2>
            <Globe size={20} strokeWidth={2.2} />
            Otros marketplaces — el mismo modelo
          </h2>
          <p className="muted">
            Encontramos {r.cross_listings.length} listing(s) similares en otros
            sitios MX. Compara precios y verifica si el vendedor está
            cross-posteando (puede ser bandera).
          </p>
          <div className="cross-listing-grid">
            {r.cross_listings.map((cl, i) => (
              <a
                key={i}
                href={cl.url}
                target="_blank"
                rel="noopener noreferrer"
                className="cross-listing-card"
              >
                <div className="cross-listing-marketplace">
                  {cl.marketplace.replace('_', ' ')}
                </div>
                <div className="cross-listing-title">{cl.title}</div>
                {cl.price_mxn && (
                  <div className="cross-listing-price">
                    ${cl.price_mxn.toLocaleString('es-MX')} MXN
                  </div>
                )}
                {cl.location && (
                  <div className="cross-listing-location">{cl.location}</div>
                )}
                <ExternalLink size={14} className="cross-listing-icon" />
              </a>
            ))}
          </div>
        </section>
      )}

      {r.consultation_links && r.consultation_links.length > 0 && (
        <section className="report-section gov-links">
          <h2>
            <ExternalLink size={20} strokeWidth={2.2} />
            Verifica tú mismo en gob.mx
          </h2>
          <p className="muted">
            Portales oficiales pre-llenados con la placa. Los marcados con
            ✓ aplican a este auto según su ubicación.
          </p>
          <div className="gov-link-grid">
            {r.consultation_links.map((link, i) => (
              <a
                key={i}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`gov-link gov-link-${link.category} ${link.applicable ? 'applicable' : 'not-applicable'}`}
              >
                <div className="gov-link-header">
                  <span className="gov-link-name">{link.name}</span>
                  <ExternalLink size={14} />
                </div>
                <p className="gov-link-desc">{link.description}</p>
                <div className="gov-link-footer">
                  <span className={`gov-link-badge gov-badge-${link.category}`}>
                    {link.category}
                  </span>
                  {link.state_scope && (
                    <span className="gov-link-scope">
                      {link.applicable ? '✓ ' : ''}{link.state_scope}
                    </span>
                  )}
                </div>
              </a>
            ))}
          </div>
        </section>
      )}

      {r.invoice && (
        <section className="report-section invoice-block">
          <h2>
            <FileText size={20} strokeWidth={2.2} />
            Factura del auto — verificación obligatoria
          </h2>
          <KVTable rows={[
            ['Folio declarado', r.invoice.invoice_number || '—'],
            ['UUID CFDI', r.invoice.folio_fiscal_uuid || (r.invoice.invoice_number ? '(no parece UUID — pide el archivo XML CFDI al vendedor)' : '—')],
            ['Estado SAT', r.invoice.sat_status
              ? r.invoice.sat_status === 'vigente' ? '✅ Vigente'
                : r.invoice.sat_status === 'cancelado' ? '🚨 Cancelada'
                : '⚠️ No encontrada'
              : 'Pendiente verificar contra SAT (próxima feature)'],
          ]} />
          {r.invoice.notes && (
            <p className="invoice-notes">{r.invoice.notes}</p>
          )}
        </section>
      )}

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
