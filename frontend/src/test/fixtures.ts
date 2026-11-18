import type { ApplicationView } from '../api/client'

export function applicationView(overrides: Partial<ApplicationView> = {}): ApplicationView {
  return {
    application_id: 'app-0123456789abcdef',
    status: 'PROCESSING',
    outcome: null,
    message: null,
    retake: [],
    progress: { completed: 2, total: 4 },
    created_at: '2026-11-17T10:00:00Z',
    updated_at: '2026-11-17T10:00:20Z',
    ...overrides,
  }
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
