import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, configureClient } from '../api/client'
import { AuthContext, type AuthValue, type LogoutReason } from './AuthContext'
import { clearSession, readSession, writeSession, type Session } from './session'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => readSession())
  const [logoutReason, setLogoutReason] = useState<LogoutReason | null>(null)

  const logout = useCallback((reason: LogoutReason = 'user') => {
    clearSession()
    setSession(null)
    setLogoutReason(reason)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const token = await api.login(email, password)
    const next: Session = { token: token.access_token, role: token.role, email,
      expiresAt: Date.now() + token.expires_in * 1000 }
    writeSession(next)
    setSession(next)
    setLogoutReason(null)
    return next
  }, [])

  // Any 401 from the API (expired or invalid token) logs the user out; the route guards then show the login page.
  useEffect(() => {
    configureClient({ onUnauthorized: () => logout('expired') })
  }, [logout])

  // Log out when the token expires, even if no request is made.
  useEffect(() => {
    if (!session) return
    const timer = window.setTimeout(() => logout('expired'), Math.max(0, session.expiresAt - Date.now()))
    return () => window.clearTimeout(timer)
  }, [session, logout])

  const value = useMemo<AuthValue>(() => ({ session, logoutReason, login, logout }), [session, logoutReason, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
