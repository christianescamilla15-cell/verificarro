/**
 * Frame analyzer — heurísticas client-side puras para auto-captura.
 *
 * Reemplaza el countdown ciego del scanner por detección de "frame listo":
 * sharpness alta + brillo OK + estable + densidad de bordes en ROI central.
 * Cero llamadas a API, todo computa en JS sobre Uint8ClampedArray.
 *
 * API pura:
 *   - `measureSharpness(luma, w, h)` → Laplacian variance (>~100 nítida)
 *   - `measureBrightness(luma)` → mean (50-200 OK)
 *   - `measureEdgeDensity(luma, w, h)` → % píxeles con edge en ROI central
 *   - `measureStability(lumaPrev, lumaCurr)` → mean abs diff
 *   - `extractLuma(rgba, w, h)` → Uint8Array luma BT.601
 *   - `analyzeFrame(prevLuma, currLuma, w, h, opts)` → veredicto
 *
 * Toda función es pure + sync + sin DOM → testable en vitest sin browser.
 *
 * El consumer (PlateScanner) downscalea via OffscreenCanvas a ~320×240
 * antes de pasar el RGBA, por performance + battery.
 */

// Umbrales por defecto. Tuneados para placas vehiculares MX a ~1m de
// distancia, con buena luz natural. Si después de uso real vemos muchos
// falsos negativos, bajar SHARPNESS_MIN o EDGE_DENSITY_MIN.
export const DEFAULT_THRESHOLDS = Object.freeze({
  SHARPNESS_MIN: 80,         // Laplacian variance — <50 muy borroso
  BRIGHTNESS_MIN: 45,        // luma mean — <40 demasiado oscuro
  BRIGHTNESS_MAX: 215,       // luma mean — >220 quemado/contraluz
  EDGE_DENSITY_MIN: 0.04,    // 4% de píxeles del ROI con edge
  STABILITY_MAX_DIFF: 12,    // mean abs luma diff entre frames
  ROI_FRACTION: 0.6,         // ROI = 60% central del frame
})

/**
 * Convierte buffer RGBA (Canvas getImageData) a luma BT.601 Uint8Array.
 * Reduce memoria 4× + acelera Laplacian/Sobel posteriores.
 */
export function extractLuma(rgba, w, h) {
  const out = new Uint8Array(w * h)
  for (let i = 0, j = 0; i < rgba.length; i += 4, j++) {
    out[j] = (rgba[i] * 299 + rgba[i + 1] * 587 + rgba[i + 2] * 114) / 1000
  }
  return out
}

/**
 * Laplacian variance — métrica clásica de blur (Pech-Pacheco 2000).
 * Aplica kernel 3x3 [0,1,0;1,-4,1;0,1,0] sobre interior, calcula
 * varianza de la respuesta. Imágenes nítidas tienen varianza alta porque
 * los edges generan respuestas grandes; imágenes borrosas → varianza baja.
 */
export function measureSharpness(luma, w, h) {
  if (w < 3 || h < 3) return 0
  let sum = 0
  let sumSq = 0
  let count = 0
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x
      const lap = (
        luma[i - w] +    // arriba
        luma[i + w] +    // abajo
        luma[i - 1] +    // izquierda
        luma[i + 1] -    // derecha
        4 * luma[i]      // centro
      )
      sum += lap
      sumSq += lap * lap
      count++
    }
  }
  if (count === 0) return 0
  const mean = sum / count
  const variance = (sumSq / count) - (mean * mean)
  return variance
}

/**
 * Brillo medio (luma 0-255). Demasiado bajo = imagen oscura, demasiado
 * alto = imagen quemada/contraluz. Sweet spot 50-200.
 */
export function measureBrightness(luma) {
  if (luma.length === 0) return 0
  let sum = 0
  for (let i = 0; i < luma.length; i++) sum += luma[i]
  return sum / luma.length
}

/**
 * Densidad de bordes en la región central (ROI). Una placa enmarcada en
 * el centro genera muchos bordes verticales (caracteres) y horizontales
 * (marco). Cielo o pared lisa = casi 0. Texto denso = > 5%.
 *
 * Usamos gradiente Sobel simplificado (|dx| + |dy|) y contamos píxeles
 * que superan threshold 30 (bajo, agresivo — preferimos falsos positivos
 * en bordes a perder placas con poco contraste).
 */
export function measureEdgeDensity(luma, w, h, roiFraction = DEFAULT_THRESHOLDS.ROI_FRACTION) {
  if (w < 3 || h < 3) return 0
  const margin = (1 - roiFraction) / 2
  const x0 = Math.max(1, Math.floor(w * margin))
  const x1 = Math.min(w - 1, Math.ceil(w * (1 - margin)))
  const y0 = Math.max(1, Math.floor(h * margin))
  const y1 = Math.min(h - 1, Math.ceil(h * (1 - margin)))

  let edgePixels = 0
  let total = 0
  const EDGE_THRESHOLD = 30

  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const i = y * w + x
      const dx = Math.abs(luma[i + 1] - luma[i - 1])
      const dy = Math.abs(luma[i + w] - luma[i - w])
      if (dx + dy > EDGE_THRESHOLD) edgePixels++
      total++
    }
  }
  return total === 0 ? 0 : edgePixels / total
}

/**
 * Mean absolute difference entre dos frames consecutivos. Mide
 * estabilidad de la cámara/objeto. Valores < 10 = muy quieto, 10-20 =
 * movimiento ligero, > 20 = mano temblando o panning.
 */
export function measureStability(lumaPrev, lumaCurr) {
  if (!lumaPrev || lumaPrev.length !== lumaCurr.length) return Infinity
  let sumDiff = 0
  for (let i = 0; i < lumaCurr.length; i++) {
    sumDiff += Math.abs(lumaCurr[i] - lumaPrev[i])
  }
  return sumDiff / lumaCurr.length
}

/**
 * Veredicto final + hint para el UI.
 *
 * Devuelve `{ ready, hint, scores }`:
 *   - `ready`: true si TODAS las heurísticas pasan
 *   - `hint`: mensaje en español para mostrar al usuario sobre QUÉ falta
 *   - `scores`: valores raw por si el caller quiere mostrar debug
 *
 * El orden de hints es por prioridad UX: primero el problema más
 * accionable (luz, blur, posición), después estabilidad.
 */
export function analyzeFrame(prevLuma, currLuma, w, h, opts = {}) {
  const t = { ...DEFAULT_THRESHOLDS, ...opts }

  const brightness = measureBrightness(currLuma)
  const sharpness = measureSharpness(currLuma, w, h)
  const edgeDensity = measureEdgeDensity(currLuma, w, h, t.ROI_FRACTION)
  const stability = measureStability(prevLuma, currLuma)

  const scores = { brightness, sharpness, edgeDensity, stability }

  // Orden de prioridad para hints — el primero que falla gana.
  if (brightness < t.BRIGHTNESS_MIN) {
    return { ready: false, hint: 'Necesita más luz', scores }
  }
  if (brightness > t.BRIGHTNESS_MAX) {
    return { ready: false, hint: 'Demasiada luz directa — sombrea', scores }
  }
  if (edgeDensity < t.EDGE_DENSITY_MIN) {
    return { ready: false, hint: 'Acerca o centra el documento', scores }
  }
  if (sharpness < t.SHARPNESS_MIN) {
    return { ready: false, hint: 'Mantén firme — está borroso', scores }
  }
  if (stability > t.STABILITY_MAX_DIFF) {
    return { ready: false, hint: 'Mantén firme', scores }
  }

  return { ready: true, hint: 'Listo, capturando', scores }
}
