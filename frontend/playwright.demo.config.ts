// The static demo site (Phase 11): Playwright against the demo BUILD, served the way GitHub Pages serves it (under
// /eKYC-Verification/, static files only, no backend). Run: npm run e2e:demo (builds first). Chromium headless shell
// (npx playwright install --only-shell chromium). Screenshots for the README go to reports/phase11/screenshots/.
import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { writeFakeCamera } from './e2e-demo/fakeCamera.ts'

const port = 4173
const site = `http://localhost:${port}/eKYC-Verification/`
// Phase 13: the "Try the camera check" page needs a camera; Chromium's fake one plays a synthetic head turn
const fakeCamera = writeFakeCamera(path.join(import.meta.dirname, 'node_modules', '.cache', 'ekyc-fake-camera')) // test-results/ is wiped per run

export default defineConfig({
  testDir: './e2e-demo',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: site,
    viewport: { width: 1366, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    permissions: ['camera'],
    launchOptions: {
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
        `--use-file-for-fake-video-capture=${fakeCamera}`],
    },
  },
  projects: [{ name: 'chromium' }],
  webServer: {
    command: `npm run build:demo && npx vite preview --mode demo --port ${port} --strictPort`,
    url: site,
    reuseExistingServer: false,
    timeout: 180_000,
  },
})
