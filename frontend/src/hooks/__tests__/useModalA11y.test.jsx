import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import { useRef } from 'react'
import { useModalA11y } from '../useModalA11y.js'

function Modal({ onClose }) {
  const ref = useRef(null)
  useModalA11y(ref, onClose)
  return (
    <div ref={ref} role="dialog" aria-modal="true">
      <button>OK</button>
      <button>Cancel</button>
    </div>
  )
}

describe('useModalA11y', () => {
  it('cierra el modal al presionar ESC', () => {
    const onClose = vi.fn()
    render(<Modal onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('NO cierra al presionar otras teclas', () => {
    const onClose = vi.fn()
    render(<Modal onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Enter' })
    fireEvent.keyDown(document, { key: 'Space' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('focus inicial cae en el primer elemento focusable', () => {
    const onClose = vi.fn()
    render(<Modal onClose={onClose} />)
    expect(document.activeElement.textContent).toBe('OK')
  })

  it('restaura focus al elemento previo cuando se desmonta', () => {
    const trigger = document.createElement('button')
    trigger.textContent = 'Open modal'
    document.body.appendChild(trigger)
    trigger.focus()

    const onClose = vi.fn()
    const { unmount } = render(<Modal onClose={onClose} />)
    expect(document.activeElement.textContent).toBe('OK')

    unmount()
    expect(document.activeElement).toBe(trigger)

    document.body.removeChild(trigger)
  })
})
