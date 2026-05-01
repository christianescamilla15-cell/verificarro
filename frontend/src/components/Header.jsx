import { Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'

/**
 * Logo: una placa estilizada con un check.
 *
 * El gráfico va inline para evitar un request extra y para que herede
 * el `currentColor` del padre (lo cual nos permite recolorear el logo
 * con la variable `--accent` de tokens.css).
 */
function BrandMark() {
  return (
    <svg
      width="28" height="28" viewBox="0 0 28 28" fill="none"
      xmlns="http://www.w3.org/2000/svg" aria-hidden="true"
    >
      {/* Marco de placa */}
      <rect
        x="2" y="6" width="24" height="16" rx="3"
        stroke="currentColor" strokeWidth="2"
      />
      {/* "Tornillos" — lados de placa MX */}
      <circle cx="5.5" cy="9" r="0.7" fill="currentColor" />
      <circle cx="22.5" cy="9" r="0.7" fill="currentColor" />
      <circle cx="5.5" cy="19" r="0.7" fill="currentColor" />
      <circle cx="22.5" cy="19" r="0.7" fill="currentColor" />
      {/* Check */}
      <path
        d="M9.5 14.2L12.5 17.2L18.5 11.2"
        stroke="currentColor" strokeWidth="2.4"
        strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  )
}

export default function Header() {
  const { user, loading, logout } = useAuth()
  return (
    <header className="site-header">
      <Link to="/" className="brand" aria-label="Verificarro inicio">
        <span className="brand-mark"><BrandMark /></span>
        <span>verifica<span className="brand-accent">rro</span></span>
      </Link>
      <nav className="header-nav">
        {!loading && user && (
          <>
            <span className="header-email">{user.email}</span>
            <button onClick={logout} className="link-button">Salir</button>
          </>
        )}
        {!loading && !user && (
          <Link to="/login" className="header-link">Iniciar sesión</Link>
        )}
      </nav>
    </header>
  )
}
