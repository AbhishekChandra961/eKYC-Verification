// Sorting the officer's case queue (pure functions, unit-tested).
import type { CaseRow } from '../api/client'

export type SortKey = 'risk_score' | 'created_at' | 'waiting'

/** How long the case has been open (from submission). Only cases still in progress or waiting for an officer
 *  are "waiting": approved/rejected cases, auto-approvals and retakes sent back to the customer are not. */
export function waitingMs(row: CaseRow, now: number): number | null {
  if (row.status === 'APPROVED' || row.status === 'REJECTED') return null
  if (row.status === 'DECIDED' && row.outcome !== 'MANUAL_REVIEW') return null
  return now - Date.parse(row.created_at)
}

export function sortRows(rows: CaseRow[], key: SortKey, direction: 'asc' | 'desc', now: number): CaseRow[] {
  const value = (row: CaseRow): number | null =>
    key === 'risk_score' ? row.risk_score ?? null : key === 'created_at' ? Date.parse(row.created_at) : waitingMs(row, now)
  return [...rows].sort((a, b) => {
    const va = value(a)
    const vb = value(b)
    if (va === null && vb === null) return Date.parse(a.created_at) - Date.parse(b.created_at)
    if (va === null) return 1 // missing values last, whatever the direction
    if (vb === null) return -1
    const diff = direction === 'asc' ? va - vb : vb - va
    return diff !== 0 ? diff : Date.parse(a.created_at) - Date.parse(b.created_at) // ties: oldest first
  })
}
