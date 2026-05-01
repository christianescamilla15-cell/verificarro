import { useEffect, useState } from 'react'
import { MessageCircle } from 'lucide-react'
import { api } from '../lib/api.js'

/**
 * Botón flotante de WhatsApp para tier Premium.
 *
 * Solo se renderiza si el backend tiene configurado
 * `WHATSAPP_SUPPORT_NUMBER`. El número se lee de `/api/config` (público)
 * la primera vez que se monta el componente; después se cachea en
 * memoria por la duración de la sesión.
 *
 * Genera un link `https://wa.me/{number}?text=...` con un mensaje
 * pre-llenado contextual:
 *   - Si recibe `reportId`/`plate`: "Hola Verificarro, soy del reporte
 *     {report_id} placa {plate}, tengo una duda..."
 *   - Si no: "Hola Verificarro, quiero información sobre el plan
 *     Premium..."
 *
 * `variant`:
 *   - "floating" (default): botón flotante bottom-right, presente en
 *     todas las páginas
 *   - "inline": versión pequeña dentro de una sección (e.g. paywall,
 *     final del reporte)
 */
export default function WhatsAppButton({ variant = 'floating', reportId, plate, label }) {
  const [config, setConfig] = useState(null)

  useEffect(() => {
    if (window.__verificarroConfig !== undefined) {
      setConfig(window.__verificarroConfig)
      return
    }
    api.get('/api/config').then((res) => {
      const data = res.ok ? res.data : { whatsapp_enabled: false }
      window.__verificarroConfig = data
      setConfig(data)
    })
  }, [])

  if (!config?.whatsapp_enabled || !config?.whatsapp_number) return null

  const text = buildMessage(reportId, plate)
  const href = `https://wa.me/${config.whatsapp_number}?text=${encodeURIComponent(text)}`

  if (variant === 'inline') {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="wa-button-inline"
      >
        <MessageCircle size={18} strokeWidth={2.4} />
        {label || 'Hablar por WhatsApp'}
      </a>
    )
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="wa-button-float"
      aria-label="Abrir chat WhatsApp con soporte Verificarro"
    >
      <MessageCircle size={26} strokeWidth={2.2} />
    </a>
  )
}

function buildMessage(reportId, plate) {
  if (reportId) {
    const platePart = plate ? ` placa ${plate}` : ''
    return (
      `Hola Verificarro, soy del reporte ${reportId.slice(0, 8)}${platePart}.`
      + ' Tengo una duda sobre los resultados.'
    )
  }
  return (
    'Hola Verificarro, vi su servicio y quiero información sobre el plan'
    + ' Premium / Búsqueda activa / Dealer.'
  )
}
