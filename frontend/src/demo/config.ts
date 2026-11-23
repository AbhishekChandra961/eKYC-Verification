// Settings of the static demo site (Phase 11, VITE_DEMO_MODE=true). Every link can be changed at build time with an
// environment variable, without code changes (see the Pages workflow, .github/workflows/pages.yml).
const env = import.meta.env

const REPO = 'https://github.com/AbhishekChandra961/eKYC-Verification'

export const DEMO_LINKS = {
  repo: (env.VITE_DEMO_REPO_URL as string | undefined) || REPO,
  report: (env.VITE_DEMO_REPORT_URL as string | undefined) || `${REPO}/blob/main/docs/report/REPORT.pdf`,
  // PLACEHOLDER: empty until the video is published. An empty link is shown as "coming soon", never as a broken
  // link. Set VITE_DEMO_VIDEO_URL, or edit it here. (The dashboards are part of this site since Phase 12: /dashboards.)
  video: (env.VITE_DEMO_VIDEO_URL as string | undefined) || '',
}

/** The one-click demo logins. No passwords: there is no server and nothing to protect. */
export const DEMO_ACCOUNTS = { CUSTOMER: 'customer@demo.securebank', OFFICER: 'officer@demo.securebank' } as const

/** A replay is sped up so that a case finishes in about this time (never slowed down: a 1 s run stays 1 s). */
export const REPLAY_TARGET_MS = 10_000

/** The banner text (also checked by the Playwright test). */
export const DEMO_BANNER = 'Demo mode: replaying precomputed results from the real pipeline. ' +
  'The full system runs locally (see GitHub + video).'
