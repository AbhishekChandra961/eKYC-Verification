import { createTheme } from '@mui/material/styles'

// SecureBank (a fictional bank) brand: a deep navy primary, neutral surfaces, and status colours dark enough that
// white text on them passes WCAG AA (>= 4.5:1). Status colours always come with an icon and a text label.
export const brand = {
  navy: '#0b3d6e',
  navyDark: '#072a4d',
  page: '#f5f7fa',
  surface: '#ffffff',
  ink: '#0b0b0b',
  inkSecondary: '#52514e',
  hairline: '#e1e0d9',
  // status palette (data-viz reference): used for borders and icons; text stays in ink colours
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const

export const theme = createTheme({
  palette: {
    primary: { main: brand.navy, dark: brand.navyDark, contrastText: '#ffffff' },
    secondary: { main: '#00695c', contrastText: '#ffffff' },
    success: { main: '#1e6b34', contrastText: '#ffffff' },
    warning: { main: '#8a5300', contrastText: '#ffffff' },
    error: { main: '#b3261e', contrastText: '#ffffff' },
    info: { main: '#0b5cad', contrastText: '#ffffff' },
    background: { default: brand.page, paper: brand.surface },
    text: { primary: brand.ink, secondary: brand.inkSecondary },
    divider: brand.hairline,
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    h1: { fontSize: '1.75rem', fontWeight: 650 },
    h2: { fontSize: '1.375rem', fontWeight: 650 },
    h3: { fontSize: '1.125rem', fontWeight: 650 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiPaper: { defaultProps: { variant: 'outlined' } },
    MuiCard: { defaultProps: { variant: 'outlined' } },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 650, color: brand.inkSecondary } } },
  },
})
