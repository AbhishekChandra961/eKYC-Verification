// The login session: kept in memory and mirrored to sessionStorage, so a page reload keeps the user logged in
// within the same browser tab (closing the tab ends it). Production note: an httpOnly, Secure, SameSite cookie
// set by the API is the safer choice, because JavaScript (and so an XSS bug) cannot read it. See README.md.

export type Role = 'CUSTOMER' | 'OFFICER'

export interface Session {
  token: string
  role: Role
  email: string
  expiresAt: number // epoch milliseconds
}

const STORAGE_KEY = 'securebank.ekyc.session'
let memory: Session | null | undefined // undefined = sessionStorage not read yet

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null // storage blocked (privacy mode): the session lives in memory only
  }
}

function parse(raw: string): Session | null {
  try {
    const value = JSON.parse(raw) as Partial<Session>
    if (typeof value.token === 'string' && (value.role === 'CUSTOMER' || value.role === 'OFFICER') &&
        typeof value.email === 'string' && typeof value.expiresAt === 'number') {
      return { token: value.token, role: value.role, email: value.email, expiresAt: value.expiresAt }
    }
  } catch {
    // corrupt entry: ignored
  }
  return null
}

export function readSession(now: number = Date.now()): Session | null {
  if (memory === undefined) {
    const raw = (() => {
      try {
        return storage()?.getItem(STORAGE_KEY) ?? null
      } catch {
        return null
      }
    })()
    memory = raw ? parse(raw) : null
  }
  if (memory && memory.expiresAt <= now) {
    clearSession()
    return null
  }
  return memory
}

export function writeSession(session: Session): void {
  memory = session
  try {
    storage()?.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // memory only
  }
}

export function clearSession(): void {
  memory = null
  try {
    storage()?.removeItem(STORAGE_KEY)
  } catch {
    // nothing stored
  }
}

/** For tests: forget the in-memory copy so the next read goes to sessionStorage again. */
export function resetSessionCache(): void {
  memory = undefined
}

export function homeFor(role: Role): string {
  return role === 'OFFICER' ? '/officer' : '/customer'
}
