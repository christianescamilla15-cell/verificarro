import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import RepuveScreenshotUploader from '../RepuveScreenshotUploader.jsx'

vi.mock('../../lib/api.js', () => ({
  api: { post: vi.fn() },
}))

import { api } from '../../lib/api.js'

function makeImageFile(name = 'modal.jpg', type = 'image/jpeg', size = 200) {
  const blob = new Blob([new Uint8Array(size)], { type })
  return new File([blob], name, { type })
}

function findHiddenFileInput(container) {
  return container.querySelector('input[type="file"]')
}

describe('RepuveScreenshotUploader', () => {
  beforeEach(() => {
    api.post.mockReset()
  })

  it('renderiza el CTA inicial con copy claro', () => {
    render(<RepuveScreenshotUploader plate="ABC1234" />)
    expect(
      screen.getByText(/Sube el PDF o captura/i),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Subir PDF o captura de REPUVE/i }),
    ).toBeInTheDocument()
  })

  it('rechaza archivos que no son imagen ni PDF sin llamar al backend', async () => {
    const { container } = render(<RepuveScreenshotUploader plate="ABC1234" />)
    const input = findHiddenFileInput(container)
    const txt = new File(['hola'], 'nota.txt', { type: 'text/plain' })

    fireEvent.change(input, { target: { files: [txt] } })

    await waitFor(() => {
      expect(screen.getByText(/Selecciona una imagen.*PDF/i)).toBeInTheDocument()
    })
    expect(api.post).not.toHaveBeenCalled()
  })

  it('rechaza imagenes mas grandes de 3MB sin llamar al backend', async () => {
    const { container } = render(<RepuveScreenshotUploader plate="ABC1234" />)
    const input = findHiddenFileInput(container)
    const huge = makeImageFile('big.jpg', 'image/jpeg', 4 * 1024 * 1024)

    fireEvent.change(input, { target: { files: [huge] } })

    await waitFor(() => {
      expect(screen.getByText(/El archivo es muy grande.*3 MB/i)).toBeInTheDocument()
    })
    expect(api.post).not.toHaveBeenCalled()
  })

  it('acepta PDF y lo manda con media_type application/pdf', async () => {
    api.post.mockResolvedValue({
      ok: true,
      data: {
        queried: true,
        plate: 'ABC1234',
        is_stolen: false,
        raw_status: 'sin_reportes',
        ocr_confidence: 'high',
        ocr_notes: '',
      },
    })
    const onResult = vi.fn()
    const { container } = render(
      <RepuveScreenshotUploader plate="ABC1234" onResult={onResult} />,
    )
    const input = findHiddenFileInput(container)
    const pdfBlob = new Blob([new Uint8Array(500)], { type: 'application/pdf' })
    const pdfFile = new File([pdfBlob], 'repuve.pdf', { type: 'application/pdf' })

    fireEvent.change(input, { target: { files: [pdfFile] } })

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/api/repuve/screenshot',
        expect.objectContaining({
          media_type: 'application/pdf',
          plate: 'ABC1234',
        }),
      )
    })
    await waitFor(() => {
      expect(onResult).toHaveBeenCalled()
    })
  })

  it('llama onResult con datos del backend cuando la consulta tiene exito', async () => {
    api.post.mockResolvedValue({
      ok: true,
      data: {
        queried: true,
        plate: 'ABC1234',
        is_stolen: false,
        has_legal_status: true,
        raw_status: 'sin_reportes',
        ocr_confidence: 'high',
        ocr_notes: '',
      },
    })
    const onResult = vi.fn()
    const { container } = render(
      <RepuveScreenshotUploader plate="ABC1234" onResult={onResult} />,
    )
    const input = findHiddenFileInput(container)

    fireEvent.change(input, { target: { files: [makeImageFile()] } })

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/api/repuve/screenshot',
        expect.objectContaining({
          plate: 'ABC1234',
          media_type: 'image/jpeg',
          source: 'mobile/0.1',
        }),
      )
    })
    await waitFor(() => {
      expect(onResult).toHaveBeenCalledWith(
        expect.objectContaining({ queried: true, is_stolen: false }),
      )
    })
    expect(screen.getByText(/Captura procesada/i)).toBeInTheDocument()
  })

  it('muestra error claro cuando el OCR no detecta modal', async () => {
    api.post.mockResolvedValue({
      ok: true,
      data: {
        queried: false,
        raw_status: 'screenshot_no_modal',
        error: 'No vimos un modal',
        ocr_confidence: 'low',
      },
    })
    const onResult = vi.fn()
    const { container } = render(
      <RepuveScreenshotUploader plate="ABC1234" onResult={onResult} />,
    )

    fireEvent.change(findHiddenFileInput(container), {
      target: { files: [makeImageFile()] },
    })

    await waitFor(() => {
      expect(screen.getByText(/No vimos un modal/i)).toBeInTheDocument()
    })
    expect(onResult).not.toHaveBeenCalled()
    // El boton de retry debe estar disponible
    expect(
      screen.getByRole('button', { name: /Intentar de nuevo/i }),
    ).toBeInTheDocument()
  })

  it('trata raw_status=no_encontrado como exito (resultado valido REPUVE)', async () => {
    api.post.mockResolvedValue({
      ok: true,
      data: {
        queried: false,
        raw_status: 'no_encontrado',
        error: 'Vehiculo no encontrado en REPUVE',
        ocr_confidence: 'high',
      },
    })
    const onResult = vi.fn()
    const { container } = render(
      <RepuveScreenshotUploader plate="ZZZ9999" onResult={onResult} />,
    )

    fireEvent.change(findHiddenFileInput(container), {
      target: { files: [makeImageFile()] },
    })

    await waitFor(() => {
      expect(onResult).toHaveBeenCalledWith(
        expect.objectContaining({ raw_status: 'no_encontrado' }),
      )
    })
  })

  it('muestra warning cuando la confianza OCR es baja', async () => {
    api.post.mockResolvedValue({
      ok: true,
      data: {
        queried: true,
        is_stolen: false,
        raw_status: 'sin_reportes',
        ocr_confidence: 'low',
        ocr_notes: 'foto borrosa pero legible',
      },
    })
    const { container } = render(
      <RepuveScreenshotUploader plate="ABC1234" onResult={() => {}} />,
    )

    fireEvent.change(findHiddenFileInput(container), {
      target: { files: [makeImageFile()] },
    })

    await waitFor(() => {
      expect(screen.getByText(/baja confianza/i)).toBeInTheDocument()
    })
  })

  it('llama onCancel cuando se hace click en el boton X', () => {
    const onCancel = vi.fn()
    render(
      <RepuveScreenshotUploader plate="ABC1234" onCancel={onCancel} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Cancelar/i }))
    expect(onCancel).toHaveBeenCalled()
  })
})
