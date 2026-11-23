// Phase 14: a small progress ring (an arc that fills clockwise), e.g. how far the head has turned towards the next
// capture. Decorative: the step's text says the same thing.
import { Box } from '@mui/material'

export function ProgressRing({ value, size = 18, color = 'currentColor', track = 'rgba(0, 0, 0, 0.15)' }: {
  value: number; size?: number; color?: string; track?: string
}) {
  const r = 7
  const progress = Math.max(0, Math.min(1, value))
  return (
    <Box component="svg" viewBox="0 0 18 18" width={size} height={size} aria-hidden sx={{ display: 'block', flexShrink: 0 }}>
      <circle cx="9" cy="9" r={r} fill="none" stroke={track} strokeWidth="2.2" />
      <circle cx="9" cy="9" r={r} fill="none" stroke={color} strokeWidth="2.2" strokeLinecap="round" pathLength={1}
        transform="rotate(-90 9 9)"
        style={{ strokeDasharray: 1, strokeDashoffset: 1 - progress, transition: 'stroke-dashoffset 160ms linear' }} />
    </Box>
  )
}
