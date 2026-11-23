// Phase 14: a checkmark that draws itself (circle, then tick): the "done" moment of the camera challenge. Decorative
// (aria-hidden): the text next to it says what happened. Reduced motion: shown fully drawn at once.
import { Box } from '@mui/material'
import { brand } from '../theme'

export function AnimatedCheck({ size = 28, color = brand.good }: { size?: number; color?: string }) {
  const draw = (duration: number, delay: number) => ({
    strokeDasharray: 1, strokeDashoffset: 1, animation: `ekyc-draw ${duration}ms ${delay}ms ease-out forwards`,
  })
  return (
    <Box component="svg" viewBox="0 0 52 52" width={size} height={size} aria-hidden data-testid="animated-check"
      sx={{ flexShrink: 0, display: 'block' }}>
      <circle cx="26" cy="26" r="23" fill="none" stroke={color} strokeWidth="3" pathLength={1} style={draw(450, 0)} />
      <path d="M15 27 l7.5 7.5 L37.5 19" fill="none" stroke={color} strokeWidth="4.5" strokeLinecap="round"
        strokeLinejoin="round" pathLength={1} style={draw(320, 380)} />
    </Box>
  )
}
