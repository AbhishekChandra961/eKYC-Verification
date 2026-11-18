import CameraAltIcon from '@mui/icons-material/CameraAlt'
import VideocamIcon from '@mui/icons-material/Videocam'
import { Box, Button, CircularProgress, Stack, Typography } from '@mui/material'
import { useCallback, useEffect, useRef, useState } from 'react'
import { cameraProblem, type CameraProblem } from './camera'

type CameraState = 'idle' | 'starting' | 'live'

interface Props {
  onCapture: (photo: Blob) => void
  onProblem: (problem: { kind: CameraProblem; message: string }) => void
}

/** Live camera preview (mirrored, like a mirror) with a face guide; "Take photo" saves an unmirrored JPEG. */
export function WebcamCapture({ onCapture, onProblem }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [state, setState] = useState<CameraState>('idle')

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  useEffect(() => stop, [stop]) // switch the camera off when the customer leaves this step

  useEffect(() => { // attach the stream once the <video> element exists
    const video = videoRef.current
    if (state === 'live' && video && streamRef.current) {
      video.srcObject = streamRef.current
      video.play().catch(() => undefined)
    }
  }, [state])

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      onProblem({ kind: 'unavailable', message: 'This browser cannot use a camera on this page. Please upload a selfie photo instead.' })
      return
    }
    setState('starting')
    try {
      streamRef.current = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
      })
      setState('live')
    } catch (error) {
      setState('idle')
      onProblem(cameraProblem(error))
    }
  }

  function capture() {
    const video = videoRef.current
    if (!video || !video.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')?.drawImage(video, 0, 0)
    canvas.toBlob((blob) => {
      if (!blob) return
      stop()
      setState('idle')
      onCapture(blob)
    }, 'image/jpeg', 0.92)
  }

  if (state !== 'live') {
    return (
      <Stack spacing={2} sx={{ alignItems: 'center', textAlign: 'center', p: { xs: 2, sm: 4 }, border: 1,
        borderColor: 'divider', borderRadius: 2, bgcolor: 'background.default' }}>
        <VideocamIcon sx={{ fontSize: 48, color: 'primary.main' }} aria-hidden />
        <Typography>Your camera is used only to take this photo. Nothing is recorded.</Typography>
        <Button variant="contained" size="large" onClick={start} disabled={state === 'starting'}
          startIcon={state === 'starting' ? <CircularProgress size={18} color="inherit" /> : <VideocamIcon />}>
          {state === 'starting' ? 'Starting camera…' : 'Turn on camera'}
        </Button>
      </Stack>
    )
  }

  return (
    <Stack spacing={2} sx={{ alignItems: 'center' }}>
      <Box sx={{ position: 'relative', width: '100%', maxWidth: 560, borderRadius: 2, overflow: 'hidden', bgcolor: '#000' }}>
        <Box component="video" ref={videoRef} autoPlay playsInline muted aria-label="Camera preview"
          sx={{ display: 'block', width: '100%', transform: 'scaleX(-1)' }} />
        {/* face guide: an oval to centre the face in */}
        <Box component="svg" viewBox="0 0 100 75" preserveAspectRatio="none" aria-hidden
          sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
          <ellipse cx="50" cy="37" rx="17" ry="27" fill="none" stroke="#fff" strokeWidth="0.6" strokeDasharray="2 1.5" />
        </Box>
      </Box>
      <Typography variant="body2" color="text.secondary">Centre your face in the oval and look at the camera.</Typography>
      <Button variant="contained" size="large" startIcon={<CameraAltIcon />} onClick={capture}>Take photo</Button>
    </Stack>
  )
}
