// Phase 14: the animated background of the landing page and the login page (nowhere else: never on the camera
// screens, where the in-browser face detector needs the CPU). A canvas behind the page: dots drift slowly, faint lines
// join dots that come close, and dots move gently away from the mouse.
//
// Performance:
// - at most 80 dots (one per ~16,000 px² of screen; 36 on small screens): the near-pair test is ~3,000 distance
//   checks per frame;
// - the canvas never asks the page for its layout while drawing (sizes are read only on resize; the mouse position
//   comes from the event itself), so no layout thrashing;
// - it stops when the tab is hidden and when the component unmounts; the pixel ratio is capped at 2;
// - every 60 frames it writes its average draw time to data-draw-ms (the Phase 14 performance run reads it).
// Reduced motion (and the Playwright tests): no canvas, a static dotted gradient instead.
import { Box, useTheme } from '@mui/material'
import { alpha } from '@mui/material/styles'
import { useEffect, useRef } from 'react'
import { useReducedMotion } from './useReducedMotion'

const AREA_PER_DOT = 16_000
const MAX_DOTS = 80
const MAX_DOTS_SMALL = 36
const SMALL_SCREEN = 600 // px wide
const LINK_DISTANCE = 130 // px
const CURSOR_RADIUS = 150 // px
const CURSOR_PUSH = 0.6 // px per frame at the cursor, fading to 0 at CURSOR_RADIUS
const LINE_LEVELS = 4 // line transparency steps (one canvas stroke each)

interface Dot { x: number; y: number; vx: number; vy: number; r: number; accent: boolean }

function makeDots(width: number, height: number): Dot[] {
  const cap = width < SMALL_SCREEN ? MAX_DOTS_SMALL : MAX_DOTS
  const count = Math.min(cap, Math.round((width * height) / AREA_PER_DOT))
  return Array.from({ length: count }, (_, i) => {
    const angle = Math.random() * Math.PI * 2
    const speed = 0.12 + Math.random() * 0.18 // px per frame at 60 fps: slow
    return { x: Math.random() * width, y: Math.random() * height, vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed, r: 1.2 + Math.random() * 1.4, accent: i % 5 === 0 }
  })
}

export function DotField() {
  const theme = useTheme()
  const reduced = useReducedMotion()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const dotColor = alpha(theme.palette.primary.main, 0.5)
  const accentColor = alpha(theme.palette.secondary.main, 0.6)
  const lineColor = theme.palette.primary.main

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (reduced || !canvas || !context) return
    let width = 0
    let height = 0
    let dots: Dot[] = []
    let frame = 0
    let last = 0
    let drawTotal = 0
    let drawFrames = 0
    const cursor = { x: -1e4, y: -1e4 }

    const resize = () => { // the only place that reads the layout
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const nextWidth = window.innerWidth
      const nextHeight = window.innerHeight
      canvas.width = Math.round(nextWidth * ratio)
      canvas.height = Math.round(nextHeight * ratio)
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      if (!dots.length || width === 0) dots = makeDots(nextWidth, nextHeight)
      else dots.forEach((d) => { d.x *= nextWidth / width; d.y *= nextHeight / height })
      width = nextWidth
      height = nextHeight
    }

    const draw = (now: number) => {
      frame = requestAnimationFrame(draw)
      const dt = last ? Math.min(3, (now - last) / 16.7) : 1 // in 60 fps frames: same speed at any refresh rate
      last = now
      const started = performance.now()
      context.clearRect(0, 0, width, height)
      for (const d of dots) {
        const dx = d.x - cursor.x
        const dy = d.y - cursor.y
        const distance = Math.hypot(dx, dy)
        if (distance < CURSOR_RADIUS && distance > 0.1) { // a gentle push away from the mouse
          const push = (1 - distance / CURSOR_RADIUS) * CURSOR_PUSH * dt
          d.x += (dx / distance) * push
          d.y += (dy / distance) * push
        }
        d.x += d.vx * dt
        d.y += d.vy * dt
        if (d.x < -10) d.x = width + 10 // wrap around the edges
        else if (d.x > width + 10) d.x = -10
        if (d.y < -10) d.y = height + 10
        else if (d.y > height + 10) d.y = -10
      }
      // lines between close dots: fainter with distance, drawn in LINE_LEVELS batches (one stroke per batch)
      const batches = Array.from({ length: LINE_LEVELS }, () => new Path2D())
      for (let i = 0; i < dots.length; i++) {
        for (let j = i + 1; j < dots.length; j++) {
          const a = dots[i]
          const b = dots[j]
          const distance = Math.hypot(a.x - b.x, a.y - b.y)
          if (distance < LINK_DISTANCE) {
            const batch = batches[Math.min(LINE_LEVELS - 1, Math.floor((distance / LINK_DISTANCE) * LINE_LEVELS))]
            batch.moveTo(a.x, a.y)
            batch.lineTo(b.x, b.y)
          }
        }
      }
      context.lineWidth = 1
      context.strokeStyle = lineColor
      batches.forEach((batch, level) => {
        context.globalAlpha = 0.24 * (1 - (level + 0.5) / LINE_LEVELS) // closest pairs: darkest
        context.stroke(batch)
      })
      context.globalAlpha = 1
      for (const d of dots) {
        context.fillStyle = d.accent ? accentColor : dotColor
        context.beginPath()
        context.arc(d.x, d.y, d.r, 0, Math.PI * 2)
        context.fill()
      }
      drawTotal += performance.now() - started
      if (++drawFrames === 60) {
        canvas.dataset.drawMs = (drawTotal / drawFrames).toFixed(3)
        drawTotal = 0
        drawFrames = 0
      }
    }

    const start = () => {
      if (!frame && !document.hidden) {
        last = 0
        frame = requestAnimationFrame(draw)
      }
    }
    const stop = () => {
      cancelAnimationFrame(frame)
      frame = 0
    }
    const visibility = () => (document.hidden ? stop() : start())
    const pointer = (event: PointerEvent) => {
      cursor.x = event.clientX
      cursor.y = event.clientY
    }
    const away = () => { cursor.x = -1e4; cursor.y = -1e4 }

    resize()
    start()
    window.addEventListener('resize', resize)
    window.addEventListener('pointermove', pointer, { passive: true })
    document.documentElement.addEventListener('pointerleave', away)
    document.addEventListener('visibilitychange', visibility)
    return () => {
      stop()
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', pointer)
      document.documentElement.removeEventListener('pointerleave', away)
      document.removeEventListener('visibilitychange', visibility)
    }
  }, [reduced, dotColor, accentColor, lineColor])

  const layer = { position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none' } as const
  if (reduced) { // static fallback: the same dots, standing still, in a soft gradient
    return (
      <Box aria-hidden data-testid="dot-field-static" sx={{
        ...layer,
        backgroundImage: `radial-gradient(circle, ${alpha(theme.palette.primary.main, 0.16)} 1.2px, transparent 1.6px),
          radial-gradient(900px 600px at 15% 10%, ${alpha(theme.palette.primary.main, 0.08)}, transparent 70%),
          radial-gradient(800px 600px at 90% 90%, ${alpha(theme.palette.secondary.main, 0.08)}, transparent 70%)`,
        backgroundSize: '26px 26px, auto, auto',
      }} />
    )
  }
  return <Box component="canvas" ref={canvasRef} aria-hidden data-testid="dot-field" sx={{ ...layer, width: '100%', height: '100%' }} />
}
