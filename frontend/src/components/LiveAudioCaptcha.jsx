import { useEffect, useRef, useState } from 'react'
import {
  Headphones, AlertCircle, CheckCircle2, X, Play, Send,
} from 'lucide-react'
import Spinner from './Spinner.jsx'

/**
 * Live audio captcha — innovación 2026-05-10 (idea 2 pioneer).
 *
 * En vez de pedirle al usuario que abra REPUVE manualmente, Verificarro:
 *   1. Drive REPUVE backend con Camoufox
 *   2. Si Google muestra audio challenge → descarga el .mp3
 *   3. Lo pipea a este componente vía WebSocket
 *   4. Usuario escucha 3-7 segundos y tipea los dígitos
 *   5. Backend submite al captcha + REPUVE → resultado
 *
 * UX intencional: feel de "banking 2FA". El usuario hace 1 acción de 3
 * segundos (escuchar + tipear), no abre REPUVE, no toma screenshot.
 *
 * IMPORTANTE: este flow solo se dispara cuando REPUVE ofrece audio
 * challenge UI. Empíricamente, REPUVE auto-rechaza muchas veces sin
 * ofrecer challenge. En ese caso, el WebSocket devuelve
 * `raw_status=captcha_required` y el usuario cae al upload manual.
 */
export default function LiveAudioCaptcha({ plate, vin, onResult, onCancel }) {
  const wsRef = useRef(null)
  const audioRef = useRef(null)
  const [stage, setStage] = useState('connecting')
  // connecting | navigating | awaiting_audio | listening | answering | submitting | done | error
  const [statusMsg, setStatusMsg] = useState('Conectando con Verificarro...')
  const [audioUrl, setAudioUrl] = useState(null)
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    // Construye WS URL desde la BASE de la API (verificarro-api.onrender.com
    // en prod, vacío en dev). El env var correcto es VITE_API_BASE (matchea
    // api.js). Si está vacío (dev), usa origin del browser (vite dev proxy
    // tiene que estar configurado para WS — ver vite.config.js).
    const apiBase = import.meta.env.VITE_API_BASE || window.location.origin
    const wsUrl = apiBase
      .replace(/^http:/, 'ws:')
      .replace(/^https:/, 'wss:')
      + '/api/repuve/live'

    // eslint-disable-next-line no-console
    console.log('[LiveAudioCaptcha] connecting WS to', wsUrl)

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setStage('navigating')
      setStatusMsg('Iniciando consulta REPUVE...')
      ws.send(JSON.stringify({ type: 'start', plate, vin }))
    }

    ws.onmessage = (evt) => {
      let msg
      try {
        msg = JSON.parse(evt.data)
      } catch {
        return
      }

      if (msg.type === 'status') {
        setStatusMsg(msg.msg || 'Procesando...')
        if (/captcha/i.test(msg.msg)) {
          setStage('awaiting_audio')
        }
      } else if (msg.type === 'audio') {
        // Decodifica base64 → Blob → URL para el <audio>
        const bytes = Uint8Array.from(atob(msg.b64), (c) => c.charCodeAt(0))
        const blob = new Blob([bytes], { type: 'audio/mpeg' })
        const url = URL.createObjectURL(blob)
        setAudioUrl(url)
        setStage('listening')
        setStatusMsg('Escucha el audio y escribe los dígitos')
        // Focus auto en input para que el user solo escuche + tipee
        setTimeout(() => inputRef.current?.focus(), 200)
      } else if (msg.type === 'result') {
        setStage('done')
        setStatusMsg('Verificado')
        onResult?.(msg.data)
      } else if (msg.type === 'error') {
        setStage('error')
        setError(msg.msg || 'Error inesperado')
      }
    }

    ws.onerror = () => {
      setStage('error')
      setError('Error de conexión con el servidor')
    }

    ws.onclose = (evt) => {
      if (stage !== 'done' && stage !== 'error') {
        setStage('error')
        setError('Conexión cerrada inesperadamente')
      }
    }

    return () => {
      // Cleanup
      try { ws.close() } catch {}
      if (audioUrl) URL.revokeObjectURL(audioUrl)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plate, vin])

  function handleSubmit(e) {
    e.preventDefault()
    if (!answer.trim()) return
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'answer', text: answer.trim() }))
    setStage('submitting')
    setStatusMsg('Validando con REPUVE...')
  }

  function handleCancel() {
    try {
      wsRef.current?.send(JSON.stringify({ type: 'cancel' }))
      wsRef.current?.close()
    } catch {}
    onCancel?.()
  }

  return (
    <div className="live-audio-captcha" role="region" aria-label="Verificación captcha audio">
      <div className="live-audio-header">
        <Headphones size={20} strokeWidth={2.4} />
        <strong>Verificación REPUVE en vivo</strong>
        <button
          type="button"
          className="icon-btn"
          onClick={handleCancel}
          aria-label="Cancelar"
        >
          <X size={16} />
        </button>
      </div>

      {(stage === 'connecting' || stage === 'navigating' || stage === 'awaiting_audio') && (
        <div className="live-audio-status">
          <Spinner message={statusMsg} />
        </div>
      )}

      {stage === 'listening' && audioUrl && (
        <div className="live-audio-listen">
          <p className="muted">
            {statusMsg} — son 3-7 segundos
          </p>
          <audio
            ref={audioRef}
            controls
            autoPlay
            src={audioUrl}
            className="live-audio-player"
          >
            Tu navegador no soporta audio HTML5.
          </audio>
          <form onSubmit={handleSubmit} className="live-audio-form">
            <input
              ref={inputRef}
              type="text"
              inputMode="text"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck="false"
              placeholder="Escribe los dígitos que escuchaste"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              className="live-audio-input"
              aria-label="Respuesta del captcha"
            />
            <button
              type="submit"
              className="primary"
              disabled={!answer.trim()}
            >
              <Send size={16} strokeWidth={2.4} />
              Enviar
            </button>
          </form>
          <button
            type="button"
            className="secondary small"
            onClick={() => audioRef.current?.play()}
          >
            <Play size={14} strokeWidth={2.4} />
            Reproducir de nuevo
          </button>
        </div>
      )}

      {stage === 'submitting' && (
        <div className="live-audio-status">
          <Spinner message={statusMsg} />
        </div>
      )}

      {stage === 'done' && (
        <div className="live-audio-success">
          <CheckCircle2 size={32} strokeWidth={2.4} />
          <strong>Verificación completada</strong>
          <p>El resultado oficial ya está en tu reporte.</p>
        </div>
      )}

      {stage === 'error' && (
        <div className="live-audio-error">
          <AlertCircle size={28} strokeWidth={2.4} />
          <p>{error}</p>
          <p className="muted">
            Esto suele pasar cuando REPUVE no ofrece captcha visible.
            Usa el método de subir captura/PDF abajo.
          </p>
          <button
            type="button"
            className="secondary"
            onClick={handleCancel}
          >
            OK
          </button>
        </div>
      )}
    </div>
  )
}
