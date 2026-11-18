import VerifiedUserIcon from '@mui/icons-material/VerifiedUser'
import { Box, Typography } from '@mui/material'

/** "SecureBank eKYC": a fictional brand with a generic shield icon (no real bank names or logos). */
export function BrandLogo({ inverse = false }: { inverse?: boolean }) {
  const color = inverse ? '#ffffff' : 'primary.main'
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <VerifiedUserIcon sx={{ color, fontSize: 30 }} aria-hidden />
      <Typography component="span" sx={{ color, fontWeight: 700, fontSize: '1.15rem', letterSpacing: 0.2 }}>
        SecureBank <Box component="span" sx={{ fontWeight: 400, opacity: 0.85 }}>eKYC</Box>
      </Typography>
    </Box>
  )
}
