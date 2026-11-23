import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import CameraAltIcon from '@mui/icons-material/CameraAlt'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked'
import VideocamIcon from '@mui/icons-material/Videocam'
import { Box, Button, Chip, CircularProgress, Stack, Typography } from '@mui/material'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ProgressRing } from '../motion/ProgressRing'
import { brand } from '../theme'
import type { FaceFinder } from '../vision/faceDetector'
import { cameraProblem, type CameraProblem } from './camera'
import {
  GUIDE, PROBLEM_TEXT, PROMPTS, advance, capture, estimateYaw, frameProblem, meanLuma, startChallenge,
  type ChallengeState, type FaceBox, type Pose, type Problem, type Step,
} from './selfieGuidance'

/** The three camera frames: looking at the camera (this one is the selfie), head turned left, head turned right. */
export interface CameraFrames { neutral: Blob; left: Blob; right: Blob }

interface Props {
  onComplete: (frames: CameraFrames) => void
  onProblem: (problem: { kind: CameraProblem; message: string }) => void
}

type CameraState = 'idle' | 'starting' | 'live'
type GuideState = 'loading' | 'ready' | 'unavailable'
// progress: display only (Phase 14), how close the current step is to its capture, 0-1: the "hold still" count for
// the first pose, then how far the head has turned towards the turn the browser asks for
interface View { step: Step; problem: Problem | null; slow: boolean; progress: number }

const POSES: { pose: Pose; label: string }[] = [
  { pose: 'neutral', label: 'Look at the camera' }, { pose: 'left', label: 'Turn left' }, { pose: 'right', label: 'Turn right' },
]
const DETECT_EVERY_MS = 100 // about 10 checks a second: enough for guidance, light on the CPU
const START: View = { step: 'neutral', problem: null, slow: false, progress: 0 }

/** View-only: how far the current step is towards its capture (rounded, so the view changes at most ~10 times). */
function stepProgress(state: ChallengeState, yaw: number | null): number {
  if (state.step === 'neutral') return Math.round((10 * state.streak) / GUIDE.neutralHold) / 10
  if (state.step === 'done' || yaw === null || state.neutralYaw === null) return state.step === 'done' ? 1 : 0
  const turn = state.step === 'left' ? yaw - state.neutralYaw : state.neutralYaw - yaw
  return Math.round(10 * Math.max(0, Math.min(1, turn / GUIDE.turnDeg))) / 10
}

/** An unmirrored JPEG of the current video frame, at most `maxSide` px. */
function grab(video: HTMLVideoElement, maxSide: number, quality: number): Promise<Blob | null> {
  const scale = Math.min(1, maxSide / Math.max(video.videoWidth, video.videoHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(video.videoWidth * scale)
  canvas.height = Math.round(video.videoHeight * scale)
  canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
}

/** Mean brightness of a region of the video frame (the whole frame when `box` is null), on a tiny canvas. */
function brightness(context: CanvasRenderingContext2D, video: HTMLVideoElement, box: FaceBox | null): number {
  const { x, y, width, height } = box ?? { x: 0, y: 0, width: video.videoWidth, height: video.videoHeight }
  const sx = Math.max(0, x)
  const sy = Math.max(0, y)
  context.drawImage(video, sx, sy, Math.max(1, Math.min(width, video.videoWidth - sx)),
    Math.max(1, Math.min(height, video.videoHeight - sy)), 0, 0, 24, 24)
  return meanLuma(context.getImageData(0, 0, 24, 24).data)
}

/** The smart selfie camera (Phase 13): a mirrored live preview with a face guide that checks each frame in the
 *  browser (one face, close enough, centred, bright enough), then asks the customer to look at the camera, turn
 *  their head left, and turn it right, capturing each pose automatically. A "Take it now" button appears when a step
 *  takes long, and replaces the guide if the face detector cannot load. The frames are unmirrored JPEGs; the server
 *  checks them itself, the browser's guidance is only help. */
export function WebcamCapture({ onComplete, onProblem }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const challenge = useRef<ChallengeState>(startChallenge(0))
  const frames = useRef<Partial<Record<Pose, Blob>>>({})
  const lastYaw = useRef<number | null>(null)
  const onCompleteRef = useRef(onComplete)
  const [state, setState] = useState<CameraState>('idle')
  const [guide, setGuide] = useState<GuideState>('loading')
  const [view, setView] = useState<View>(START)

  useEffect(() => { onCompleteRef.current = onComplete }, [onComplete])

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  useEffect(() => stop, [stop]) // switch the camera off when the customer leaves this step

  /** Keep the frame for `pose`; after the third one, hand all three over and switch the camera off. */
  const keep = useCallback(async (pose: Pose) => {
    const video = videoRef.current
    if (!video) return
    const blob = await grab(video, pose === 'neutral' ? 1280 : 960, pose === 'neutral' ? 0.92 : 0.85)
    if (!blob) return
    frames.current = { ...frames.current, [pose]: blob }
    const { neutral, left, right } = frames.current
    if (neutral && left && right) {
      stop()
      setState('idle')
      onCompleteRef.current({ neutral, left, right })
    }
  }, [stop])

  useEffect(() => { // attach the stream once the <video> element exists
    const video = videoRef.current
    if (state === 'live' && video && streamRef.current) {
      video.srcObject = streamRef.current
      video.play().catch(() => undefined)
    }
  }, [state])

  useEffect(() => { // load the face detector, then check ~10 frames a second until the three poses are captured
    if (state !== 'live') return
    let alive = true
    let timer = 0
    let last = 0
    let finder: FaceFinder | null = null
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 24
    const context = canvas.getContext('2d', { willReadFrequently: true })

    function tick(now: number) {
      if (!alive) return
      timer = requestAnimationFrame(tick)
      const video = videoRef.current
      if (!finder || !context || !video || now - last < DETECT_EVERY_MS || video.readyState < 2 || !video.videoWidth) return
      last = now
      const faces = finder.find(video, now)
      const problem = frameProblem(faces, { width: video.videoWidth, height: video.videoHeight },
        faces.length === 1 ? brightness(context, video, faces[0].box) : null, brightness(context, video, null))
      const yaw = faces.length === 1 ? estimateYaw(faces[0].keypoints) : null
      lastYaw.current = yaw
      const result = advance(challenge.current, { problem, yaw }, now)
      challenge.current = result.state
      if (result.capture) void keep(result.capture)
      const slow = now - result.state.stepStartedAt > GUIDE.stepTimeoutMs
      const progress = stepProgress(result.state, yaw)
      setView((v) => (v.step === result.state.step && v.problem === problem && v.slow === slow && v.progress === progress ? v
        : { step: result.state.step, problem, slow, progress }))
    }

    import('../vision/faceDetector').then((m) => m.loadFaceFinder()).then((loaded) => {
      if (!alive) {
        loaded.close()
        return
      }
      finder = loaded
      setGuide('ready')
      challenge.current = startChallenge(performance.now())
      timer = requestAnimationFrame(tick)
    }).catch(() => {
      if (alive) setGuide('unavailable') // an old browser, or WebAssembly blocked: the customer takes the photos
    })
    return () => {
      alive = false
      cancelAnimationFrame(timer)
      finder?.close()
    }
  }, [state, keep])

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      onProblem({ kind: 'unavailable', message: 'This browser cannot use a camera on this page. Please upload a selfie photo instead.' })
      return
    }
    setState('starting')
    setGuide('loading')
    setView(START)
    frames.current = {}
    challenge.current = startChallenge(performance.now())
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

  function takeNow() { // the manual fallback: capture the current step's pose as it is
    const result = capture(challenge.current, lastYaw.current, performance.now())
    challenge.current = result.state
    setView({ step: result.state.step, problem: null, slow: false, progress: 0 })
    if (result.capture) void keep(result.capture)
  }

  if (state !== 'live') {
    return (
      <Stack spacing={2} sx={{ alignItems: 'center', textAlign: 'center', p: { xs: 2, sm: 4 }, border: 1,
        borderColor: 'divider', borderRadius: 2, bgcolor: 'background.default' }}>
        <VideocamIcon sx={{ fontSize: 48, color: 'primary.main' }} aria-hidden />
        <Typography>
          You will look at the camera, then turn your head to the left and to the right: three photos are taken
          automatically. Your camera is used only for these photos. Nothing is recorded.
        </Typography>
        <Button variant="contained" size="large" onClick={start} disabled={state === 'starting'}
          startIcon={state === 'starting' ? <CircularProgress size={18} color="inherit" /> : <VideocamIcon />}>
          {state === 'starting' ? 'Starting camera…' : 'Turn on camera'}
        </Button>
      </Stack>
    )
  }

  const step = view.step === 'done' ? 'right' : view.step
  const good = guide === 'ready' && view.step === 'neutral' && view.problem === null
  const blocking = view.problem !== null && (view.step === 'neutral' ||
    view.problem === 'no_face' || view.problem === 'several_faces' || view.problem === 'too_dark')
  let hint: string
  if (guide === 'loading') hint = 'Starting the face guide…'
  else if (guide === 'unavailable') hint = 'Automatic capture is not available in this browser: press "Take photo" for each step.'
  else if (blocking && view.problem) hint = PROBLEM_TEXT[view.problem]
  else hint = view.step === 'neutral' ? 'Hold still…' : 'Keep turning, slowly…'
  const doneIndex = POSES.findIndex((p) => p.pose === view.step)

  return (
    <Stack spacing={2} sx={{ alignItems: 'center' }} data-testid="smart-camera">
      <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', justifyContent: 'center' }} aria-label="Camera steps">
        {POSES.map((p, i) => {
          const finished = view.step === 'done' || i < doneIndex
          const current = p.pose === step && !finished
          let icon = <RadioButtonUncheckedIcon />
          if (finished) icon = <CheckCircleIcon className="ekyc-pop" />
          else if (current) icon = <ProgressRing value={view.progress} color="#ffffff" track="rgba(255, 255, 255, 0.35)" />
          return (
            <Chip key={p.pose} size="small" variant={current ? 'filled' : 'outlined'}
              color={finished ? 'success' : current ? 'primary' : 'default'} icon={icon}
              label={`${i + 1}. ${p.label}`} />
          )
        })}
      </Stack>
      <Box sx={{ position: 'relative', width: '100%', maxWidth: 560, borderRadius: 2, overflow: 'hidden', bgcolor: '#000' }}>
        <Box component="video" ref={videoRef} autoPlay playsInline muted aria-label="Camera preview"
          sx={{ display: 'block', width: '100%', transform: 'scaleX(-1)' }} />
        {/* face guide: an oval to centre the face in. It pulses gently while it searches, and turns solid green with
            a soft glow when the frame is good (Phase 14; static for reduced motion) */}
        <Box component="svg" viewBox="0 0 100 75" preserveAspectRatio="none" aria-hidden data-guide={good ? 'good' : 'searching'}
          sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none',
            filter: good ? `drop-shadow(0 0 6px ${brand.good})` : 'none', transition: 'filter 300ms ease' }}>
          <ellipse cx="50" cy="37" rx="17" ry="27" fill="none" stroke={good ? brand.good : '#fff'}
            strokeWidth={good ? 1.2 : 0.6} strokeDasharray={good ? undefined : '2 1.5'}
            style={{ transition: 'stroke 300ms ease, stroke-width 300ms ease',
              animation: good ? 'none' : 'ekyc-pulse 1.6s ease-in-out infinite' }} />
        </Box>
      </Box>
      <Box role="status" aria-live="polite" sx={{ textAlign: 'center' }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', justifyContent: 'center' }}>
          {step === 'left' && view.step !== 'done' && (
            <ArrowBackIcon color="primary" aria-hidden sx={{ animation: 'ekyc-nudge-left 1.2s ease-in-out infinite' }} />
          )}
          <Typography variant="h3" component="p" data-testid="camera-prompt">{PROMPTS[view.step]}</Typography>
          {step === 'right' && view.step !== 'done' && (
            <ArrowForwardIcon color="primary" aria-hidden sx={{ animation: 'ekyc-nudge-right 1.2s ease-in-out infinite' }} />
          )}
        </Stack>
        <Typography variant="body2" color={blocking ? 'warning.main' : 'text.secondary'} data-testid="camera-hint">
          {hint}
        </Typography>
      </Box>
      {(guide !== 'ready' || view.slow) && (
        <Button variant={guide === 'unavailable' ? 'contained' : 'outlined'} size="large" startIcon={<CameraAltIcon />}
          onClick={takeNow}>
          {guide === 'unavailable' ? 'Take photo' : 'Take it now'}
        </Button>
      )}
    </Stack>
  )
}
