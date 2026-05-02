import { Link } from 'react-router-dom'

/**
 * Aviso de Privacidad — cumple LFPDPPP MX (artículos 8 y 16) e
 * incluye los derechos ARCO (artículos 22-26).
 *
 * IMPORTANTE: este es un draft elaborado en buena fe pero NO ha sido
 * revisado por abogado certificado MX. Christian debe pedir review
 * legal antes de considerarlo definitivo. La fecha de última
 * actualización es necesaria por ley para tracking de cambios.
 */
export default function Privacidad() {
  return (
    <main className="legal-page">
      <Link to="/" className="back-link">← Volver al inicio</Link>
      <article>
        <h1>Aviso de Privacidad</h1>
        <p className="muted small">Última actualización: 2 de mayo de 2026</p>

        <section>
          <h2>1. Identidad del responsable</h2>
          <p>
            <strong>Christian Hernández Escamilla</strong>, opera el
            servicio Verificarro (en adelante "Verificarro" o "el
            Servicio") como persona física con actividad empresarial.
          </p>
          <p>
            <strong>Domicilio para efectos legales</strong>: México.{' '}
            <strong>Contacto para temas de privacidad</strong>:{' '}
            <a href="mailto:hola@verificarro.mx">hola@verificarro.mx</a>
            {' '}o por WhatsApp al +52 1 55 7960 5324.
          </p>
        </section>

        <section>
          <h2>2. Datos personales que recolectamos</h2>
          <p>Para prestar el Servicio, Verificarro recolecta:</p>
          <ul>
            <li>
              <strong>Email</strong>: para enviar el reporte y, si te
              registras, para autenticar tu sesión vía magic link.
            </li>
            <li>
              <strong>Número de WhatsApp</strong> (opcional): si lo
              proporcionas en checkout, lo usamos para soporte
              prioritario y nada más.
            </li>
            <li>
              <strong>Datos del vehículo que escaneas</strong>: placa,
              VIN/NIV, foto de la placa, foto del VIN, listing URL del
              anuncio. Estos NO son datos personales tuyos sino del
              vehículo en cuestión.
            </li>
            <li>
              <strong>Datos del CFDI</strong> (si subes factura): folio
              fiscal UUID, RFC del emisor y del receptor, fecha y
              total. Datos del titular ANTERIOR del vehículo, no tuyos.
            </li>
            <li>
              <strong>Datos de pago</strong>: procesados por Mercado
              Pago. Verificarro NO ve ni almacena tus datos de tarjeta.
              Solo recibimos el confirmation token y el estado del
              pago de Mercado Pago.
            </li>
            <li>
              <strong>Datos técnicos</strong>: dirección IP, user-agent
              del navegador, timestamps. Usados para rate limiting y
              seguridad. Anonimizados después de 30 días.
            </li>
          </ul>
        </section>

        <section>
          <h2>3. Finalidades del tratamiento</h2>
          <p>Tus datos se usan exclusivamente para:</p>
          <ul>
            <li>
              <strong>Primaria</strong>: generar el reporte de
              verificación que solicitas y entregártelo por email +
              dashboard.
            </li>
            <li>
              <strong>Primaria</strong>: procesar el pago vía Mercado
              Pago y emitir CFDI cuando lo solicites.
            </li>
            <li>
              <strong>Primaria</strong>: dar soporte si abres ticket
              por WhatsApp o email.
            </li>
            <li>
              <strong>Secundaria</strong>: notificarte sobre
              actualizaciones críticas del servicio (cambios en
              pricing, terms, o brechas de seguridad si aplica). NO
              marketing — solo cosas que afectan tu uso.
            </li>
          </ul>
          <p>
            Si en el futuro queremos usar tus datos para otra finalidad
            (e.g. newsletter mensual), te pediremos consentimiento
            explícito separado.
          </p>
        </section>

        <section>
          <h2>4. Transferencias a terceros</h2>
          <p>
            Para prestar el servicio, Verificarro transfiere algunos
            datos a proveedores específicos:
          </p>
          <ul>
            <li>
              <strong>Mercado Pago</strong> (procesamiento de pagos):
              email del comprador, monto, IP. No incluye datos del
              vehículo. Su política:{' '}
              <a href="https://www.mercadopago.com.mx/privacidad" target="_blank" rel="noreferrer">
                mercadopago.com.mx/privacidad
              </a>
            </li>
            <li>
              <strong>Resend</strong> (envío de emails transaccionales):
              email del destinatario y contenido del email
              (reporte, magic link). Política:{' '}
              <a href="https://resend.com/legal/privacy-policy" target="_blank" rel="noreferrer">
                resend.com/legal/privacy-policy
              </a>
            </li>
            <li>
              <strong>Anthropic</strong> (análisis de fotos con IA): las
              imágenes que subes para análisis. Anthropic NO entrena
              modelos con esos datos por configuración. Política:{' '}
              <a href="https://www.anthropic.com/privacy" target="_blank" rel="noreferrer">
                anthropic.com/privacy
              </a>
            </li>
            <li>
              <strong>Render</strong> (hosting backend) y{' '}
              <strong>Vercel</strong> (hosting frontend): datos en
              tránsito y at-rest en los servidores donde corre la
              aplicación.
            </li>
          </ul>
          <p>
            <strong>NO vendemos</strong> tus datos a terceros para
            marketing. <strong>NO compartimos</strong> con dealers ni
            con servicios de scoring crediticio.
          </p>
        </section>

        <section>
          <h2>5. Conservación de datos</h2>
          <ul>
            <li>
              <strong>Reportes y datos del vehículo</strong>: 30 días
              después de generados. Después se anonimizan (perdiendo
              el vínculo con tu cuenta).
            </li>
            <li>
              <strong>CFDI emitidos</strong>: 5 años (obligación SAT,
              Código Fiscal de la Federación artículo 67).
            </li>
            <li>
              <strong>Logs técnicos</strong>: 90 días, después
              anonimizados.
            </li>
            <li>
              <strong>Cuenta de usuario</strong>: hasta que solicites
              eliminación vía ARCO (sección 7) o 3 años de inactividad.
            </li>
          </ul>
        </section>

        <section>
          <h2>6. Medidas de seguridad</h2>
          <ul>
            <li>
              Comunicación cifrada en tránsito (TLS 1.3) entre tu
              navegador, nuestros servidores y todos los proveedores
              terceros.
            </li>
            <li>
              Encriptación at-rest de datos personales sensibles
              (email del comprador, placa, VIN) usando Fernet
              (AES-128-CBC + HMAC-SHA256).
            </li>
            <li>
              Tokens de sesión JWT con TTL de 30 días, rotables.
            </li>
            <li>
              Validación HMAC estricta de webhooks de Mercado Pago.
            </li>
            <li>
              Rate limiting en endpoints públicos para prevenir abuse.
            </li>
            <li>
              Monitoreo de errores con Sentry (sin PII por
              configuración explícita).
            </li>
          </ul>
        </section>

        <section>
          <h2>7. Derechos ARCO</h2>
          <p>
            Bajo la LFPDPPP tienes derecho a:
          </p>
          <ul>
            <li>
              <strong>Acceso</strong>: pedirnos qué datos tuyos tenemos
              guardados.
            </li>
            <li>
              <strong>Rectificación</strong>: corregir datos
              incorrectos o incompletos.
            </li>
            <li>
              <strong>Cancelación</strong>: eliminar tus datos. Excepto
              CFDI emitidos (obligación SAT 5 años).
            </li>
            <li>
              <strong>Oposición</strong>: limitar el uso de tus datos
              para finalidades secundarias (notificaciones de
              servicio, etc.).
            </li>
          </ul>
          <p>
            Para ejercer cualquiera de estos derechos, escríbenos a{' '}
            <a href="mailto:hola@verificarro.mx">hola@verificarro.mx</a>{' '}
            con asunto "Solicitud ARCO" e indícanos tu email
            registrado más el derecho que quieres ejercer. Te
            respondemos en un máximo de 20 días hábiles.
          </p>
          <p>
            Si consideras que tu solicitud no fue atendida
            correctamente, puedes acudir al INAI (Instituto Nacional
            de Transparencia):{' '}
            <a href="https://home.inai.org.mx/" target="_blank" rel="noreferrer">
              home.inai.org.mx
            </a>
          </p>
        </section>

        <section>
          <h2>8. Uso de cookies</h2>
          <p>
            Verificarro usa solo cookies estrictamente necesarias para
            el funcionamiento del Servicio:
          </p>
          <ul>
            <li>
              <strong>verificarro_jwt</strong> (sessionStorage): tu token
              de sesión cuando inicias con magic link.
            </li>
            <li>
              <strong>verificarro_theme</strong> (localStorage): tu
              preferencia de tema dark/light.
            </li>
            <li>
              <strong>verificarro_polling_*</strong> (localStorage,
              temporal): para validar el estado de tu pago tras
              regresar de Mercado Pago. Se elimina cuando el reporte
              está listo.
            </li>
          </ul>
          <p>
            <strong>NO usamos</strong> cookies de tracking de terceros
            (Google Analytics, Facebook Pixel, etc.). Si activamos
            analytics propios (Vercel), son privacy-preserving y NO
            recolectan PII.
          </p>
        </section>

        <section>
          <h2>9. Menores de edad</h2>
          <p>
            Verificarro es un servicio dirigido a personas mayores de
            18 años. Si eres menor, no debes usar el Servicio sin
            consentimiento explícito de tus padres o tutores legales.
          </p>
        </section>

        <section>
          <h2>10. Cambios a este aviso</h2>
          <p>
            Si modificamos sustancialmente este Aviso, te notificaremos
            por email a la dirección registrada al menos 15 días antes
            de que entren en vigor los cambios. Cambios menores
            (correcciones de redacción, actualizaciones de URLs) se
            publican aquí sin notificación previa.
          </p>
          <p>
            Esta es la versión <strong>1.0</strong> del Aviso, vigente
            desde el 2 de mayo de 2026.
          </p>
        </section>

        <section>
          <h2>11. Jurisdicción</h2>
          <p>
            Este Aviso se rige por la legislación de los Estados Unidos
            Mexicanos. Para cualquier controversia, nos sometemos a la
            jurisdicción de los tribunales competentes en la Ciudad de
            México.
          </p>
        </section>

        <p style={{ marginTop: 'var(--space-8)' }}>
          <Link to="/terminos">Ver Términos y Condiciones →</Link>
        </p>
      </article>
    </main>
  )
}
