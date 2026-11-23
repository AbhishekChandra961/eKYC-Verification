import LogoutIcon from '@mui/icons-material/Logout'
import { AppBar, Box, Button, Chip, Container, Link, Stack, Toolbar, Typography } from '@mui/material'
import { Outlet, Link as RouterLink, useLocation } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import { homeFor } from '../auth/session'
import { DemoAttribution } from '../demo/DemoBanner'
import { BrandLogo } from './BrandLogo'

interface NavItem { to: string; label: string; active: (path: string) => boolean }

const NAV: Record<'CUSTOMER' | 'OFFICER' | 'VISITOR', NavItem[]> = {
  CUSTOMER: [
    { to: '/customer', label: 'My applications', active: (p) => p === '/customer' || p.startsWith('/customer/applications') },
    { to: '/customer/verify', label: 'Verify my identity', active: (p) => p.startsWith('/customer/verify') },
  ],
  OFFICER: [
    { to: '/officer', label: 'Case queue', active: (p) => p === '/officer' || p.startsWith('/officer/cases') },
    { to: '/officer/analytics', label: 'Analytics', active: (p) => p.startsWith('/officer/analytics') },
  ],
  // demo site, not logged in (the public dashboards)
  VISITOR: [
    { to: '/login', label: 'Demo home', active: () => false },
    { to: '/dashboards', label: 'Dashboards', active: (p) => p.startsWith('/dashboards') },
    { to: '/camera-check', label: 'Camera check', active: (p) => p.startsWith('/camera-check') },
  ],
}

export function AppShell() {
  const { session, logout } = useAuth()
  const { pathname } = useLocation()
  const nav = session ? NAV[session.role] : __DEMO_MODE__ ? NAV.VISITOR : []
  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* keyboard users can jump straight past the navigation */}
      <Link href="#main" sx={{ position: 'absolute', left: -9999, '&:focus': { left: 16, top: 8, zIndex: 2000,
        bgcolor: 'background.paper', p: 1, borderRadius: 1 } }}>
        Skip to main content
      </Link>
      <AppBar position="static" elevation={0}>
        <Toolbar sx={{ gap: 2, flexWrap: 'wrap', py: { xs: 1, sm: 0 } }}>
          <Box component={RouterLink} to={session ? homeFor(session.role) : '/login'} aria-label="SecureBank eKYC home"
            sx={{ textDecoration: 'none', mr: 2 }}>
            <BrandLogo inverse />
          </Box>
          {nav.length > 0 && (
            <Box component="nav" aria-label="Main" sx={{ display: 'flex', gap: 0.5, flexGrow: 1, flexWrap: 'wrap' }}>
              {nav.map((item) => {
                const active = item.active(pathname)
                return (
                  <Button key={item.to} component={RouterLink} to={item.to} color="inherit" aria-current={active ? 'page' : undefined}
                    className={active ? 'active' : undefined}
                    sx={{ opacity: 0.85, '&.active': { opacity: 1, textDecoration: 'underline', textUnderlineOffset: 6 } }}>
                    {item.label}
                  </Button>
                )
              })}
            </Box>
          )}
          {session && (
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', ml: 'auto' }}>
              <Chip size="small" label={session.role === 'OFFICER' ? 'Compliance officer' : 'Customer'}
                sx={{ bgcolor: 'rgba(255,255,255,0.15)', color: '#fff', display: { xs: 'none', sm: 'flex' } }} />
              <Typography variant="body2" sx={{ display: { xs: 'none', md: 'block' } }}>{session.email}</Typography>
              <Button color="inherit" startIcon={<LogoutIcon />} onClick={() => logout('user')}>Log out</Button>
            </Stack>
          )}
        </Toolbar>
      </AppBar>
      <Container component="main" id="main" tabIndex={-1} maxWidth="lg" sx={{ py: { xs: 2, sm: 4 }, flexGrow: 1, outline: 'none' }}>
        <Outlet />
      </Container>
      <Box component="footer" sx={{ py: 2, px: 2, textAlign: 'center', color: 'text.secondary', borderTop: 1, borderColor: 'divider' }}>
        <Typography variant="caption">
          SecureBank is a fictional bank (data science capstone demo). Synthetic test documents only.
        </Typography>
        {__DEMO_MODE__ && <DemoAttribution />}
      </Box>
    </Box>
  )
}
