import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ScoreChip from '../ScoreChip.jsx'

describe('ScoreChip', () => {
  it('renderiza score numérico + /100', () => {
    render(<ScoreChip score={73} risk="green" />)
    expect(screen.getByText('73')).toBeInTheDocument()
    expect(screen.getByText('/ 100')).toBeInTheDocument()
  })

  it('label "RIESGO BAJO" cuando risk=green', () => {
    render(<ScoreChip score={85} risk="green" />)
    expect(screen.getByText('RIESGO BAJO')).toBeInTheDocument()
  })

  it('label "PRECAUCIÓN" cuando risk=yellow', () => {
    render(<ScoreChip score={55} risk="yellow" />)
    expect(screen.getByText('PRECAUCIÓN')).toBeInTheDocument()
  })

  it('label "ALTO RIESGO" cuando risk=red', () => {
    render(<ScoreChip score={20} risk="red" />)
    expect(screen.getByText('ALTO RIESGO')).toBeInTheDocument()
  })

  it('aplica la clase score-{risk} al contenedor', () => {
    const { container } = render(<ScoreChip score={50} risk="red" />)
    expect(container.firstChild).toHaveClass('score-chip', 'score-red')
  })
})
