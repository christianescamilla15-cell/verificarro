import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import PaywallModal from '../components/PaywallModal.jsx'
import ScoreChip from '../components/ScoreChip.jsx'
import KVTable from '../components/KVTable.jsx'
import Spinner from '../components/Spinner.jsx'

/**
 * Muestra el preview gratis del reporte: score visible + REPUVE básico
 * + paywall para desbloquear el resto.
 *
 * Recibe el data inicial vía `location.state.initial` (cuando navegamos
 * desde el scanner). Si entras por URL directa, se podría hacer GET al
 * reporte por id — out of scope para esta iteración.
 */
export default function PreviewReport() {
  const { reportId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [data, setData] = useState(location.state?.initial || null)
  const [paywallOpen, setPaywallOpen] = useState(false)

  useEffect(() => {
    if (!data && reportId) {
      // Sin estado preservado: por ahora redirigimos al scan.
      // (Endpoint GET /api/scan/preview/{id} lo agregamos después si
      // los usuarios comparten links de preview.)
      navigate('/', { replace: true })
    }
  }, [data, reportId, navigate])

  if (!data) {
    return (
      <main className="report-view">
        <Spinner message="Cargando preview…" />
      </main>
    )
  }

  const repuve = data.repuve || {}
  const repuveStatusText = repuve.is_stolen === true
    ? '🚨 VEHÍCULO ROBADO'
    : repuve.is_stolen === false
    ? '✅ Sin reportes de robo'
    : repuve.error || 'No consultado'

  return (
    <main className="report-view preview-view">
      <ScoreChip score={data.score} risk={data.risk_level} />
      <p className="report-summary">{data.summary}</p>

      <section className="report-section">
        <h2>REPUVE (preview gratis)</h2>
        <KVTable rows={[
          ['Estatus', repuveStatusText],
          ['Placa', data.plate || '—'],
          ['NIV', data.vin || '—'],
          ['Situación legal',
            repuve.has_legal_status === true ? 'Regular'
              : repuve.has_legal_status === false ? '⚠️ Irregular'
              : '—'],
        ]} />
        {data.ocr_confidence && (
          <p className="muted small">
            OCR de placa: confianza {data.ocr_confidence}
            {data.ocr_notes ? ` — ${data.ocr_notes}` : ''}
          </p>
        )}
      </section>

      <section className="report-section paywall-cta">
        <h2>Desbloquea el reporte completo</h2>
        <p>
          Por <strong>$49 MXN</strong> incluimos análisis del anuncio (precio
          justo, fotos con IA, banderas en la descripción) y la herramienta
          para escanear el VIN físico cuando vayas a ver el auto.
        </p>
        <button
          onClick={() => setPaywallOpen(true)}
          className="primary big"
        >
          🔓 Desbloquear por $49 MXN
        </button>
      </section>

      <section className="report-section locked-preview">
        <h2 className="locked-heading">🔒 Lo que se desbloquea con el pago</h2>
        <ul className="locked-list">
          <li>
            <strong>Precio justo</strong> — comparamos contra ~50 anuncios
            similares en ML Motors y te decimos si está sobrepuesto o
            sospechosamente barato.
          </li>
          <li>
            <strong>Análisis de fotos con IA</strong> — Claude visión revisa
            cada foto del anuncio buscando paneles desalineados, óxido,
            repintado, watermarks y otros indicios.
          </li>
          <li>
            <strong>Banderas en la descripción</strong> — 21 patrones
            lingüísticos de estafa-clásica.
          </li>
          <li>
            <strong>Análisis del vendedor</strong> — cuenta nueva, sin otros
            anuncios, fotos duplicadas, baja tasa de respuesta.
          </li>
          <li>
            <strong>Escaneo de VIN físico</strong> — la killer feature.
            Cuando vayas a ver el auto, escanea el VIN del tablero o marco
            de puerta. Te decimos si NO coincide con el anuncio (placa
            clonada).
          </li>
          <li>
            <strong>Reporte PDF</strong> descargable.
          </li>
          <li>
            <strong>3 preguntas clave</strong> para hacerle al vendedor antes
            de cerrar.
          </li>
        </ul>
      </section>

      {paywallOpen && (
        <PaywallModal
          reportId={data.report_id}
          onClose={() => setPaywallOpen(false)}
        />
      )}
    </main>
  )
}
