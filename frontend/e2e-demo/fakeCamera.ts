// A fake webcam for the demo site's Playwright tests (Phase 13): Chromium plays a Motion-JPEG file as the camera
// (--use-file-for-fake-video-capture). The file is built here, when the config loads, from three committed frames
// (fixtures/camera/: the genuine_1 demo selfie looking at the camera, turned left, turned right; the turns are
// SYNTHETIC, made by scripts/make_demo_samples.py): an MJPEG is just JPEG images one after another, so no image
// library is needed. Each pose is held ~2 s (Chromium plays MJPEG files at 30 frames a second) and the video loops.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const FRAMES = path.join(import.meta.dirname, 'fixtures', 'camera')
const POSES = ['neutral', 'left', 'right'] as const
const COPIES = 60 // frames per pose

/** Writes the looping head-turn video into `outDir` (outside test-results/, which Playwright empties) and returns its path. */
export function writeFakeCamera(outDir: string): string {
  mkdirSync(outDir, { recursive: true })
  const file = path.join(outDir, 'head_turn.mjpeg')
  const parts = POSES.flatMap((pose) => Array<Buffer>(COPIES).fill(readFileSync(path.join(FRAMES, `${pose}.jpg`))))
  writeFileSync(file, Buffer.concat(parts))
  return file
}
