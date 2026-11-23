// The demo site's "Try the camera check" page (Phase 13): the real smart selfie camera (guidance + head-turn
// challenge) running entirely in this browser. Nothing is uploaded or stored: there is no server behind the demo site,
// and the frames are discarded when the visitor leaves. The rest of the demo stays replay-only.
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import ReplayIcon from '@mui/icons-material/Replay'
import { Alert, Box, Button, Grid, Paper, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { WebcamCapture, type CameraFrames } from '../customer/WebcamCapture'
import { AnimatedCheck } from '../motion/AnimatedCheck'

const TITLES = { neutral: 'Looking at the camera', left: 'Turned left', right: 'Turned right' } as const

type FrameUrls = Record<keyof CameraFrames, string>

export function CameraCheckPage() {
  const [urls, setUrls] = useState<FrameUrls | null>(null) // local previews of the captured frames
  const [problem, setProblem] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0) // a new WebcamCapture for each try

  useEffect(() => () => { // free the previews when they are replaced or the page closes
    if (urls) Object.values(urls).forEach((url) => URL.revokeObjectURL(url))
  }, [urls])

  function completed(frames: CameraFrames) {
    setUrls({ neutral: URL.createObjectURL(frames.neutral), left: URL.createObjectURL(frames.left),
      right: URL.createObjectURL(frames.right) })
  }

  return (
    <Stack spacing={3} className="ekyc-fade-up">
      <Box>
        <Typography variant="h1" sx={{ mb: 0.5 }}>Try the camera check</Typography>
        <Typography color="text.secondary">
          The selfie step of the real app: a face guide checks each camera frame, then asks you to look at the camera and
          turn your head left and right, and takes the three photos automatically.
        </Typography>
      </Box>
      <Alert severity="info" icon={<InfoOutlinedIcon />} data-testid="camera-check-note">
        Everything runs in your browser: the face detector (MediaPipe) is part of this site, and nothing is uploaded or
        stored. The photos stay in this tab and are gone when you leave. In the real system the server checks the
        head turn itself; the browser only guides.
      </Alert>
      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        {urls ? (
          <Stack spacing={2}>
            <Alert severity="success" icon={<AnimatedCheck size={24} color="#1e6b34" />} data-testid="camera-check-done"
              className="ekyc-fade-up">
              Liveness challenge completed (browser preview; the real system verifies on the server).
            </Alert>
            <Grid container spacing={2}>
              {(Object.keys(TITLES) as (keyof CameraFrames)[]).map((pose) => (
                <Grid key={pose} size={{ xs: 12, sm: 4 }}>
                  <Box component="figure" sx={{ m: 0 }}>
                    {/* mirrored like the preview, so the turns look the way the visitor made them */}
                    <Box component="img" src={urls[pose]} alt={`Your photo: ${TITLES[pose].toLowerCase()}`}
                      sx={{ width: '100%', borderRadius: 1, display: 'block', transform: 'scaleX(-1)' }} />
                    <Typography component="figcaption" variant="body2" sx={{ mt: 0.5 }}>{TITLES[pose]}</Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
            <Box>
              <Button variant="outlined" startIcon={<ReplayIcon />}
                onClick={() => { setUrls(null); setAttempt((a) => a + 1) }}>Try again</Button>
            </Box>
          </Stack>
        ) : (
          <Stack spacing={2}>
            {problem && <Alert severity="warning" role="alert">{problem}</Alert>}
            <WebcamCapture key={attempt} onComplete={completed} onProblem={(p) => setProblem(p.message)} />
          </Stack>
        )}
      </Paper>
    </Stack>
  )
}
