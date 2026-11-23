// The smart selfie camera's logic (Phase 13), kept free of React and of the detector so that it can be unit tested:
// what to tell the customer about the current frame, the head-turn estimate, and the three-step challenge
// (look at the camera, turn left, turn right) with its automatic captures.
//
// This only GUIDES the customer. Nothing here is trusted: the browser sends the three frames, and the server's
// face-worker decides whether they show a live head turn (src/ekyc/liveness.py, 20 degrees each way).
// Calibration (Phase 13): on 88 real LFW photos the browser's estimate (BlazeFace keypoints) was ~0.87 x the
// server's (YuNet landmarks; correlation 0.96). Asking the browser for 20 degrees therefore means ~23 on the server:
// a turn the browser accepts clears the server's bar, without asking customers to turn further than needed.

export interface Point { x: number; y: number }
export interface FaceBox { x: number; y: number; width: number; height: number }
/** One face found in a frame, in pixels of the UNMIRRORED camera image. Keypoints (BlazeFace): eye, eye, nose tip,
 *  mouth, ear, ear. */
export interface DetectedFace { box: FaceBox; keypoints: Point[] }
export interface FrameSize { width: number; height: number }

export const GUIDE = {
  minFaceWidth: 0.2, // face width / frame width: smaller -> "Move closer"
  maxFaceWidth: 0.65, // larger -> "Move back a little"
  maxOffsetX: 0.15, // face centre this far from the frame centre (share of the width) -> "Centre your face"
  maxOffsetY: 0.2,
  minFaceLuma: 60, // mean brightness of the face (0-255) below this -> "Too dark"
  minFrameLuma: 45, // no face found and the whole frame this dark -> "Too dark" rather than "No face"
  neutralMaxYaw: 12, // degrees: "looking at the camera" (~14 on the server, which allows 15)
  turnDeg: 20, // degrees from the looking-at-the-camera frame (~23 on the server, which needs 20)
  neutralHold: 6, // good detections in a row before the automatic capture (~0.6 s at 10 per second)
  turnHold: 3,
  stepTimeoutMs: 12_000, // after this, a "Take it now" button appears (manual capture fallback)
} as const

export type Problem = 'no_face' | 'several_faces' | 'too_far' | 'too_close' | 'off_centre' | 'too_dark'

export const PROBLEM_TEXT: Record<Problem, string> = {
  no_face: 'No face found: look at the camera',
  several_faces: 'Only one person in the picture, please',
  too_far: 'Move closer',
  too_close: 'Move back a little',
  off_centre: 'Centre your face in the oval',
  too_dark: 'Too dark: find more light',
}

/** What is wrong with this frame for a selfie, or null when it is good. `faceLuma`: mean brightness of the face box
 *  (null when there is no face); `frameLuma`: of the whole frame. Checked in this order: the first problem wins. */
export function frameProblem(faces: DetectedFace[], frame: FrameSize, faceLuma: number | null, frameLuma: number,
  guide = GUIDE): Problem | null {
  if (faces.length === 0) return frameLuma < guide.minFrameLuma ? 'too_dark' : 'no_face'
  if (faces.length > 1) return 'several_faces'
  const { box } = faces[0]
  const share = box.width / frame.width
  if (share < guide.minFaceWidth) return 'too_far'
  if (share > guide.maxFaceWidth) return 'too_close'
  const dx = Math.abs(box.x + box.width / 2 - frame.width / 2) / frame.width
  const dy = Math.abs(box.y + box.height / 2 - frame.height / 2) / frame.height
  if (dx > guide.maxOffsetX || dy > guide.maxOffsetY) return 'off_centre'
  if (faceLuma !== null && faceLuma < guide.minFaceLuma) return 'too_dark'
  return null
}

/** Approximate head yaw in degrees from the eyes, nose tip and mouth (the server's formula, liveness.py): level the
 *  eyes, then atan(nose offset from the eye-mouth midline / (0.5 x eye distance)). Positive = turned to the person's
 *  LEFT (the nose moves to the right of the unmirrored image). null when the keypoints are missing. */
export function estimateYaw(keypoints: Point[], noseDepth = 0.5): number | null {
  if (keypoints.length < 4) return null
  const [a, b, nose, mouth] = keypoints
  const [eyeR, eyeL] = a.x <= b.x ? [a, b] : [b, a] // the person's right eye is on the image's left
  const roll = Math.atan2(eyeL.y - eyeR.y, eyeL.x - eyeR.x)
  const level = (p: Point) => p.x * Math.cos(-roll) - p.y * Math.sin(-roll) // x after levelling the eyes
  const eyeDistance = Math.abs(level(eyeL) - level(eyeR))
  if (eyeDistance < 1e-6) return null
  const midline = ((level(eyeR) + level(eyeL)) / 2 + level(mouth)) / 2
  return (Math.atan((level(nose) - midline) / (noseDepth * eyeDistance)) * 180) / Math.PI
}

export type Pose = 'neutral' | 'left' | 'right'
export type Step = Pose | 'done'

export const PROMPTS: Record<Step, string> = {
  neutral: 'Look straight at the camera',
  left: 'Now turn your head slowly to your left',
  right: 'Now turn your head slowly to your right',
  done: 'Done: thank you',
}

export interface ChallengeState {
  step: Step
  streak: number // good detections in a row for the current step
  neutralYaw: number | null // the head's yaw when it looked at the camera: the turns are measured from it
  stepStartedAt: number // ms, for the manual capture fallback
}

export function startChallenge(now: number): ChallengeState {
  return { step: 'neutral', streak: 0, neutralYaw: null, stepStartedAt: now }
}

export interface Observation { problem: Problem | null; yaw: number | null }

/** One detection result -> the next state, and which pose to capture now (if any). Looking at the camera needs a
 *  good frame (one face, close enough, centred, bright enough) that faces the camera; a turn needs one face turned far
 *  enough from the neutral yaw (it may move off centre while turning). */
export function advance(state: ChallengeState, seen: Observation, now: number,
  guide = GUIDE): { state: ChallengeState; capture: Pose | null } {
  if (state.step === 'done') return { state, capture: null }
  let ok: boolean
  if (state.step === 'neutral') {
    ok = seen.problem === null && seen.yaw !== null && Math.abs(seen.yaw) <= guide.neutralMaxYaw
  } else {
    const oneFace = seen.problem !== 'no_face' && seen.problem !== 'several_faces' && seen.problem !== 'too_dark'
    const turn = seen.yaw === null || state.neutralYaw === null ? 0 : seen.yaw - state.neutralYaw
    ok = oneFace && (state.step === 'left' ? turn >= guide.turnDeg : turn <= -guide.turnDeg)
  }
  const streak = ok ? state.streak + 1 : 0
  if (streak < (state.step === 'neutral' ? guide.neutralHold : guide.turnHold)) {
    return { state: { ...state, streak }, capture: null }
  }
  return capture(state, seen.yaw, now)
}

/** Capture the current step's pose now (automatically, or by the customer's "Take it now" button). */
export function capture(state: ChallengeState, yaw: number | null, now: number): { state: ChallengeState; capture: Pose | null } {
  if (state.step === 'done') return { state, capture: null }
  const pose = state.step
  const next: Step = pose === 'neutral' ? 'left' : pose === 'left' ? 'right' : 'done'
  const neutralYaw = pose === 'neutral' ? (yaw ?? 0) : state.neutralYaw
  return { state: { step: next, streak: 0, neutralYaw, stepStartedAt: now }, capture: pose }
}

/** Mean brightness (0-255, Rec. 601 luma) of RGBA pixels. */
export function meanLuma(rgba: Uint8ClampedArray): number {
  let total = 0
  for (let i = 0; i < rgba.length; i += 4) total += 0.299 * rgba[i] + 0.587 * rgba[i + 1] + 0.114 * rgba[i + 2]
  return rgba.length ? total / (rgba.length / 4) : 0
}
