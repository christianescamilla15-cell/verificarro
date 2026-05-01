export default function CheckoutFailure() {
  return (
    <div className="auth-card">
      <h1>⚠️ El pago no se completó</h1>
      <p>
        Mercado Pago no aprobó tu pago. Esto puede pasar por:
      </p>
      <ul>
        <li>Datos de tarjeta incorrectos</li>
        <li>Saldo insuficiente</li>
        <li>El banco rechazó la transacción por seguridad</li>
      </ul>
      <p>No se te cobró nada. Puedes intentar de nuevo:</p>
      <a href="/" className="primary big">Volver al inicio</a>
    </div>
  )
}
