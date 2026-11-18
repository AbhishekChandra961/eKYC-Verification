import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { messageOf } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { homeFor, type Role } from '../auth/session'
import { BrandLogo } from '../components/BrandLogo'

/** After login, go back to the page the user asked for if it belongs to their role; otherwise to their home. */
function target(from: unknown, role: Role): string {
  const home = homeFor(role)
  return typeof from === 'string' && from.startsWith(home) ? from : home
}

export function LoginPage() {
  const { session, login, logoutReason } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: unknown } | null)?.from
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (session) return <Navigate to={target(from, session.role)} replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const next = await login(email.trim(), password)
      navigate(target(from, next.role), { replace: true })
    } catch (err) {
      setError(messageOf(err))
      setBusy(false)
    }
  }

  return (
    <Box component="main" sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 2, bgcolor: 'background.default' }}>
      <Paper sx={{ width: '100%', maxWidth: 420, p: { xs: 3, sm: 4 } }}>
        <Stack spacing={3} component="form" onSubmit={submit} noValidate aria-labelledby="login-title">
          <BrandLogo />
          <Box>
            <Typography id="login-title" variant="h1" sx={{ mb: 0.5 }}>Log in</Typography>
            <Typography color="text.secondary">Verify your identity online, or review cases as an officer.</Typography>
          </Box>
          {logoutReason === 'expired' && (
            <Alert severity="info">Your session has expired. Please log in again.</Alert>
          )}
          {error && <Alert severity="error" role="alert">{error}</Alert>}
          <TextField label="Email" type="email" autoComplete="username" required
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <TextField label="Password" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <Button type="submit" variant="contained" size="large" disabled={busy || !email || !password}>
            {busy ? 'Logging in…' : 'Log in'}
          </Button>
          <Typography variant="body2" color="text.secondary">
            Demo: use the customer or officer account configured in the project's <code>.env</code> file.
          </Typography>
        </Stack>
      </Paper>
    </Box>
  )
}
