// Chart colours (Phase 12). The status colours are the app's (theme.ts: brand.good / warning / critical / serious);
// the series colours are the data-viz reference palette (blue, orange, aqua). Every set below was checked with the
// data-viz palette validator (colour-blind separation and normal-vision distance between colours that sit next to
// each other), and none carries meaning alone: each chart has a legend or labels, tooltips and a table view.
import { brand } from '../theme'

export const ink = { primary: brand.ink, secondary: brand.inkSecondary, muted: '#898781', grid: brand.hairline }

/** One hue for a single measure (counts, funnel, risk-score histogram). */
export const MEASURE = '#2a78d6'

/** System outcome. Resubmit is NEUTRAL grey (no risk assessment: the image was unusable), not the orange "serious":
 *  orange beside the amber "Manual review" fails the normal-vision distance check. */
export const OUTCOME_COLORS: Record<string, string> = {
  'Auto-approved': brand.good,
  'Manual review': brand.warning,
  'Resubmit required': '#a8a7a0',
}

/** Decision-reason effect, drawn in this group order: serious sits beside critical only (beside amber it fails). */
export const EFFECT_COLORS: Record<string, string> = {
  Resubmit: brand.serious,
  High: brand.critical,
  Medium: brand.warning,
  'Info only': '#a8a7a0',
}

export const RISK_COLORS: Record<string, string> = { High: brand.critical, Medium: brand.warning }

/** System decision vs ground truth: the highlight-table cell tints (the verdict is also written in each cell). */
export function verdictColor(verdict: string | null): string | null {
  if (!verdict) return null
  if (verdict.startsWith('Correct') || verdict.startsWith('Caught')) return brand.good
  if (verdict.startsWith('False alarm')) return brand.warning
  if (verdict.startsWith('Missed')) return brand.critical
  return '#a8a7a0'
}

/** Officer agreement: confirmed / overruled is a comparison, not a status, so series colours (no red beside green). */
export const AGREEMENT_COLORS = { confirmed: '#2a78d6', overruled: '#eb6834', waiting: '#a8a7a0' }

/** Two steps of one blue for two measures of the same thing (median, then the larger 95th percentile). */
export const LATENCY_COLORS = { median: '#6da7ec', p95: '#1c5cab' }

/** Comparison series 1-3 (forgery metrics; SFace vs Siamese; exact vs normalized). */
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a'] as const
