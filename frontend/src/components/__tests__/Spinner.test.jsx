import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Spinner from '../Spinner.jsx'

describe('Spinner', () => {
  it('renderiza sin mensaje', () => {
    const { container } = render(<Spinner />)
    expect(container.querySelector('.spinner')).toBeInTheDocument()
    expect(container.querySelector('.spinner-message')).toBeNull()
  })

  it('renderiza con mensaje opcional', () => {
    render(<Spinner message="Cargando reportes…" />)
    expect(screen.getByText('Cargando reportes…')).toBeInTheDocument()
  })
})
