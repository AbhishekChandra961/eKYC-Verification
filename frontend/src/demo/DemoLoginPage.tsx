import ArticleOutlinedIcon from '@mui/icons-material/ArticleOutlined'
import BarChartIcon from '@mui/icons-material/BarChart'
import CodeIcon from '@mui/icons-material/Code'
import GavelIcon from '@mui/icons-material/Gavel'
import PersonOutlineIcon from '@mui/icons-material/PersonOutlined'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutlined'
import {
  Alert, Box, Button, Divider, Grid, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Paper, Stack, Typography,
} from '@mui/material'
import { useState, type ReactNode } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { messageOf } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { homeFor, type Role } from '../auth/session'
import { BrandLogo } from '../components/BrandLogo'
import { DemoAttribution } from './DemoBanner'
import { DEMO_ACCOUNTS, DEMO_LINKS } from './config'

const ROLES: { role: Role; label: string; icon: ReactNode; text: string }[] = [
  { role: 'CUSTOMER', label: 'Try as customer', icon: <PersonOutlineIcon />,
    text: 'Verify your identity with one of six bundled samples (genuine, forged or unusable) and watch the checks run.' },
  { role: 'OFFICER', label: 'Try as officer', icon: <GavelIcon />,
    text: 'Work the review queue: forgery heatmaps, face match, extracted fields, reasons with evidence, audit trail.' },
]

function ResourceLink({ href, icon, label, detail }: { href: string; icon: ReactNode; label: string; detail: string }) {
  if (!href) { // a placeholder link in config.ts: say so instead of showing a broken link
    return (
      <ListItem>
        <ListItemIcon>{icon}</ListItemIcon>
        <ListItemText primary={label} secondary="Coming soon" />
      </ListItem>
    )
  }
  return (
    <ListItem disablePadding>
      <ListItemButton component="a" href={href} target="_blank" rel="noopener">
        <ListItemIcon>{icon}</ListItemIcon>
        <ListItemText primary={label} secondary={detail} />
      </ListItemButton>
    </ListItem>
  )
}

/** The demo site's landing page: one-click logins (no passwords) and links to the project. */
export function DemoLoginPage() {
  const { session, login } = useAuth()
  const navigate = useNavigate()
  const [busy, setBusy] = useState<Role | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (session) return <Navigate to={homeFor(session.role)} replace />

  async function enter(role: Role) {
    setBusy(role)
    setError(null)
    try {
      const next = await login(DEMO_ACCOUNTS[role], '')
      navigate(homeFor(next.role), { replace: true })
    } catch (err) {
      setError(messageOf(err))
      setBusy(null)
    }
  }

  return (
    <Box component="main" sx={{ display: 'grid', placeItems: 'center', p: 2, py: { xs: 3, sm: 6 }, bgcolor: 'background.default' }}>
      <Paper sx={{ width: '100%', maxWidth: 880, p: { xs: 3, sm: 4 } }}>
        <Stack spacing={3}>
          <BrandLogo />
          <Box>
            <Typography variant="h1" sx={{ mb: 1 }}>eKYC verification: live demo</Typography>
            <Typography color="text.secondary">
              A bank onboarding check: an ID document photo and a selfie go through document classification, forgery
              detection, face matching and field extraction, then a rule-based decision. Everything you see here was
              produced by the real pipeline and is replayed in your browser: there is no server behind this page.
            </Typography>
          </Box>
          {error && <Alert severity="error" role="alert">{error}</Alert>}
          <Grid container spacing={2}>
            {ROLES.map((r) => (
              <Grid key={r.role} size={{ xs: 12, sm: 6 }}>
                <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
                  <Stack spacing={1.5} sx={{ height: '100%' }}>
                    <Typography sx={{ flexGrow: 1 }}>{r.text}</Typography>
                    <Button variant="contained" size="large" startIcon={r.icon} disabled={busy !== null}
                      onClick={() => void enter(r.role)}>
                      {busy === r.role ? 'Opening…' : r.label}
                    </Button>
                  </Stack>
                </Paper>
              </Grid>
            ))}
          </Grid>
          <Divider />
          <Box>
            <Typography variant="h2" sx={{ mb: 1 }}>About the project</Typography>
            <List dense disablePadding>
              <ResourceLink href={DEMO_LINKS.repo} icon={<CodeIcon />} label="Source code on GitHub"
                detail="Python microservices over Kafka, TensorFlow models, React frontend; how to run it locally" />
              <ResourceLink href={DEMO_LINKS.video} icon={<PlayCircleOutlineIcon />} label="Demo video"
                detail="The full system running locally, end to end" />
              <ResourceLink href={DEMO_LINKS.dashboards} icon={<BarChartIcon />} label="Tableau dashboards"
                detail="Outcomes, latency and model performance over a 150-application batch" />
              <ResourceLink href={DEMO_LINKS.report} icon={<ArticleOutlinedIcon />} label="Project report (PDF)"
                detail="Data, models, evaluation, architecture, limitations and ethics" />
            </List>
          </Box>
          <DemoAttribution />
        </Stack>
      </Paper>
    </Box>
  )
}
