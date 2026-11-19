// Backup footage for the demo video (Phase 10): the same end-to-end flows as playwright.config.ts (e2e/kyc-flow.spec.ts),
// but in a visible browser, slowed down, with video recording on. Needs the whole system in host mode
// (scripts/run_all.sh) and demo_samples/. Run: npm run record
// Videos: ../reports/phase10/video/raw/<test>/video.webm (gitignored; docs/DEMO_SCRIPT.md says how they are renamed).
import { defineConfig } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'
import base from './playwright.config.ts'

const root = path.resolve(import.meta.dirname, '..')
// the spec saves screenshots as it goes: keep the Phase 8 report's screenshots untouched
process.env.EKYC_SCREENSHOTS ??= path.join(os.tmpdir(), 'ekyc-record-screenshots')

export default defineConfig({
  ...base,
  outputDir: path.join(root, 'reports', 'phase10', 'video', 'raw'),
  reporter: [['list']],
  use: {
    ...base.use,
    headless: false,
    video: { mode: 'on', size: { width: 1366, height: 900 } },
    trace: 'off',
    launchOptions: { ...base.use?.launchOptions, slowMo: 350 }, // ms between actions, so a viewer can follow
  },
})
