// The demo client (Phase 11): the same EkycApi interface as the HTTP client, backed by fixtures instead of a server.
// Honesty rules (README: Live demo):
//   - it never calls the network and never computes or invents a result: every status, score, reason, summary and
//     audit entry comes from a REAL pipeline run (scripts/export_demo_fixtures.py);
//   - a submission is accepted only if both images are bundled samples (recognised by their SHA-256) and the details
//     are the ones that real run used; anything else is refused with a clear message;
//   - a customer submission REPLAYS the recorded status events of that sample's real run, at their real relative
//     times, sped up so that a case finishes in about 10 s;
//   - officer approve/reject works in this browser tab only (memory, gone on reload) and is labelled as such.
import type {
  ApplicationView, AuditEntry, CaseDetail, CaseRow, EkycApi, NewApplication, OfficerAction, OfficerDecisionResult,
  StatusHandlers, SubmitResponse, Token,
} from '../api/client'
import { ApiError } from '../api/errors'
import { readSession, type Role } from '../auth/session'
import { DEMO_ACCOUNTS, REPLAY_TARGET_MS } from './config'
import type { DemoCase, DemoFixtures, DemoScenario, RecordedEvent } from './types'

interface DemoData {
  fixtures: DemoFixtures
  imageUrl: (file: string) => string
}

// The fixtures and images are a separate chunk, downloaded on first use (the login page does not need them).
let loading: Promise<DemoData> | null = null
export function loadDemoData(): Promise<DemoData> {
  loading ??= import('./data').then((m) => m.demoData)
  return loading
}

export const UPLOAD_REFUSED = 'Demo mode cannot check new photos: there is no server here, and results are never ' +
  'made up. Please choose one of the bundled samples.'
export const DETAILS_REFUSED = 'Demo mode replays the real run of this sample, which used the name and date of ' +
  'birth printed on its document. Choose the sample again to restore them.'
export const DEMO_DECISION_ACTOR = 'officer:demo-visitor (this browser tab only)'

// ------------------------------------------------------------------ customer replays

interface Replay {
  id: string
  scenario: string
  startedAt: number // epoch ms
}

// Kept in sessionStorage so a reload of the status page continues the replay; closing the tab forgets it.
const REPLAYS_KEY = 'securebank.ekyc.demo.replays'
let memoryReplays: Replay[] = []

function readReplays(): Replay[] {
  try {
    const raw = window.sessionStorage.getItem(REPLAYS_KEY)
    return raw ? (JSON.parse(raw) as Replay[]) : []
  } catch {
    return memoryReplays // storage blocked or corrupt: memory only
  }
}

function saveReplays(replays: Replay[]): void {
  memoryReplays = replays
  try {
    window.sessionStorage.setItem(REPLAYS_KEY, JSON.stringify(replays))
  } catch {
    // memory only
  }
}

/** How much faster than real time a scenario is replayed (1 = real time). */
export function replaySpeed(scenario: DemoScenario): number {
  const events = scenario.run.events
  const total = events.length ? events[events.length - 1].at_ms : 0
  return Math.max(1, total / REPLAY_TARGET_MS)
}

/** The customer view of a replay at `now`: the last recorded event that has happened by then, re-dated to the replay
 *  (the status, outcome, message, retake list and progress are exactly the recorded ones). */
export function viewAt(replay: Replay, scenario: DemoScenario, now: number): ApplicationView {
  return replayed(replay, scenario, scenario.run.events[currentIndex(replay, scenario, now)])
}

/** The index of the last recorded event that has happened by `now` (the first one until then). */
function currentIndex(replay: Replay, scenario: DemoScenario, now: number): number {
  const elapsed = (now - replay.startedAt) * replaySpeed(scenario) // in the real run's milliseconds
  let index = 0
  scenario.run.events.forEach((event, i) => { if (event.at_ms <= elapsed) index = i })
  return index
}

/** One recorded event as the replay shows it: its own view, with the replay's id and times. */
function replayed(replay: Replay, scenario: DemoScenario, event: RecordedEvent): ApplicationView {
  const iso = (ms: number) => new Date(ms).toISOString()
  return { ...event.view, application_id: replay.id, created_at: iso(replay.startedAt),
    updated_at: iso(replay.startedAt + event.at_ms / replaySpeed(scenario)) }
}

async function bytesOf(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer()
  return new Promise((resolve, reject) => { // older engines (and jsdom): FileReader
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.onerror = () => reject(reader.error ?? new Error('could not read the file'))
    reader.readAsArrayBuffer(blob)
  })
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await bytesOf(blob))
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

// ------------------------------------------------------------------ officer state (this tab only)

interface Decision {
  action: OfficerAction
  reason: string
  at: string
}
const decisions = new Map<string, Decision>() // gone on reload, by design

/** For tests: forget the officer decisions and the customer replays. */
export function resetDemoState(): void {
  decisions.clear()
  saveReplays([])
}

function withDecision(item: DemoCase, imageUrl: (file: string) => string): { row: CaseRow; detail: CaseDetail } {
  const row = structuredClone(item.row)
  const detail = structuredClone(item.detail)
  detail.images.document_url = imageUrl(item.detail.images.document_url)
  detail.images.selfie_url = imageUrl(item.detail.images.selfie_url)
  const decision = decisions.get(row.application_id)
  if (!decision) return { row, detail }
  const status = decision.action === 'approve' ? 'APPROVED' : 'REJECTED'
  const entry: AuditEntry = { application_id: row.application_id, actor: DEMO_DECISION_ACTOR, from_status: 'DECIDED',
    to_status: status, reason: decision.reason, at: decision.at }
  Object.assign(row, { status, updated_at: decision.at })
  Object.assign(detail.application, { status, updated_at: decision.at,
    officer_decision: { action: decision.action, reason: decision.reason, officer_id: 'demo-visitor', at: decision.at } })
  detail.audit_trail = [...detail.audit_trail, entry]
  return { row, detail }
}

// ------------------------------------------------------------------ the client

function requireRole(role: Role): void {
  const session = readSession()
  if (!session) throw new ApiError(401, 'Your session has expired. Please log in again.')
  if (session.role !== role) throw new ApiError(403, 'You do not have access to this page.')
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function scenarioOf(replay: Replay): Promise<DemoScenario> {
  const scenario = (await loadDemoData()).fixtures.scenarios.find((s) => s.id === replay.scenario)
  if (!scenario) throw new ApiError(404, 'application not found')
  return scenario
}

function findReplay(applicationId: string): Replay {
  const replay = readReplays().find((r) => r.id === applicationId)
  if (!replay) throw new ApiError(404, 'application not found')
  return replay
}

export const demoApi: EkycApi = {
  async login(email: string): Promise<Token> {
    const role = (Object.keys(DEMO_ACCOUNTS) as Role[]).find((r) => DEMO_ACCOUNTS[r] === email)
    if (!role) throw new ApiError(401, 'Demo mode: use the "Try as customer" or "Try as officer" button.')
    return { access_token: `demo-${role.toLowerCase()}`, token_type: 'bearer', role, expires_in: 8 * 3600 }
  },

  async submitApplication(input: NewApplication): Promise<SubmitResponse> {
    requireRole('CUSTOMER')
    const { fixtures } = await loadDemoData()
    const [document, selfie] = await Promise.all([sha256Hex(input.idImage), sha256Hex(input.selfie)])
    const scenario = fixtures.scenarios.find((s) => s.document.sha256 === document && s.selfie.sha256 === selfie)
    if (!scenario) throw new ApiError(422, UPLOAD_REFUSED)
    if (scenario.applicant.full_name !== input.fullName.trim() || scenario.applicant.date_of_birth !== input.dateOfBirth) {
      throw new ApiError(422, DETAILS_REFUSED)
    }
    await wait(Math.min(scenario.run.submit_ms / replaySpeed(scenario), 1500)) // the upload, sped up like the rest
    const replays = readReplays()
    const id = `${scenario.run.application_id}-replay-${replays.filter((r) => r.scenario === scenario.id).length + 1}`
    saveReplays([...replays, { id, scenario: scenario.id, startedAt: Date.now() }])
    return { application_id: id, status: 'SUBMITTED', status_url: `/applications/${id}`, events_url: `/applications/${id}/events` }
  },

  async myApplications(): Promise<ApplicationView[]> {
    requireRole('CUSTOMER')
    const now = Date.now()
    const views = await Promise.all(readReplays().map(async (r) => viewAt(r, await scenarioOf(r), now)))
    return views.sort((a, b) => b.created_at.localeCompare(a.created_at))
  },

  async myApplication(applicationId: string): Promise<ApplicationView> {
    requireRole('CUSTOMER')
    const replay = findReplay(applicationId)
    return viewAt(replay, await scenarioOf(replay), Date.now())
  },

  /** Plays the recorded status events that are still to come, at their (sped-up) real times. */
  watchApplication(applicationId: string, { onOpen, onStatus, onLost }: StatusHandlers): () => void {
    const timers: number[] = []
    let stopped = false
    const start = async () => {
      const replay = findReplay(applicationId)
      const scenario = await scenarioOf(replay)
      if (stopped) return
      onOpen()
      const now = Date.now()
      const current = currentIndex(replay, scenario, now)
      const events = scenario.run.events
      onStatus(replayed(replay, scenario, events[current])) // like the real stream: the current state first,
      for (const event of events.slice(current + 1)) { // then each later change at its (sped-up) time
        const due = replay.startedAt + event.at_ms / replaySpeed(scenario)
        timers.push(window.setTimeout(() => { if (!stopped) onStatus(replayed(replay, scenario, event)) }, due - now))
      }
    }
    start().catch(() => { if (!stopped) onLost() })
    return () => {
      stopped = true
      timers.forEach((t) => window.clearTimeout(t))
    }
  },

  async officerCases(filters): Promise<CaseRow[]> {
    requireRole('OFFICER')
    const { fixtures, imageUrl } = await loadDemoData()
    const rows = fixtures.cases.map((c) => withDecision(c, imageUrl).row)
      .filter((r) => (!filters.status || r.status === filters.status) && (!filters.outcome || r.outcome === filters.outcome))
    // the API's order: highest risk score first (cases without a score last), then oldest first
    return rows.sort((a, b) => (b.risk_score ?? -1) - (a.risk_score ?? -1) || a.created_at.localeCompare(b.created_at))
  },

  async officerCase(applicationId: string): Promise<CaseDetail> {
    requireRole('OFFICER')
    const { fixtures, imageUrl } = await loadDemoData()
    const item = fixtures.cases.find((c) => c.row.application_id === applicationId)
    if (!item) throw new ApiError(404, 'case not found')
    return withDecision(item, imageUrl).detail
  },

  async officerDecision(applicationId: string, action: OfficerAction, reason: string): Promise<OfficerDecisionResult> {
    requireRole('OFFICER')
    const { fixtures, imageUrl } = await loadDemoData()
    const item = fixtures.cases.find((c) => c.row.application_id === applicationId)
    if (!item) throw new ApiError(404, 'case not found')
    const text = reason.trim()
    if (text.length < 5 || text.length > 1000) throw new ApiError(422, 'reason: between 5 and 1000 characters')
    if (withDecision(item, imageUrl).row.status !== 'DECIDED') {
      throw new ApiError(409, 'only a case awaiting an officer (status DECIDED) can be approved or rejected')
    }
    decisions.set(applicationId, { action, reason: text, at: new Date().toISOString() })
    const { row, detail } = withDecision(item, imageUrl)
    return { application_id: applicationId, status: row.status, audit_trail: detail.audit_trail }
  },
}

// ------------------------------------------------------------------ for the demo pages (not part of EkycApi)

export interface DemoSample {
  id: string
  title: string
  description: string
  applicant: { full_name: string; date_of_birth: string }
  documentUrl: string
  selfieUrl: string
}

/** The bundled samples a visitor can submit as the customer. */
export async function demoSamples(): Promise<DemoSample[]> {
  const { fixtures, imageUrl } = await loadDemoData()
  return fixtures.scenarios.map((s) => ({ id: s.id, title: s.title, description: s.description, applicant: s.applicant,
    documentUrl: imageUrl(s.document.file), selfieUrl: imageUrl(s.selfie.file) }))
}

/** When the fixtures were recorded (the officer data was read from the real system). On the demo site this is "now"
 *  for relative times such as the queue's Waiting column, so they show what they were at the time of recording
 *  instead of growing with today's date. */
export async function demoRecordedAt(): Promise<number> {
  return Date.parse((await loadDemoData()).fixtures.generated_at)
}

export interface ReplayInfo {
  realApplicationId: string
  recordedAt: string
  realSeconds: number
  speed: number
}

/** What the status page says about a replay: which real run it is, and how much it is sped up. */
export async function describeReplay(applicationId: string): Promise<ReplayInfo | null> {
  const replay = readReplays().find((r) => r.id === applicationId)
  if (!replay) return null
  const scenario = await scenarioOf(replay)
  const events = scenario.run.events
  return { realApplicationId: scenario.run.application_id, recordedAt: scenario.run.recorded_at,
    realSeconds: events.length ? events[events.length - 1].at_ms / 1000 : 0, speed: replaySpeed(scenario) }
}
