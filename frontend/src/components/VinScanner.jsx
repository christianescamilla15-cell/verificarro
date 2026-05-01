import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import Spinner from './Spinner.jsx'

/**
 * Modal con cámara para escanear el VIN del auto físico.
 *
 * Flow:
 * 1. getUserMedia({video: {facingMode: 'environment'}}) → cámara trasera
 * 2. Usuario encuadra el VIN con guías visuales
 * 3. "Capturar" → snapshot a canvas
 * 4. "Enviar" → base64 → POST /api/vin/scan (Claude visión OCR)
 * 5. Si vin extraído + confidence aceptable → POST /api/vin/check
 * 6. onResult({decoded, matches_listing, alerts}) callback
 *
 * Soporta retry: re-tomar foto si OCR no tuvo confidence high.
 */
export default function VinScanner({ listing, repuve, onResult, onClose }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const [stage, setStage] = useState('camera')  // camera | preview | scanning | result | error
  const [error, setError] = useState(null)
  const [scanResult, setScanResult] = useState(null)  // de /vin/scan
  const [checkResult, setCheckResult] = useState(null)  // de /vin/check
  const [manualVin, setManualVin] = useState('')

  // Iniciar cámara al montar
  useEffect(() => {
    let mounted = true
    async function init() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: 1280, height: 720 },
          audio: false,
        })
        if (!mounted) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
        }
      } catch (err) {
        setError(`No pude acceder a la cámara: ${err.message}. Puedes ingresar el VIN manualmente.`)
        setStage('error')
      }
    }
    init()
    return () => {
      mounted = false
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop())
      }
    }
  }, [])

  function capture() {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    ctx.drawImage(video, 0, 0)
    setStage('preview')
  }

  function retake() {
    setStage('camera')
    setScanResult(null)
    setCheckResult(null)
  }

  async function submitScan() {
    const canvas = canvasRef.current
    if (!canvas) return
    setStage('scanning')
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    const base64 = dataUrl.split(',')[1]
    const res = await api.post('/api/vin/scan', {
      image_base64: base64,
      media_type: 'image/jpeg',
    })
    if (!res.ok) {
      setError(`OCR falló: ${res.error}`)
      setStage('error')
      return
    }
    setScanResult(res.data)
    if (!res.data.vin || res.data.vin.length !== 17) {
      // VIN incompleto — usuario decide re-tomar o entrar manual
      setStage('result')
      return
    }
    await runCheck(res.data.vin)
  }

  async function runCheck(vin) {
    const res = await api.post('/api/vin/check', {
      vin,
      listing,
      repuve: repuve || null,
    })
    if (!res.ok) {
      setError(`Verificación falló: ${res.error}`)
      setStage('error')
      return
    }
    setCheckResult(res.data)
    setStage('result')
    if (onResult) onResult(res.data)
  }

  async function submitManual(e) {
    e.preventDefault()
    const cleaned = manualVin.toUpperCase().replace(/[^A-Z0-9]/g, '')
    if (cleaned.length !== 17) {
      setError('VIN debe tener 17 caracteres exactos')
      return
    }
    setError(null)
    await runCheck(cleaned)
  }

  return (
    <div className="vin-scanner-overlay" role="dialog" aria-modal="true">
      <div className="vin-scanner">
        <div className="vin-scanner-header">
          <h2>Escanear VIN del auto</h2>
          <button onClick={onClose} className="close-btn" aria-label="Cerrar">×</button>
        </div>

        {stage === 'camera' && (
          <>
            <p className="muted">
              Encuadra los 17 caracteres del VIN. Está en el tablero del piloto
              (visible por el parabrisas) o en el marco de la puerta del chofer.
            </p>
            <div className="camera-preview">
              <video ref={videoRef} autoPlay playsInline muted className="camera-video" />
              <div className="vin-guide" />
            </div>
            <div className="actions">
              <button onClick={capture} className="primary">📸 Capturar</button>
            </div>
            <details className="manual-vin">
              <summary>O ingresa el VIN manualmente</summary>
              <form onSubmit={submitManual} className="manual-form">
                <input
                  type="text" maxLength={20}
                  value={manualVin}
                  onChange={(e) => setManualVin(e.target.value.toUpperCase())}
                  placeholder="17 caracteres alfanuméricos"
                />
                <button type="submit" className="secondary">Verificar</button>
              </form>
              {error && <p className="error">{error}</p>}
            </details>
          </>
        )}

        {stage === 'preview' && (
          <>
            <p>Revisa que el VIN se vea claro y completo en la foto.</p>
            <div className="actions">
              <button onClick={retake} className="secondary">Re-tomar</button>
              <button onClick={submitScan} className="primary">Enviar para análisis</button>
            </div>
          </>
        )}

        {stage === 'scanning' && (
          <Spinner message="Analizando VIN con IA… (~5 segundos)" />
        )}

        {stage === 'result' && (
          <ScanResultView
            scan={scanResult}
            check={checkResult}
            onRetake={retake}
            onClose={onClose}
          />
        )}

        {stage === 'error' && (
          <div className="error-box">
            <p>⚠️ {error}</p>
            <details className="manual-vin">
              <summary>Ingresa el VIN manualmente</summary>
              <form onSubmit={submitManual} className="manual-form">
                <input
                  type="text" maxLength={20}
                  value={manualVin}
                  onChange={(e) => setManualVin(e.target.value.toUpperCase())}
                  placeholder="17 caracteres alfanuméricos"
                />
                <button type="submit" className="primary">Verificar</button>
              </form>
            </details>
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


function ScanResultView({ scan, check, onRetake, onClose }) {
  const ok = check && check.matches_listing && check.alerts.every((a) => a.severity !== 'high')
  const hasHigh = check && check.alerts.some((a) => a.severity === 'high')
  const status = hasHigh ? 'red' : ok ? 'green' : 'yellow'

  return (
    <div className={`scan-result scan-${status}`}>
      <div className="scan-banner">
        {status === 'green' && <h3>✅ VIN coincide con el anuncio</h3>}
        {status === 'yellow' && <h3>⚠️ Hay puntos a revisar</h3>}
        {status === 'red' && <h3>🚨 ALERTA: NO COINCIDE — no compres</h3>}
      </div>

      {scan && (
        <div className="scan-info">
          <p><strong>VIN extraído:</strong> {scan.vin || '(no legible)'}</p>
          <p><strong>Confianza del OCR:</strong> {scan.confidence}</p>
          {scan.notes && <p className="muted">{scan.notes}</p>}
        </div>
      )}

      {check && (
        <div className="check-info">
          {check.decoded && (
            <p>
              <strong>Decodificación VIN:</strong>{' '}
              {check.decoded.manufacturer || 'desconocido'}
              {check.decoded.year ? ` ${check.decoded.year}` : ''}
              {check.decoded.country ? ` (${check.decoded.country})` : ''}
            </p>
          )}
          {check.alerts.length > 0 && (
            <ul className="check-alerts">
              {check.alerts.map((a, i) => (
                <li key={i} className={`alert alert-${a.severity}`}>
                  <strong>[{a.severity.toUpperCase()}]</strong> {a.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="actions">
        <button onClick={onRetake} className="secondary">Re-escanear</button>
        <button onClick={onClose} className="primary">Cerrar</button>
      </div>
    </div>
  )
}
