import { Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'

export default function Header() {
  const { user, loading, logout } = useAuth()
  return (
    <header className="site-header">
      <Link to="/" className="brand">Verificarro</Link>
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
