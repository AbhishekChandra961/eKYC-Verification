import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from './AuthContext'
import { homeFor, type Role } from './session'

/** Route guard: not logged in -> the login page (remembering where the user wanted to go);
 *  logged in with the other role -> that role's home page. The API checks roles too: this only shapes the UI. */
export function RequireRole({ allow, children }: { allow: Role; children: ReactNode }) {
  const { session } = useAuth()
  const location = useLocation()
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (session.role !== allow) return <Navigate to={homeFor(session.role)} replace />
  return <>{children}</>
}
