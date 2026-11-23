// The demo site's "Try the camera check" page (Phase 13): the smart selfie camera runs in the browser with Chromium's
// fake webcam (a synthetic head turn, e2e-demo/fakeCamera.ts): the face guide finds the face, the three poses are
// captured automatically, and nothing leaves the browser (no upload, no CDN). Screenshots go to reports/phase13/.
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const shots = path.resolve(import.meta.dirname, '..', '..', 'reports', 'phase13')
mkdirSync(shots, { recursive: true })

/** Every request that leaves the site, and every request that would send data (an upload). */
function watchRequests(page: Page, site: string) {
  const outside: string[] = []
  const sending: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (!url.startsWith(site) && !url.startsWith('data:') && !url.startsWith('blob:')) outside.push(url)
    if (request.method() !== 'GET') sending.push(`${request.method()} ${url}`)
  })
  return { outside, sending }
}

test('camera check: guidance, then look / turn left / turn right captured automatically, nothing uploaded', async ({ page, baseURL }) => {
  const traffic = watchRequests(page, new URL(baseURL ?? '').origin)
  await page.goto('./')
  await page.getByRole('link', { name: /Try the camera check/ }).click()
  await expect(page).toHaveURL(/#\/camera-check$/)
  await expect(page.getByTestId('camera-check-note')).toContainText('nothing is uploaded')

  await page.getByRole('button', { name: 'Turn on camera' }).click()
  const camera = page.getByTestId('smart-camera')
  await expect(camera).toBeVisible()
  await page.waitForFunction(() => (document.querySelector('video')?.videoWidth ?? 0) > 0)
  await expect(page.getByTestId('camera-hint')).not.toHaveText('Starting the face guide…', { timeout: 30_000 })
  // the guide found the face and captured the first pose: now it asks for the turns
  await expect(page.getByTestId('camera-prompt')).toHaveText(/turn your head slowly to your left/, { timeout: 30_000 })
  await page.screenshot({ path: path.join(shots, '01_camera_check_turn_left.png'), animations: 'disabled' })

  const started = Date.now()
  await expect(page.getByTestId('camera-check-done')).toContainText(
    'Liveness challenge completed (browser preview; the real system verifies on the server)', { timeout: 45_000 })
  console.log(`head turns captured ${((Date.now() - started) / 1000).toFixed(1)} s after the first pose`)
  for (const pose of ['looking at the camera', 'turned left', 'turned right']) {
    await expect(page.getByAltText(`Your photo: ${pose}`)).toBeVisible()
  }
  await expect(page.getByTestId('smart-camera')).toHaveCount(0) // the camera is off again
  await page.screenshot({ path: path.join(shots, '02_camera_check_done.png'), fullPage: true, animations: 'disabled' })

  expect(traffic.outside).toEqual([]) // the detector and its model come from the site itself
  expect(traffic.sending).toEqual([]) // nothing uploaded
})

test('camera check at phone width: the guide still fits and completes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./#/camera-check')
  await page.getByRole('button', { name: 'Turn on camera' }).click()
  await expect(page.getByTestId('camera-prompt')).toHaveText(/turn your head slowly to your left/, { timeout: 30_000 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  await page.screenshot({ path: path.join(shots, '03_camera_check_phone.png'), fullPage: true, animations: 'disabled' })
  await expect(page.getByTestId('camera-check-done')).toBeVisible({ timeout: 45_000 })
})
