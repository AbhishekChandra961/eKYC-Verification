import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jsonResponse } from '../test/fixtures'
import { API_URL, ApiError, api, applicationEventsUrl, configureClient } from './client'

let token: string | null = 'token-123'
const onUnauthorized = vi.fn()

beforeEach(() => {
  token = 'token-123'
  onUnauthorized.mockReset()
  configureClient({ getToken: () => token, onUnauthorized })
})

function mockFetch(response: Response | { reject: unknown }) {
  const fetchMock = response instanceof Response ? vi.fn().mockResolvedValue(response) : vi.fn().mockRejectedValue(response.reject)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError)
    return error as ApiError
  }
  throw new Error('expected the call to fail')
}

describe('API client', () => {
  it('sends the bearer token and returns the parsed body', async () => {
    const fetchMock = mockFetch(jsonResponse(200, []))
    await expect(api.myApplications()).resolves.toEqual([])
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${API_URL}/applications`)
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer token-123')
  })

  it('a 401 on a logged-in call logs the user out', async () => {
    mockFetch(jsonResponse(401, { detail: 'invalid or expired token' }))
    const error = await failure(api.officerCases({}))
    expect(error.status).toBe(401)
    expect(error.message).toMatch(/session has expired/)
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('a 401 at login means a wrong password, not an expired session', async () => {
    const fetchMock = mockFetch(jsonResponse(401, { detail: 'wrong email or password' }))
    const error = await failure(api.login('a@b.c', 'nope'))
    expect(error.message).toBe('wrong email or password')
    expect(onUnauthorized).not.toHaveBeenCalled()
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
    expect(String(init.body)).toBe('username=a%40b.c&password=nope')
  })

  it('turns FastAPI validation errors into readable text', async () => {
    mockFetch(jsonResponse(422, { detail: [
      { loc: ['body', 'date_of_birth'], msg: 'Input should be a valid date', type: 'date_parsing' },
      { loc: ['body', 'full_name'], msg: 'String should have at least 2 characters', type: 'string_too_short' },
    ] }))
    const error = await failure(api.myApplication('app-1'))
    expect(error.status).toBe(422)
    expect(error.message).toBe('date_of_birth: Input should be a valid date; full_name: String should have at least 2 characters')
  })

  it('passes on the API detail of a 409', async () => {
    mockFetch(jsonResponse(409, { detail: 'only a case awaiting an officer (status DECIDED) can be approved or rejected' }))
    const error = await failure(api.officerDecision('app-1', 'reject', 'Edited surname'))
    expect(error.status).toBe(409)
    expect(error.message).toBe('only a case awaiting an officer (status DECIDED) can be approved or rejected')
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('gives a friendly message for errors without a JSON body', async () => {
    mockFetch(new Response('<html>Bad gateway</html>', { status: 502 }))
    expect((await failure(api.myApplications())).message).toMatch(/temporarily unavailable/)
    mockFetch(new Response('', { status: 415 }))
    expect((await failure(api.myApplications())).message).toMatch(/JPEG or PNG/)
  })

  it('reports an unreachable server as status 0', async () => {
    mockFetch({ reject: new TypeError('Failed to fetch') })
    const error = await failure(api.myApplications())
    expect(error.status).toBe(0)
    expect(error.message).toMatch(/Cannot reach the server/)
  })

  it('lets a cancelled request end quietly (AbortError, not ApiError)', async () => {
    mockFetch({ reject: new DOMException('The operation was aborted.', 'AbortError') })
    await expect(api.myApplications()).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('puts the token in the SSE URL (EventSource cannot send headers)', () => {
    token = 'a.b/c'
    expect(applicationEventsUrl('app-1')).toBe(`${API_URL}/applications/app-1/events?token=a.b%2Fc`)
  })

  it('follows an application over Server-Sent Events and reports a stream that gave up', () => {
    const sources: { url: string; closed: boolean; readyState: number; onopen?: () => void; onerror?: () => void;
      listeners: Record<string, (event: MessageEvent<string>) => void> }[] = []
    class FakeEventSource {
      static CLOSED = 2
      url: string; closed = false; readyState = 1; onopen?: () => void; onerror?: () => void
      listeners: Record<string, (event: MessageEvent<string>) => void> = {}
      constructor(url: string) { this.url = url; sources.push(this) }
      addEventListener(name: string, listener: (event: MessageEvent<string>) => void) { this.listeners[name] = listener }
      close() { this.closed = true }
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const handlers = { onOpen: vi.fn(), onStatus: vi.fn(), onLost: vi.fn() }
    const stop = api.watchApplication('app-1', handlers)
    const source = sources[0]
    expect(source.url).toBe(applicationEventsUrl('app-1'))
    source.onopen?.()
    source.listeners.status(new MessageEvent('status', { data: JSON.stringify({ status: 'PROCESSING' }) }))
    expect(handlers.onOpen).toHaveBeenCalledOnce()
    expect(handlers.onStatus).toHaveBeenCalledWith({ status: 'PROCESSING' })
    source.onerror?.() // still connecting: EventSource retries by itself
    expect(handlers.onLost).not.toHaveBeenCalled()
    source.readyState = FakeEventSource.CLOSED
    source.onerror?.()
    expect(handlers.onLost).toHaveBeenCalledOnce()
    stop()
    expect(source.closed).toBe(true)
  })

  it('submits the application as multipart form data', async () => {
    const fetchMock = mockFetch(jsonResponse(202, { application_id: 'app-1', status: 'SUBMITTED', status_url: '', events_url: '' }))
    const idImage = new File([new Uint8Array([1, 2, 3])], 'passport.png', { type: 'image/png' })
    const selfie = new Blob([new Uint8Array([4, 5])], { type: 'image/jpeg' })
    await api.submitApplication({ fullName: 'Maria Lopez', dateOfBirth: '1990-02-03', idImage, selfie })
    const form = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData
    expect(form.get('full_name')).toBe('Maria Lopez')
    expect(form.get('date_of_birth')).toBe('1990-02-03')
    expect((form.get('id_image') as File).name).toBe('passport.png')
    expect((form.get('selfie') as File).name).toBe('selfie.jpg')
  })
})
