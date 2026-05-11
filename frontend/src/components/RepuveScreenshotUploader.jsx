import { useRef, useState, useMemo } from 'react'
import {
  Camera, CheckCircle2, AlertCircle, RefreshCcw, X, FileText,
} from 'lucide-react'
import { api } from '../lib/api.js'
import Spinner from './Spinner.jsx'

/**
 * Heurística mobile vs desktop — mobile bloquea screenshots de REPUVE
 * con FLAG_SECURE en Android (mismo concepto en iOS con AVB), así que
 * mobile users DEBEN usar "Exportar a PDF". Desktop sí puede screenshot
 * tradicional. Cambia el copy según el caso.
 */
function detectIsMobile() {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent || ''
  return /Mobi|Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua)
}

/**
 * Subir captura del modal REPUVE (post-consulta manual en repuve.gob.mx)
 * y obtener resultado parseado.
 *
 * Flow esperado del usuario:
 * 1. Hizo click en "Abrir REPUVE oficial" (boton de PreviewReport)
 * 2. Resolvio el captcha en el portal y vio el modal de resultado
 * 3. Tomo una captura (boton fisico de screenshot del celular)
 * 4. Vuelve a Verificarro y sube la captura aqui
 * 5. Backend Claude Vision OCR + parser canonico
 * 6. Resultado real se inyecta al reporte via `onResult`
 *
 * Acepta camera+gallery (`accept="image/*" capture="environment"`)
 * para que mobile abra el picker nativo con opcion de "tomar foto" o
 * "elegir de galeria" (depende del OS).
 */
export default function RepuveScreenshotUploader({
  plate, vin, onResult, onCancel,
}) {
  const fileInputRef = useRef(null)
  const [stage, setStage] = useState('idle')
  // idle | uploading | success | error
  const [previewUrl, setPreviewUrl] = useState(null)
  const [error, setError] = useState(null)
  const [warning, setWarning] = useState(null)
  const isMobile = useMemo(detectIsMobile, [])

  function pickFile() {
    fileInputRef.current?.click()
  }

  function reset() {
    setStage('idle')
    setError(null)
    setWarning(null)
    setPreviewUrl(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setWarning(null)

    const isImage = file.type.startsWith('image/')
    const isPdf = file.type === 'application/pdf'
    if (!isImage && !isPdf) {
      setError('Selecciona una imagen (JPG/PNG/WebP) o el PDF que descargaste de REPUVE.')
      setStage('error')
      return
    }
    // Limite 3MB para imagen, 4MB para PDF (REPUVE PDF puede pesar mas).
    const maxBytes = isPdf ? 4 * 1024 * 1024 : 3 * 1024 * 1024
    if (file.size > maxBytes) {
      const limitMB = isPdf ? '4 MB' : '3 MB'
      setError(`El archivo es muy grande (limite ${limitMB}).`)
      setStage('error')
      return
    }

    const reader = new FileReader()
    reader.onload = async () => {
      const dataUrl = String(reader.result || '')
      // Solo guardamos preview visual para imagenes (PDFs no se renderean inline)
      setPreviewUrl(isImage ? dataUrl : null)
      const base64 = dataUrl.split(',')[1]
      const mediaType = isPdf ? 'application/pdf'
        : file.type === 'image/png' ? 'image/png'
        : file.type === 'image/webp' ? 'image/webp'
        : 'image/jpeg'

      setStage('uploading')
      const res = await api.post('/api/repuve/screenshot', {
        plate: plate || null,
        vin: vin || null,
        image_base64: base64,
        media_type: mediaType,
        source: 'mobile/0.1',
      })

      if (!res.ok) {
        setError(res.error || 'No pudimos procesar la captura')
        setStage('error')
        return
      }

      const data = res.data
      // Parser exitoso → entregamos al padre, que actualiza el reporte.
      if (data.queried) {
        setStage('success')
        if (data.ocr_confidence === 'low' && data.ocr_notes) {
          setWarning(`Lectura con baja confianza: ${data.ocr_notes}`)
        }
        onResult?.(data)
        return
      }

      // Casos de error claros que el user puede corregir.
      if (data.raw_status === 'screenshot_no_modal') {
        setError(
          'No vimos un modal REPUVE en la captura. Toma la foto cuando '
          + 'el resultado ya este en pantalla, despues de hacer "Buscar".',
        )
      } else if (data.raw_status === 'screenshot_not_repuve') {
        setError(
          'La captura no parece ser de repuve.gob.mx. Verifica que '
          + 'estes en el portal oficial.',
        )
      } else if (data.raw_status === 'no_encontrado') {
        // Esto es un resultado VALIDO del parser (REPUVE dice no encontrado).
        setStage('success')
        onResult?.(data)
        return
      } else {
        setError(data.error || 'No pudimos leer el resultado de REPUVE.')
      }
      setStage('error')
    }
    reader.onerror = () => {
      setError('No pudimos leer el archivo.')
      setStage('error')
    }
    reader.readAsDataURL(file)
  }

  return (
    <div className="repuve-uploader" role="region" aria-label="Subir captura REPUVE">
      <div className="repuve-uploader-header">
        <strong>
          {isMobile
            ? 'Paso 4 — Sube el PDF de REPUVE'
            : 'Paso 4 — Sube el PDF o captura del resultado'}
        </strong>
        {onCancel && (
          <button
            type="button"
            className="icon-btn"
            onClick={onCancel}
            aria-label="Cancelar"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* Instrucciones específicas por device — Android/iOS bloquean
          screenshots de REPUVE (FLAG_SECURE / equivalente), así que
          mobile DEBE usar "Exportar a PDF". Desktop puede cualquiera. */}
      {isMobile ? (
        <p className="repuve-uploader-desc">
          <FileText size={14} strokeWidth={2.4} aria-hidden="true" />{' '}
          En REPUVE móvil: pulsa el botón <strong>"Exportar a PDF"</strong> al
          final del modal de resultado (las capturas no funcionan en móvil,
          REPUVE las bloquea por seguridad). Súbelo aquí.
        </p>
      ) : (
        <p className="repuve-uploader-desc">
          <Camera size={14} strokeWidth={2.4} aria-hidden="true" />{' '}
          En desktop: toma captura del resultado con{' '}
          <kbd>Win+Shift+S</kbd> (Windows) o{' '}
          <kbd>Cmd+Shift+4</kbd> (Mac). Súbela aquí. También aceptamos
          el PDF si prefieres <strong>"Exportar a PDF"</strong>.
        </p>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,application/pdf"
        onChange={handleFile}
        style={{ display: 'none' }}
      />

      {stage === 'idle' && (
        <button
          type="button"
          className="primary big repuve-uploader-cta"
          onClick={pickFile}
        >
          {isMobile ? (
            <>
              <FileText size={20} strokeWidth={2.4} />
              Subir PDF de REPUVE
            </>
          ) : (
            <>
              <Camera size={20} strokeWidth={2.4} />
              Subir PDF o captura de REPUVE
            </>
          )}
        </button>
      )}

      {stage === 'uploading' && (
        <div className="repuve-uploader-status">
          {previewUrl && (
            <img
              src={previewUrl}
              alt="Captura subida"
              className="repuve-uploader-preview"
            />
          )}
          <Spinner message="Leyendo el resultado…" />
        </div>
      )}

      {stage === 'success' && (
        <div className="repuve-uploader-status repuve-uploader-success">
          <CheckCircle2 size={32} strokeWidth={2.4} />
          <strong>Captura procesada</strong>
          <p>El resultado oficial ya esta en tu reporte.</p>
          {warning && (
            <small className="repuve-uploader-warning">{warning}</small>
          )}
        </div>
      )}

      {stage === 'error' && (
        <div className="repuve-uploader-status repuve-uploader-error">
          <AlertCircle size={28} strokeWidth={2.4} />
          <p>{error}</p>
          <button
            type="button"
            className="secondary"
            onClick={reset}
          >
            <RefreshCcw size={16} />
            Intentar de nuevo
          </button>
        </div>
      )}
    </div>
  )
}
