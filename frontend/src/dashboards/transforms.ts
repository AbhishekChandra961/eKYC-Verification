// The dashboards' numbers (Phase 12): pure functions from the snapshot rows to what each chart and tile shows.
// They follow the rules of the pre-computed CSV columns (dashboard/TABLEAU_GUIDE.md, Quick path):
//   - `applications` is 1 per application, so its sum counts applications;
//   - a (0/1) column's average is a rate among the cases it applies to (null = does not apply, skipped);
//   - risk_fraud has a row per reason: case-level numbers come from caseRows() only (no double counting).
import type { ModelRow, OperationsRow, RiskFraudRow } from './snapshot'

export type Value = number | null

// ---------- statistics ----------

export function sum(values: Value[]): number {
  return values.reduce<number>((total, v) => total + (v ?? 0), 0)
}

/** Mean of the non-empty values (null when there is none): the rate of a (0/1) column. */
export function mean(values: Value[]): number | null {
  const present = values.filter((v): v is number => v !== null)
  return present.length ? sum(present) / present.length : null
}

/** Quantile q (0-1) of the non-empty values, linear between the closest ranks: the default of numpy and pandas
 *  (and Excel's PERCENTILE.INC), so the median equals the one in reports/. */
export function quantile(values: Value[], q: number): number | null {
  const sorted = values.filter((v): v is number => v !== null).sort((a, b) => a - b)
  if (!sorted.length) return null
  const position = (sorted.length - 1) * q
  const below = Math.floor(position)
  const above = Math.min(below + 1, sorted.length - 1)
  return sorted[below] + (sorted[above] - sorted[below]) * (position - below)
}

export const median = (values: Value[]) => quantile(values, 0.5)

/** A share as a whole fraction: hits of total, and the rate (null when total is 0). */
export interface Share { hits: number; total: number; rate: number | null }

function share(flags: Value[]): Share {
  const present = flags.filter((v): v is number => v !== null)
  return { hits: sum(present), total: present.length, rate: mean(present) }
}

// ---------- filters (one row above the charts; they apply to every chart of the tab) ----------

export interface Filters { docType: string | null; outcome: string | null } // null = all

export const NO_FILTERS: Filters = { docType: null, outcome: null }

export function applyFilters<T extends { docType: string; outcome: string }>(rows: T[], filters: Filters): T[] {
  return rows.filter((r) => (filters.docType === null || r.docType === filters.docType) &&
    (filters.outcome === null || r.outcome === filters.outcome))
}

/** The distinct values of a column, sorted, for a filter's options. */
export function optionsOf<T>(rows: T[], pick: (row: T) => string): string[] {
  return [...new Set(rows.map(pick))].sort((a, b) => a.localeCompare(b))
}

// ---------- Operations ----------

export const SYSTEM_OUTCOMES = ['Auto-approved', 'Manual review', 'Resubmit required'] as const

export interface OperationsKpis {
  applications: number
  autoApproval: Share
  manualReview: Share
  resubmit: Share
  medianTimeToDecisionS: number | null
  waiting: number
  oldestWaitingMin: number | null
}

export function operationsKpis(rows: OperationsRow[]): OperationsKpis {
  const queue = rows.map((r) => r.queueAgeMin).filter((v): v is number => v !== null)
  return {
    applications: sum(rows.map((r) => r.applications)),
    autoApproval: share(rows.map((r) => r.autoApproved)),
    manualReview: share(rows.map((r) => r.manualReview)),
    resubmit: share(rows.map((r) => r.resubmitRequired)),
    medianTimeToDecisionS: median(rows.map((r) => r.timeToDecisionS)),
    waiting: sum(rows.map((r) => r.waitingForOfficer)),
    oldestWaitingMin: queue.length ? Math.max(...queue) : null,
  }
}

export function funnel(rows: OperationsRow[], stages: string[]): { stage: string; applications: number }[] {
  const columns = ['funnel1', 'funnel2', 'funnel3', 'funnel4', 'funnel5'] as const
  return columns.map((column, i) => ({ stage: stages[i], applications: sum(rows.map((r) => r[column])) }))
}

export type OutcomeCounts = Record<(typeof SYSTEM_OUTCOMES)[number], number>

/** System outcome per document type, the busiest document type first. */
export function outcomesByDocType(rows: OperationsRow[]): ({ docType: string; total: number } & OutcomeCounts)[] {
  const byType = new Map<string, OutcomeCounts>()
  for (const row of rows) {
    const counts = byType.get(row.docType) ?? { 'Auto-approved': 0, 'Manual review': 0, 'Resubmit required': 0 }
    if (!(row.systemOutcome in counts)) throw new Error(`unknown system outcome ${row.systemOutcome}`)
    counts[row.systemOutcome as keyof OutcomeCounts] += row.applications
    byType.set(row.docType, counts)
  }
  return [...byType.entries()]
    .map(([docType, counts]) => ({ docType, total: sum(Object.values(counts)), ...counts }))
    .sort((a, b) => b.total - a.total || a.docType.localeCompare(b.docType))
}

export const CHECKS = [
  { key: 'docCheckS', label: 'Document type' },
  { key: 'faceCheckS', label: 'Face match' },
  { key: 'forgeryCheckS', label: 'Forgery' },
  { key: 'extractionCheckS', label: 'Field extraction' },
] as const

/** Worker processing time per check: median and 95th percentile (seconds), over the cases where it ran. */
export function latencyByCheck(rows: OperationsRow[]): { check: string; medianS: number | null; p95S: number | null; runs: number }[] {
  return CHECKS.map(({ key, label }) => {
    const values = rows.map((r) => r[key])
    return { check: label, medianS: median(values), p95S: quantile(values, 0.95), runs: values.filter((v) => v !== null).length }
  })
}

/** The cases waiting for an officer, the longest wait first. */
export function queueAge(rows: OperationsRow[]): { case: string; riskLevel: string; minutes: number }[] {
  return rows.filter((r) => r.waitingForOfficer === 1 && r.queueAgeMin !== null)
    .map((r) => ({ case: r.case, riskLevel: r.riskLevel, minutes: r.queueAgeMin as number }))
    .sort((a, b) => b.minutes - a.minutes || a.case.localeCompare(b.case))
}

// ---------- Risk & fraud ----------

/** THE NO-DOUBLE-COUNTING RULE. risk_fraud has one row per decision reason, and a case's own numbers sit on its
 *  first row only (applications = 1 there, null on its other rows). Every case-level chart uses these rows, so a
 *  case with three reasons still counts once. */
export function caseRows(rows: RiskFraudRow[]): RiskFraudRow[] {
  return rows.filter((r) => r.applications === 1)
}

export interface RiskKpis {
  fraudCaught: Share // frauds and mismatches NOT auto-approved, of all frauds and mismatches
  missedFrauds: number // frauds and mismatches auto-approved
  falseAlarms: Share // legitimate applications sent to manual review, of all legitimate ones
  flagConfirmed: Share // cases an officer decided where the officer rejected (confirmed the system's flag)
  officerAgreesWithTruth: Share // simulated officer: decides from the ground truth, so 100 % by construction
}

export function riskKpis(rows: RiskFraudRow[]): RiskKpis {
  const cases = caseRows(rows)
  return {
    fraudCaught: share(cases.map((r) => r.fraudCaught)),
    missedFrauds: sum(cases.map((r) => r.missedFraud)),
    falseAlarms: share(cases.map((r) => r.falseAlarm)),
    flagConfirmed: share(cases.map((r) => r.officerConfirmedFlag)),
    officerAgreesWithTruth: share(cases.map((r) => r.officerAgreesWithTruth)),
  }
}

/** In this order on the chart (it keeps colours that are hard to tell apart away from each other, see palette.ts). */
export const EFFECTS = ['Resubmit', 'High', 'Medium', 'Info only'] as const

/** How many cases have each reason (distinct cases), grouped by effect, the most frequent first within a group.
 *  A case with several reasons counts once for each of its reasons (and once only for any one reason). */
export function reasonFrequencies(rows: RiskFraudRow[], noReason: string): { reason: string; effect: string; raisedBy: string; cases: number }[] {
  const byReason = new Map<string, { effect: string; raisedBy: string; cases: Set<string> }>()
  for (const row of rows) {
    if (row.reason === noReason) continue
    const entry = byReason.get(row.reason) ?? { effect: row.reasonEffect ?? '', raisedBy: row.raisedBy ?? '', cases: new Set() }
    entry.cases.add(row.case)
    byReason.set(row.reason, entry)
  }
  const rank = (effect: string) => { const i = EFFECTS.indexOf(effect as (typeof EFFECTS)[number]); return i < 0 ? EFFECTS.length : i }
  return [...byReason.entries()]
    .map(([reason, e]) => ({ reason, effect: e.effect, raisedBy: e.raisedBy, cases: e.cases.size }))
    .sort((a, b) => rank(a.effect) - rank(b.effect) || b.cases - a.cases || a.reason.localeCompare(b.reason))
}

export const NO_RISK_SCORE = 'None (resubmit)' // risk level of the cases sent back for a new photo: not assessed

/** Applications per risk-score band (0-9, 10-19, ... 90-99, 100), case level. Cases sent back for a new photo have
 *  no risk assessment and are counted apart. */
export function riskScoreDistribution(rows: RiskFraudRow[]): { bands: { band: number; label: string; applications: number }[]; notScored: number } {
  const cases = caseRows(rows)
  const scored = cases.filter((r) => r.riskLevel !== NO_RISK_SCORE)
  const bands = Array.from({ length: 11 }, (_, i) => i * 10).map((band) => ({
    band,
    label: band === 100 ? '100' : `${band}–${band + 9}`,
    applications: scored.filter((r) => r.riskScoreBand === band).length,
  }))
  return { bands, notScored: cases.length - scored.length }
}

export const TRUTH_CLASSES = ['Fraud or mismatch', 'Legitimate', 'Unusable image'] as const

export interface ConfusionCell { truth: string; outcome: string; applications: number; verdict: string | null }

/** System decision (columns) vs ground truth (rows), with the verdict of each cell (Correct, Caught, False alarm,
 *  Missed...), from the case rows. */
export function confusionMatrix(rows: RiskFraudRow[]): { cells: ConfusionCell[]; rowTotals: Record<string, number>; columnTotals: Record<string, number>; total: number } {
  const cases = caseRows(rows)
  const cells = TRUTH_CLASSES.flatMap((truth) => SYSTEM_OUTCOMES.map((outcome) => {
    const inCell = cases.filter((r) => r.truthClass === truth && r.systemOutcome === outcome)
    return { truth, outcome, applications: inCell.length, verdict: inCell[0]?.systemVsTruth ?? null }
  }))
  const rowTotals = Object.fromEntries(TRUTH_CLASSES.map((t) => [t, cases.filter((r) => r.truthClass === t).length]))
  const columnTotals = Object.fromEntries(SYSTEM_OUTCOMES.map((o) => [o, cases.filter((r) => r.systemOutcome === o).length]))
  return { cells, rowTotals, columnTotals, total: cases.length }
}

/** Per system risk level: officer decisions that confirmed the flag (reject), overruled it (approve), and cases still
 *  waiting. Low risk is auto-approved and never reaches an officer, so only High and Medium are listed. */
export function officerAgreement(rows: RiskFraudRow[]): { riskLevel: string; confirmed: number; overruled: number; waiting: number }[] {
  const cases = caseRows(rows)
  return ['High', 'Medium'].map((riskLevel) => {
    const level = cases.filter((r) => r.riskLevel === riskLevel)
    return {
      riskLevel,
      confirmed: level.filter((r) => r.officerConfirmedFlag === 1).length,
      overruled: level.filter((r) => r.officerConfirmedFlag === 0).length,
      waiting: level.filter((r) => r.outcome === 'Awaiting officer').length,
    }
  })
}

// ---------- Model performance (offline evaluations, not the batch) ----------

function valueOf(rows: ModelRow[], match: Partial<ModelRow>): number | null {
  const found = rows.find((r) => Object.entries(match).every(([k, v]) => r[k as keyof ModelRow] === v))
  return found ? found.value : null
}

export const FORGERY_METRICS = [
  { metric: 'document PR-AUC', label: 'Document PR-AUC' },
  { metric: 'localisation (heat on the edit)', label: 'Heat on the edit' },
  { metric: 'position-matched control AUC (~0.5 = no cue)', label: 'Control AUC (0.5 = no hidden cue)' },
] as const

export interface ForgeryVersion {
  version: string
  order: number
  values: Record<(typeof FORGERY_METRICS)[number]['metric'], number | null>
}

/** Forgery v1 -> v2 -> v3 on the validation split (the shortcut story), in version order. */
export function forgeryStory(rows: ModelRow[]): ForgeryVersion[] {
  const story = rows.filter((r) => r.model === 'Forgery detector' && r.chart === 'Forgery story')
  const versions = [...new Map(story.map((r) => [r.version, r.versionOrder])).entries()].sort((a, b) => a[1] - b[1])
  return versions.map(([version, order]) => ({
    version,
    order,
    values: Object.fromEntries(FORGERY_METRICS.map(({ metric }) =>
      [metric, valueOf(story, { version, metric })])) as ForgeryVersion['values'],
  }))
}

/** The one test-split number of the accepted forgery model (used once). */
export function forgeryTestPrAuc(rows: ModelRow[]): number | null {
  return valueOf(rows, { model: 'Forgery detector', versionOrder: 3, split: 'test', metric: 'document PR-AUC' })
}

export const FACE_METRICS = [
  { metric: 'ROC-AUC', label: 'ROC-AUC' },
  { metric: 'TAR at FAR 1 %', label: 'True accepts at 1% FAR' },
  { metric: 'equal error rate', label: 'Equal error rate (↓ better)' },
] as const

/** Face verification on the LFW test split: the production model (SFace) vs the Siamese showcase. */
export function faceComparison(rows: ModelRow[]): { versions: string[]; metrics: { metric: string; label: string; values: (number | null)[] }[] } {
  const face = rows.filter((r) => r.model === 'Face verification' && r.chart === 'Face verification')
  const versions = [...new Map(face.map((r) => [r.version, r.versionOrder])).entries()]
    .sort((a, b) => b[1] - a[1]).map(([v]) => v) // production first
  return {
    versions,
    metrics: FACE_METRICS.map(({ metric, label }) => ({ metric, label, values: versions.map((version) => valueOf(face, { version, metric })) })),
  }
}

/** Share of different people accepted on synthetic ID portraits (why weak face scores go to manual review). */
export function faceSyntheticFalseAccepts(rows: ModelRow[]): number | null {
  return valueOf(rows, { model: 'Face verification', split: 'synthetic ID pairs', metric: 'share of different people accepted' })
}

/** Field extraction accuracy per field (test split): exact and normalized match, the best field first. */
export function extractionPerField(rows: ModelRow[]): { field: string; exact: number | null; normalized: number | null; documents: string }[] {
  const perField = rows.filter((r) => r.chart === 'Extraction per field' && r.field !== null)
  const fields = [...new Set(perField.map((r) => r.field as string))]
  return fields.map((field) => ({
    field,
    exact: valueOf(perField, { field, matchType: 'Exact' }),
    normalized: valueOf(perField, { field, matchType: 'Normalized' }),
    documents: perField.find((r) => r.field === field)?.note ?? '',
  })).sort((a, b) => (b.normalized ?? 0) - (a.normalized ?? 0) || (b.exact ?? 0) - (a.exact ?? 0))
}
