// Phase 14 motion: reduced motion gives static versions, the officer portal is restrained, and the status page's
// celebration plays only for a result the customer watched arrive.
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CustomerStatusView } from '../customer/CustomerStatusView'
import { toCustomerStatus } from '../customer/customerStatus'
import { applicationView } from '../test/fixtures'
import { Celebration } from './Celebration'
import { DotField } from './DotField'
import { prefersReducedMotion } from './useReducedMotion'

function mediaQuery(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('reduce'), media: query,
    addEventListener: () => undefined, removeEventListener: () => undefined,
  }))
}

beforeEach(() => { // jsdom has no canvas drawing: the components cope with a missing 2-D context
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})
afterEach(() => vi.unstubAllGlobals())

describe('reduced motion', () => {
  it('follows the system setting, and assumes "reduce" where the browser cannot say', () => {
    mediaQuery(true)
    expect(prefersReducedMotion()).toBe(true)
    mediaQuery(false)
    expect(prefersReducedMotion()).toBe(false)
    vi.stubGlobal('matchMedia', undefined)
    expect(prefersReducedMotion()).toBe(true)
  })

  it('the dot field becomes a static gradient, and the celebration is not shown', () => {
    mediaQuery(true)
    render(<><DotField /><Celebration /></>)
    expect(screen.getByTestId('dot-field-static')).toBeInTheDocument()
    expect(screen.queryByTestId('dot-field')).toBeNull()
    expect(screen.queryByTestId('celebration')).toBeNull()
  })

  it('with motion allowed, the dot field is a canvas behind the page (decorative, not focusable)', () => {
    mediaQuery(false)
    render(<DotField />)
    const canvas = screen.getByTestId('dot-field')
    expect(canvas.tagName).toBe('CANVAS')
    expect(canvas).toHaveAttribute('aria-hidden')
  })
})

describe('status page motion', () => {
  function view(stage: 'verifying' | 'verified') {
    return toCustomerStatus(stage === 'verifying'
      ? applicationView({ status: 'PROCESSING', progress: { completed: 2, total: 4 } })
      : applicationView({ status: 'APPROVED', outcome: 'AUTO_APPROVED', progress: { completed: 4, total: 4 } }))
  }

  it('shows one marker per check, completed ones first', () => {
    render(<MemoryRouter><CustomerStatusView status={view('verifying')} live /></MemoryRouter>)
    const markers = screen.getByTestId('check-markers')
    expect(markers.children).toHaveLength(4)
    expect(markers.querySelectorAll('.ekyc-pop')).toHaveLength(2)
    expect(screen.getByText('2 of 4 checks complete')).toBeInTheDocument()
  })

  it('celebrates a result watched live, not one reopened later', () => {
    mediaQuery(false)
    const { rerender } = render(<MemoryRouter><CustomerStatusView status={view('verifying')} live /></MemoryRouter>)
    rerender(<MemoryRouter><CustomerStatusView status={view('verified')} live /></MemoryRouter>)
    expect(screen.getByTestId('celebration')).toBeInTheDocument()
    render(<MemoryRouter><CustomerStatusView status={view('verified')} live={false} /></MemoryRouter>, { container: document.createElement('div') })
    expect(screen.getAllByTestId('celebration')).toHaveLength(1) // the reopened one has none
  })
})
