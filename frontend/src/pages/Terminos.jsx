import { Link } from 'react-router-dom'

/**
 * Términos y Condiciones — define el alcance del servicio,
 * limitación de responsabilidad y obligaciones del usuario.
 *
 * IMPORTANTE: este draft cubre los issues identificados en la
 * auditoría legal interna pero NO es definitivo hasta review por
 * abogado certificado MX. Cláusulas críticas (limitación de
 * responsabilidad, jurisdicción) deben validarse contra LFPC y
 * Código de Comercio antes de procesar volumen.
 */
export default function Terminos() {
  return (
    <main className="legal-page">
      <Link to="/" className="back-link">← Volver al inicio</Link>
      <article>
        <h1>Términos y Condiciones</h1>
        <p className="muted small">Última actualización: 2 de mayo de 2026</p>

        <section>
          <h2>1. Aceptación</h2>
          <p>
            Al usar Verificarro (sitio web, dashboard, reportes,
            servicios relacionados — en adelante "el Servicio"), aceptas
            estos Términos y Condiciones. Si no estás de acuerdo con
            algún término, no uses el Servicio.
          </p>
          <p>
            El operador es <strong>Christian Hernández Escamilla</strong>,
            persona física con actividad empresarial bajo régimen
            RESICO, contactable en{' '}
            <a href="mailto:hola@verificarro.mx">hola@verificarro.mx</a>.
          </p>
        </section>

        <section>
          <h2>2. Qué es Verificarro y qué NO es</h2>
          <p><strong>Verificarro ES</strong>:</p>
          <ul>
            <li>
              Un servicio que consulta fuentes públicas (REPUVE,
              NHTSA, SAT) y analiza información del anuncio que tú nos
              proporcionas (URL de Mercado Libre, fotos, etc.).
            </li>
            <li>
              Un agregador de señales de riesgo basado en datos
              accesibles legalmente.
            </li>
            <li>
              Una herramienta para AYUDARTE a tomar mejor decisión
              antes de comprar un auto usado.
            </li>
          </ul>
          <p><strong>Verificarro NO ES</strong>:</p>
          <ul>
            <li>
              Una agencia gubernamental ni representante de gob.mx,
              SAT, REPUVE, ni NHTSA.
            </li>
            <li>
              Un seguro que te indemnice si el auto resulta tener
              problemas no detectados.
            </li>
            <li>
              Un sustituto de inspección mecánica presencial. NO podemos
              detectar problemas mecánicos sin ver el auto.
            </li>
            <li>
              Una garantía de compra. La decisión final y el riesgo de
              la transacción es 100% tuyo.
            </li>
          </ul>
        </section>

        <section>
          <h2>3. Limitación de responsabilidad</h2>
          <p>
            <strong>El Servicio se ofrece "tal como está"</strong>. La
            información proviene de fuentes públicas que pueden:
          </p>
          <ul>
            <li>Estar desactualizadas (REPUVE no es tiempo real).</li>
            <li>
              Tener cobertura geográfica limitada (algunos estados no
              participan en la base nacional REPUVE).
            </li>
            <li>
              No reflejar estafas sofisticadas (clones perfectos de
              fotos, NIVs duplicados de unidades importadas, etc.).
            </li>
          </ul>
          <p>
            <strong>Responsabilidad máxima de Verificarro</strong>: el
            monto que pagaste por el reporte específico. Si recibiste
            un reporte basic ($49 MXN), nuestra responsabilidad máxima
            por ese reporte es $49 MXN. Esto aplica para cualquier tipo
            de reclamación, incluyendo pero no limitado a:
          </p>
          <ul>
            <li>Información incorrecta o incompleta en el reporte.</li>
            <li>No detección de algún problema del vehículo.</li>
            <li>Demora en la entrega del reporte.</li>
            <li>Caída del servicio durante consulta.</li>
          </ul>
          <p>
            <strong>Verificarro NO se hace responsable</strong> por:
          </p>
          <ul>
            <li>
              Pérdidas financieras derivadas de comprar un auto que
              resultó problemático.
            </li>
            <li>
              Daños indirectos, lucro cesante, daño moral, o
              consecuenciales.
            </li>
            <li>
              Decisiones de compra basadas exclusivamente en nuestro
              reporte. Siempre recomendamos validación adicional con
              mecánico de confianza y verificación presencial del auto.
            </li>
          </ul>
        </section>

        <section>
          <h2>4. Tarifas y pagos</h2>
          <p>
            <strong>Modalidades</strong>:
          </p>
          <ul>
            <li>
              <strong>Básico</strong>: $49 MXN por reporte (pago único,
              IVA incluido).
            </li>
            <li>
              <strong>Premium</strong>: $99 MXN por reporte + soporte
              prioritario WhatsApp (pago único).
            </li>
            <li>
              <strong>Búsqueda Activa</strong>: $199 MXN/mes,
              suscripción recurrente con hasta 50 reportes/mes.
            </li>
            <li>
              <strong>Dealer</strong>: $1,499 MXN/mes, suscripción
              recurrente con hasta 500 reportes/mes + acceso API.
            </li>
          </ul>
          <p>
            Los pagos se procesan vía Mercado Pago. Aceptamos tarjeta
            de crédito/débito, OXXO y SPEI. Las suscripciones
            recurrentes se cobran automáticamente cada mes hasta que
            las canceles.
          </p>
          <p>
            <strong>CFDI</strong>: si necesitas factura fiscal,
            solicítala enviando tus datos fiscales (RFC, razón
            social, uso CFDI) a hola@verificarro.mx dentro del mes
            calendario del pago.
          </p>
        </section>

        <section>
          <h2>5. Cancelación y reembolsos</h2>
          <p>
            <strong>Reportes one-time (Básico/Premium)</strong>: una
            vez generado el reporte, el servicio se considera
            entregado. Si el reporte falló por problema técnico
            nuestro (e.g. error 500 en el servidor durante generación),
            te lo regeneramos sin costo o reembolsamos íntegro.
          </p>
          <p>
            <strong>Suscripciones (Búsqueda/Dealer)</strong>: puedes
            cancelar en cualquier momento desde tu Dashboard o
            contactándonos. La cancelación toma efecto al final del
            ciclo mensual ya pagado — sigues teniendo acceso hasta
            entonces. NO hay reembolso prorrateado.
          </p>
          <p>
            <strong>Reembolso por error nuestro</strong>: si la
            información del reporte resulta materialmente incorrecta
            por error de nuestro pipeline (no por desactualización de
            la fuente), reembolsamos el monto pagado por ese reporte
            específico. Plazo: 30 días desde la fecha de generación
            del reporte.
          </p>
        </section>

        <section>
          <h2>6. Uso aceptable</h2>
          <p>
            Al usar Verificarro, te comprometes a:
          </p>
          <ul>
            <li>
              No automatizar el acceso al Servicio fuera de la API
              oficial (tier Dealer). Scrapers, bots, o herramientas que
              consuman el servicio sin autorización son detectados y
              bloqueados vía rate limiting.
            </li>
            <li>
              No usar el Servicio para fines ilícitos (lavado de
              dinero, fraude, identidad falsa, etc.).
            </li>
            <li>
              Proporcionar información veraz al checkout (email,
              número de WhatsApp, datos del vehículo).
            </li>
            <li>
              No revender los reportes a terceros sin autorización
              expresa. Cada reporte es para uso del comprador específico.
            </li>
          </ul>
          <p>
            Violaciones a estos términos pueden resultar en suspensión
            o cancelación de tu cuenta sin reembolso.
          </p>
        </section>

        <section>
          <h2>7. Propiedad intelectual</h2>
          <p>
            La marca <strong>Verificarro</strong>, el logo, el diseño
            del sitio, el algoritmo de scoring y el contenido de los
            reportes son propiedad intelectual del operador. La
            información de fuentes públicas (REPUVE, NHTSA, SAT) NO es
            nuestra y la respetamos como pertenencia de sus
            instituciones originarias.
          </p>
          <p>
            Tienes licencia personal y limitada para usar los reportes
            que pagas — para tu propia decisión de compra. NO incluye
            redistribución, modificación, o uso comercial.
          </p>
        </section>

        <section>
          <h2>8. Datos personales</h2>
          <p>
            El tratamiento de tus datos personales se rige por nuestro{' '}
            <Link to="/privacidad">Aviso de Privacidad</Link>, que es
            parte integral de estos Términos.
          </p>
        </section>

        <section>
          <h2>9. Modificaciones al Servicio y a estos Términos</h2>
          <p>
            Podemos modificar funcionalidades, pricing, o estos
            Términos en cualquier momento. Cambios materiales se
            notifican por email con 15 días de anticipación.
            Continuar usando el Servicio después de la fecha de
            entrada en vigor implica aceptación.
          </p>
          <p>
            Cambios en pricing aplican únicamente a nuevos pagos —
            tu suscripción activa mantiene el precio del momento de
            tu última renovación.
          </p>
        </section>

        <section>
          <h2>10. Suspensión y terminación</h2>
          <p>
            Podemos suspender o cancelar tu acceso al Servicio si:
          </p>
          <ul>
            <li>Violas estos Términos.</li>
            <li>
              No has pagado una suscripción activa después de 7 días de
              gracia.
            </li>
            <li>
              Por orden judicial o autoridad competente.
            </li>
            <li>
              Si el Servicio se discontinua (te notificaremos con 30
              días de anticipación y haremos refund prorrateado de
              suscripciones activas).
            </li>
          </ul>
        </section>

        <section>
          <h2>11. Jurisdicción y resolución de disputas</h2>
          <p>
            Estos Términos se rigen por las leyes de los Estados
            Unidos Mexicanos. Para cualquier controversia, ambas
            partes se someten expresamente a la competencia y
            jurisdicción de los tribunales de la Ciudad de México,
            renunciando a cualquier otro fuero que pudiera
            corresponderles.
          </p>
          <p>
            Antes de iniciar acción legal, recomendamos contactarnos
            directamente — la mayoría de los problemas se resuelven en
            menos de 48 horas por email o WhatsApp.
          </p>
          <p>
            En caso de litigio relacionado con derechos del consumidor,
            puedes acudir a la Procuraduría Federal del Consumidor
            (PROFECO):{' '}
            <a href="https://www.gob.mx/profeco" target="_blank" rel="noreferrer">
              gob.mx/profeco
            </a>
          </p>
        </section>

        <section>
          <h2>12. Disposiciones generales</h2>
          <p>
            Si alguna cláusula de estos Términos resulta inválida o
            inaplicable, el resto de las disposiciones permanecen en
            pleno vigor.
          </p>
          <p>
            La falta de ejercicio inmediato por nuestra parte de un
            derecho derivado de estos Términos no constituye renuncia
            a ese derecho.
          </p>
        </section>

        <p style={{ marginTop: 'var(--space-8)' }}>
          <Link to="/privacidad">← Aviso de Privacidad</Link>
        </p>
      </article>
    </main>
  )
}
