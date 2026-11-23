// Phase 14: does this person want less motion? (the system setting "reduce motion"; the Playwright tests emulate it)
// Where the browser cannot say (old browsers, the jsdom test environment), the answer is "yes": static is the safe
// default. CSS animations are switched off by a rule in theme.ts; this hook is for the JavaScript ones (the dot
// field, the tilt, the celebration).
import { useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

function subscribe(onChange: () => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined
  const list = window.matchMedia(QUERY)
  list.addEventListener('change', onChange)
  return () => list.removeEventListener('change', onChange)
}

export function prefersReducedMotion(): boolean {
  return typeof window === 'undefined' || !window.matchMedia || window.matchMedia(QUERY).matches
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => true)
}
