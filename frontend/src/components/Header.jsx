import { Link } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { useAuth } from '../hooks/useAuth.js'
import ThemeToggle from './ThemeToggle.jsx'

/**
 * Logo: caja con gradient brand y un escudo-check adentro.
 *
 * El gradient `--gradient-brand` (azul → cyan) ya transmite el lenguaje
 * visual de "verificación / scanning". Combinado con el ícono de escudo
 * con check (símbolo universal de "verificado seguro") cierra el
 * mensaje sin necesidad de copy explicativo.
 */
export default function Header() {
  const { user, loading, logout } = useAuth()
  return (
    <header className="site-header">
      <Link to="/" className="brand" aria-label="Verificarro inicio">
        <span className="brand-mark">
          <ShieldCheck size={20} strokeWidth={2.4} />
        </span>
        <span>verifica<span className="brand-accent">rro</span></span>
      </Link>
      <nav className="header-nav">
        <Link to="/precios" className="header-link">Precios</Link>
        {!loading && user && (
          <>
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
