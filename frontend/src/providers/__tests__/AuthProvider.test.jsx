import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import AuthProvider from '../AuthProvider.jsx'
import { useAuth } from '../../hooks/useAuth.js'

// Mock api.js — el AuthProvider importa api + getToken + clearToken.
vi.mock('../../lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  getToken: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
}))

import { api, getToken } from '../../lib/api.js'

function Consumer() {
  const { user, loading } = useAuth()
  if (loading) return <div data-testid="status">loading</div>
  if (user) return <div data-testid="status">user:{user.email}</div>
  return <div data-testid="status">guest</div>
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sin token, queda en guest sin llamar /me', async () => {
    getToken.mockReturnValue(null)
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )
    await waitFor(() => {
      expect(screen.getByTestId('status').textContent).toBe('guest')
    })
    expect(api.get).not.toHaveBeenCalled()
  })

  it('con token, /me responde user → expone via context', async () => {
    getToken.mockReturnValue('jwt-fake')
    api.get.mockResolvedValue({
      ok: true,
      data: { id: 'u1', email: 'foo@bar.mx', last_login_at: null },
    })
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )
    await waitFor(() => {
      expect(screen.getByTestId('status').textContent).toBe('user:foo@bar.mx')
    })
    expect(api.get).toHaveBeenCalledWith('/api/auth/me')
  })

  it('con token pero /me falla (401), user queda null', async () => {
    getToken.mockReturnValue('jwt-stale')
    api.get.mockResolvedValue({ ok: false, status: 401 })
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )
    await waitFor(() => {
      expect(screen.getByTestId('status').textContent).toBe('guest')
    })
  })

  it('llama /me solo UNA vez con múltiples consumers (single fetch)', async () => {
    getToken.mockReturnValue('jwt-shared')
    api.get.mockResolvedValue({
      ok: true,
      data: { id: 'u1', email: 'a@b.mx', last_login_at: null },
    })
    render(
      <AuthProvider>
        <Consumer />
        <Consumer />
        <Consumer />
      </AuthProvider>,
    )
    await waitFor(() => {
      const els = screen.getAllByTestId('status')
      expect(els.every((el) => el.textContent === 'user:a@b.mx')).toBe(true)
    })
    expect(api.get).toHaveBeenCalledTimes(1)
  })
})
