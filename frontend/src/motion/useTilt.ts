// Phase 14: a card that lifts on hover and tilts very slightly towards the mouse (at most MAX_DEG degrees).
// Use with the "ekyc-lift" class (theme.ts), which turns --tilt-x / --tilt-y / --lift into a transform:
//     const tilt = useTilt<HTMLDivElement>()
//     <Paper ref={tilt} className="ekyc-lift">...</Paper>
// The pointer position is written to two CSS variables (no React re-render, no layout read per move except the card's
// own box). No tilt for touch, for reduced motion, or in the officer portal (MotionLevel "restrained": lift only).
import { useEffect, useRef } from 'react'
import { useMotionLevel } from './motionLevel'
import { useReducedMotion } from './useReducedMotion'

const MAX_DEG = 3

export function useTilt<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const reduced = useReducedMotion()
  const level = useMotionLevel()

  useEffect(() => {
    const element = ref.current
    if (!element || reduced || level !== 'full') return
    let box: DOMRect | null = null
    const enter = () => { box = element.getBoundingClientRect() } // measured once per hover, not per move
    const move = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return
      box ??= element.getBoundingClientRect()
      const x = (event.clientX - box.left) / box.width - 0.5 // -0.5 ... 0.5
      const y = (event.clientY - box.top) / box.height - 0.5
      element.style.setProperty('--tilt-y', `${(x * 2 * MAX_DEG).toFixed(2)}deg`)
      element.style.setProperty('--tilt-x', `${(-y * 2 * MAX_DEG).toFixed(2)}deg`)
    }
    const leave = () => {
      box = null
      element.style.removeProperty('--tilt-x')
      element.style.removeProperty('--tilt-y')
    }
    element.addEventListener('pointerenter', enter)
    element.addEventListener('pointermove', move)
    element.addEventListener('pointerleave', leave)
    return () => {
      element.removeEventListener('pointerenter', enter)
      element.removeEventListener('pointermove', move)
      element.removeEventListener('pointerleave', leave)
      leave()
    }
  }, [reduced, level])

  return ref
}
