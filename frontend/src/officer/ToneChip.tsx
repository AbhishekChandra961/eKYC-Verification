import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlineOutlined'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutlineOutlined'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { Chip } from '@mui/material'
import { brand } from '../theme'
import type { Tone } from './labels'

const TONES = {
  good: { color: brand.good, Icon: CheckCircleOutlineIcon },
  warning: { color: brand.warning, Icon: WarningAmberIcon },
  critical: { color: brand.critical, Icon: ErrorOutlineIcon },
  info: { color: '#2a78d6', Icon: InfoOutlinedIcon },
  neutral: { color: '#898781', Icon: RemoveCircleOutlineIcon },
} as const

/** A status label: coloured border + icon, with the text in normal ink (readable contrast; never colour alone). */
export function ToneChip({ tone, label, size = 'small' }: { tone: Tone; label: string; size?: 'small' | 'medium' }) {
  const { color, Icon } = TONES[tone]
  return (
    <Chip size={size} variant="outlined" label={label}
      icon={<Icon aria-hidden sx={{ '&&': { color } }} />}
      sx={{ borderColor: color, borderWidth: 1.5, color: 'text.primary', bgcolor: 'background.paper', fontWeight: 600 }} />
  )
}
