import { useEffect, useRef, useState } from 'react'
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
  const attemptsRef = useRef(0)  // MOD-006: leer attempts sin re-disparar effect

  useEffect(() => {
    if (!externalRef) {
      setError('No encontramos tu pago. Si ya pagaste, contáctanos.')
      return
    }

    // MOD-005: el polling token vive en localStorage; lo guardamos antes
    // del redirect a MP. Sin él el backend rechaza con 401.
    let pollingToken = null
    try {
      pollingToken = localStorage.getItem(`verificarro_polling_${externalRef}`)
    } catch { /* modo privado, lo manejamos abajo */ }

    if (!pollingToken) {
      setError(
        'No encontramos tu sesión de pago. Si ya pagaste, te llegará el ' +
        'reporte por email en ~1 min. Si tienes dudas escríbenos por WhatsApp.',
      )
      return
    }

    let mounted = true
    let timer

    async function poll() {
      const res = await api.get(
        `/api/payments/${externalRef}?token=${encodeURIComponent(pollingToken)}`,
      )
      if (!mounted) return
      if (!res.ok) {
        if (res.status === 404) {
          setError('Pago no encontrado. Si pagaste, espera unos segundos y refresca.')
          return
        }
        if (res.status === 401) {
          setError(
            'No pudimos validar tu sesión. Si ya pagaste te llegará el ' +
            'reporte por email; si tienes dudas escríbenos por WhatsApp.',
          )
          return
        }
        setError(res.error)
        return
      }
      setPaymentStatus(res.data.status)
      if (res.data.report_status === 'unlocked' && res.data.report_json) {
        setReport(res.data.report_json)
        // Cleanup del token: ya no lo necesitamos
        try {
          localStorage.removeItem(`verificarro_polling_${externalRef}`)
        } catch { /* ignore */ }
        return
      }
      if (res.data.status === 'failed') {
        setError('El pago falló. Intenta de nuevo desde la página principal.')
        return
      }
      // MOD-006: usamos ref para chequear cap sin re-disparar el effect.
      attemptsRef.current += 1
      setAttempts(attemptsRef.current)
      if (attemptsRef.current < MAX_POLL_ATTEMPTS) {
        timer = setTimeout(poll, POLL_INTERVAL_MS)
      } else {
        setError(
          'Tu reporte está tardando más de lo esperado. Te avisaremos al ' +
          'email cuando esté listo.',
        )
      }
    }

    poll()
    return () => {
      mounted = false
      if (timer) clearTimeout(timer)
    }
    // MOD-006: SIN `attempts` en deps — antes el effect se re-disparaba
    // cada incremento, generando timers paralelos y duplicando el polling.
  }, [externalRef])

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
