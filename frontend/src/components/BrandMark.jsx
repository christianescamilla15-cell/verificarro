/**
 * Verificarro brand mark.
 *
 * Glifo propio en lugar del ShieldCheck genérico de Lucide. La idea
 * geométrica es un híbrido `V/✓`: una v profunda (initial de
 * Verificarro) cuya pierna derecha se prolonga hasta volverse un
 * check rebasando el lado superior, lo cual lo lee como "verificado"
 * sin recurrir al cliché del escudo. Una sola path stroke, escala
 * impecable a 16/24/36/80 px.
 *
 * Render:
 *   - Modo `solid` (default): caja rounded con gradient brand y la
 *     V/✓ blanca al centro. Para el header y la favicon.
 *   - Modo `glyph`: solo el path en `currentColor` sin caja, para
 *     usos donde ya hay fondo (footer, watermark del PDF).
 */
export default function BrandMark({
  size = 36,
  variant = 'solid',
  ariaLabel = 'Verificarro',
  className,
}) {
  // viewBox 32×32. Path: (top-left) → (vertex bajo) → (extiende hasta
  // arriba-derecha pasando del top-right corner para leer como check).
  const path = 'M 8 11 L 16 22 L 25 9'

  if (variant === 'glyph') {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        viewBox="0 0 32 32"
        role="img"
        aria-label={ariaLabel}
        className={className}
      >
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="3.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  // solid: caja gradient + glyph blanco
  const gradId = `vmark-grad-${size}`
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label={ariaLabel}
      className={className}
    >
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#1e64dc" />
          <stop offset="100%" stopColor="#06b6d4" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="7" fill={`url(#${gradId})`} />
      <path
        d={path}
        fill="none"
        stroke="#ffffff"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
