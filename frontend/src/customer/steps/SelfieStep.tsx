import ReplayIcon from '@mui/icons-material/Replay'
import { Alert, Box, Button, Grid, Stack, Typography } from '@mui/material'
import { useState } from 'react'
import { ImageDropzone } from '../ImageDropzone'
import type { PickedImage } from '../usePickedImage'
import { WebcamCapture } from '../WebcamCapture'
import { TipList } from './DocumentStep'

const TIPS = [
  'Face the camera with a neutral expression and your eyes open.',
  'Stand in good light, with no strong light behind you.',
  'Remove sunglasses, hats and anything covering your face.',
  'Make sure you are the only person in the photo.',
]

interface Props {
  picked: PickedImage | null
  onCapture: (photo: Blob) => void
  onFile: (file: File) => void
  onClear: () => void
}

/** Camera first; uploading a photo is the fallback (no camera, permission denied) and is always available. */
export function SelfieStep({ picked, onCapture, onFile, onClear }: Props) {
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
        {picked.error && <Alert severity="error" role="alert">{picked.error}</Alert>}
        <Button variant="outlined" startIcon={<ReplayIcon />} onClick={retake}>Retake photo</Button>
      </Stack>
    )
  } else if (mode === 'camera') {
    body = (
      <WebcamCapture onCapture={onCapture} onProblem={(problem) => {
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
