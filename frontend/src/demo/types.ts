// The shape of the demo fixtures (fixtures/fixtures.gen.ts, written by scripts/export_demo_fixtures.py). Every
// view, row and case detail is typed with the real API types, so a fixture that no longer matches the API fails the
// type check.
import type { ApplicationView, CaseDetail, CaseRow } from '../api/client'

export interface DemoImage {
  file: string // a file in fixtures/images/
  sha256: string // of that file: how the demo client recognises a bundled sample (anything else is refused)
}

/** One status event of the real run, as the API streamed it, with its time since the upload started. */
export interface RecordedEvent {
  at_ms: number
  view: ApplicationView
}

/** A demo sample a visitor can submit as the customer, with the real run it replays. */
export interface DemoScenario {
  id: string // genuine_1 ... blank (demo_samples/ names)
  title: string
  description: string
  applicant: { full_name: string; date_of_birth: string }
  document: DemoImage
  selfie: DemoImage
  run: {
    application_id: string // the real application the replay comes from
    recorded_at: string
    submit_ms: number // how long the upload took
    events: RecordedEvent[]
  }
}

/** A case in the officer portal: the queue row and the case detail exactly as the real API returned them (the image
 *  links are bundled file names). */
export interface DemoCase {
  source: 'demo_sample' | 'batch' // one of the six demo samples, or a Phase 9 batch application
  label: string // the demo sample name, or the batch scenario
  row: CaseRow
  detail: CaseDetail
}

export interface DemoFixtures {
  generated_at: string
  source: string
  scenarios: DemoScenario[]
  cases: DemoCase[]
}
