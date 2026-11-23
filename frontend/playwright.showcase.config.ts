// Phase 14 showcase: screenshots of the main screens (before/after the visual polish), short screen recordings of
// the motion (landing background, liveness challenge) for the demo video, and a frame-time measurement of the dot
// field. Motion is ON here (the test configs run with prefers-reduced-motion, so they stay deterministic).
//   npm run showcase                          # -> reports/phase14/after/, reports/phase14/video/, perf.json
//   EKYC_SHOWCASE_DIR=before npm run showcase -- screens   # screenshots only, into reports/phase14/before/
// Two servers: the demo build (static site, like GitHub Pages) and the real app's dev server for its login page
// (no backend needed to show it).
import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { writeFakeCamera } from './e2e-demo/fakeCamera.ts'

const demoPort = 4176
const realPort = 4177
const fakeCamera = writeFakeCamera(path.join(import.meta.dirname, 'node_modules', '.cache', 'ekyc-fake-camera'))

export default defineConfig({
  testDir: './e2e-showcase',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: `http://localhost:${demoPort}/eKYC-Verification/`,
    viewport: { width: 1366, height: 900 },
    reducedMotion: 'no-preference',
    permissions: ['camera'],
    launchOptions: {
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
        `--use-file-for-fake-video-capture=${fakeCamera}`],
    },
  },
  projects: [{ name: 'chromium' }],
  webServer: [
    {
      command: `npm run build:demo && npx vite preview --mode demo --port ${demoPort} --strictPort`,
      url: `http://localhost:${demoPort}/eKYC-Verification/`,
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      command: `npx vite --port ${realPort} --strictPort`,
      url: `http://localhost:${realPort}/login`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
