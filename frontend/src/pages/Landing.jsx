import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PlateScanner from '../components/PlateScanner.jsx'

/**
 * Scan-first landing.
 *
 * Un solo botón grande "Escanear placa" abre el modal con tres
 * modalidades: cámara, galería, ingreso manual. Cuando el scan
 * resuelve, redirigimos a /preview/{report_id} donde el usuario ve
 * el score y los demás campos blurred con CTA de pago.
 */
export default function Landing() {
  const navigate = useNavigate()
  const [scannerOpen, setScannerOpen] = useState(false)

  function handleScanResult(data) {
    // El backend persiste el preview, basta con redirigir al ID.
    navigate(`/preview/${data.report_id}`, { state: { initial: data } })
  }

  return (
    <main>
      <section className="hero">
        <h1>
          Checa tu auto antes de <span className="accent">soltar el cash</span>
        </h1>
        <p className="tagline">
          REPUVE · precio justo · análisis de fotos con IA · detecta clonación de placa
        </p>
        <p className="subtag">
          Escanea la placa, recibe un preview gratis. Desbloquea el reporte
          completo por $49 MXN.
        </p>

        <div className="hero-cta">
          <button
            onClick={() => setScannerOpen(true)}
            className="primary big hero-button"
          >
            📷 Escanear placa
          </button>
          <p className="micro-trust">
            Sin registro previo. Pago sólo cuando desbloqueas el reporte.
          </p>
        </div>
      </section>

      <section className="how-it-works">
        <h2>¿Cómo funciona?</h2>
        <div className="steps">
          <div className="step">
            <div className="step-num">1</div>
            <h3>Escaneas la placa</h3>
            <p>
              Con la cámara del celular, una foto desde galería, o tipeas la
              placa si prefieres.
            </p>
          </div>
          <div className="step">
            <div className="step-num">2</div>
            <h3>Ves el preview gratis</h3>
            <p>
              Score de riesgo + REPUVE básico + verdict en segundos. Sin
              ingresar email ni tarjeta.
            </p>
          </div>
          <div className="step">
            <div className="step-num">3</div>
            <h3>Desbloqueas con $49</h3>
            <p>
              Pagas y recibes el análisis completo: precio justo, fotos con IA,
              red flags del anuncio, escaneo de VIN físico.
            </p>
          </div>
        </div>
      </section>

      <section className="use-cases">
        <h2>Casos reales que detectamos</h2>
        <div className="use-case-grid">
          <div className="use-case">
            <h3>🚨 Placa clonada</h3>
            <p>
              Auto robado con placa duplicada de uno legítimo. REPUVE sale "limpio"
              pero el VIN físico es de otra marca/año. Verificarro lo detecta antes
              de pagar.
            </p>
          </div>
          <div className="use-case">
            <h3>💸 Auto sobrepuesto</h3>
            <p>
              Vendedor pide 30% más que el precio justo del mercado. Comparamos
              contra ~50 listings similares en ML Motors.
            </p>
          </div>
          <div className="use-case">
            <h3>📸 Fotos manipuladas</h3>
            <p>
              Cofre con tono distinto al resto, paneles desalineados, óxido oculto.
              Claude visión las analiza y reporta.
            </p>
          </div>
          <div className="use-case">
            <h3>📝 Descripción sospechosa</h3>
            <p>
              "Estoy en el extranjero, deposita primero". Detectamos 21 patrones
              lingüísticos de estafa-clásica.
            </p>
          </div>
        </div>
      </section>

      <section className="faq">
        <h2>Preguntas frecuentes</h2>

        <details>
          <summary>¿Cuánto cuesta?</summary>
          <p>
            El preview (score + REPUVE básico) es <strong>gratis</strong>. El
            reporte completo cuesta <strong>$49 MXN</strong> (Básico) o
            $99 MXN (Premium con soporte por WhatsApp).
          </p>
        </details>

        <details>
          <summary>¿Sustituye una revisión mecánica?</summary>
          <p>
            No. Verificarro detecta fraudes documentales y de fotos antes de que
            veas el auto. La revisión mecánica sigue siendo necesaria — pídele al
            vendedor que te acompañe a tu mecánico de confianza.
          </p>
        </details>

        <details>
          <summary>¿Por qué a veces REPUVE no responde?</summary>
          <p>
            El portal de gob.mx tiene reCaptcha de Google que bloquea consultas
            automáticas. Cuando pasa, el preview te avisa y aún puedes desbloquear
            el reporte completo — incluye instrucciones para que tu confirmes
            REPUVE manualmente en repuve.gob.mx.
          </p>
        </details>

        <details>
          <summary>¿Cómo funciona el escaneo de VIN físico?</summary>
          <p>
            Después de desbloquear el reporte, abres el link en tu celular cuando
            vayas a ver el auto. Apuntas la cámara al tablero (visible por el
            parabrisas) o al marco de la puerta del chofer. Te decimos si el VIN
            del auto físico coincide con el anuncio — la mejor protección
            anti-placa-clonada disponible.
          </p>
        </details>

        <details>
          <summary>¿Cobran si el auto resulta robado?</summary>
          <p>
            El preview es siempre gratis. Si el preview ya marca el auto como
            robado (REPUVE Robado, score &lt; 40), descubriste el problema sin
            pagar nada. Si decides desbloquear igualmente, los $49 MXN incluyen
            el análisis completo y la documentación que necesites.
          </p>
        </details>
      </section>

      <footer className="footer">
        <small>
          Verificarro v0.2 · MVP scan-first · Hecho en México 🇲🇽 · Reportes
          informativos, no sustituyen revisión mecánica profesional.
        </small>
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
