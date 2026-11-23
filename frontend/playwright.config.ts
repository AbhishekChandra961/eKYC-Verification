// End-to-end test against the WHOLE running system (scripts/run_all.sh: API, orchestrator, workers, Ollama, Docker
// infrastructure). Chromium only. Its fake webcam plays demo_samples/camera/genuine_1_head_turn.y4m (Phase 13: the
// genuine_1 selfie looking at the camera, then SYNTHETICALLY turned left and right), so the smart camera, its head-turn
// challenge and the server's liveness check are tested with a face that matches the ID.
// Run: npm run e2e (after scripts/make_demo_samples.py).
import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
try {
  process.loadEnvFile(path.join(root, '.env')) // demo account logins (DEMO_CUSTOMER_*, DEMO_OFFICER_*)
} catch {
  // no .env: the test reports which variables are missing
}

export default defineConfig({
  testDir: './e2e',
  timeout: 300_000, // one application takes ~25-60 s (the vision model runs one extraction at a time)
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    viewport: { width: 1366, height: 900 },
    reducedMotion: 'reduce', // Phase 14: motion off (prefers-reduced-motion), so screens are deterministic
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    permissions: ['camera'],
    launchOptions: {
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        `--use-file-for-fake-video-capture=${path.join(root, 'demo_samples', 'camera', 'genuine_1_head_turn.y4m')}`,
      ],
    },
  },
  projects: [{ name: 'chromium' }],
  webServer: { command: 'npm run dev', url: 'http://localhost:5173', reuseExistingServer: true, timeout: 60_000 },
})
