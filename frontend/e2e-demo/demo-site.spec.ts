// The static demo site (Phase 11), built and served like GitHub Pages: the customer replays a bundled sample, the
// officer works a precomputed case. Every request must stay on the site itself: there is no backend to call.
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const shots = path.resolve(import.meta.dirname, '..', '..', 'reports', 'phase11', 'screenshots')
mkdirSync(shots, { recursive: true })
const BANNER = 'Demo mode: replaying precomputed results from the real pipeline.'

/** Records every request that leaves the site (an API call, a CDN, anything): the test expects none. */
function watchRequests(page: Page, site: string): string[] {
  const outside: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (!url.startsWith(site) && !url.startsWith('data:') && !url.startsWith('blob:')) outside.push(url)
  })
  return outside
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(shots, `${name}.png`), animations: 'disabled' })
}

async function enterAs(page: Page, role: 'customer' | 'officer') {
  await page.goto('./')
  await expect(page.getByTestId('demo-banner')).toContainText(BANNER)
  await page.getByRole('button', { name: `Try as ${role}` }).click()
  await expect(page).toHaveURL(new RegExp(`#/${role}$`))
}

test.describe.configure({ mode: 'serial' })

test('landing page: banner, one-click logins and project links', async ({ page, baseURL }) => {
  const outside = watchRequests(page, new URL(baseURL ?? '').origin)
  await page.goto('./')
  await expect(page.getByTestId('demo-banner')).toContainText(BANNER)
  await expect(page.getByRole('link', { name: /Source code on GitHub/ })).toHaveAttribute('href', /github\.com/)
  await expect(page.getByRole('link', { name: /Project report/ })).toBeVisible()
  await expect(page.getByText('Coming soon')).toHaveCount(2) // video and dashboards: placeholders until published
  await expect(page.getByText(/CC BY-SA 4\.0/)).toBeVisible()
  await shot(page, '01_demo_landing')
  expect(outside).toEqual([])
})

test('customer: picks a genuine sample, watches the replay, is verified', async ({ page, baseURL }) => {
  const outside = watchRequests(page, new URL(baseURL ?? '').origin)
  await enterAs(page, 'customer')
  await page.getByRole('link', { name: 'Verify my identity' }).first().click()
  await expect(page.getByRole('heading', { name: /Step 1 of 4/ })).toBeVisible()

  await page.getByRole('button', { name: 'Continue' }).click() // nothing chosen yet: refused
  await expect(page.getByText('Please choose a sample to continue.')).toBeVisible()
  await page.getByRole('button', { name: /Serbian passport, genuine/ }).click()
  await expect(page.getByTestId('demo-details')).toContainText('LIDIJA NIKOLIĆ')
  await shot(page, '02_demo_sample_picker')
  await page.getByRole('button', { name: 'Continue' }).click()

  await expect(page.getByRole('heading', { name: /Step 2 of 4/ })).toBeVisible()
  await expect(page.getByText(/uploads and the camera are turned off/)).toBeVisible()
  await expect(page.getByLabel('ID document photo')).toHaveCount(0) // no file input in demo mode
  await expect(page.getByAltText('Preview of your ID document')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: /Step 3 of 4/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Turn on camera' })).toHaveCount(0) // the camera is never used
  await expect(page.getByAltText('Your selfie')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()

  await expect(page.getByRole('heading', { name: /Step 4 of 4/ })).toBeVisible()
  await page.getByRole('checkbox').check()
  const started = Date.now()
  await page.getByRole('button', { name: 'Submit' }).click()
  await expect(page).toHaveURL(/#\/customer\/applications\/app-[0-9a-f]+-replay-1$/)
  await expect(page.getByTestId('demo-replay-note')).toContainText('Demo replay of a real run')
  await expect(page.getByText(/of 4 checks complete/).first()).toBeVisible()
  await shot(page, '03_demo_replay_verifying')
  await expect(page.getByRole('alert').filter({ hasText: 'Verified' })).toBeVisible({ timeout: 20_000 })
  const seconds = (Date.now() - started) / 1000
  console.log(`replay finished after ${seconds.toFixed(1)} s`)
  expect(seconds).toBeLessThan(16) // sped up to ~10 s
  await expect(page.locator('main')).not.toContainText(/score|forgery|risk|flag|mismatch|confidence/i)
  await shot(page, '04_demo_replay_verified')

  await page.getByRole('link', { name: 'My applications', exact: true }).click()
  await expect(page.getByRole('table', { name: 'My applications' })).toContainText('Verified')
  expect(outside).toEqual([])
})

test('customer: a forged sample ends under review, with no fraud signals shown', async ({ page }) => {
  await enterAs(page, 'customer')
  await page.getByRole('link', { name: 'Verify my identity' }).first().click()
  await page.getByRole('button', { name: /Azerbaijani passport, forged/ }).click()
  await expect(page.getByTestId('demo-details')).toContainText('FAMILA FERNANDO')
  for (let step = 0; step < 3; step++) await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Submit' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Under review by our team' })).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('main')).not.toContainText(/score|forgery|risk|flag|mismatch|confidence/i)
})

test('officer: opens the forged sample case, rejects it in the browser only', async ({ page, baseURL }) => {
  const outside = watchRequests(page, new URL(baseURL ?? '').origin)
  await enterAs(page, 'officer')
  const rows = page.getByTestId('case-row')
  await expect(rows.first()).toContainText('High risk') // highest risk first
  expect(await rows.count()).toBeGreaterThanOrEqual(5) // awaiting an officer: 2 demo samples + 3 batch cases
  await shot(page, '05_demo_officer_queue')

  await page.getByRole('link', { name: 'app-6b6fd4213a30fbe8' }).click() // forged_1's real run
  await expect(page.getByTestId('forgery-heatmap')).toBeVisible()
  await expect(page.getByTestId('forgery-top-tile')).toBeVisible()
  await expect(page.getByText('Forgery suspected').first()).toBeVisible()
  await expect(page.getByText('Official summary')).toBeVisible()
  await shot(page, '06_demo_officer_case')

  await page.getByRole('button', { name: 'Reject' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('kept in this browser tab only')
  await dialog.getByLabel(/Reason/).fill('Surname area edited (heatmap top tile) and the selfie does not match.')
  await dialog.getByRole('button', { name: 'Reject' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Awaiting officer → Rejected')).toBeVisible()
  await expect(page.getByText(/demo-visitor \(this browser tab only\)/)).toBeVisible()

  await page.reload() // the decision lived in this tab's memory only
  await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()
  await expect(page.getByText('Awaiting officer → Rejected')).toHaveCount(0)
  expect(outside).toEqual([])
})

test('officer: "Waiting" is shown at the time of recording, whatever today\'s date', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2031-06-01T12:00:00Z')) // a visitor years after the recording
  await enterAs(page, 'officer')
  await expect(page.getByRole('columnheader', { name: /Waiting/ })).toContainText('at time of recording')
  await expect(page.getByText(/waiting times at time of recording/)).toBeVisible()
  const forged = page.getByTestId('case-row').filter({ hasText: 'app-6b6fd4213a30fbe8' })
  const waiting = forged.getByRole('cell').last()
  // recorded the same day as the run: seconds, minutes or hours, never the ~4.5 years to the fake "today"
  await expect(waiting).toHaveText(/^(\d+ s|\d+ min|\d+ h \d{2} min)$/)
})
