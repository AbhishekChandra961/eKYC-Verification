import { createContext, useContext } from 'react'
import type { Session } from './session'

export type LogoutReason = 'user' | 'expired'

export interface AuthValue {
  session: Session | null
  logoutReason: LogoutReason | null
  login: (email: string, password: string) => Promise<Session>
  logout: (reason?: LogoutReason) => void
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
