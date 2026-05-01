import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ScanLine, ShieldCheck, Zap, Lock, Camera, Eye, FileText,
  Copy, TrendingUp, ImageOff, AlertTriangle, CheckCircle2,
  Fingerprint, Search,
} from 'lucide-react'
import PlateScanner from '../components/PlateScanner.jsx'

/**
 * Landing scan-first con jerarquía emocional:
 *
 *   1. Trust signal (eyebrow)        → "verificación profesional"
 *   2. Promesa clara (hero)           → titular + subtítulo
 *   3. Acción dominante (CTA)         → un solo botón grande
 *   4. Prueba (stats strip)           → números concretos
 *   5. Por qué confiar (trust pillars)→ 3 razones con iconos
 *   6. Cómo funciona (steps)          → flujo visual
 *   7. Qué detectamos (use cases)     → fraudes reales
 *   8. FAQ                             → objeciones
 *   9. CTA final                       → cierre
 */
export default function Landing() {
  const navigate = useNavigate()
  const [scannerOpen, setScannerOpen] = useState(false)

  function handleScanResult(data) {
    navigate(`/preview/${data.report_id}`, { state: { initial: data } })
  }

  return (
    <main>
      {/* ===== HERO ===== */}
      <section className="hero">
        <span className="hero-eyebrow">
          <ShieldCheck size={14} strokeWidth={2.5} />
          Verificación profesional · Marketplace MX
        </span>

        <h1>
          Checa tu auto antes de <span className="accent">soltar el cash</span>
        </h1>
        <p className="tagline">
          Escanea la placa y recibe un preview gratis con score de riesgo
          y consulta REPUVE. Desbloquea el reporte completo desde $49 MXN.
        </p>
        <p className="subtag">
          Análisis con IA del anuncio, precio justo del mercado y la única
          herramienta MX que detecta clonación de placa al ver el auto.
        </p>

        <div className="hero-cta">
          <button
            onClick={() => setScannerOpen(true)}
            className="primary big hero-button"
          >
            <ScanLine size={20} strokeWidth={2.4} />
            Escanear placa
          </button>
          <p className="micro-trust">
            <Lock size={12} />
            Sin registro previo · Pago solo al desbloquear
          </p>
        </div>
      </section>

      {/* ===== STATS STRIP ===== */}
      <div className="stats-strip">
        <div className="stat-card">
          <span className="stat-num">30s</span>
          <span className="stat-label">preview gratis</span>
        </div>
        <div className="stat-card">
          <span className="stat-num">$49</span>
          <span className="stat-label">reporte completo MXN</span>
        </div>
        <div className="stat-card">
          <span className="stat-num">~50</span>
          <span className="stat-label">comparables por modelo</span>
        </div>
        <div className="stat-card">
          <span className="stat-num">21</span>
          <span className="stat-label">patrones de estafa</span>
        </div>
      </div>

      {/* ===== TRUST PILLARS ===== */}
      <section className="section">
        <span className="section-eyebrow">Por qué Verificarro</span>
        <h2 className="section-title">Hecho para no caer en estafa</h2>
        <p className="section-lede">
          La compra de un auto usado en México es donde se pierden más
          ahorros del año. Verificarro te da en minutos la información
          que un perito tarda días — sin dejar rastro al vendedor.
        </p>

        <div className="trust-pillars">
          <article className="trust-pillar">
            <div className="pillar-icon">
              <ShieldCheck size={26} strokeWidth={2.2} />
            </div>
            <h3>REPUVE oficial</h3>
            <p>
              Consulta directa al portal de gob.mx con la placa. Si el auto
              está reportado robado o con situación legal irregular, te
              avisamos antes de que muevas un peso.
            </p>
          </article>

          <article className="trust-pillar">
            <div className="pillar-icon">
              <Search size={26} strokeWidth={2.2} />
            </div>
            <h3>IA que ve lo que tú no</h3>
            <p>
              Claude analiza cada foto del anuncio buscando paneles
              desalineados, óxido oculto, repintado y watermarks robados.
              También detecta 21 patrones de descripción-estafa.
            </p>
          </article>

          <article className="trust-pillar">
            <div className="pillar-icon">
              <Fingerprint size={26} strokeWidth={2.2} />
            </div>
            <h3>Anti placa-clonada</h3>
            <p>
              La feature única en México: cuando vayas a ver el auto,
              escanea el VIN físico y te decimos si coincide con el
              anuncio. Detección inmediata de clonación.
            </p>
          </article>
        </div>
      </section>

      {/* ===== HOW IT WORKS ===== */}
      <section className="section">
        <span className="section-eyebrow">Cómo funciona</span>
        <h2 className="section-title">3 pasos. 30 segundos.</h2>
        <p className="section-lede">
          No hay registro, no hay formularios largos. Apuntas la cámara,
          ves el preview, decides si pagas.
        </p>

        <div className="steps">
          <article className="step-card">
            <span className="step-num-tag">PASO 01</span>
            <div className="step-icon">
              <Camera size={26} strokeWidth={2.2} />
            </div>
            <h3>Escanea la placa</h3>
            <p>
              Con la cámara del celular, una foto desde galería, o
              tipeas la placa si prefieres no usar cámara.
            </p>
          </article>

          <article className="step-card">
            <span className="step-num-tag">PASO 02</span>
            <div className="step-icon">
              <Eye size={26} strokeWidth={2.2} />
            </div>
            <h3>Lee el preview gratis</h3>
            <p>
              Score de riesgo + REPUVE básico + verdict de seguridad.
              Sin email, sin tarjeta, sin registro.
            </p>
          </article>

          <article className="step-card">
            <span className="step-num-tag">PASO 03</span>
            <div className="step-icon">
              <FileText size={26} strokeWidth={2.2} />
            </div>
            <h3>Desbloquea el reporte</h3>
            <p>
              Por $49 MXN: precio justo, fotos con IA, red flags del
              anuncio y escáner de VIN físico cuando veas el auto.
            </p>
          </article>
        </div>
      </section>

      {/* ===== USE CASES ===== */}
      <section className="section">
        <span className="section-eyebrow">Lo que detectamos</span>
        <h2 className="section-title">Fraudes reales que pasan en MX</h2>
        <p className="section-lede">
          Casos que vemos cada semana en Marketplace y ML Motors.
          Cualquiera de estos vale los $49 MXN del reporte.
        </p>

        <div className="use-case-grid">
          <article className="use-case case-danger">
            <div className="case-icon">
              <Copy size={22} strokeWidth={2.2} />
            </div>
            <h3>Placa clonada</h3>
            <p>
              Auto robado con placa duplicada de uno legítimo. REPUVE sale
              "limpio" pero el VIN físico es de otra marca/año. Detección
              al verificar el VIN del auto.
            </p>
          </article>

          <article className="use-case case-warning">
            <div className="case-icon">
              <TrendingUp size={22} strokeWidth={2.2} />
            </div>
            <h3>Auto sobrepuesto</h3>
            <p>
              Vendedor pide 30%+ sobre el precio justo. Comparamos contra
              ~50 anuncios similares en ML Motors y te decimos cuánto
              vale realmente.
            </p>
          </article>

          <article className="use-case case-info">
            <div className="case-icon">
              <ImageOff size={22} strokeWidth={2.2} />
            </div>
            <h3>Fotos manipuladas</h3>
            <p>
              Cofre con tono distinto, paneles desalineados, óxido oculto,
              watermarks robados. Claude visión revisa cada foto del
              anuncio.
            </p>
          </article>

          <article className="use-case case-accent">
            <div className="case-icon">
              <AlertTriangle size={22} strokeWidth={2.2} />
            </div>
            <h3>Descripción sospechosa</h3>
            <p>
              "Estoy en el extranjero, deposita primero", "urgente por
              viaje", "no acepto inspección". 21 patrones de estafa-
              clásica detectados al instante.
            </p>
          </article>
        </div>
      </section>

      {/* ===== FAQ ===== */}
      <section className="section">
        <span className="section-eyebrow">Preguntas frecuentes</span>
        <h2 className="section-title">Lo que dudas antes de comprar</h2>

        <div className="faq-list faq">
          <details>
            <summary>¿Cuánto cuesta?</summary>
            <p>
              El preview (score + REPUVE básico) es <strong>gratis</strong>.
              El reporte completo cuesta <strong>$49 MXN</strong> (Básico)
              o $99 MXN (Premium con soporte por WhatsApp). Pagas vía
              Mercado Pago, recibes el reporte al instante.
            </p>
          </details>

          <details>
            <summary>¿Sustituye una revisión mecánica?</summary>
            <p>
              No. Verificarro detecta fraudes documentales y de fotos
              antes de que veas el auto. La revisión mecánica con tu
              persona de confianza sigue siendo necesaria — pero ya no
              vas a perder tiempo viendo autos que ya vienen mal de origen.
            </p>
          </details>

          <details>
            <summary>¿Por qué a veces REPUVE no responde?</summary>
            <p>
              El portal de gob.mx tiene reCaptcha de Google que bloquea
              consultas automáticas. Cuando pasa, el preview te avisa con
              un score conservador y aún puedes desbloquear el reporte
              completo — incluye instrucciones para que confirmes REPUVE
              manualmente en repuve.gob.mx.
            </p>
          </details>

          <details>
            <summary>¿Cómo funciona el escaneo de VIN físico?</summary>
            <p>
              Después de desbloquear el reporte, abres el link en tu
              celular cuando vayas a ver el auto. Apuntas la cámara al
              tablero (visible por el parabrisas) o al marco de la puerta
              del chofer. Te decimos si el VIN del auto físico coincide
              con el anuncio — la mejor protección anti-clonación
              disponible en México.
            </p>
          </details>

          <details>
            <summary>¿Cobran si el auto resulta robado?</summary>
            <p>
              El preview es siempre gratis. Si el preview ya marca el auto
              como robado (REPUVE Robado, score &lt; 40), descubriste el
              problema sin pagar nada. Si decides desbloquear igualmente,
              los $49 MXN incluyen el análisis completo y la documentación
              que necesites.
            </p>
          </details>

          <details>
            <summary>¿Mis datos están seguros?</summary>
            <p>
              No pedimos nombre, dirección, ni teléfono. Solo email al
              momento de pagar (para enviarte el reporte). El pago va
              directo a Mercado Pago — nosotros no guardamos tu tarjeta.
              Las consultas REPUVE no quedan registradas con tu nombre.
            </p>
          </details>
        </div>
      </section>

      {/* ===== FINAL CTA ===== */}
      <section className="final-cta">
        <h2>Antes de soltar tu dinero, gasta 30 segundos.</h2>
        <p>
          El preview es gratis. Sólo decides pagar si el auto pasa el
          filtro inicial — y así no inviertes en uno que ya viene torcido.
        </p>
        <button
          onClick={() => setScannerOpen(true)}
          className="primary big hero-button"
        >
          <ScanLine size={20} strokeWidth={2.4} />
          Escanear placa ahora
        </button>
      </section>

      <footer className="footer">
        <p>
          <CheckCircle2 size={12} style={{ display: 'inline', verticalAlign: '-2px' }} />
          {' '}Verificarro v0.2 · Hecho en México 🇲🇽 · Pagos vía Mercado Pago.
        </p>
        <p className="muted small">
          Reportes informativos, no sustituyen revisión mecánica profesional.
        </p>
      </footer>

      {scannerOpen && (
        <PlateScanner
          onResult={handleScanResult}
          onClose={() => setScannerOpen(false)}
        />
      )}
    </main>
  )
}
