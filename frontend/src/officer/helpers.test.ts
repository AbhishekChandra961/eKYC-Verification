import { describe, expect, it } from 'vitest'
import type { CaseRow } from '../api/client'
import { fileProblem, dimensionProblem, dimensionWarning } from '../customer/imageValidation'
import { validatePersonal } from '../customer/steps/personal'
import { formatDuration } from '../format'
import { heatCells, heatColor, heatOpacity, HEAT_RAMP } from './heatmap'
import { sortRows, waitingMs } from './queue'

describe('forgery heatmap cells', () => {
  // 2 x 2 overlapping tiles of 224 px with stride 112 on a 336 x 336 page
  const grid = { size: 224, xy: [[0, 0], [112, 0], [0, 112], [112, 112]], scores: [0.1, 0.9, 0.2, 0.3] }

  it('cuts the page along tile edges and gives each cell the highest covering score', () => {
    const cells = heatCells(grid)
    expect(cells).toHaveLength(9)
    const at = (x: number, y: number) => cells.find((c) => c.x === x && c.y === y)?.score
    expect(at(0, 0)).toBe(0.1) // only the first tile
    expect(at(112, 0)).toBe(0.9) // first + second tile
    expect(at(112, 112)).toBe(0.9) // all four tiles
    expect(at(0, 224)).toBe(0.2)
    expect(cells.reduce((area, c) => area + c.width * c.height, 0)).toBe(336 * 336)
  })

  it('handles an edge tile that is not on the stride (clamped to the page border)', () => {
    const cells = heatCells({ size: 224, xy: [[0, 0], [112, 0], [176, 0]], scores: [0, 0, 1] })
    expect(cells.map((c) => [c.x, c.width])).toEqual([[0, 112], [112, 64], [176, 48], [224, 112], [336, 64]])
    expect(cells.at(-1)?.score).toBe(1)
  })

  it('keeps near-zero cells invisible and darkens with the score (one hue)', () => {
    expect(heatOpacity(0.05)).toBe(0)
    expect(heatOpacity(0.9)).toBeGreaterThan(heatOpacity(0.5))
    expect(heatColor(0)).toBe(HEAT_RAMP[0])
    expect(heatColor(1)).toBe(HEAT_RAMP.at(-1))
  })
})

describe('case queue sorting', () => {
  const row = (id: string, score: number | null, created: string, status: CaseRow['status'] = 'DECIDED'): CaseRow =>
    ({ application_id: id, status, risk_score: score, created_at: created, updated_at: created, reason_codes: [] })
  const rows = [
    row('a', 20, '2026-11-17T10:00:00Z'),
    row('b', 100, '2026-11-17T11:00:00Z'),
    row('c', null, '2026-11-17T09:00:00Z'),
    row('d', 20, '2026-11-17T09:30:00Z'),
  ]
  const now = Date.parse('2026-11-17T12:00:00Z')

  it('defaults to highest risk first; ties oldest first; no score last', () => {
    expect(sortRows(rows, 'risk_score', 'desc', now).map((r) => r.application_id)).toEqual(['b', 'd', 'a', 'c'])
    expect(sortRows(rows, 'risk_score', 'asc', now).map((r) => r.application_id)).toEqual(['d', 'a', 'b', 'c'])
  })

  it('measures waiting time from submission, and not for closed cases', () => {
    expect(waitingMs({ ...rows[0], status: 'PROCESSING' }, now)).toBe(2 * 3600_000) // checks still running
    expect(waitingMs(row('e', 5, '2026-11-17T10:00:00Z', 'REJECTED'), now)).toBeNull()
    expect(waitingMs({ ...rows[0], outcome: 'MANUAL_REVIEW' }, now)).toBe(2 * 3600_000) // waits for an officer
    expect(waitingMs({ ...rows[0], outcome: 'AUTO_APPROVED' }, now)).toBeNull() // nobody needs to act
    expect(formatDuration(2 * 3600_000 + 5 * 60_000)).toBe('2 h 05 min')
  })
})

describe('upload checks (mirror the API rules)', () => {
  it.each([
    [{ type: 'image/jpeg', size: 2_000_000 }, null],
    [{ type: 'image/png', size: 10 * 1024 * 1024 }, null],
    [{ type: 'image/gif', size: 1000 }, /JPEG or PNG/],
    [{ type: 'application/pdf', size: 1000 }, /JPEG or PNG/],
    [{ type: 'image/jpeg', size: 10 * 1024 * 1024 + 1 }, /limit is 10 MB/],
    [{ type: 'image/jpeg', size: 0 }, /empty/],
  ])('%o', (file, expected) => {
    const problem = fileProblem(file)
    if (expected === null) expect(problem).toBeNull()
    else expect(problem).toMatch(expected)
  })

  it('checks pixel size', () => {
    expect(dimensionProblem(99, 400)).toMatch(/too small/)
    expect(dimensionProblem(100, 100)).toBeNull()
    expect(dimensionWarning(800, 500, 'document')).toMatch(/quite small/)
    expect(dimensionWarning(800, 500, 'selfie')).toBeNull()
  })

  it('validates the personal details like the API', () => {
    const today = '2026-11-17'
    expect(validatePersonal({ fullName: 'Maria Lopez', dateOfBirth: '1990-02-03' }, today)).toEqual({})
    expect(validatePersonal({ fullName: ' K ', dateOfBirth: '2027-01-01' }, today)).toMatchObject({
      fullName: expect.any(String), dateOfBirth: expect.any(String),
    })
    expect(validatePersonal({ fullName: '12345', dateOfBirth: '' }, today)).toMatchObject({ fullName: expect.any(String) })
  })
})
