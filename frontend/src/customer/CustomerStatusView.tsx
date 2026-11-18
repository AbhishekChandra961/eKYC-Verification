import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import HourglassTopIcon from '@mui/icons-material/HourglassTop'
import ReplayIcon from '@mui/icons-material/Replay'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Alert, AlertTitle, Box, Button, Chip, LinearProgress, Paper, Stack, Step, StepLabel, Stepper, Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { formatDateTime } from '../format'
import type { CustomerStatus } from './customerStatus'

const RESULT_STYLE = {
  verified: { severity: 'success', icon: <CheckCircleIcon /> },
  under_review: { severity: 'info', icon: <HourglassTopIcon /> },
  resubmit: { severity: 'warning', icon: <WarningAmberIcon /> },
  not_verified: { severity: 'error', icon: <ErrorOutlineIcon /> },
} as const

/** The customer's view of one application. It receives ONLY a CustomerStatus (see customerStatus.ts). */
export function CustomerStatusView({ status, live }: { status: CustomerStatus; live: boolean }) {
  const activeStep = status.stage === 'result' ? (status.final ? 3 : 2) : 1
  const resultLabel = status.stage === 'result' ? status.title : 'Result'
  const failed = status.outcome === 'resubmit' || status.outcome === 'not_verified'
  const percent = Math.round((100 * status.progress.completed) / status.progress.total)

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h1" sx={{ mb: 0.5 }}>Identity verification</Typography>
        <Typography color="text.secondary">
          Reference <Box component="span" sx={{ fontFamily: 'monospace' }}>{status.applicationId}</Box>
          {' · '}submitted {formatDateTime(status.submittedAt)}
        </Typography>
      </Box>

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <Stepper activeStep={activeStep} alternativeLabel aria-label="Progress of your application">
          <Step completed><StepLabel>Submitted</StepLabel></Step>
          <Step completed={status.stage === 'result'}><StepLabel>Verifying</StepLabel></Step>
          <Step completed={status.final}>
            <StepLabel error={failed}>{resultLabel}</StepLabel>
          </Step>
        </Stepper>
      </Paper>

      <Box aria-live="polite" aria-atomic="true">
        {status.stage !== 'result' ? (
          <Paper sx={{ p: { xs: 2, sm: 3 } }}>
            <Stack spacing={1.5}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                <Typography variant="h2" component="h2">{status.title}</Typography>
                {live && <Chip size="small" color="secondary" variant="outlined" label="Live updates" />}
              </Stack>
              <Typography>{status.detail}</Typography>
              {status.stage === 'verifying' ? (
                <>
                  <LinearProgress variant="determinate" value={percent}
                    aria-label={`${status.progress.completed} of ${status.progress.total} checks complete`} />
                  <Typography variant="body2" color="text.secondary">
                    {status.progress.completed} of {status.progress.total} checks complete
                  </Typography>
                </>
              ) : (
                <LinearProgress aria-label="Starting the checks" />
              )}
            </Stack>
          </Paper>
        ) : (
          <Alert severity={RESULT_STYLE[status.outcome as keyof typeof RESULT_STYLE]?.severity ?? 'info'}
            icon={RESULT_STYLE[status.outcome as keyof typeof RESULT_STYLE]?.icon} variant="outlined"
            sx={{ bgcolor: 'background.paper', '& .MuiAlert-message': { width: '100%' } }}>
            <AlertTitle sx={{ fontSize: '1.25rem', fontWeight: 650 }}>{status.title}</AlertTitle>
            <Typography sx={{ mb: status.nextSteps.length ? 1.5 : 0 }}>{status.detail}</Typography>
            {status.nextSteps.length > 0 && (
              <>
                <Typography sx={{ fontWeight: 600 }}>What to do:</Typography>
                <Box component="ul" sx={{ mt: 0.5, mb: 2, pl: 3 }}>
                  {status.nextSteps.map((line) => <li key={line}>{line}</li>)}
                </Box>
                <Button component={RouterLink} to="/customer/verify" variant="contained" startIcon={<ReplayIcon />}>
                  Start again
                </Button>
              </>
            )}
          </Alert>
        )}
      </Box>

      <Box>
        <Button component={RouterLink} to="/customer" variant="text">Back to my applications</Button>
      </Box>
    </Stack>
  )
}
