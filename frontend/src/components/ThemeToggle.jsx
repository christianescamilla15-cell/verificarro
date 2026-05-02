import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'

const STORAGE_KEY = 'verificarro_theme'

/**
 * Toggle dark ↔ light. Estado persistente en localStorage.
 *
 * Aplica/remueve la clase `light` en `<html>` (y simétricamente
 * mantiene `dark`). Los tokens en `tokens.css` reaccionan según
 * `:root.dark` vs `:root.light`.
 *
 * Default: dark (matching la marca actual). Honra prefers-color-scheme
 * en el primer load si el usuario no ha elegido aún.
 */
export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => readInitial())

  useEffect(() => {
    applyTheme(theme)
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* localStorage puede fallar en modo privado; ignorable */
    }
  }, [theme])

  return (
    <button
      type="button"
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      className="theme-toggle"
      aria-label={theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
      title={theme === 'dark' ? 'Tema claro' : 'Tema oscuro'}
    >
      {theme === 'dark' ? <Sun size={18} strokeWidth={2.2} /> : <Moon size={18} strokeWidth={2.2} />}
    </button>
  )
}

function readInitial() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    /* ignore */
  }
  // Honra OS preference
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: light)').matches
      ? 'light'
      : 'dark'
  }
  return 'dark'
}

function applyTheme(theme) {
  const html = document.documentElement
  const body = document.body
  if (theme === 'light') {
    html.classList.add('light')
    html.classList.remove('dark')
    if (body) {
      body.classList.add('light')
      body.classList.remove('dark')
    }
  } else {
    html.classList.add('dark')
    html.classList.remove('light')
    if (body) {
      body.classList.add('dark')
      body.classList.remove('light')
    }
  }
}
