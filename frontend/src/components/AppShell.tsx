import LogoutIcon from '@mui/icons-material/Logout'
import { AppBar, Box, Button, Chip, Container, Link, Stack, Toolbar, Typography } from '@mui/material'
import { NavLink, Outlet, Link as RouterLink } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import { homeFor } from '../auth/session'
import { DemoAttribution } from '../demo/DemoBanner'
import { BrandLogo } from './BrandLogo'

const NAV = {
  CUSTOMER: [
    { to: '/customer', label: 'My applications', end: true },
    { to: '/customer/verify', label: 'Verify my identity', end: false },
  ],
  OFFICER: [{ to: '/officer', label: 'Case queue', end: false }],
}

export function AppShell() {
  const { session, logout } = useAuth()
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
          {session && (
            <Box component="nav" aria-label="Main" sx={{ display: 'flex', gap: 0.5, flexGrow: 1 }}>
              {NAV[session.role].map((item) => (
                <Button key={item.to} component={NavLink} to={item.to} end={item.end} color="inherit"
                  sx={{ opacity: 0.85, '&.active': { opacity: 1, textDecoration: 'underline', textUnderlineOffset: 6 } }}>
                  {item.label}
                </Button>
              ))}
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
