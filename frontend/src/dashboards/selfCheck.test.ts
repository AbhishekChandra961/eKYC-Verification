// SELF-CHECK (Phase 12): the dashboards' numbers, computed from the bundled snapshot by the same transforms the
// charts use, must equal the Phase 9 batch report (reports/phase9/batch_summary.md / .json) exactly.
import { describe, expect, it } from 'vitest'
import { percent } from './format'
import { snapshot } from './snapshot'
import { caseRows, confusionMatrix, funnel, operationsKpis, riskKpis, riskScoreDistribution } from './transforms'

// the report itself, read at test time (a glob, so that a build without the reports/ folder still typechecks)
const reports = import.meta.glob('../../../reports/phase9/batch_summary.json', { eager: true, import: 'default' })
const summary = Object.values(reports)[0] as {
  metrics: Record<string, number | string>
  outcome_mix: Record<string, number>
  status_mix: Record<string, number>
  confusion: Record<string, Record<string, number>>
}

describe('dashboard numbers match reports/phase9/batch_summary', () => {
  const ops = operationsKpis(snapshot.operations)
  const risk = riskKpis(snapshot.riskFraud)

  it('Operations KPIs: 150 applications, auto-approval 32.7 %, manual review 62.7 %, resubmit 4.7 %', () => {
    expect(ops.applications).toBe(150)
    expect(percent(ops.autoApproval.rate)).toBe('32.7%')
    expect(percent(ops.manualReview.rate)).toBe('62.7%')
    expect(percent(ops.resubmit.rate)).toBe('4.7%')
    expect([ops.autoApproval.hits, ops.manualReview.hits, ops.resubmit.hits]).toEqual([49, 94, 7])
    expect(ops.waiting).toBe(28)
  })

  it('Risk & fraud KPIs: 67 of 68 frauds caught, 1 missed, 27 false alarms', () => {
    expect([risk.fraudCaught.hits, risk.fraudCaught.total]).toEqual([67, 68])
    expect(risk.missedFrauds).toBe(1)
    expect([risk.falseAlarms.hits, risk.falseAlarms.total]).toEqual([27, 75])
  })

  it('the report file is there, and every number above equals it', () => {
    expect(Object.keys(reports)).toHaveLength(1) // reports/phase9/batch_summary.json found
    const m = summary.metrics
    expect(ops.applications).toBe(m.applications)
    expect(`${risk.fraudCaught.hits}/${risk.fraudCaught.total}`).toBe(m['fraud_caught (not auto-approved)'])
    expect(risk.missedFrauds).toBe(m['fraud_missed (auto-approved)'])
    expect(risk.falseAlarms.hits).toBe(m['false_alarms (legitimate -> manual review)'])
    expect(ops.waiting).toBe(m.still_awaiting_officer)
    expect(risk.flagConfirmed.total).toBe(m.officer_decided)
    expect(risk.flagConfirmed.hits).toBe(m.officer_rejected)
    expect({ AUTO_APPROVED: ops.autoApproval.hits, MANUAL_REVIEW: ops.manualReview.hits,
      RESUBMIT_REQUIRED: ops.resubmit.hits }).toEqual(summary.outcome_mix)
  })

  it('the funnel and the confusion matrix equal the report', () => {
    const stages = funnel(snapshot.operations, snapshot.funnelStages).map((s) => s.applications)
    expect(stages).toEqual([150, 150, summary.outcome_mix.MANUAL_REVIEW, summary.metrics.officer_decided, summary.metrics.officer_rejected])
    const m = confusionMatrix(snapshot.riskFraud)
    const codes = { 'Auto-approved': 'AUTO_APPROVED', 'Manual review': 'MANUAL_REVIEW', 'Resubmit required': 'RESUBMIT_REQUIRED' } as const
    const truth = { 'Fraud or mismatch': 'fraud_or_mismatch', Legitimate: 'legitimate', 'Unusable image': 'unusable' } as const
    for (const cell of m.cells) {
      expect(cell.applications).toBe(summary.confusion[codes[cell.outcome as keyof typeof codes]][truth[cell.truth as keyof typeof truth]])
    }
  })

  it('risk_fraud: one case row per application, so the risk-score histogram sums to the batch', () => {
    const cases = caseRows(snapshot.riskFraud)
    expect(snapshot.riskFraud.length).toBeGreaterThan(150) // a row per reason
    expect(cases).toHaveLength(150)
    expect(new Set(cases.map((r) => r.case)).size).toBe(150)
    const { bands, notScored } = riskScoreDistribution(snapshot.riskFraud)
    expect(bands.reduce((n, b) => n + b.applications, 0) + notScored).toBe(150)
    expect(notScored).toBe(summary.outcome_mix.RESUBMIT_REQUIRED)
  })

  it('the snapshot says what it is: synthetic data, and when', () => {
    expect(snapshot.synthetic).toBe(true)
    expect(snapshot.dataAsOf).toBe('2026-11-18T09:36:12Z')
  })
})
