import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  Lock, ShieldCheck, TrendingUp, Image as ImageIcon, Search,
  Fingerprint, FileText, MessageCircle, Unlock,
} from 'lucide-react'
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
        <h2>
          <Unlock size={22} strokeWidth={2.2} />
          Desbloquea el reporte completo
        </h2>
        <p>
          Por <strong>$49 MXN</strong> incluimos análisis del anuncio (precio
          justo, fotos con IA, banderas en la descripción) y la herramienta
          para escanear el VIN físico cuando vayas a ver el auto.
        </p>
        <button
          onClick={() => setPaywallOpen(true)}
          className="primary big"
        >
          <Unlock size={18} />
          Desbloquear por $49 MXN
        </button>
      </section>

      <section className="report-section locked-preview">
        <h2 className="locked-heading">
          <Lock size={18} /> Lo que se desbloquea con el pago
        </h2>
        <ul className="locked-list">
          <li>
            <TrendingUp size={20} strokeWidth={2} />
            <span>
              <strong>Precio justo</strong>
              Comparamos contra ~50 anuncios similares en ML Motors y te
              decimos si está sobrepuesto o sospechosamente barato.
            </span>
          </li>
          <li>
            <ImageIcon size={20} strokeWidth={2} />
            <span>
              <strong>Análisis de fotos con IA</strong>
              Claude visión revisa cada foto del anuncio buscando paneles
              desalineados, óxido, repintado, watermarks y otros indicios.
            </span>
          </li>
          <li>
            <Search size={20} strokeWidth={2} />
            <span>
              <strong>Banderas en la descripción</strong>
              21 patrones lingüísticos de estafa-clásica detectados al
              instante.
            </span>
          </li>
          <li>
            <ShieldCheck size={20} strokeWidth={2} />
            <span>
              <strong>Análisis del vendedor</strong>
              Cuenta nueva, sin otros anuncios, fotos duplicadas, baja
              tasa de respuesta.
            </span>
          </li>
          <li>
            <Fingerprint size={20} strokeWidth={2} />
            <span>
              <strong>Escaneo de VIN físico</strong>
              La killer feature. Cuando vayas a ver el auto, escanea el VIN
              del tablero o marco de puerta. Te decimos si NO coincide con
              el anuncio (placa clonada).
            </span>
          </li>
          <li>
            <FileText size={20} strokeWidth={2} />
            <span>
              <strong>Reporte PDF</strong>
              Descargable, archivable, compartible con tu mecánico.
            </span>
          </li>
          <li>
            <MessageCircle size={20} strokeWidth={2} />
            <span>
              <strong>3 preguntas clave</strong>
              Las preguntas exactas para hacerle al vendedor antes de cerrar
              trato.
            </span>
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
