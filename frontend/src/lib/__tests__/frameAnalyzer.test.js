import { describe, it, expect } from 'vitest'
import {
  extractLuma,
  measureSharpness,
  measureBrightness,
  measureEdgeDensity,
  measureStability,
  analyzeFrame,
  DEFAULT_THRESHOLDS,
} from '../frameAnalyzer.js'

/**
 * Helpers para construir Uint8 buffers sintéticos de test.
 * NO usamos jsdom Canvas porque las funciones son pure → arrays directos.
 */

function makeUniformLuma(w, h, value) {
  const arr = new Uint8Array(w * h)
  arr.fill(value)
  return arr
}

function makeNoisyLuma(w, h, seed = 1) {
  // PRNG determinístico para tests reproducibles.
  let state = seed
  const arr = new Uint8Array(w * h)
  for (let i = 0; i < arr.length; i++) {
    state = (state * 1103515245 + 12345) & 0x7fffffff
    arr[i] = state % 256
  }
  return arr
}

function makeStripedLuma(w, h, period = 4) {
  // Líneas verticales blancas/negras alternadas — máxima edge density.
  const arr = new Uint8Array(w * h)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      arr[y * w + x] = Math.floor(x / period) % 2 === 0 ? 0 : 255
    }
  }
  return arr
}

// ---------------------------------------------------------------------------

describe('extractLuma', () => {
  it('convierte RGBA a luma BT.601', () => {
    const rgba = new Uint8ClampedArray([
      255, 0, 0, 255,    // rojo puro → ~76
      0, 255, 0, 255,    // verde puro → ~150
      0, 0, 255, 255,    // azul puro → ~29
      255, 255, 255, 255, // blanco → 255
    ])
    const luma = extractLuma(rgba, 4, 1)
    // Tolerancia ±2 por truncación entera del Uint8Array
    expect(luma[0]).toBeGreaterThanOrEqual(74)
    expect(luma[0]).toBeLessThanOrEqual(78)
    expect(luma[1]).toBeGreaterThanOrEqual(148)
    expect(luma[1]).toBeLessThanOrEqual(151)
    expect(luma[2]).toBeGreaterThanOrEqual(28)
    expect(luma[2]).toBeLessThanOrEqual(30)
    expect(luma[3]).toBe(255)
  })
})

describe('measureBrightness', () => {
  it('retorna mean luma', () => {
    expect(measureBrightness(makeUniformLuma(10, 10, 100))).toBe(100)
    expect(measureBrightness(makeUniformLuma(10, 10, 0))).toBe(0)
    expect(measureBrightness(makeUniformLuma(10, 10, 255))).toBe(255)
  })

  it('retorna 0 para buffer vacío', () => {
    expect(measureBrightness(new Uint8Array(0))).toBe(0)
  })
})

describe('measureSharpness', () => {
  it('imagen uniforme tiene variance ~0 (totalmente borrosa)', () => {
    const luma = makeUniformLuma(50, 50, 128)
    expect(measureSharpness(luma, 50, 50)).toBeLessThan(1)
  })

  it('imagen rayada tiene variance alta (nítida)', () => {
    const luma = makeStripedLuma(50, 50, 3)
    expect(measureSharpness(luma, 50, 50)).toBeGreaterThan(1000)
  })

  it('imagen ruidosa tiene variance moderada', () => {
    const luma = makeNoisyLuma(50, 50)
    const v = measureSharpness(luma, 50, 50)
    expect(v).toBeGreaterThan(100)
  })

  it('frames muy chicos retornan 0 sin error', () => {
    expect(measureSharpness(new Uint8Array(4), 2, 2)).toBe(0)
  })
})

describe('measureEdgeDensity', () => {
  it('imagen uniforme tiene 0 edges en ROI', () => {
    const luma = makeUniformLuma(50, 50, 128)
    expect(measureEdgeDensity(luma, 50, 50)).toBe(0)
  })

  it('imagen rayada vertical tiene density alta en ROI central', () => {
    const luma = makeStripedLuma(50, 50, 3)
    const d = measureEdgeDensity(luma, 50, 50)
    expect(d).toBeGreaterThan(0.3)
  })

  it('respeta roiFraction (más chica = menos píxeles totales)', () => {
    const luma = makeStripedLuma(100, 100, 3)
    const wide = measureEdgeDensity(luma, 100, 100, 0.9)
    const narrow = measureEdgeDensity(luma, 100, 100, 0.3)
    // ambos altos pero la densidad debe ser similar (rayas uniformes)
    expect(wide).toBeGreaterThan(0.3)
    expect(narrow).toBeGreaterThan(0.3)
  })
})

describe('measureStability', () => {
  it('frames idénticos → diff = 0', () => {
    const a = makeUniformLuma(10, 10, 128)
    const b = makeUniformLuma(10, 10, 128)
    expect(measureStability(a, b)).toBe(0)
  })

  it('frames diferentes → diff > 0', () => {
    const a = makeUniformLuma(10, 10, 100)
    const b = makeUniformLuma(10, 10, 150)
    expect(measureStability(a, b)).toBe(50)
  })

  it('prevLuma null → Infinity (primer frame)', () => {
    const curr = makeUniformLuma(10, 10, 128)
    expect(measureStability(null, curr)).toBe(Infinity)
  })

  it('size mismatch → Infinity (no comparable)', () => {
    expect(measureStability(new Uint8Array(50), new Uint8Array(100))).toBe(Infinity)
  })
})

describe('analyzeFrame', () => {
  const W = 50
  const H = 50

  it('frame negro → "Necesita más luz"', () => {
    const luma = makeUniformLuma(W, H, 10)
    const result = analyzeFrame(luma, luma, W, H)
    expect(result.ready).toBe(false)
    expect(result.hint).toMatch(/luz/i)
  })

  it('frame quemado → "Demasiada luz"', () => {
    const luma = makeUniformLuma(W, H, 240)
    const result = analyzeFrame(luma, luma, W, H)
    expect(result.ready).toBe(false)
    expect(result.hint).toMatch(/sombrea|demasiada/i)
  })

  it('frame uniforme medio → "Acerca o centra"', () => {
    const luma = makeUniformLuma(W, H, 128)
    const result = analyzeFrame(luma, luma, W, H)
    expect(result.ready).toBe(false)
    expect(result.hint).toMatch(/acerca|centra/i)
  })

  it('frame rayado estable → ready=true', () => {
    const luma = makeStripedLuma(W, H, 3)
    const result = analyzeFrame(luma, luma, W, H)
    expect(result.ready).toBe(true)
    expect(result.hint).toMatch(/listo|capturando/i)
  })

  it('frame rayado pero movido → "Mantén firme"', () => {
    const a = makeStripedLuma(W, H, 3)
    // Shift 2px horizontal — frames muy diferentes
    const b = new Uint8Array(W * H)
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        b[y * W + x] = a[y * W + ((x + 2) % W)]
      }
    }
    const result = analyzeFrame(a, b, W, H)
    expect(result.ready).toBe(false)
    expect(result.hint).toMatch(/firme/i)
  })

  it('scores raw siempre disponibles para debug', () => {
    const luma = makeStripedLuma(W, H, 3)
    const result = analyzeFrame(luma, luma, W, H)
    expect(result.scores).toMatchObject({
      brightness: expect.any(Number),
      sharpness: expect.any(Number),
      edgeDensity: expect.any(Number),
      stability: expect.any(Number),
    })
  })

  it('opts override umbrales default', () => {
    const dim = makeUniformLuma(W, H, 30)
    // Default rejecta (< 45). Override BRIGHTNESS_MIN=10 lo deja pasar
    // a la siguiente heurística (uniforme → "acerca o centra").
    const r = analyzeFrame(dim, dim, W, H, { BRIGHTNESS_MIN: 10 })
    expect(r.hint).toMatch(/acerca|centra/i)
  })
})

describe('DEFAULT_THRESHOLDS', () => {
  it('expone valores readonly para customización del caller', () => {
    expect(DEFAULT_THRESHOLDS.SHARPNESS_MIN).toBeGreaterThan(0)
    expect(DEFAULT_THRESHOLDS.BRIGHTNESS_MIN).toBeLessThan(DEFAULT_THRESHOLDS.BRIGHTNESS_MAX)
    expect(DEFAULT_THRESHOLDS.ROI_FRACTION).toBeGreaterThan(0)
    expect(DEFAULT_THRESHOLDS.ROI_FRACTION).toBeLessThanOrEqual(1)
  })
})
