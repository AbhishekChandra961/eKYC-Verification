// The smart selfie camera's logic (Phase 13): frame guidance, the head-turn estimate and the challenge's automatic
// captures. Pure functions, so no camera or detector is needed.
import { describe, expect, it } from 'vitest'
import {
  GUIDE, PROBLEM_TEXT, PROMPTS, advance, capture, estimateYaw, frameProblem, meanLuma, startChallenge,
  type ChallengeState, type DetectedFace, type Point,
} from './selfieGuidance'

const FRAME = { width: 640, height: 480 }

/** BlazeFace-style keypoints (eye, eye, nose, mouth, ear, ear) of a face whose head is turned by `yaw` degrees
 *  (positive = to the person's left: the nose moves to the right of the image), eye distance 80 px. */
function keypoints(yaw = 0, cx = 320, cy = 220): Point[] {
  const a = (yaw * Math.PI) / 180
  const project = (x: number, y: number, z: number) => ({ x: cx + 80 * (x * Math.cos(a) + z * Math.sin(a)), y: cy + 80 * y })
  return [project(-0.5, 0, 0), project(0.5, 0, 0), project(0, 0.55, 0.5), project(0, 1.1, 0.05),
    project(-1, 0.3, -0.6), project(1, 0.3, -0.6)]
}

function face(width = 200, x = 220, y = 140, yaw = 0): DetectedFace {
  return { box: { x, y, width, height: width * 1.2 }, keypoints: keypoints(yaw, x + width / 2, y + width * 0.45) }
}

describe('frame guidance', () => {
  it('a single, close, centred, bright face is good', () => {
    expect(frameProblem([face()], FRAME, 140, 120)).toBeNull()
  })

  it('names the first problem, in a fixed order', () => {
    expect(frameProblem([], FRAME, null, 120)).toBe('no_face')
    expect(frameProblem([], FRAME, null, 20)).toBe('too_dark') // nothing found in a dark room: say so
    expect(frameProblem([face(), face(120, 40, 40)], FRAME, 140, 120)).toBe('several_faces')
    expect(frameProblem([face(100, 270, 180)], FRAME, 140, 120)).toBe('too_far') // 16 % of the width
    expect(frameProblem([face(480, 80, 10)], FRAME, 140, 120)).toBe('too_close') // 75 %
    expect(frameProblem([face(200, 20, 140)], FRAME, 140, 120)).toBe('off_centre')
    expect(frameProblem([face()], FRAME, 40, 120)).toBe('too_dark') // a dark face in a bright frame (backlight)
  })

  it('every problem has a short instruction for the customer', () => {
    expect(PROBLEM_TEXT.too_far).toBe('Move closer')
    expect(Object.values(PROBLEM_TEXT).every((text) => text.length > 0 && text.length < 50)).toBe(true)
  })

  it('measures brightness as Rec. 601 luma', () => {
    expect(meanLuma(new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255]))).toBeCloseTo(127.5)
    expect(meanLuma(new Uint8ClampedArray([]))).toBe(0)
  })
})

describe('head-turn estimate (same formula as the server)', () => {
  it.each([-35, -20, 0, 20, 35])('tracks a turn of %i degrees', (yaw) => {
    expect(estimateYaw(keypoints(yaw))).toBeCloseTo(yaw, -0.6) // within a few degrees
  })

  it('positive means the person turned to their left', () => {
    expect(estimateYaw(keypoints(25))).toBeGreaterThan(15)
    expect(estimateYaw(keypoints(-25))).toBeLessThan(-15)
  })

  it('does not depend on which eye comes first or on a sideways tilt', () => {
    const k = keypoints(25)
    expect(estimateYaw([k[1], k[0], ...k.slice(2)])).toBeCloseTo(estimateYaw(k) ?? 0)
    const tilt = (p: Point) => ({ x: 320 + (p.x - 320) * Math.cos(0.3) - (p.y - 220) * Math.sin(0.3),
      y: 220 + (p.x - 320) * Math.sin(0.3) + (p.y - 220) * Math.cos(0.3) })
    expect(estimateYaw(k.map(tilt))).toBeCloseTo(estimateYaw(k) ?? 0, 0)
  })

  it('returns null without enough keypoints', () => {
    expect(estimateYaw(keypoints().slice(0, 3))).toBeNull()
  })
})

describe('the head-turn challenge', () => {
  const good = { problem: null, yaw: 1 }

  function run(state: ChallengeState, seen: { problem: null | 'no_face' | 'off_centre'; yaw: number | null }, times: number, now = 0) {
    const captures: string[] = []
    for (let i = 0; i < times; i++) {
      const r = advance(state, seen, now)
      state = r.state
      if (r.capture) captures.push(r.capture)
    }
    return { state, captures }
  }

  it('captures "looking at the camera" after a short hold of good frames', () => {
    let { state, captures } = run(startChallenge(0), good, GUIDE.neutralHold - 1)
    expect(captures).toEqual([])
    ;({ state, captures } = run(state, good, 1))
    expect(captures).toEqual(['neutral'])
    expect(state.step).toBe('left')
    expect(state.neutralYaw).toBe(1)
  })

  it('any bad frame restarts the hold', () => {
    let { state } = run(startChallenge(0), good, GUIDE.neutralHold - 1)
    ;({ state } = run(state, { problem: 'off_centre', yaw: 1 }, 1))
    expect(state.streak).toBe(0)
    expect(run(state, good, GUIDE.neutralHold - 1).captures).toEqual([])
  })

  it('a head already turned is not "looking at the camera"', () => {
    expect(run(startChallenge(0), { problem: null, yaw: GUIDE.neutralMaxYaw + 3 }, 20).captures).toEqual([])
  })

  it('then needs a turn of turnDeg to the left, then to the right, measured from the first pose', () => {
    let { state } = run(startChallenge(0), { problem: null, yaw: -6 }, GUIDE.neutralHold) // looks slightly right
    expect(run(state, { problem: null, yaw: 10 }, 10).captures).toEqual([]) // only 16 degrees from -6
    let captures: string[]
    ;({ state, captures } = run(state, { problem: 'off_centre', yaw: -6 + GUIDE.turnDeg }, GUIDE.turnHold))
    expect(captures).toEqual(['left']) // moving off centre while turning is fine
    expect(run(state, { problem: null, yaw: 30 }, 10).captures).toEqual([]) // left again is not right
    ;({ state, captures } = run(state, { problem: null, yaw: -6 - GUIDE.turnDeg }, GUIDE.turnHold))
    expect(captures).toEqual(['right'])
    expect(state.step).toBe('done')
    expect(advance(state, good, 0).capture).toBeNull() // finished: nothing more
  })

  it('losing the face during a turn restarts its hold', () => {
    const { state } = run(startChallenge(0), good, GUIDE.neutralHold)
    const half = run(state, { problem: null, yaw: 30 }, GUIDE.turnHold - 1).state
    expect(run(half, { problem: 'no_face', yaw: null }, 1).state.streak).toBe(0)
  })

  it('the manual fallback captures the current pose at once', () => {
    let r = capture(startChallenge(0), null, 5)
    expect(r.capture).toBe('neutral')
    expect(r.state).toMatchObject({ step: 'left', neutralYaw: 0, stepStartedAt: 5 })
    r = capture(r.state, 12, 9)
    expect(r.capture).toBe('left')
    r = capture(r.state, -12, 12)
    expect(r.capture).toBe('right')
    expect(capture(r.state, 0, 20).capture).toBeNull()
  })

  it('prompts say what to do, in plain words', () => {
    expect(PROMPTS.left).toMatch(/turn your head slowly to your left/)
    expect(PROMPTS.right).toMatch(/to your right/)
  })
})
