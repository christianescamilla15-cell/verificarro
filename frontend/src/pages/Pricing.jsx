import { Link } from 'react-router-dom'
import {
  CheckCircle2, ScanLine, ShieldCheck, Zap, Crown, Building2,
  ArrowRight, MessageCircle,
} from 'lucide-react'

/**
 * Página /precios — 4 tiers comparados.
 *
 * El flow del usuario consumer ya pasa por el paywall modal con los 2
 * tiers básicos (basic / premium). Esta página existe para usuarios que
 * vienen de marketing / leads B2B (búsqueda activa o lotero) que necesitan
 * ver el catálogo completo antes de decidir.
 *
 * Los tiers `search` y `dealer` operacionalmente requieren validación
 * manual hasta que implementemos subscriptions automáticas. Cuando alguien
 * paga uno de estos tiers, el webhook MP nos avisa y manualmente
 * activamos el "pase" en su cuenta.
 */
export default function Pricing() {
  return (
    <main>
      <section className="hero" style={{ paddingTop: 'var(--space-12)', paddingBottom: 'var(--space-8)' }}>
        <span className="hero-eyebrow">
          <ShieldCheck size={14} strokeWidth={2.5} />
          Precios transparentes · Sin suscripción obligatoria
        </span>
        <h1>
          Paga sólo cuando <span className="accent">desbloqueas el reporte</span>
        </h1>
        <p className="tagline">
          Preview siempre gratis. 4 tiers según qué tanto compres autos —
          desde 1 reporte casual hasta lotero con 500 reportes/mes.
        </p>
      </section>

      <section className="pricing-grid">
        {/* Basic */}
        <article className="pricing-tier">
          <div className="pricing-icon"><ScanLine size={28} /></div>
          <h3>Básico</h3>
          <div className="pricing-price">
            <span className="amount">$49</span>
            <span className="period">MXN / reporte</span>
          </div>
          <p className="pricing-tagline">Para revisar 1 auto antes de comprarlo.</p>
          <ul className="pricing-features">
            <li><CheckCircle2 size={16} /> Score de riesgo + REPUVE básico</li>
            <li><CheckCircle2 size={16} /> Análisis del anuncio con IA (~50 comparables, fotos, descripción)</li>
            <li><CheckCircle2 size={16} /> Escaneo de VIN físico cuando veas el auto</li>
            <li><CheckCircle2 size={16} /> Reporte PDF descargable</li>
            <li><CheckCircle2 size={16} /> 6 links gob.mx pre-llenados</li>
          </ul>
          <Link to="/" className="primary big tier-cta">
            Empezar con un reporte <ArrowRight size={18} />
          </Link>
        </article>

        {/* Premium */}
        <article className="pricing-tier">
          <div className="pricing-icon"><Zap size={28} /></div>
          <h3>Premium</h3>
          <div className="pricing-price">
            <span className="amount">$99</span>
            <span className="period">MXN / reporte</span>
          </div>
          <p className="pricing-tagline">Lo del Básico + asesoría personal.</p>
          <ul className="pricing-features">
            <li><CheckCircle2 size={16} /> Todo lo de Básico</li>
            <li><CheckCircle2 size={16} /> Soporte por <strong>WhatsApp directo</strong> con Christian (24h SLA)</li>
            <li><CheckCircle2 size={16} /> Te ayudamos a interpretar el reporte si tienes dudas</li>
            <li><CheckCircle2 size={16} /> Lista personalizada de preguntas para el vendedor</li>
          </ul>
          <Link to="/" className="primary big tier-cta">
            Empezar Premium <ArrowRight size={18} />
          </Link>
        </article>

        {/* Búsqueda activa */}
        <article className="pricing-tier pricing-featured">
          <div className="pricing-badge">Más vendido</div>
          <div className="pricing-icon"><Crown size={28} /></div>
          <h3>Búsqueda activa</h3>
          <div className="pricing-price">
            <span className="amount">$199</span>
            <span className="period">MXN / mes</span>
          </div>
          <p className="pricing-tagline">
            Para cuando estás viendo varios autos antes de comprar.
          </p>
          <ul className="pricing-features">
            <li><CheckCircle2 size={16} /> Hasta <strong>50 reportes/mes</strong></li>
            <li><CheckCircle2 size={16} /> Soporte WhatsApp prioritario</li>
            <li><CheckCircle2 size={16} /> Historial de tus reportes en tu cuenta</li>
            <li><CheckCircle2 size={16} /> Alertas cuando un auto que reportaste cambia de precio</li>
            <li><CheckCircle2 size={16} /> Sin caducidad de reportes individuales</li>
          </ul>
          <Link to="/checkout-tier?tier=search" className="primary big tier-cta">
            Activar búsqueda <ArrowRight size={18} />
          </Link>
          <p className="pricing-finetext">
            Cancela cuando quieras. Si compras auto antes del mes, pides
            reembolso prorrateado.
          </p>
        </article>

        {/* Dealer */}
        <article className="pricing-tier">
          <div className="pricing-icon"><Building2 size={28} /></div>
          <h3>Dealer / Lotero</h3>
          <div className="pricing-price">
            <span className="amount">$1,499</span>
            <span className="period">MXN / mes</span>
          </div>
          <p className="pricing-tagline">
            Para distribuidores que evalúan autos a diario.
          </p>
          <ul className="pricing-features">
            <li><CheckCircle2 size={16} /> Hasta <strong>500 reportes/mes</strong> ($3 por reporte)</li>
            <li><CheckCircle2 size={16} /> Acceso multi-usuario (hasta 5 cuentas)</li>
            <li><CheckCircle2 size={16} /> API directa para integrar con tu CRM</li>
            <li><CheckCircle2 size={16} /> Reporte ejecutivo mensual con tu pipeline</li>
            <li><CheckCircle2 size={16} /> Soporte WhatsApp + onboarding 1:1</li>
          </ul>
          <Link to="/checkout-tier?tier=dealer" className="primary big tier-cta">
            Activar Dealer <ArrowRight size={18} />
          </Link>
          <p className="pricing-finetext">
            Si revisas más de 500 autos/mes hablamos de plan custom.
            Escríbenos.
          </p>
        </article>
      </section>

      <section className="section">
        <span className="section-eyebrow">Comparativa rápida</span>
        <h2 className="section-title">¿Cuál tier me sirve?</h2>

        <div className="pricing-compare">
          <div className="compare-row compare-head">
            <div></div>
            <div>Básico</div>
            <div>Premium</div>
            <div>Búsqueda</div>
            <div>Dealer</div>
          </div>
          <div className="compare-row">
            <div>Reportes</div>
            <div>1</div>
            <div>1</div>
            <div>50/mes</div>
            <div>500/mes</div>
          </div>
          <div className="compare-row">
            <div>Costo unitario efectivo</div>
            <div>$49</div>
            <div>$99</div>
            <div>~$4</div>
            <div>~$3</div>
          </div>
          <div className="compare-row">
            <div>WhatsApp directo</div>
            <div>—</div>
            <div>✓</div>
            <div>Prioritario</div>
            <div>+ onboarding</div>
          </div>
          <div className="compare-row">
            <div>API integración</div>
            <div>—</div>
            <div>—</div>
            <div>—</div>
            <div>✓</div>
          </div>
          <div className="compare-row">
            <div>Multi-usuario</div>
            <div>—</div>
            <div>—</div>
            <div>—</div>
            <div>5 cuentas</div>
          </div>
        </div>
      </section>

      <section className="final-cta">
        <h2>Empieza con el preview gratis</h2>
        <p>
          Escanea cualquier placa, recibe el score y los datos REPUVE
          básicos. Sin tarjeta, sin email. Decides después si pagas.
        </p>
        <Link to="/" className="primary big">
          <ScanLine size={20} strokeWidth={2.4} />
          Escanear placa ahora
        </Link>
      </section>

      <section className="section faq">
        <h2 className="section-title">Dudas comunes sobre los planes</h2>
        <div className="faq-list">
          <details>
            <summary>¿Cómo funciona el plan mensual de Búsqueda activa o Dealer?</summary>
            <p>
              Pagas el monto mensual vía Mercado Pago (tarjeta, OXXO, SPEI). Te
              activamos el pase y desde el primer minuto puedes generar reportes
              ilimitados hasta el cap del plan. Si llegas al cap antes del mes,
              avísanos por WhatsApp y vemos. Si no llegas al cap, los reportes
              no usados no se acumulan al siguiente mes.
            </p>
          </details>

          <details>
            <summary>¿Si compro Búsqueda y compro auto a la primera, me regresan dinero?</summary>
            <p>
              Sí. Cancelas escribiendo a soporte y te reembolsamos prorrateado
              por días no usados (descuentas días corridos × $199/30). Mercado
              Pago te devuelve a la misma forma de pago en 1-3 días hábiles.
            </p>
          </details>

          <details>
            <summary>¿La API del plan Dealer cómo se ve?</summary>
            <p>
              REST simple — POST con placa o URL del listing, recibes JSON con
              el score + análisis completo. Documentación en{' '}
              <code>verificarro.mx/docs/api</code> (te la enviamos al activar
              el plan). Hooks de webhook para alertas de placa robada.
            </p>
          </details>

          <details>
            <summary>¿Hay descuentos por volumen sobre Dealer?</summary>
            <p>
              Sí. Si proyectas más de 500 reportes/mes, escribimos un plan
              custom — usualmente entre $2-2.5 por reporte para volumen 1000+
              y $1.5-2 para 5000+. Escríbenos en{' '}
              <a href="mailto:hola@verificarro.mx">hola@verificarro.mx</a>.
            </p>
          </details>

          <details>
            <summary>¿Sustituye el reporte una revisión mecánica profesional?</summary>
            <p>
              No. Verificarro detecta fraudes documentales, fotos manipuladas,
              precios fuera de mercado y placa clonada. Una revisión mecánica
              sigue siendo necesaria — pero ya no vas a perder el tiempo
              llevando al taller un auto que viene mal de origen.
            </p>
          </details>
        </div>
      </section>

      <footer className="footer">
        <p>
          <CheckCircle2 size={12} style={{ display: 'inline', verticalAlign: '-2px' }} />
          {' '}Verificarro · Hecho en México 🇲🇽 · Pagos vía Mercado Pago.
        </p>
        <p className="muted small">
          ¿Dudas?{' '}
          <a href="mailto:hola@verificarro.mx">
            <MessageCircle size={12} style={{ verticalAlign: '-2px' }} /> hola@verificarro.mx
          </a>
        </p>
      </footer>
    </main>
  )
}
