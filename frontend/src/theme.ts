import { createTheme } from '@mui/material/styles'

// SecureBank (a fictional bank) brand, Phase 14 refresh: a confident royal navy primary with a teal accent, soft
// gradients and softer depth. Every text colour clears WCAG AA (contrast checked in reports/phase14/README.md):
// white on the primary 8.0:1, on the accent 5.6:1, on every gradient stop >= 5.6:1. The status colours keep their
// meaning (approved / review / resubmit / rejected) and always come with an icon and a text label.
export const brand = {
  navy: '#0b4f9c', // primary
  navyDark: '#083a70',
  navyLight: '#3d78bd', // decorative only (never text on white)
  accent: '#0b7285', // teal accent
  page: '#f4f7fb',
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

/** Soft gradients for surfaces that carry the brand (top bar, hero accents). */
export const gradients = {
  brand: `linear-gradient(120deg, ${brand.navyDark} 0%, ${brand.navy} 55%, ${brand.accent} 100%)`,
  button: `linear-gradient(180deg, #1559a8 0%, ${brand.navy} 100%)`,
  page: `radial-gradient(1100px 560px at 8% -12%, rgba(11, 79, 156, 0.09), transparent 70%),
    radial-gradient(900px 520px at 108% 0%, rgba(11, 114, 133, 0.08), transparent 70%)`,
} as const

/** Depth: soft, layered shadows (never heavy). */
export const depth = {
  rest: '0 1px 2px rgba(16, 24, 40, 0.05), 0 2px 8px rgba(16, 24, 40, 0.04)',
  raised: '0 2px 4px rgba(16, 24, 40, 0.06), 0 12px 28px rgba(11, 79, 156, 0.12)',
} as const

// ---- motion (Phase 14): CSS only. Entrance fades and slides, small pops, a pulse, and a drawn checkmark, all on
// transform / opacity (the compositor animates them without layout work). One rule below turns every animation and
// transition off for people who ask their system for reduced motion; the Playwright tests emulate that setting, so
// they stay deterministic.
const EASE = 'cubic-bezier(0.22, 1, 0.36, 1)' // a soft "ease-out-quint": quick start, gentle landing

const keyframes = {
  '@keyframes ekyc-fade-up': { from: { opacity: 0, transform: 'translateY(8px)' }, to: { opacity: 1, transform: 'none' } },
  '@keyframes ekyc-step-forward': { from: { opacity: 0, transform: 'translateX(28px)' }, to: { opacity: 1, transform: 'none' } },
  '@keyframes ekyc-step-back': { from: { opacity: 0, transform: 'translateX(-28px)' }, to: { opacity: 1, transform: 'none' } },
  '@keyframes ekyc-pop': { '0%': { transform: 'scale(0.6)', opacity: 0 }, '60%': { transform: 'scale(1.12)', opacity: 1 },
    '100%': { transform: 'scale(1)', opacity: 1 } },
  '@keyframes ekyc-pulse': { '0%, 100%': { opacity: 1 }, '50%': { opacity: 0.45 } }, // ends where it starts
  '@keyframes ekyc-nudge-left': { '0%, 100%': { transform: 'none' }, '50%': { transform: 'translateX(-6px)' } },
  '@keyframes ekyc-nudge-right': { '0%, 100%': { transform: 'none' }, '50%': { transform: 'translateX(6px)' } },
  '@keyframes ekyc-draw': { to: { strokeDashoffset: 0 } },
}

export const theme = createTheme({
  palette: {
    primary: { main: brand.navy, dark: brand.navyDark, light: brand.navyLight, contrastText: '#ffffff' },
    secondary: { main: brand.accent, contrastText: '#ffffff' },
    success: { main: '#1e6b34', contrastText: '#ffffff' },
    warning: { main: '#8a5300', contrastText: '#ffffff' },
    error: { main: '#b3261e', contrastText: '#ffffff' },
    info: { main: '#0b5cad', contrastText: '#ffffff' },
    background: { default: brand.page, paper: brand.surface },
    text: { primary: brand.ink, secondary: brand.inkSecondary },
    divider: brand.hairline,
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    h1: { fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.01em' },
    h2: { fontSize: '1.375rem', fontWeight: 650, letterSpacing: '-0.005em' },
    h3: { fontSize: '1.125rem', fontWeight: 650 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        ...keyframes,
        body: { backgroundImage: gradients.page, backgroundAttachment: 'fixed' },
        // keyboard focus: always visible, never colour-only (a 3 px ring with an offset)
        ':focus-visible': { outline: `3px solid ${brand.navyLight}`, outlineOffset: 2 },
        '.MuiAppBar-root :focus-visible, .MuiAppBar-root .Mui-focusVisible': { outlineColor: '#ffffff !important' },
        // reusable motion classes
        '.ekyc-fade-up': { animation: `ekyc-fade-up 420ms ${EASE} both` },
        '.ekyc-step-forward': { animation: `ekyc-step-forward 340ms ${EASE} both` },
        '.ekyc-step-back': { animation: `ekyc-step-back 340ms ${EASE} both` },
        '.ekyc-pop': { animation: `ekyc-pop 420ms ${EASE} both` },
        '.ekyc-lift': {
          transition: `transform 220ms ${EASE}, box-shadow 220ms ${EASE}`,
          transform: 'perspective(900px) rotateX(var(--tilt-x, 0deg)) rotateY(var(--tilt-y, 0deg)) translateY(var(--lift, 0px))',
          willChange: 'transform',
          '&:hover': { '--lift': '-3px', boxShadow: depth.raised },
        },
        '@media (prefers-reduced-motion: reduce)': {
          '*, *::before, *::after': {
            animationDuration: '0.01ms !important', animationDelay: '0s !important', animationIterationCount: '1 !important',
            transitionDuration: '0.01ms !important', scrollBehavior: 'auto !important',
          },
          '.ekyc-lift': { transform: 'none !important' },
        },
      },
    },
    MuiButtonBase: { // buttons, list items, tabs, clickable chips: MUI removes the browser outline, so draw the ring here
      styleOverrides: {
        root: { '&.Mui-focusVisible': { outline: `3px solid ${brand.navyLight}`, outlineOffset: 2 } },
      },
    },
    MuiAppBar: {
      styleOverrides: { root: { backgroundImage: gradients.brand, boxShadow: '0 6px 20px rgba(8, 58, 112, 0.18)' } },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          borderRadius: 10,
          transition: `transform 160ms ${EASE}, box-shadow 160ms ${EASE}, background-color 160ms, border-color 160ms`,
          '&:active': { transform: 'translateY(0) scale(0.98)' },
          variants: [{
            props: { variant: 'contained', color: 'primary' },
            style: {
              backgroundImage: gradients.button,
              '&:hover': { transform: 'translateY(-1px)', boxShadow: '0 6px 16px rgba(11, 79, 156, 0.28)' },
              '&:active': { transform: 'translateY(0) scale(0.98)', boxShadow: 'none' },
              '&.Mui-disabled': { backgroundImage: 'none' },
            },
          }],
        },
      },
    },
    MuiPaper: {
      defaultProps: { variant: 'outlined' },
      styleOverrides: { outlined: { boxShadow: depth.rest, borderColor: '#e3e8f0' } },
    },
    MuiCard: {
      defaultProps: { variant: 'outlined' },
      styleOverrides: { root: { boxShadow: depth.rest, borderColor: '#e3e8f0' } },
    },
    MuiChip: { styleOverrides: { root: { transition: `background-color 200ms, border-color 200ms, color 200ms` } } },
    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: 999, height: 6, backgroundColor: '#e3eaf4' },
        bar: { borderRadius: 999, backgroundImage: `linear-gradient(90deg, ${brand.navy}, ${brand.accent})` },
      },
    },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 650, color: brand.inkSecondary } } },
  },
})
