// Customers must NEVER see fraud signals (forgery/face scores, rule flags, risk level or score). This file proves it
// three ways: (1) the mapping is a whitelist, (2) a rendered status page shows nothing it was not meant to, even if
// the API sent extra fields, (3) no customer source file mentions any fraud-signal field at all.
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { ApplicationView } from '../api/client'
import { applicationView } from '../test/fixtures'
import { CUSTOMER_STATUS_KEYS, toCustomerStatus } from './customerStatus'
import { CustomerStatusView } from './CustomerStatusView'

/** An API answer with fraud signals smuggled in (as if a backend bug leaked them). */
function leakyView(overrides: Partial<ApplicationView> = {}): ApplicationView {
  return {
    ...applicationView({ status: 'DECIDED', outcome: 'MANUAL_REVIEW', progress: { completed: 4, total: 4 }, ...overrides }),
    risk_score: 97.25,
    risk_level: 'high',
    forgery_score: 0.9997,
    face_score: 0.2095,
    decision: { reasons: [{ code: 'forgery_suspected', message: 'Forgery suspected', evidence: { score: 0.9997 } }] },
    flags: [{ rule: 'mrz_vs_surname', detail: "page 'FERNANDO' vs MRZ 'FEERNANDO'" }],
  } as ApplicationView
}

describe('customer status mapping', () => {
  it.each([
    ['SUBMITTED', null, 'submitted', 'pending', 'Application received', false],
    ['PROCESSING', null, 'verifying', 'pending', 'Verifying your identity', false],
    ['DECIDED', 'AUTO_APPROVED', 'result', 'verified', 'Verified', true],
    ['DECIDED', 'MANUAL_REVIEW', 'result', 'under_review', 'Under review by our team', false],
    ['DECIDED', 'RESUBMIT_REQUIRED', 'result', 'resubmit', 'Please resubmit', true],
    ['APPROVED', 'MANUAL_REVIEW', 'result', 'verified', 'Verified', true],
    ['REJECTED', 'MANUAL_REVIEW', 'result', 'not_verified', 'We could not verify your identity', true],
  ] as const)('%s / %s -> %s, %s', (status, outcome, stage, customerOutcome, title, final) => {
    const result = toCustomerStatus(applicationView({ status, outcome }))
    expect(result).toMatchObject({ stage, outcome: customerOutcome, title, final })
  })

  it('copies only the whitelisted fields', () => {
    const result = toCustomerStatus(leakyView())
    expect(Object.keys(result).sort()).toEqual([...CUSTOMER_STATUS_KEYS].sort())
    const text = JSON.stringify(result)
    for (const leaked of ['97.25', '0.9997', '0.2095', 'forgery', 'FERNANDO', 'risk', 'high']) {
      expect(text).not.toContain(leaked)
    }
  })

  it('shows what to retake only for a resubmission, never for a case under review', () => {
    const retake = ['No face found on the selfie: please retake the selfie']
    expect(toCustomerStatus(applicationView({ status: 'DECIDED', outcome: 'RESUBMIT_REQUIRED', retake })).nextSteps).toEqual(retake)
    expect(toCustomerStatus(applicationView({ status: 'DECIDED', outcome: 'MANUAL_REVIEW', retake })).nextSteps).toEqual([])
    expect(toCustomerStatus(applicationView({ status: 'DECIDED', outcome: 'RESUBMIT_REQUIRED', retake: [] })).nextSteps[0])
      .toMatch(/take new photos/)
  })

  it('keeps progress as a plain count within range', () => {
    expect(toCustomerStatus(applicationView({ progress: { completed: 9, total: 4 } })).progress).toEqual({ completed: 4, total: 4 })
    expect(toCustomerStatus(applicationView({ progress: { completed: -1, total: 0 } })).progress).toEqual({ completed: 0, total: 1 })
  })
})

describe('customer status page', () => {
  function renderStatus(view: ApplicationView) {
    return render(<MemoryRouter><CustomerStatusView status={toCustomerStatus(view)} live={false} /></MemoryRouter>)
  }

  it('shows "Under review" and nothing about why, even when the API leaks fraud signals', () => {
    const { container } = renderStatus(leakyView())
    expect(within(screen.getByRole('alert')).getByText('Under review by our team')).toBeInTheDocument()
    const text = container.textContent ?? ''
    for (const leaked of ['97', '0.99', '0.20', 'orgery', 'FERNANDO', 'risk', 'score', 'flag', 'face']) {
      expect(text.toLowerCase()).not.toContain(leaked.toLowerCase())
    }
    expect(screen.queryByRole('link', { name: 'Start again' })).not.toBeInTheDocument()
  })

  it('shows progress while verifying, as a count only', () => {
    renderStatus(applicationView({ status: 'PROCESSING', progress: { completed: 2, total: 4 } }))
    expect(screen.getByText('2 of 4 checks complete')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: '2 of 4 checks complete' })).toHaveAttribute('aria-valuenow', '50')
  })

  it('offers "Start again" with the neutral instruction for a resubmission', () => {
    renderStatus(applicationView({ status: 'DECIDED', outcome: 'RESUBMIT_REQUIRED', progress: { completed: 1, total: 1 },
      retake: ['Image unreadable: no document visible, please upload a new photo'] }))
    expect(within(screen.getByRole('alert')).getByText('Please resubmit')).toBeInTheDocument()
    expect(screen.getByText(/please upload a new photo/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start again' })).toHaveAttribute('href', '/customer/verify')
  })

  it('shows "Verified" for an approved application', () => {
    renderStatus(applicationView({ status: 'DECIDED', outcome: 'AUTO_APPROVED', progress: { completed: 4, total: 4 } }))
    expect(within(screen.getByRole('alert')).getByText('Verified')).toBeInTheDocument()
  })
})

describe('customer source code', () => {
  // Every customer file, as text (Vite's raw import). Comments are removed first: they may explain the rule.
  const sources = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>
  const forbidden = [/\bscores?\b/i, /risk/i, /forgery/i, /\bbands?\b/i, /\bflags?\b/i, /evidence/i, /confidence/i,
    /reason_codes/i, /heatmap/i, /\btiles?\b/i, /officer_decision/i, /\bdecision\b/i]

  it('covers the customer portal files', () => {
    expect(Object.keys(sources).length).toBeGreaterThanOrEqual(10)
  })

  it.each(Object.entries(sources))('%s never mentions a fraud-signal field', (_, source) => {
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
    for (const pattern of forbidden) expect(code).not.toMatch(pattern)
  })
})
