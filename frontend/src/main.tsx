import { CssBaseline, ThemeProvider } from '@mui/material'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppRouter, AppRoutes } from './AppRoutes'
import { AuthProvider } from './auth/AuthProvider'
import { DemoBanner } from './demo/DemoBanner'
import { theme } from './theme'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AuthProvider>
        <AppRouter>
          {__DEMO_MODE__ && <DemoBanner />}
          <AppRoutes />
        </AppRouter>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
)
