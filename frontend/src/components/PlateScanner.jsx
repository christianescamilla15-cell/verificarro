import { useEffect, useRef, useState } from 'react'
import {
  X, Camera, Image as ImageIcon, Keyboard, ScanLine,
  AlertTriangle, ArrowLeft, RefreshCcw, Send, FileText, CheckCircle2,
} from 'lucide-react'
import { api } from '../lib/api.js'
import { useModalA11y } from '../hooks/useModalA11y.js'
import Spinner from './Spinner.jsx'

/**
 * Modal con tres modalidades para capturar la placa o VIN:
 *
 * 1. Cámara → snapshot → OCR con Claude visión
 * 2. Subir foto desde galería → mismo OCR
 * 3. Tipear placa o VIN manualmente (fallback sin cámara)
 *
 * Tras éxito, llama `onResult({report_id, plate, score, risk_level, summary})`.
 * El padre redirige a `/preview/{report_id}`.
 */
const AUTO_CAPTURE_INITIAL_DELAY_MS = 2000  // espera estabilización antes del 1er shot
const AUTO_CAPTURE_RETRY_DELAY_MS = 2500    // entre reintentos
const AUTO_CAPTURE_MAX_ATTEMPTS = 3         // ~3 × $0.006 = $0.018 USD máximo por sesión

export default function PlateScanner({ onResult, onClose }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const fileInputRef = useRef(null)
  const streamRef = useRef(null)
  const autoCaptureCancelRef = useRef(false)
  const modalRef = useRef(null)
  // MOD-028: ESC + focus trap + restore focus.
  useModalA11y(modalRef, onClose)
  const [stage, setStage] = useState('mode')
  // mode | camera | scanning | invoice_detected | manual | error
  const [error, setError] = useState(null)
  const [cameraError, setCameraError] = useState(null)
  const [manualPlate, setManualPlate] = useState('')
  const [manualVin, setManualVin] = useState('')
  const [manualKind, setManualKind] = useState('plate')
  const [captureCountdown, setCaptureCountdown] = useState(0)
  const [captureAttempt, setCaptureAttempt] = useState(0)
  // Smart scanner: cuando detecta factura, almacenamos los datos
  // extraídos y mostramos un panel especial pidiendo placa/VIN.
  const [invoiceData, setInvoiceData] = useState(null)

  function stopStream() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }

  useEffect(() => {
    return () => {
      autoCaptureCancelRef.current = true
      stopStream()
    }
  }, [])

  async function openCamera() {
    setStage('camera')
    setError(null)
    autoCaptureCancelRef.current = false
    setCaptureAttempt(0)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: 1280, height: 720 },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
      // Arrancar el loop de auto-captura
      runAutoCaptureLoop()
    } catch (err) {
      setCameraError(err.message || 'No pudimos acceder a la cámara')
      setStage('mode')
    }
  }

  /**
   * Loop de captura automática:
   *   1. Espera estabilización (2s) — da tiempo al usuario a posicionar
   *   2. Captura frame → envía a OCR
   *   3. Si OK → onResult
   *   4. Si falla → espera 2.5s, reintenta hasta MAX_ATTEMPTS
   *   5. Tras MAX_ATTEMPTS sin éxito → muestra mensaje + opción manual
   */
  async function runAutoCaptureLoop() {
    for (let attempt = 1; attempt <= AUTO_CAPTURE_MAX_ATTEMPTS; attempt++) {
      if (autoCaptureCancelRef.current) return
      const delay = attempt === 1 ? AUTO_CAPTURE_INITIAL_DELAY_MS : AUTO_CAPTURE_RETRY_DELAY_MS

      // Countdown visual
      const countdownStart = Math.ceil(delay / 1000)
      for (let s = countdownStart; s > 0; s--) {
        if (autoCaptureCancelRef.current) return
        setCaptureCountdown(s)
        await sleep(1000)
      }
      setCaptureCountdown(0)

      if (autoCaptureCancelRef.current) return
      setCaptureAttempt(attempt)

      const success = await tryAutoCapture()
      if (success) return  // onResult ya se invocó adentro
    }

    // Tras 3 intentos fallidos
    if (!autoCaptureCancelRef.current) {
      setError(
        'No pudimos leer la placa con la cámara después de 3 intentos. ' +
        'Prueba con mejor luz o ingresa la placa manualmente.'
      )
      setStage('error')
      stopStream()
    }
  }

  async function tryAutoCapture() {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return false

    canvas.width = video.videoWidth || 1280
    canvas.height = video.videoHeight || 720
    canvas.getContext('2d').drawImage(video, 0, 0)
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    const base64 = dataUrl.split(',')[1]

    const res = await api.post('/api/scan/plate', {
      image_base64: base64,
      media_type: 'image/jpeg',
    })

    if (autoCaptureCancelRef.current) return false

    if (res.ok) {
      // Smart scanner detectó factura — flujo especial: mostrar datos
      // extraídos y pedir al usuario escanear placa/VIN para completar.
      if (res.data.detected_type === 'invoice' && !res.data.report_id) {
        autoCaptureCancelRef.current = true
        stopStream()
        setInvoiceData(res.data.invoice_extra || {})
        setStage('invoice_detected')
        return true
      }
      // Plate o VIN normal → preview
      stopStream()
      autoCaptureCancelRef.current = true
      onResult(res.data)
      return true
    }
    // Falló — el loop reintentará si quedan attempts
    return false
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  function handleOverlayClick() {
    autoCaptureCancelRef.current = true
    stopStream()
    onClose()
  }

  async function handleFileUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    const reader = new FileReader()
    reader.onload = async () => {
      const dataUrl = reader.result
      const base64 = String(dataUrl).split(',')[1]
      const mediaType = file.type === 'image/png' ? 'image/png'
        : file.type === 'image/webp' ? 'image/webp' : 'image/jpeg'
      setStage('scanning')
      const res = await api.post('/api/scan/plate', {
        image_base64: base64,
        media_type: mediaType,
      })
      if (!res.ok) {
        setError(res.error || 'No pudimos leer la placa')
        setStage('error')
        return
      }
      // Smart scanner detectó factura
      if (res.data.detected_type === 'invoice' && !res.data.report_id) {
        setInvoiceData(res.data.invoice_extra || {})
        setStage('invoice_detected')
        return
      }
      onResult(res.data)
    }
    reader.readAsDataURL(file)
  }

  async function submitManual(e) {
    e.preventDefault()
    setError(null)
    if (manualKind === 'plate') {
      const cleaned = manualPlate.toUpperCase().replace(/[^A-Z0-9]/g, '')
      if (cleaned.length < 5 || cleaned.length > 7) {
        setError('La placa debe tener entre 5 y 7 caracteres alfanuméricos.')
        return
      }
      setStage('scanning')
      const res = await api.post('/api/scan/plate', { manual_plate: cleaned })
      if (!res.ok) {
        setError(res.error || 'No pudimos consultar la placa')
        setStage('manual')
        return
      }
      onResult(res.data)
    } else {
      const cleaned = manualVin.toUpperCase().replace(/[^A-Z0-9]/g, '')
      if (cleaned.length !== 17) {
        setError('El VIN debe tener exactamente 17 caracteres alfanuméricos.')
        return
      }
      setStage('scanning')
      const res = await api.post('/api/scan/plate', { manual_vin: cleaned })
      if (!res.ok) {
        setError(res.error || 'No pudimos consultar el VIN')
        setStage('manual')
        return
      }
      onResult(res.data)
    }
  }

  return (
    <div
      className="vin-scanner-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="plate-scanner-title"
      onClick={handleOverlayClick}
    >
      <div className="vin-scanner" ref={modalRef} onClick={(e) => e.stopPropagation()}>
        <div className="vin-scanner-header">
          <h2 id="plate-scanner-title"><ScanLine size={20} style={{ verticalAlign: '-3px', marginRight: 6, color: 'var(--accent-text)' }} />Escanear placa</h2>
          <button onClick={handleOverlayClick} className="close-btn" aria-label="Cerrar">
            <X size={22} />
          </button>
        </div>

        {stage === 'mode' && (
          <div className="scan-modes">
            <p className="muted">
              Tres formas de capturar — elige la más cómoda.
            </p>
            <button onClick={openCamera} className="primary big">
              <Camera size={20} strokeWidth={2.2} />
              Abrir cámara
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="secondary big"
            >
              <ImageIcon size={20} strokeWidth={2.2} />
              Subir foto desde galería
            </button>
            <button onClick={() => setStage('manual')} className="secondary big">
              <Keyboard size={20} strokeWidth={2.2} />
              Ingresar placa manualmente
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              onChange={handleFileUpload}
              style={{ display: 'none' }}
            />
            {cameraError && (
              <p className="muted small">
                Cámara no disponible: {cameraError}. Usa galería o ingreso manual.
              </p>
            )}
          </div>
        )}

        {stage === 'camera' && (
          <>
            <p className="muted">
              Encuadra los caracteres de la placa dentro del marco.
              Captura automática cuando esté lista.
              {captureAttempt > 0 && ` · Intento ${captureAttempt}/${AUTO_CAPTURE_MAX_ATTEMPTS}`}
            </p>
            <div className="camera-preview">
              <video ref={videoRef} autoPlay playsInline muted className="camera-video" />
              <div className="vin-guide" />
              {captureCountdown > 0 && (
                <div className="capture-countdown">
                  <span className="countdown-num">{captureCountdown}</span>
                  <span className="countdown-label">capturando…</span>
                </div>
              )}
              {captureAttempt > 0 && captureCountdown === 0 && (
                <div className="capture-countdown">
                  <span className="countdown-label">leyendo…</span>
                </div>
              )}
            </div>
            <p className="muted small" style={{ textAlign: 'center', marginTop: 8 }}>
              Click fuera de este recuadro para cerrar
            </p>
          </>
        )}

        {stage === 'scanning' && (
          <Spinner message="Leyendo con IA y consultando REPUVE… (~5-15 segundos)" />
        )}

        {stage === 'invoice_detected' && (
          <div className="invoice-detected">
            <div className="invoice-detected-banner">
              <CheckCircle2 size={22} />
              <strong>Detectamos una factura del auto</strong>
            </div>
            <p className="muted">
              Extrajimos estos datos del CFDI. Para completar el reporte
              necesito que también escanees la placa o el NIV del auto.
            </p>
            <div className="invoice-detected-fields">
              {invoiceData?.folio_fiscal_uuid && (
                <div className="invoice-field">
                  <span className="invoice-field-label">UUID CFDI</span>
                  <code className="invoice-field-value">{invoiceData.folio_fiscal_uuid}</code>
                </div>
              )}
              {invoiceData?.rfc_emisor && (
                <div className="invoice-field">
                  <span className="invoice-field-label">RFC Emisor</span>
                  <code className="invoice-field-value">{invoiceData.rfc_emisor}</code>
                </div>
              )}
              {invoiceData?.rfc_receptor && (
                <div className="invoice-field">
                  <span className="invoice-field-label">RFC Receptor</span>
                  <code className="invoice-field-value">{invoiceData.rfc_receptor}</code>
                </div>
              )}
              {(invoiceData?.marca || invoiceData?.modelo || invoiceData?.año) && (
                <div className="invoice-field">
                  <span className="invoice-field-label">Auto en factura</span>
                  <span className="invoice-field-value">
                    {[invoiceData?.marca, invoiceData?.modelo, invoiceData?.año].filter(Boolean).join(' ')}
                  </span>
                </div>
              )}
              {invoiceData?.total && (
                <div className="invoice-field">
                  <span className="invoice-field-label">Total factura</span>
                  <span className="invoice-field-value">${Number(invoiceData.total).toLocaleString('es-MX')} MXN</span>
                </div>
              )}
            </div>
            <p className="muted small">
              Estos datos se cross-validarán contra el listing y SAT cuando
              desbloquees el reporte completo.
            </p>
            <div className="actions">
              <button onClick={() => setStage('mode')} className="primary">
                <Camera size={18} /> Ahora escanea la placa o VIN
              </button>
            </div>
          </div>
        )}

        {stage === 'manual' && (
          <form onSubmit={submitManual} className="manual-form">
            <div className="manual-kind-toggle">
              <label className={manualKind === 'plate' ? 'active' : ''}>
                <input
                  type="radio" name="kind" value="plate"
                  checked={manualKind === 'plate'}
                  onChange={() => setManualKind('plate')}
                />
                Placa
              </label>
              <label className={manualKind === 'vin' ? 'active' : ''}>
                <input
                  type="radio" name="kind" value="vin"
                  checked={manualKind === 'vin'}
                  onChange={() => setManualKind('vin')}
                />
                NIV (VIN)
              </label>
            </div>
            {manualKind === 'plate' ? (
              <label>
                Placa (5-7 caracteres alfanuméricos)
                <input
                  type="text" maxLength={10}
                  value={manualPlate}
                  onChange={(e) => setManualPlate(e.target.value.toUpperCase())}
                  placeholder="ABC123D"
                  autoFocus
                />
              </label>
            ) : (
              <label>
                NIV / VIN (17 caracteres alfanuméricos)
                <input
                  type="text" maxLength={20}
                  value={manualVin}
                  onChange={(e) => setManualVin(e.target.value.toUpperCase())}
                  placeholder="3VWFE21C04M000001"
                  autoFocus
                />
              </label>
            )}
            <div className="actions">
              <button type="button" onClick={() => setStage('mode')} className="secondary">
                <ArrowLeft size={18} /> Volver
              </button>
              <button type="submit" className="primary">
                <Send size={18} /> Verificar
              </button>
            </div>
            {error && (
              <p className="error">
                <AlertTriangle size={16} /> {error}
              </p>
            )}
          </form>
        )}

        {stage === 'error' && (
          <div className="error-box">
            <p className="error">
              <AlertTriangle size={18} /> {error}
            </p>
            <div className="actions">
              <button onClick={() => setStage('mode')} className="secondary">
                <RefreshCcw size={18} /> Re-intentar
              </button>
              <button onClick={() => setStage('manual')} className="primary">
                <Keyboard size={18} /> Ingresar manualmente
              </button>
            </div>
          </div>
        )}

        {/* Canvas único siempre montado: visible en preview, oculto en otros stages.
            React no debe desmontarlo al cambiar stage o se pierde el dibujo del frame. */}
        <canvas
          ref={canvasRef}
          className={stage === 'preview' ? 'capture-canvas' : ''}
          style={stage === 'preview' ? undefined : { display: 'none' }}
        />
      </div>
    </div>
  )
}
