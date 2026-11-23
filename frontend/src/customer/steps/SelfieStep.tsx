import ReplayIcon from '@mui/icons-material/Replay'
import { Alert, Box, Button, Chip, Grid, Stack, Typography } from '@mui/material'
import { useState } from 'react'
import { AnimatedCheck } from '../../motion/AnimatedCheck'
import { ImageDropzone } from '../ImageDropzone'
import type { PickedImage } from '../usePickedImage'
import { WebcamCapture, type CameraFrames } from '../WebcamCapture'
import { TipList } from './DocumentStep'

const TIPS = [
  'Face the camera with a neutral expression and your eyes open.',
  'When asked, turn your head slowly to the left, then to the right, and back.',
  'Stand in good light, with no strong light behind you.',
  'Remove sunglasses, hats and anything covering your face.',
  'Make sure you are the only person in the picture.',
]

interface Props {
  picked: PickedImage | null
  headTurns: boolean // the camera's head-turn photos were taken (Phase 13)
  onCapture: (frames: CameraFrames) => void
  onFile: (file: File) => void
  onClear: () => void
}

/** Camera first (the smart camera: guidance, then look / turn left / turn right); uploading a photo is the fallback
 *  (no camera, permission denied) and is always available. */
export function SelfieStep({ picked, headTurns, onCapture, onFile, onClear }: Props) {
  const [mode, setMode] = useState<'camera' | 'upload'>('camera')
  const [cameraMessage, setCameraMessage] = useState<string | null>(null)

  function retake() {
    onClear()
    setMode('camera')
    setCameraMessage(null)
  }

  let body
  if (picked && mode === 'camera') {
    body = (
      <Stack spacing={2} sx={{ alignItems: 'center' }}>
        <Box component="img" src={picked.url} alt="Your selfie"
          sx={{ width: '100%', maxWidth: 420, borderRadius: 2, boxShadow: 1 }} />
        {headTurns && (
          <Chip color="success" variant="outlined" label="Head-turn photos taken"
            icon={<Box sx={{ display: 'flex', ml: 0.5 }}><AnimatedCheck size={20} color="#1e6b34" /></Box>} />
        )}
        {picked.error && <Alert severity="error" role="alert">{picked.error}</Alert>}
        <Button variant="outlined" startIcon={<ReplayIcon />} onClick={retake}>Retake photo</Button>
      </Stack>
    )
  } else if (mode === 'camera') {
    body = (
      <WebcamCapture onComplete={onCapture} onProblem={(problem) => {
        setCameraMessage(problem.message)
        setMode('upload')
      }} />
    )
  } else {
    body = (
      <Stack spacing={2}>
        {cameraMessage && <Alert severity="info">{cameraMessage}</Alert>}
        <ImageDropzone label="Selfie photo" previewAlt="Preview of your selfie" picked={picked} onFile={onFile} onClear={onClear} />
      </Stack>
    )
  }

  return (
    <Grid container spacing={3}>
      <Grid size={{ xs: 12, md: 7 }}>
        <Stack spacing={2}>
          {body}
          <Typography variant="body2" sx={{ textAlign: 'center' }}>
            {mode === 'camera' ? (
              <Button variant="text" size="small" onClick={() => { onClear(); setMode('upload') }}>
                Upload a photo instead
              </Button>
            ) : (
              <Button variant="text" size="small" onClick={retake}>Use my camera instead</Button>
            )}
          </Typography>
        </Stack>
      </Grid>
      <Grid size={{ xs: 12, md: 5 }}>
        <TipList title="Tips for a good selfie" tips={TIPS} />
      </Grid>
    </Grid>
  )
}
