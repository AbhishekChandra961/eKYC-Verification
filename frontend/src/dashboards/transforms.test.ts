// The dashboards' data transforms on small hand-made tables: the counting rules (above all, no double counting
// across reason rows), the statistics, the filters and the chart orderings.
import { describe, expect, it } from 'vitest'
import { metricValue, percent, wrapLabel } from './format'
import { parseSnapshot, type ModelRow, type OperationsRow, type RiskFraudRow } from './snapshot'
import {
  applyFilters, caseRows, confusionMatrix, extractionPerField, faceComparison, forgeryStory, funnel, latencyByCheck,
  mean, median, officerAgreement, operationsKpis, outcomesByDocType, quantile, queueAge, reasonFrequencies, riskKpis,
  riskScoreDistribution,
} from './transforms'

function ops(over: Partial<OperationsRow>): OperationsRow {
  return {
    case: 'C0001', docType: 'Serbian passport', systemOutcome: 'Auto-approved', outcome: 'Auto-approved', riskLevel: 'Low',
    applications: 1, autoApproved: 1, manualReview: 0, resubmitRequired: 0, timeToDecisionS: 20, docCheckS: 1,
    faceCheckS: 1, forgeryCheckS: 5, extractionCheckS: 25, funnel1: 1, funnel2: 1, funnel3: 0, funnel4: 0, funnel5: 0,
    waitingForOfficer: 0, queueAgeMin: null, ...over,
  }
}

const review = { systemOutcome: 'Manual review', autoApproved: 0, manualReview: 1, funnel3: 1 } as const

/** A case's rows as in risk_fraud.csv: the case's own numbers on the first row, null on the others. */
function riskCase(over: Partial<RiskFraudRow>, reasons: [string, string][]): RiskFraudRow[] {
  const first: RiskFraudRow = {
    case: 'C0001', docType: 'Serbian passport', systemOutcome: 'Auto-approved', outcome: 'Auto-approved', riskLevel: 'Low',
    riskScoreBand: 0, truthClass: 'Legitimate', systemVsTruth: 'Correct: approved', reason: 'No reason', reasonEffect: null,
    raisedBy: null, casesWithReason: null, applications: 1, riskScore: 5, fraudCaught: null, missedFraud: null,
    falseAlarm: 0, officerConfirmedFlag: null, officerAgreesWithTruth: null, ...over,
  }
  if (!reasons.length) return [first]
  return reasons.map(([reason, effect], i) => ({
    ...first, reason, reasonEffect: effect, raisedBy: 'Forgery detector', casesWithReason: 1,
    ...(i > 0 ? { applications: null, riskScore: null, fraudCaught: null, missedFraud: null, falseAlarm: null,
      officerConfirmedFlag: null, officerAgreesWithTruth: null } : {}),
  }))
}

// A forged case caught with THREE reasons (high risk, rejected by the officer), a false alarm with one reason (still
// waiting), and a clean auto-approval without any reason: 5 rows, 3 cases.
const risk: RiskFraudRow[] = [
  ...riskCase({ case: 'C0001', systemOutcome: 'Manual review', outcome: 'Rejected by officer', riskLevel: 'High',
    riskScoreBand: 60, riskScore: 61, truthClass: 'Fraud or mismatch', systemVsTruth: 'Caught: sent to review',
    fraudCaught: 1, missedFraud: 0, falseAlarm: null, officerConfirmedFlag: 1, officerAgreesWithTruth: 1 },
  [['Forgery suspected', 'High'], ['Selfie does not match the ID photo', 'High'], ['Document expired (informational)', 'Info only']]),
  ...riskCase({ case: 'C0002', docType: 'Estonian ID card', systemOutcome: 'Manual review', outcome: 'Awaiting officer',
    riskLevel: 'Medium', riskScoreBand: 20, riskScore: 25, systemVsTruth: 'False alarm: sent to review', falseAlarm: 1 },
  [['Possible document edit', 'Medium']]),
  ...riskCase({ case: 'C0003' }, []),
]

describe('statistics', () => {
  it('quantiles interpolate linearly between ranks, like numpy and pandas', () => {
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 3, 2])).toBe(2.5)
    expect(quantile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95)).toBeCloseTo(9.55) // numpy.percentile(1..10, 95)
    expect(median([null, 5, null])).toBe(5) // empty cells are skipped
    expect(quantile([], 0.5)).toBeNull()
  })

  it('the mean of a (0/1) column skips empty cells: a rate among the cases it applies to', () => {
    expect(mean([1, 0, null, 1, null])).toBeCloseTo(2 / 3)
    expect(mean([null])).toBeNull()
  })
})

describe('operations', () => {
  const rows = [
    ops({ case: 'C0001' }),
    ops({ case: 'C0002', ...review, outcome: 'Rejected by officer', riskLevel: 'High', funnel4: 1, funnel5: 1,
      timeToDecisionS: 60, extractionCheckS: null }),
    ops({ case: 'C0003', ...review, outcome: 'Awaiting officer', riskLevel: 'Medium', waitingForOfficer: 1, queueAgeMin: 30.2,
      docType: 'Estonian ID card', timeToDecisionS: 40 }),
    ops({ case: 'C0004', systemOutcome: 'Resubmit required', outcome: 'Retake requested', riskLevel: 'None (resubmit)',
      autoApproved: 0, resubmitRequired: 1, docType: 'Not classified', timeToDecisionS: 1, forgeryCheckS: null, extractionCheckS: null }),
  ]

  it('KPIs: applications are summed, rates are averages of the (0/1) columns', () => {
    const k = operationsKpis(rows)
    expect(k.applications).toBe(4)
    expect(k.autoApproval).toEqual({ hits: 1, total: 4, rate: 0.25 })
    expect(k.manualReview.rate).toBe(0.5)
    expect(k.resubmit.rate).toBe(0.25)
    expect(k.medianTimeToDecisionS).toBe(30) // median of 1, 20, 40, 60
    expect(k.waiting).toBe(1)
    expect(k.oldestWaitingMin).toBe(30.2)
  })

  it('funnel stages add up the pre-computed funnel columns', () => {
    expect(funnel(rows, ['a', 'b', 'c', 'd', 'e']).map((s) => s.applications)).toEqual([4, 4, 2, 1, 1])
  })

  it('outcomes by document type: the busiest type first, every application in one outcome', () => {
    const byType = outcomesByDocType(rows)
    expect(byType[0]).toMatchObject({ docType: 'Serbian passport', total: 2, 'Auto-approved': 1, 'Manual review': 1 })
    expect(byType.reduce((n, t) => n + t.total, 0)).toBe(4)
  })

  it('latency per check skips the checks that did not run', () => {
    const extraction = latencyByCheck(rows).find((l) => l.check === 'Field extraction')!
    expect(extraction).toMatchObject({ runs: 2, medianS: 25 })
  })

  it('the queue lists only the waiting cases, the longest wait first', () => {
    expect(queueAge(rows)).toEqual([{ case: 'C0003', riskLevel: 'Medium', minutes: 30.2 }])
  })

  it('filters combine document type and outcome', () => {
    expect(applyFilters(rows, { docType: 'Serbian passport', outcome: null })).toHaveLength(2)
    expect(applyFilters(rows, { docType: 'Serbian passport', outcome: 'Rejected by officer' }).map((r) => r.case)).toEqual(['C0002'])
    expect(applyFilters(rows, { docType: null, outcome: null })).toHaveLength(4)
  })
})

describe('risk & fraud: no double counting across reason rows', () => {
  it('caseRows keeps exactly one row per case (its first row)', () => {
    expect(risk).toHaveLength(5)
    expect(caseRows(risk).map((r) => r.case)).toEqual(['C0001', 'C0002', 'C0003'])
  })

  it('the risk-score distribution counts the three-reason case once', () => {
    const { bands, notScored } = riskScoreDistribution(risk)
    expect(bands.reduce((n, b) => n + b.applications, 0)).toBe(3) // not 5 (the number of rows)
    expect(bands.find((b) => b.band === 60)!.applications).toBe(1)
    expect(bands.map((b) => b.label)).toEqual(['0–9', '10–19', '20–29', '30–39', '40–49', '50–59', '60–69', '70–79', '80–89', '90–99', '100'])
    expect(notScored).toBe(0)
  })

  it('cases sent back for a new photo are left out of the score bands, and counted apart', () => {
    const resubmit = riskCase({ case: 'C0009', systemOutcome: 'Resubmit required', riskLevel: 'None (resubmit)', riskScore: 0 },
      [['Image unreadable (no document visible)', 'Resubmit']])
    const { bands, notScored } = riskScoreDistribution([...risk, ...resubmit])
    expect(bands.reduce((n, b) => n + b.applications, 0)).toBe(3)
    expect(notScored).toBe(1)
  })

  it('the confusion matrix and the KPIs count cases, not reasons', () => {
    const m = confusionMatrix(risk)
    expect(m.total).toBe(3)
    expect(m.cells.find((c) => c.truth === 'Fraud or mismatch' && c.outcome === 'Manual review'))
      .toMatchObject({ applications: 1, verdict: 'Caught: sent to review' })
    expect(m.rowTotals).toEqual({ 'Fraud or mismatch': 1, Legitimate: 2, 'Unusable image': 0 })
    const k = riskKpis(risk)
    expect(k.fraudCaught).toEqual({ hits: 1, total: 1, rate: 1 })
    expect(k.falseAlarms).toEqual({ hits: 1, total: 2, rate: 0.5 })
    expect(k.flagConfirmed).toEqual({ hits: 1, total: 1, rate: 1 })
  })

  it('reason frequencies count distinct cases, grouped by effect, and skip "No reason"', () => {
    const twice = [...risk, { ...risk[1], applications: null }] // the same reason listed twice for one case
    const reasons = reasonFrequencies(twice, 'No reason')
    expect(reasons.map((r) => [r.reason, r.effect, r.cases])).toEqual([
      ['Forgery suspected', 'High', 1],
      ['Selfie does not match the ID photo', 'High', 1],
      ['Possible document edit', 'Medium', 1],
      ['Document expired (informational)', 'Info only', 1],
    ])
  })

  it('officer agreement per risk level: confirmed, overruled, still waiting', () => {
    expect(officerAgreement(risk)).toEqual([
      { riskLevel: 'High', confirmed: 1, overruled: 0, waiting: 0 },
      { riskLevel: 'Medium', confirmed: 0, overruled: 0, waiting: 1 },
    ])
  })
})

describe('model performance', () => {
  const m = (over: Partial<ModelRow>): ModelRow => ({
    model: 'Forgery detector', version: 'v1', versionOrder: 1, split: 'val', metric: 'document PR-AUC', value: 0.9,
    chart: 'Forgery story', field: null, matchType: null, note: null, source: 'x.json', ...over,
  })
  const rows = [
    m({ version: 'v3', versionOrder: 3, value: 0.96 }),
    m({ version: 'v1', versionOrder: 1, value: 0.98 }),
    m({ version: 'v1', versionOrder: 1, metric: 'localisation (heat on the edit)', value: 0 }),
    m({ model: 'Face verification', chart: 'Face verification', version: 'Siamese', versionOrder: 1, split: 'LFW test', metric: 'ROC-AUC', value: 0.78 }),
    m({ model: 'Face verification', chart: 'Face verification', version: 'SFace', versionOrder: 2, split: 'LFW test', metric: 'ROC-AUC', value: 0.997 }),
    m({ model: 'Field extraction', chart: 'Extraction per field', field: 'surname', matchType: 'Exact', value: 0.9 }),
    m({ model: 'Field extraction', chart: 'Extraction per field', field: 'surname', matchType: 'Normalized', value: 0.92 }),
    m({ model: 'Field extraction', chart: 'Extraction per field', field: 'mrz_line0', matchType: 'Exact', value: 0.13 }),
    m({ model: 'Field extraction', chart: 'Extraction per field', field: 'mrz_line0', matchType: 'Normalized', value: 0.77 }),
  ]

  it('the forgery story is in version order, with a gap where a version has no value', () => {
    const story = forgeryStory(rows)
    expect(story.map((v) => v.version)).toEqual(['v1', 'v3'])
    expect(story[0].values['localisation (heat on the edit)']).toBe(0)
    expect(story[1].values['localisation (heat on the edit)']).toBeNull()
  })

  it('face: the production model first; extraction: the best field first', () => {
    expect(faceComparison(rows).versions).toEqual(['SFace', 'Siamese'])
    expect(extractionPerField(rows).map((f) => [f.field, f.exact, f.normalized])).toEqual([['surname', 0.9, 0.92], ['mrz_line0', 0.13, 0.77]])
  })
})

describe('formatting and the snapshot format', () => {
  it('formats rates, metrics and long labels', () => {
    expect(percent(49 / 150)).toBe('32.7%')
    expect(percent(null)).toBe('–')
    expect(metricValue(0.98529411)).toBe('0.9853')
    expect(wrapLabel('Document data inconsistent: mrz check document number', 22))
      .toBe('Document data\ninconsistent: mrz\ncheck document number')
  })

  it('rejects a snapshot whose columns changed', () => {
    const table = { columns: ['case'], rows: [['C0001']] }
    expect(() => parseSnapshot({ schemaVersion: 1, dataAsOf: '2026-11-18T09:36:12Z', synthetic: true, funnelStages: [],
      noReason: 'No reason', tables: { operations: table, riskFraud: table, modelPerformance: table } }))
      .toThrow(/operations: columns case/)
  })
})
