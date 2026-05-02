import { Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'
import BrandMark from './BrandMark.jsx'
import ThemeToggle from './ThemeToggle.jsx'

export default function Header() {
  const { user, loading, logout } = useAuth()
  return (
    <header className="site-header">
      <Link to="/" className="brand" aria-label="Verificarro inicio">
        <span className="brand-mark" aria-hidden="true">
          <BrandMark size={22} variant="glyph" />
        </span>
        <span>verifica<span className="brand-accent">rro</span></span>
      </Link>
      <nav className="header-nav">
        <Link to="/precios" className="header-link">Precios</Link>
        {!loading && user && (
          <>
            <Link to="/dashboard" className="header-link">Tablero</Link>
            <span className="header-email">{user.email}</span>
            <button onClick={logout} className="link-button">Salir</button>
          </>
        )}
        {!loading && !user && (
          <Link to="/login" className="header-link">Iniciar sesión</Link>
        )}
        <ThemeToggle />
      </nav>
    </header>
  )
}
