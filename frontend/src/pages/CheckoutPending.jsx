export default function CheckoutPending() {
  return (
    <div className="auth-card">
      <h1>⏳ Pago pendiente</h1>
      <p>
        Tu pago está en proceso (común si pagaste con OXXO o SPEI).
        Te llegará un email cuando esté confirmado y tu reporte esté listo.
      </p>
      <p className="muted">
        OXXO confirma en ~30 minutos. SPEI suele ser instantáneo.
      </p>
      <a href="/" className="primary big">Volver al inicio</a>
    </div>
  )
}
