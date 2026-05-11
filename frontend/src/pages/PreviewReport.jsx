import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  Lock, ShieldCheck, TrendingUp, Image as ImageIcon, Search,
  Fingerprint, FileText, MessageCircle, Unlock, ExternalLink,
  AlertCircle, ClipboardCheck, Clock,
} from 'lucide-react'
import PaywallModal from '../components/PaywallModal.jsx'
import ScoreChip from '../components/ScoreChip.jsx'
import KVTable from '../components/KVTable.jsx'
import Spinner from '../components/Spinner.jsx'
import RepuveScreenshotUploader from '../components/RepuveScreenshotUploader.jsx'

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

  // ¿REPUVE auto-query falló? Cuando falla, hacemos hero los links manuales
  // porque son la ÚNICA forma confiable de verificar REPUVE en este momento.
  const repuveAutoFailed = !repuve.queried && repuve.raw_status === 'captcha_required'

  // Filtrar y priorizar links: primero los aplicables a la ubicación, después los demás
  const sortedLinks = (data.consultation_links || [])
    .slice()
    .sort((a, b) => Number(b.applicable) - Number(a.applicable))
  const repuveLink = sortedLinks.find((l) => l.name?.includes('REPUVE'))
  const otherLinks = sortedLinks.filter((l) => !l.name?.includes('REPUVE'))

  return (
    <main className="report-view preview-view">
      <ScoreChip score={data.score} risk={data.risk_level} />
      <p className="report-summary">{data.summary}</p>

      {/* MOD-031: disclaimer prominente */}
      <aside className="report-disclaimer" role="note">
        <strong>Preview informativo</strong> — Verificarro consulta
        fuentes públicas (REPUVE, NHTSA, SAT) y analiza datos del
        anuncio. La decisión y riesgo de compra son del usuario. Ver{' '}
        <a href="/terminos" target="_blank" rel="noreferrer">Términos</a>.
      </aside>

      {/* CTA HERO — reframe 2026-05-10: tono "feature intencional" en vez
          de "error técnico". REPUVE como sistema de seguridad pública NO
          permite consultas programáticas — y eso ES CORRECTO. El flow
          manual de 30s es el método legítimo. Lo presentamos como tal:
          ShieldCheck icon, lenguaje de confianza, tiempos explícitos. */}
      {repuveAutoFailed && repuveLink && (
        <section className="report-section gov-hero">
          <div className="gov-hero-banner">
            <ShieldCheck size={22} strokeWidth={2.4} />
            <div>
              <strong>Verificación REPUVE oficial en 30 segundos</strong>
              <p>
                Por seguridad del padrón vehicular nacional, REPUVE solo
                acepta consultas humanas — así garantiza que tu reporte
                es real y no manipulado. Abre el portal pre-cargado abajo,
                haz click en "Buscar", y nosotros leemos el resultado por
                ti con IA. Es el método que usan los compradores serios.
              </p>
            </div>
          </div>
          <div className="gov-hero-instructions">
            <ol>
              <li>
                <Clock size={14} strokeWidth={2.4} aria-hidden="true" />
                <span>
                  <strong>Click "Abrir REPUVE oficial"</strong> abajo (~5s) —
                  ya copiamos tu {data.plate ? 'placa' : 'NIV'} al portapapeles
                </span>
              </li>
              <li>
                <Clock size={14} strokeWidth={2.4} aria-hidden="true" />
                <span>
                  En el portal, <strong>pega</strong> (Ctrl+V / pulsar y pegar) tu{' '}
                  {data.plate ? 'placa' : 'NIV'}:{' '}
                  <code className="gov-hero-plate">{data.plate || data.vin}</code>{' '}
                  <button
                    type="button"
                    className="gov-hero-copy"
                    onClick={() => navigator.clipboard?.writeText(data.plate || data.vin || '')}
                    aria-label="Copiar placa al portapapeles"
                  >
                    <ClipboardCheck size={12} strokeWidth={2.4} /> copiar
                  </button>
                  (~10s)
                </span>
              </li>
              <li>
                <Clock size={14} strokeWidth={2.4} aria-hidden="true" />
                <span>Click <strong>"Buscar"</strong> en REPUVE (~5s)</span>
              </li>
              <li>
                <Clock size={14} strokeWidth={2.4} aria-hidden="true" />
                <span>
                  Sube el <strong>PDF</strong> (botón "Exportar a PDF" en REPUVE)
                  o una captura del resultado aquí abajo (~10s)
                </span>
              </li>
            </ol>
          </div>
          <a
            href={repuveLink.url}
            target="_blank"
            rel="noopener noreferrer"
            className="primary big gov-hero-cta"
            onClick={() => {
              // Auto-copy placa/NIV cuando el usuario abre el portal —
              // está literal a 1 paste de distancia.
              try {
                navigator.clipboard?.writeText(data.plate || data.vin || '')
              } catch (_) { /* clipboard puede estar bloqueado en algunos navegadores */ }
            }}
          >
            <ExternalLink size={20} strokeWidth={2.4} />
            Abrir REPUVE oficial · 30s
          </a>
          <RepuveScreenshotUploader
            plate={data.plate}
            vin={data.vin}
            onResult={(parsed) => {
              setData((prev) => prev && ({
                ...prev,
                repuve: {
                  queried: parsed.queried,
                  plate: parsed.plate,
                  vin: parsed.vin,
                  is_stolen: parsed.is_stolen,
                  has_legal_status: parsed.has_legal_status,
                  raw_status: parsed.raw_status,
                  error: parsed.error,
                },
              }))
            }}
          />
        </section>
      )}

      {/* Sección de otros links gob.mx (tenencia, multas, verificación).
          Si REPUVE no falló, mostramos esto + REPUVE en grid normal. */}
      {sortedLinks.length > 0 && (
        <section className="report-section gov-links">
          <h2>
            <ExternalLink size={20} strokeWidth={2.2} />
            {repuveAutoFailed
              ? 'Otras consultas oficiales gob.mx (gratis)'
              : 'Verifica tú mismo en gob.mx (gratis)'}
          </h2>
          <p className="muted">
            {repuveAutoFailed
              ? 'Más portales que aplican según el estado del auto. Adicional al REPUVE de arriba.'
              : 'Portales oficiales pre-llenados con tu placa. Los marcados con ✓ aplican a tu auto.'}
          </p>
          <div className="gov-link-grid">
            {(repuveAutoFailed ? otherLinks : sortedLinks).map((link, i) => (
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
