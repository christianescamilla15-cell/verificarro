import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import Spinner from '../components/Spinner.jsx'
import ReportView from './Report.jsx'

const POLL_INTERVAL_MS = 2500
const MAX_POLL_ATTEMPTS = 120  // ~5 min

export default function CheckoutSuccess() {
  const [params] = useSearchParams()
  // MP redirige con `external_reference` o `preference_id` según config
  const externalRef =
    params.get('external_reference') ||
    params.get('preference_id') ||
    params.get('payment_id')

  const [paymentStatus, setPaymentStatus] = useState(null)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [attempts, setAttempts] = useState(0)

  useEffect(() => {
    if (!externalRef) {
      setError('No encontramos tu pago. Si ya pagaste, contáctanos.')
      return
    }
    let mounted = true
    let timer

    async function poll() {
      const res = await api.get(`/api/payments/${externalRef}`)
      if (!mounted) return
      if (!res.ok) {
        if (res.status === 404) {
          setError('Pago no encontrado. Si pagaste, espera unos segundos y refresca.')
          return
        }
        setError(res.error)
        return
      }
      setPaymentStatus(res.data.status)
      if (res.data.report_json) {
        setReport(res.data.report_json)
        return
      }
      if (res.data.status === 'failed') {
        setError('El pago falló. Intenta de nuevo desde la página principal.')
        return
      }
      setAttempts((n) => n + 1)
      if (attempts < MAX_POLL_ATTEMPTS) {
        timer = setTimeout(poll, POLL_INTERVAL_MS)
      } else {
        setError('Tu reporte está tardando más de lo esperado. Te avisaremos al email cuando esté listo.')
      }
    }

    poll()
    return () => {
      mounted = false
      if (timer) clearTimeout(timer)
    }
  }, [externalRef, attempts])

  if (error) {
    return (
      <div className="auth-card">
        <h1>⚠️ {error}</h1>
        <a href="/" className="primary">Volver al inicio</a>
      </div>
    )
  }

  if (report) {
    return <ReportView reportData={report} />
  }

  return (
    <div className="auth-card">
      <h1>{paymentStatus === 'paid' ? 'Generando tu reporte…' : 'Confirmando pago…'}</h1>
      <Spinner message={
        paymentStatus === 'paid'
          ? 'Estamos analizando el anuncio. Esto toma ~30 segundos. No cierres esta página.'
          : 'Esperando confirmación de Mercado Pago…'
      } />
      <p className="muted small">
        Estado del pago: <strong>{paymentStatus || 'consultando…'}</strong>
        {' · '} Intento {attempts + 1} de {MAX_POLL_ATTEMPTS}
      </p>
    </div>
  )
}
