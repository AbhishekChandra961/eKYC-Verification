// Human-readable names for the codes the API returns (officer portal).
import type { ApplicationStatus, Outcome, RiskLevel } from '../api/client'

export type Tone = 'good' | 'warning' | 'critical' | 'info' | 'neutral'

export const DOC_TYPES: Record<string, string> = {
  alb_id: 'Albanian ID card',
  aze_passport: 'Azerbaijani passport',
  esp_id: 'Spanish ID card',
  est_id: 'Estonian ID card',
  fin_id: 'Finnish ID card',
  grc_passport: 'Greek passport',
  lva_passport: 'Latvian passport',
  rus_internalpassport: 'Russian internal passport',
  srb_passport: 'Serbian passport',
  svk_id: 'Slovak ID card',
}

export function docTypeLabel(code: string | null | undefined): string {
  return code ? (DOC_TYPES[code] ?? code) : '–'
}

// Phase 9 lifecycle: DECIDED means "waiting for an officer" (manual review only). An auto-approval is closed as
// APPROVED by the system, a retake request as RESUBMIT_REQUESTED.
export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  SUBMITTED: 'Submitted',
  PROCESSING: 'Processing',
  DECIDED: 'Awaiting officer',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  RESUBMIT_REQUESTED: 'Retake requested',
}

/** The statuses in which someone still has to act (the checks are running, or an officer must decide). */
export const OPEN_STATUSES: ReadonlySet<ApplicationStatus> = new Set(['SUBMITTED', 'PROCESSING', 'DECIDED'])

/** An APPROVED case was approved either by the system (auto) or by an officer after a manual review. */
export function statusLabel(status: ApplicationStatus, outcome: Outcome | null | undefined): string {
  if (status === 'APPROVED') return outcome === 'AUTO_APPROVED' ? 'Auto-approved' : 'Approved by officer'
  return STATUS_LABELS[status]
}

export const OUTCOME_LABELS: Record<Outcome, string> = {
  AUTO_APPROVED: 'Auto-approved',
  MANUAL_REVIEW: 'Manual review',
  RESUBMIT_REQUIRED: 'Resubmit required',
}

export const RISK: Record<RiskLevel, { label: string; tone: Tone }> = {
  low: { label: 'Low risk', tone: 'good' },
  medium: { label: 'Medium risk', tone: 'warning' },
  high: { label: 'High risk', tone: 'critical' },
}

export const FACE_BANDS: Record<string, { label: string; tone: Tone }> = {
  match: { label: 'Match', tone: 'good' },
  needs_review: { label: 'Uncertain: review', tone: 'warning' },
  mismatch: { label: 'Mismatch', tone: 'critical' },
  no_face_found: { label: 'No face found', tone: 'warning' },
}

export const FORGERY_BANDS: Record<string, { label: string; tone: Tone }> = {
  pass: { label: 'Pass', tone: 'good' },
  needs_review: { label: 'Needs review', tone: 'warning' },
  forgery_suspected: { label: 'Forgery suspected', tone: 'critical' },
}

export const EFFECTS: Record<string, { label: string; tone: Tone }> = {
  high: { label: 'High', tone: 'critical' },
  medium: { label: 'Medium', tone: 'warning' },
  resubmit: { label: 'Retake', tone: 'info' },
  info: { label: 'Info', tone: 'neutral' },
}

export const CHECK_STATUS: Record<string, { label: string; tone: Tone }> = {
  ok: { label: 'Completed', tone: 'good' },
  failed: { label: 'Failed', tone: 'critical' },
  timed_out: { label: 'Timed out', tone: 'warning' },
  skipped: { label: 'Skipped', tone: 'neutral' },
}

export const RULE_SEVERITY: Record<string, { label: string; tone: Tone }> = {
  strong: { label: 'Reliable rule', tone: 'critical' },
  review: { label: 'Review', tone: 'warning' },
}

export const RULE_LABELS: Record<string, string> = {
  mrz_check_document_number: 'MRZ check digit: document number',
  mrz_check_birth_date: 'MRZ check digit: date of birth',
  mrz_check_expiry_date: 'MRZ check digit: expiry date',
  mrz_check_composite: 'MRZ composite check digit',
  mrz_vs_document_number: 'MRZ vs printed document number',
  mrz_vs_expiry_date: 'MRZ vs printed expiry date',
  date_order: 'Date order (birth, issue, expiry)',
  mrz_format: 'MRZ format',
  mrz_vs_surname: 'MRZ vs printed surname',
  mrz_vs_given_names: 'MRZ vs printed given names',
  mrz_vs_birth_date: 'MRZ vs printed date of birth',
  dates_parseable: 'Dates readable',
}

/** Which extracted fields a failed rule points at (to highlight them in the field table). */
export const RULE_FIELDS: Record<string, string[]> = {
  mrz_check_document_number: ['document_number', 'mrz_line0', 'mrz_line1'],
  mrz_check_birth_date: ['birth_date', 'mrz_line1'],
  mrz_check_expiry_date: ['expiry_date', 'mrz_line1'],
  mrz_check_composite: ['mrz_line1'],
  mrz_vs_document_number: ['document_number'],
  mrz_vs_expiry_date: ['expiry_date'],
  date_order: ['birth_date', 'issue_date', 'expiry_date'],
  mrz_format: ['mrz_line0', 'mrz_line1'],
  mrz_vs_surname: ['surname'],
  mrz_vs_given_names: ['given_names'],
  mrz_vs_birth_date: ['birth_date'],
  dates_parseable: ['birth_date', 'issue_date', 'expiry_date'],
}

export const FIELD_LABELS: Record<string, string> = {
  surname: 'Surname',
  given_names: 'Given names',
  birth_date: 'Date of birth',
  gender: 'Sex',
  nationality: 'Nationality',
  document_number: 'Document number',
  personal_number: 'Personal number',
  issue_date: 'Date of issue',
  expiry_date: 'Date of expiry',
  birth_place: 'Place of birth',
  authority: 'Issuing authority',
  mrz_line0: 'MRZ line 1',
  mrz_line1: 'MRZ line 2',
}

export function ruleLabel(rule: string): string {
  return RULE_LABELS[rule] ?? rule.replaceAll('_', ' ')
}

export function actorLabel(actor: string): string {
  const [kind, id] = actor.split(':')
  if (kind === 'system') return `System (${id ?? 'orchestrator'})`
  if (kind === 'officer') return `Officer ${id ?? ''}`.trim()
  if (kind === 'customer') return `Customer ${id ?? ''}`.trim()
  return actor
}
