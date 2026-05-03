import { useRef, useState } from 'react'
import {
  Camera, CheckCircle2, AlertCircle, RefreshCcw, X,
} from 'lucide-react'
import { api } from '../lib/api.js'
import Spinner from './Spinner.jsx'

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

    if (!file.type.startsWith('image/')) {
      setError('Selecciona una imagen (JPG, PNG o WebP).')
      setStage('error')
      return
    }
    // Limite ~3MB original (a ~4MB en base64). Mobile JPEG suele ser <2MB.
    if (file.size > 3 * 1024 * 1024) {
      setError('La imagen es muy grande. Usa una captura del celular (no foto HD).')
      setStage('error')
      return
    }

    const reader = new FileReader()
    reader.onload = async () => {
      const dataUrl = String(reader.result || '')
      setPreviewUrl(dataUrl)
      const base64 = dataUrl.split(',')[1]
      const mediaType = file.type === 'image/png' ? 'image/png'
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
        <strong>Ya tienes el resultado? Sube la captura</strong>
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

      <p className="repuve-uploader-desc">
        Despues de ver el resultado en repuve.gob.mx, toma una captura
        de pantalla con tu celular y subela aqui. Lo leemos y completamos
        tu reporte automaticamente.
      </p>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handleFile}
        style={{ display: 'none' }}
      />

      {stage === 'idle' && (
        <button
          type="button"
          className="primary big repuve-uploader-cta"
          onClick={pickFile}
        >
          <Camera size={20} strokeWidth={2.4} />
          Subir captura del modal REPUVE
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
