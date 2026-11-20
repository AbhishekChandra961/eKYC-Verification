// The demo client (Phase 11): it never calls the network, refuses anything but the bundled samples, replays the
// recorded runs in order and on time, and keeps officer decisions in this tab only.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplicationView } from '../api/client'
import { waitingMs } from '../officer/queue'
import { ApiError } from '../api/errors'
import { resetSessionCache, writeSession, type Role } from '../auth/session'
import {
  DEMO_DECISION_ACTOR, DETAILS_REFUSED, UPLOAD_REFUSED, demoApi, demoRecordedAt, demoSamples, describeReplay, replaySpeed,
  resetDemoState, sha256Hex,
} from './client'
import { REPLAY_TARGET_MS } from './config'
import fixtures from './fixtures/fixtures.gen'
import type { DemoScenario } from './types'

const FINAL = ['DECIDED', 'APPROVED', 'REJECTED', 'RESUBMIT_REQUESTED']
// the bundled images, as data URLs (no file system or network needed)
const images = import.meta.glob<string>('./fixtures/images/*.jpg', { query: '?inline', import: 'default', eager: true })

function image(file: string): Blob {
  const dataUrl = images[`./fixtures/images/${file}`]
  if (!dataUrl) throw new Error(`image not bundled: ${file}`)
  const bytes = Uint8Array.from(atob(dataUrl.split(',')[1]), (c) => c.charCodeAt(0))
  return new Blob([bytes], { type: 'image/jpeg' })
}

function scenario(id: string): DemoScenario {
  const found = fixtures.scenarios.find((s) => s.id === id)
  if (!found) throw new Error(`no scenario ${id}`)
  return found
}

function submission(s: DemoScenario) {
  return { fullName: s.applicant.full_name, dateOfBirth: s.applicant.date_of_birth,
    idImage: image(s.document.file), selfie: image(s.selfie.file) }
}

async function loginAs(role: Role) {
  const token = await demoApi.login(role === 'CUSTOMER' ? 'customer@demo.securebank' : 'officer@demo.securebank', '')
  writeSession({ token: token.access_token, role: token.role, email: `${role}@demo`, expiresAt: Date.now() + 3_600_000 })
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

/** Every way a page could reach a server: each one fails the test if it is used. */
function forbidNetwork() {
  const calls: string[] = []
  const deny = (name: string) => vi.fn(() => { calls.push(name); throw new Error(`${name} must not be used in demo mode`) })
  vi.stubGlobal('fetch', deny('fetch'))
  vi.stubGlobal('EventSource', deny('EventSource'))
  vi.stubGlobal('XMLHttpRequest', deny('XMLHttpRequest'))
  vi.stubGlobal('WebSocket', deny('WebSocket'))
  return calls
}

beforeEach(() => {
  resetSessionCache()
  resetDemoState()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('demo client', () => {
  it('never calls the network: login, submit, live status, queue, case, decision', async () => {
    const calls = forbidNetwork()
    await loginAs('CUSTOMER')
    expect(await demoSamples()).toHaveLength(fixtures.scenarios.length)
    const created = await demoApi.submitApplication(submission(scenario('genuine_2')))
    const seen: ApplicationView[] = []
    const stop = demoApi.watchApplication(created.application_id, {
      onOpen: () => undefined, onStatus: (v) => seen.push(v), onLost: () => { throw new Error('lost') } })
    await vi.waitFor(() => expect(seen.length).toBeGreaterThan(0))
    stop()
    await demoApi.myApplication(created.application_id)
    await demoApi.myApplications()

    resetSessionCache()
    await loginAs('OFFICER')
    const rows = await demoApi.officerCases({ status: 'DECIDED' })
    await demoApi.officerCase(rows[0].application_id)
    await demoApi.officerDecision(rows[0].application_id, 'reject', 'Checked the heatmap and the MRZ by hand.')
    expect(calls).toEqual([])
  })

  it('refuses uploads that are not a bundled sample, with a clear message', async () => {
    forbidNetwork()
    await loginAs('CUSTOMER')
    const own = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], { type: 'image/jpeg' })
    const genuine = scenario('genuine_1')
    let error = await failure(demoApi.submitApplication({ ...submission(genuine), idImage: own }))
    expect(error.status).toBe(422)
    expect(error.message).toBe(UPLOAD_REFUSED)
    error = await failure(demoApi.submitApplication({ ...submission(genuine), selfie: own }))
    expect(error.message).toBe(UPLOAD_REFUSED)
    // the right images with other details: the real run used the document's own details, so this is refused too
    error = await failure(demoApi.submitApplication({ ...submission(genuine), dateOfBirth: '1990-01-01' }))
    expect(error.message).toBe(DETAILS_REFUSED)
    expect(await demoApi.myApplications()).toEqual([])
  })

  it('replays the recorded status events in order, sped up to about 10 s', async () => {
    await loginAs('CUSTOMER')
    const s = scenario('forged_1')
    const created = await demoApi.submitApplication(submission(s)) // real timers: jsdom reads files with timers
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] }) // then a fake clock, starting now
    const seen: ApplicationView[] = []
    demoApi.watchApplication(created.application_id, { onOpen: () => undefined, onStatus: (v) => seen.push(v), onLost: () => undefined })
    await vi.advanceTimersByTimeAsync(REPLAY_TARGET_MS + 500)

    const recorded = s.run.events.map((e) => [e.view.status, e.view.outcome, e.view.progress.completed])
    const replayed = seen.map((v) => [v.status, v.outcome, v.progress.completed])
    expect(replayed).toEqual(recorded) // exactly the recorded events, in order, each once
    expect(FINAL).toContain(seen[seen.length - 1].status)
    expect(seen.every((v) => v.application_id === created.application_id)).toBe(true)
    expect(replaySpeed(s)).toBeCloseTo(s.run.events[s.run.events.length - 1].at_ms / REPLAY_TARGET_MS)
    expect((await describeReplay(created.application_id))?.realApplicationId).toBe(s.run.application_id)
  })

  it('a very short run is replayed in real time, never slowed down', () => {
    expect(replaySpeed(scenario('blank'))).toBe(1)
  })

  it('checks roles like the API: a customer cannot open the officer queue, an officer cannot submit', async () => {
    await loginAs('CUSTOMER')
    expect((await failure(demoApi.officerCases({}))).status).toBe(403)
    resetSessionCache()
    await loginAs('OFFICER')
    expect((await failure(demoApi.submitApplication(submission(scenario('blank'))))).status).toBe(403)
    expect((await failure(demoApi.login('someone@example.com', 'x'))).status).toBe(401)
  })

  it('officer decisions: only cases awaiting an officer, audited as this-tab-only, gone after a reload', async () => {
    await loginAs('OFFICER')
    const waiting = await demoApi.officerCases({ status: 'DECIDED' })
    const id = waiting[0].application_id
    const result = await demoApi.officerDecision(id, 'approve', 'False alarm: checked the fields by hand.')
    expect(result.status).toBe('APPROVED')
    expect(result.audit_trail.at(-1)).toMatchObject({ actor: DEMO_DECISION_ACTOR, from_status: 'DECIDED', to_status: 'APPROVED' })
    expect((await demoApi.officerCase(id)).application.status).toBe('APPROVED')
    expect((await failure(demoApi.officerDecision(id, 'reject', 'Changed my mind.'))).status).toBe(409)
    expect((await failure(demoApi.officerDecision(id, 'reject', 'no'))).status).toBe(422)
    expect((await failure(demoApi.officerCase('app-unknown'))).status).toBe(404)

    vi.resetModules() // a page reload: the module starts again with no decisions
    const reloaded = await import('./client')
    expect((await reloaded.demoApi.officerCase(id)).application.status).toBe('DECIDED')
  })

  it('relative times are measured at the time of recording, so they do not grow with today\'s date', async () => {
    await loginAs('OFFICER')
    const recordedAt = await demoRecordedAt()
    expect(recordedAt).toBe(Date.parse(fixtures.generated_at))
    const rows = await demoApi.officerCases({})
    for (const row of rows) expect(Date.parse(row.created_at)).toBeLessThanOrEqual(recordedAt) // recorded after every case
    const before = rows.map((row) => waitingMs(row, recordedAt))
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2031-06-01T00:00:00Z')) // years later
    expect(await demoRecordedAt()).toBe(recordedAt)
    expect(rows.map((row) => waitingMs(row, recordedAt))).toEqual(before)
    const forged = rows.find((row) => row.application_id === scenario('forged_1').run.application_id)
    expect(forged && waitingMs(forged, recordedAt)).toBeLessThan(24 * 3600 * 1000) // exported the same day
  })

  it('the queue is sorted like the API: highest risk score first', async () => {
    await loginAs('OFFICER')
    const scores = (await demoApi.officerCases({})).map((r) => r.risk_score ?? -1)
    expect(scores).toEqual([...scores].sort((a, b) => b - a))
  })
})

describe('demo fixtures (exported from real runs)', () => {
  const customerFields = ['application_id', 'created_at', 'message', 'outcome', 'progress', 'retake', 'status', 'updated_at']

  it('six samples: 3 genuine, 2 forged, 1 blank, each ending where the real run ended', () => {
    expect(fixtures.scenarios.map((s) => s.id).sort()).toEqual(['blank', 'forged_1', 'forged_2', 'genuine_1', 'genuine_2', 'genuine_3'])
    for (const s of fixtures.scenarios) {
      const last = s.run.events[s.run.events.length - 1].view
      expect(FINAL).toContain(last.status)
      const officerCase = fixtures.cases.find((c) => c.row.application_id === s.run.application_id)
      expect(officerCase?.detail.application.status).toBe(last.status) // the same real application, both portals
      expect(s.run.events.map((e) => e.at_ms)).toEqual([...s.run.events.map((e) => e.at_ms)].sort((a, b) => a - b))
    }
  })

  it('customer views carry only customer-safe fields (no scores or reasons)', () => {
    for (const s of fixtures.scenarios) {
      for (const e of s.run.events) expect(Object.keys(e.view).sort()).toEqual(customerFields)
    }
  })

  it('every image is bundled, matches its checksum, and no server link is left', async () => {
    for (const s of fixtures.scenarios) {
      for (const img of [s.document, s.selfie]) expect(await sha256Hex(image(img.file))).toBe(img.sha256)
    }
    for (const c of fixtures.cases) {
      for (const file of [c.detail.images.document_url, c.detail.images.selfie_url]) {
        expect(file).toMatch(/^[0-9a-f]{16}\.jpg$/)
        expect(images[`./fixtures/images/${file}`]).toBeDefined()
      }
    }
    expect(JSON.stringify(fixtures)).not.toMatch(/https?:\/\/|X-Amz-/)
  })
})
