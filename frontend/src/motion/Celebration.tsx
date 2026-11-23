// Phase 14: a brief, quiet celebration when the identity is verified: ~50 small confetti pieces in the brand colours
// rise and fall for 1.6 s on a canvas over the message, then the canvas is removed. No sound. Decorative
// (aria-hidden, pointer-events none). Not shown at all for reduced motion (or in the tests, which emulate it).
import { Box } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { brand } from '../theme'
import { useReducedMotion } from './useReducedMotion'

const DURATION_MS = 1600
const COLORS = [brand.navy, brand.accent, brand.good, '#f2b705', brand.navyLight]

interface Piece { x: number; y: number; vx: number; vy: number; angle: number; spin: number; color: string; w: number; h: number }

export function Celebration() {
  const reduced = useReducedMotion()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (reduced || !canvas || !context) return
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    const { width, height } = canvas.getBoundingClientRect()
    canvas.width = Math.round(width * ratio)
    canvas.height = Math.round(height * ratio)
    context.scale(ratio, ratio)
    const pieces: Piece[] = Array.from({ length: 50 }, (_, i) => ({
      x: width / 2 + (Math.random() - 0.5) * 60, y: height * 0.55,
      vx: (Math.random() - 0.5) * 7, vy: -6 - Math.random() * 6,
      angle: Math.random() * Math.PI, spin: (Math.random() - 0.5) * 0.3,
      color: COLORS[i % COLORS.length], w: 5 + Math.random() * 4, h: 8 + Math.random() * 6,
    }))
    const start = performance.now()
    let frame = 0
    let last = start
    const draw = (now: number) => {
      const t = now - start
      const dt = Math.min(2, (now - last) / 16.7) // in 60 fps frames (steady on slower or faster screens)
      last = now
      context.clearRect(0, 0, width, height)
      context.globalAlpha = t > DURATION_MS * 0.6 ? Math.max(0, 1 - (t - DURATION_MS * 0.6) / (DURATION_MS * 0.4)) : 1
      for (const p of pieces) {
        p.vy += 0.28 * dt // gravity
        p.vx *= 0.99
        p.x += p.vx * dt
        p.y += p.vy * dt
        p.angle += p.spin * dt
        context.save()
        context.translate(p.x, p.y)
        context.rotate(p.angle)
        context.fillStyle = p.color
        context.fillRect(-p.w / 2, -p.h / 2, p.w, p.h)
        context.restore()
      }
      if (t < DURATION_MS) frame = requestAnimationFrame(draw)
      else setDone(true)
    }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [reduced])

  if (reduced || done) return null
  return (
    <Box component="canvas" ref={canvasRef} aria-hidden data-testid="celebration"
      // a canvas keeps its default 300 x 150 size unless width AND height are set (edges alone are not enough)
      sx={{ position: 'absolute', top: -40, left: -8, width: 'calc(100% + 16px)', height: 'calc(100% + 48px)',
        pointerEvents: 'none', zIndex: 2 }} />
  )
}
