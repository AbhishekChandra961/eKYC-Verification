import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { AppRoutes } from '../AppRoutes'
import { jsonResponse } from '../test/fixtures'
import { AuthContext, useAuth, type AuthValue } from './AuthContext'
import { AuthProvider } from './AuthProvider'
import { RequireRole } from './RequireRole'
import { readSession, resetSessionCache, writeSession, type Role, type Session } from './session'

function session(role: Role, minutes = 30): Session {
  return { token: `token-${role}`, role, email: `${role.toLowerCase()}@test`, expiresAt: Date.now() + minutes * 60_000 }
}

function auth(current: Session | null): AuthValue {
  return { session: current, logoutReason: null, login: vi.fn(), logout: vi.fn() }
}

function LoginStub() {
  const location = useLocation()
  return <p>login page (from {(location.state as { from?: string } | null)?.from})</p>
}

function renderGuarded(path: string, current: Session | null) {
  return render(
    <AuthContext.Provider value={auth(current)}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginStub />} />
          <Route path="/customer" element={<RequireRole allow="CUSTOMER"><p>customer home</p></RequireRole>} />
          <Route path="/officer/*" element={<RequireRole allow="OFFICER"><p>officer area</p></RequireRole>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('route guards', () => {
  it('sends a visitor who is not logged in to the login page, remembering the page', () => {
    renderGuarded('/officer/cases/app-1', null)
    expect(screen.getByText('login page (from /officer/cases/app-1)')).toBeInTheDocument()
    expect(screen.queryByText('officer area')).not.toBeInTheDocument()
  })

  it('sends a customer who opens an officer page to the customer home', () => {
    renderGuarded('/officer', session('CUSTOMER'))
    expect(screen.getByText('customer home')).toBeInTheDocument()
    expect(screen.queryByText('officer area')).not.toBeInTheDocument()
  })

  it('sends an officer who opens a customer page to the officer home', () => {
    renderGuarded('/customer', session('OFFICER'))
    expect(screen.getByText('officer area')).toBeInTheDocument()
  })

  it('lets each role into its own portal', () => {
    renderGuarded('/officer', session('OFFICER'))
    expect(screen.getByText('officer area')).toBeInTheDocument()
    renderGuarded('/customer', session('CUSTOMER'))
    expect(screen.getByText('customer home')).toBeInTheDocument()
  })

  it('shows the real login page for a protected route in the full app', () => {
    render(
      <AuthContext.Provider value={auth(null)}>
        <MemoryRouter initialEntries={['/officer']}><AppRoutes /></MemoryRouter>
      </AuthContext.Provider>,
    )
    expect(screen.getByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })
})

describe('session storage', () => {
  it('drops an expired session', () => {
    writeSession({ ...session('CUSTOMER'), expiresAt: Date.now() - 1000 })
    resetSessionCache()
    expect(readSession()).toBeNull()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('ignores a corrupt or tampered entry', () => {
    window.sessionStorage.setItem('securebank.ekyc.session', JSON.stringify({ token: 'x', role: 'ADMIN', email: 'a', expiresAt: 9e12 }))
    resetSessionCache()
    expect(readSession()).toBeNull()
  })

  it('restores a valid session after a reload', () => {
    writeSession(session('OFFICER'))
    resetSessionCache() // as after a page reload
    expect(readSession()?.role).toBe('OFFICER')
  })
})

describe('auto-logout', () => {
  function Probe() {
    const { session: current, logoutReason } = useAuth()
    return <p>{current ? `logged in as ${current.role}` : `logged out (${logoutReason})`}</p>
  }

  it('logs the user out when the API answers 401', async () => {
    writeSession(session('CUSTOMER'))
    resetSessionCache()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'invalid or expired token' })))
    render(<AuthProvider><Probe /></AuthProvider>)
    expect(screen.getByText('logged in as CUSTOMER')).toBeInTheDocument()
    await act(async () => { await api.myApplications().catch(() => undefined) })
    await waitFor(() => expect(screen.getByText('logged out (expired)')).toBeInTheDocument())
    expect(readSession()).toBeNull()
  })

  it('logs the user out when the token expires, without any request', async () => {
    vi.useFakeTimers()
    try {
      writeSession(session('OFFICER', 1))
      resetSessionCache()
      render(<AuthProvider><Probe /></AuthProvider>)
      expect(screen.getByText('logged in as OFFICER')).toBeInTheDocument()
      await act(async () => { vi.advanceTimersByTime(61_000) })
      expect(screen.getByText('logged out (expired)')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
