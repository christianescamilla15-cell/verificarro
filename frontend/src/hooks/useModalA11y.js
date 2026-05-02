import { useEffect, useRef } from 'react'

/**
 * Hook reusable para accesibilidad de modales (MOD-028):
 *
 * 1. **ESC handler**: cierra el modal cuando el usuario presiona Escape.
 * 2. **Focus trap**: Tab/Shift+Tab cyclan entre los elementos focusables
 *    DENTRO del modal — no se puede tabbear hacia el contenido detrás.
 * 3. **Initial focus**: pone focus en el primer elemento focusable del
 *    modal al montar (el screen reader anuncia el contexto).
 * 4. **Restore focus**: cuando el modal se desmonta, devuelve focus al
 *    elemento que lo abrió (aria spec).
 *
 * Uso:
 *
 *     const ref = useRef(null)
 *     useModalA11y(ref, onClose)
 *     return <div ref={ref} role="dialog" aria-modal="true">...</div>
 */
export function useModalA11y(modalRef, onClose) {
  const previouslyFocusedRef = useRef(null)

  useEffect(() => {
    // Guarda elemento que tenía focus antes de abrir el modal
    previouslyFocusedRef.current = document.activeElement

    // Initial focus: primer elemento focusable dentro del modal
    const focusables = getFocusableElements(modalRef.current)
    if (focusables.length > 0) {
      focusables[0].focus()
    } else if (modalRef.current) {
      // Si no hay focusables, focus en el container (con tabIndex=-1
      // implícito) para que ESC funcione
      modalRef.current.focus()
    }

    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose?.()
        return
      }
      if (e.key === 'Tab') {
        trapFocus(e, modalRef.current)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      // Restore focus al cerrar
      if (previouslyFocusedRef.current && previouslyFocusedRef.current.focus) {
        try {
          previouslyFocusedRef.current.focus()
        } catch {
          /* element may have been removed from DOM */
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}


function getFocusableElements(container) {
  if (!container) return []
  return Array.from(
    container.querySelectorAll(
      'a[href], button:not([disabled]), textarea:not([disabled]), ' +
      'input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
      '[tabindex]:not([tabindex="-1"])',
    ),
  )
}


function trapFocus(event, container) {
  const focusables = getFocusableElements(container)
  if (focusables.length === 0) {
    event.preventDefault()
    return
  }
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const active = document.activeElement

  if (event.shiftKey) {
    // Shift+Tab desde el primer elemento → wrap al último
    if (active === first || !container.contains(active)) {
      event.preventDefault()
      last.focus()
    }
  } else {
    // Tab desde el último elemento → wrap al primero
    if (active === last) {
      event.preventDefault()
      first.focus()
    }
  }
}
