// The one module that talks to the eKYC API. Every response type comes from schema.d.ts, which is generated from
// the API's OpenAPI schema (npm run gen:api), so a backend change that breaks the frontend fails the type check.
import { readSession } from '../auth/session'
import type { components } from './schema'

type Schemas = components['schemas']
export type Token = Schemas['Token']
export type ApplicationView = Schemas['ApplicationView']
export type SubmitResponse = Schemas['SubmitResponse']
export type CaseRow = Schemas['CaseRow']
export type CaseDetail = Schemas['CaseDetail']
export type CheckOut = Schemas['CheckOut']
export type ReasonOut = Schemas['ReasonOut']
export type DecisionOut = Schemas['DecisionOut']
export type AuditEntry = Schemas['AuditEntry']
export type Heatmap = Schemas['Heatmap']
export type TileGrid = Schemas['TileGrid']
export type OfficerDecisionResult = Schemas['OfficerDecisionResult']
export type ApplicationStatus = ApplicationView['status']
export type Outcome = NonNullable<ApplicationView['outcome']>
export type RiskLevel = NonNullable<CaseRow['risk_level']>
export type OfficerAction = Schemas['OfficerDecision']['action']

// The API address: set at container START by the Docker image (/config.js, from EKYC_API_URL), else at BUILD time
// (VITE_API_URL, e.g. .env.local for the dev server), else the local default. One built image serves any address.
declare global {
  interface Window { EKYC_CONFIG?: { apiUrl?: string } }
}
const runtime = typeof window !== 'undefined' ? window.EKYC_CONFIG?.apiUrl?.trim() : undefined
const configured = (import.meta.env.VITE_API_URL as string | undefined)?.trim()
export const API_URL: string = (runtime || configured || 'http://127.0.0.1:8000').replace(/\/+$/, '')

/** Every failed call throws this. status 0 = the server could not be reached. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let getToken: () => string | null = () => readSession()?.token ?? null
let onUnauthorized: () => void = () => {}

/** The auth provider registers what happens on a 401 (log out). Tests can also replace the token source. */
export function configureClient(options: { getToken?: () => string | null; onUnauthorized?: () => void }): void {
  if (options.getToken) getToken = options.getToken
  if (options.onUnauthorized) onUnauthorized = options.onUnauthorized
}

const STATUS_MESSAGES: Record<number, string> = {
  403: 'You do not have access to this page.',
  404: 'Not found.',
  409: 'This action is no longer possible: the case has changed. Reload the page.',
  413: 'The file is too large.',
  415: 'Unsupported file type. Use a JPEG or PNG image.',
  429: 'Too many requests. Please wait a moment and try again.',
}

/** FastAPI errors are {"detail": "text"} or, for validation errors, {"detail": [{"loc": [...], "msg": "..."}]}. */
export async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      const parts = body.detail.map((item: { loc?: unknown[]; msg?: unknown }) => {
        const field = Array.isArray(item.loc) ? item.loc.filter((p) => p !== 'body').join('.') : ''
        return typeof item.msg === 'string' ? (field ? `${field}: ${item.msg}` : item.msg) : ''
      })
      const text = parts.filter(Boolean).join('; ')
      if (text) return text
    }
  } catch {
    // not JSON: fall through to a generic message
  }
  return STATUS_MESSAGES[response.status] ??
    (response.status >= 500 ? 'The service is temporarily unavailable. Please try again.' : `Request failed (${response.status}).`)
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: BodyInit
  json?: unknown
  auth?: boolean // false for the login call: its 401 means "wrong password", not "session expired"
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', auth = true } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  let body = options.body
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  }
  const token = auth ? getToken() : null
  if (token) headers.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, { method, headers, body, signal: options.signal })
  } catch (error) {
    if (isAbort(error)) throw error // the caller cancelled
    throw new ApiError(0, 'Cannot reach the server. Please check your connection and try again.')
  }
  if (response.status === 401 && auth) {
    onUnauthorized() // expired or invalid token: log out everywhere
    throw new ApiError(401, 'Your session has expired. Please log in again.')
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  return (await response.json()) as T
}

function fileName(blob: Blob, base: string): string {
  if (blob instanceof File && blob.name) return blob.name
  return `${base}.${blob.type === 'image/png' ? 'png' : 'jpg'}`
}

export interface NewApplication {
  fullName: string
  dateOfBirth: string // YYYY-MM-DD
  idImage: Blob
  selfie: Blob
}

export const api = {
  login(email: string, password: string): Promise<Token> {
    const form = new URLSearchParams({ username: email, password })
    return request<Token>('/auth/login', { method: 'POST', body: form, auth: false })
  },

  // ---- customer
  submitApplication(input: NewApplication): Promise<SubmitResponse> {
    const form = new FormData()
    form.append('full_name', input.fullName)
    form.append('date_of_birth', input.dateOfBirth)
    form.append('id_image', input.idImage, fileName(input.idImage, 'id-document'))
    form.append('selfie', input.selfie, fileName(input.selfie, 'selfie'))
    return request<SubmitResponse>('/applications', { method: 'POST', body: form })
  },
  myApplications(signal?: AbortSignal): Promise<ApplicationView[]> {
    return request<ApplicationView[]>('/applications', { signal })
  },
  myApplication(applicationId: string, signal?: AbortSignal): Promise<ApplicationView> {
    return request<ApplicationView>(`/applications/${encodeURIComponent(applicationId)}`, { signal })
  },
  /** Server-Sent Events URL. The token goes in the query string: the browser's EventSource cannot send headers. */
  applicationEventsUrl(applicationId: string): string {
    return `${API_URL}/applications/${encodeURIComponent(applicationId)}/events?token=${encodeURIComponent(getToken() ?? '')}`
  },

  // ---- officer
  officerCases(filters: { status?: ApplicationStatus; outcome?: Outcome }, signal?: AbortSignal): Promise<CaseRow[]> {
    const query = new URLSearchParams()
    if (filters.status) query.set('status', filters.status)
    if (filters.outcome) query.set('outcome', filters.outcome)
    const suffix = query.size ? `?${query.toString()}` : ''
    return request<CaseRow[]>(`/officer/cases${suffix}`, { signal })
  },
  officerCase(applicationId: string, signal?: AbortSignal): Promise<CaseDetail> {
    return request<CaseDetail>(`/officer/cases/${encodeURIComponent(applicationId)}`, { signal })
  },
  officerDecision(applicationId: string, action: OfficerAction, reason: string): Promise<OfficerDecisionResult> {
    return request<OfficerDecisionResult>(`/officer/cases/${encodeURIComponent(applicationId)}/decision`,
      { method: 'POST', json: { action, reason } })
  },
}

/** A request cancelled by its AbortController (checked by name: not every runtime's DOMException is an Error). */
export function isAbort(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError'
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
