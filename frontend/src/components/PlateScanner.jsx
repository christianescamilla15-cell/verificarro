import { useEffect, useRef, useState } from 'react'
import {
  X, Camera, Image as ImageIcon, Keyboard, ArrowLeft, ScanLine,
  RefreshCcw, Send, AlertTriangle,
} from 'lucide-react'
import { api } from '../lib/api.js'
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
export default function PlateScanner({ onResult, onClose }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const fileInputRef = useRef(null)
  const streamRef = useRef(null)
  const [stage, setStage] = useState('mode')
  // mode | camera | preview | scanning | manual | error
  const [error, setError] = useState(null)
  const [cameraError, setCameraError] = useState(null)
  const [manualPlate, setManualPlate] = useState('')
  const [manualVin, setManualVin] = useState('')
  const [manualKind, setManualKind] = useState('plate')

  function stopStream() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }

  useEffect(() => {
    return () => stopStream()
  }, [])

  async function openCamera() {
    setStage('camera')
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: 1280, height: 720 },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
    } catch (err) {
      setCameraError(err.message || 'No pudimos acceder a la cámara')
      setStage('mode')
    }
  }

  function capture() {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d').drawImage(video, 0, 0)
    stopStream()
    setStage('preview')
  }

  function retake() {
    setStage('mode')
    setError(null)
  }

  async function submitImage() {
    const canvas = canvasRef.current
    if (!canvas) return
    setStage('scanning')
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    const base64 = dataUrl.split(',')[1]
    const res = await api.post('/api/scan/plate', {
      image_base64: base64,
      media_type: 'image/jpeg',
    })
    if (!res.ok) {
      setError(res.error || 'No pudimos leer la placa')
      setStage('error')
      return
    }
    onResult(res.data)
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
    <div className="vin-scanner-overlay" role="dialog" aria-modal="true">
      <div className="vin-scanner">
        <div className="vin-scanner-header">
          <h2><ScanLine size={20} style={{ verticalAlign: '-3px', marginRight: 6, color: 'var(--accent-text)' }} />Escanear placa</h2>
          <button onClick={onClose} className="close-btn" aria-label="Cerrar">
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
              Encuadra los caracteres de la placa dentro del marco. Acerca
              el teléfono para que ocupe la mayor parte del cuadro.
            </p>
            <div className="camera-preview">
              <video ref={videoRef} autoPlay playsInline muted className="camera-video" />
              <div className="vin-guide" />
            </div>
            <div className="actions">
              <button onClick={() => { stopStream(); setStage('mode') }} className="secondary">
                <ArrowLeft size={18} /> Volver
              </button>
              <button onClick={capture} className="primary">
                <Camera size={18} /> Capturar
              </button>
            </div>
          </>
        )}

        {stage === 'preview' && (
          <>
            <p>Revisa que la placa se vea clara y completa.</p>
            <div className="actions">
              <button onClick={retake} className="secondary">
                <RefreshCcw size={18} /> Re-tomar
              </button>
              <button onClick={submitImage} className="primary">
                <Send size={18} /> Enviar
              </button>
            </div>
          </>
        )}

        {stage === 'scanning' && (
          <Spinner message="Leyendo placa con IA y consultando REPUVE… (~5-15 segundos)" />
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
