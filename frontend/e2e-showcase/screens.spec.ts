// The main screens, for the before/after comparison (Phase 14) and the README. Works on the old and the new UI alike:
// it only uses roles, labels and test ids that both have. EKYC_SHOWCASE_DIR picks the folder (default: after).
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const dir = path.resolve(import.meta.dirname, '..', '..', 'reports', 'phase14', process.env.EKYC_SHOWCASE_DIR ?? 'after')
mkdirSync(dir, { recursive: true })
const REAL_LOGIN = 'http://localhost:4177/login'

async function shot(page: Page, name: string, fullPage = false) {
  await page.waitForTimeout(600) // let entrance transitions finish
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage })
}

async function enterAs(page: Page, role: 'customer' | 'officer') {
  await page.goto('./')
  await page.getByRole('button', { name: `Try as ${role}` }).click()
  await expect(page).toHaveURL(new RegExp(`#/${role}$`))
}

test.describe.configure({ mode: 'serial' })

test('landing page and login', async ({ page }) => {
  await page.goto('./')
  await expect(page.getByRole('button', { name: 'Try as customer' })).toBeVisible()
  await shot(page, '01_landing')
  await page.goto(REAL_LOGIN)
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible()
  await shot(page, '02_login')
})

test('customer wizard and status', async ({ page }) => {
  await enterAs(page, 'customer')
  await page.getByRole('link', { name: 'Verify my identity' }).first().click()
  await page.getByRole('button', { name: /Serbian passport, genuine/ }).click()
  await shot(page, '03_wizard_step1')
  for (let step = 0; step < 3; step++) await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('checkbox').check()
  await shot(page, '04_wizard_review')
  await page.getByRole('button', { name: 'Submit' }).click()
  await expect(page.getByText(/of 4 checks complete/).first()).toBeVisible()
  await shot(page, '05_status_verifying')
  await expect(page.getByRole('alert').filter({ hasText: 'Verified' })).toBeVisible({ timeout: 30_000 })
  if (await page.getByTestId('celebration').count()) { // the new UI: catch the celebration mid-flight
    await page.waitForTimeout(450)
    await page.screenshot({ path: path.join(dir, '06a_status_celebration.png') })
  }
  await page.waitForTimeout(2500) // after the celebration
  await shot(page, '06_status_verified')
})

test('camera check: challenge and done', async ({ page }) => {
  await page.goto('./#/camera-check')
  await page.getByRole('button', { name: 'Turn on camera' }).click()
  await expect(page.getByTestId('camera-prompt')).toHaveText(/turn your head slowly to your left/, { timeout: 30_000 })
  await page.screenshot({ path: path.join(dir, '07_camera_turn_left.png') })
  await expect(page.getByTestId('camera-check-done')).toBeVisible({ timeout: 45_000 })
  await shot(page, '08_camera_done')
})

test('officer queue, case and dashboards', async ({ page }) => {
  await enterAs(page, 'officer')
  await expect(page.getByTestId('case-row').first()).toBeVisible()
  await shot(page, '09_officer_queue')
  await page.getByRole('link', { name: 'app-6b6fd4213a30fbe8' }).click()
  await expect(page.getByTestId('forgery-heatmap')).toBeVisible()
  await shot(page, '10_officer_case')
  await page.goto('./#/dashboards')
  await expect(page.getByTestId('kpi').first()).toBeVisible()
  await shot(page, '11_dashboard_operations')
})

test('phone width: landing and camera check', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./')
  await expect(page.getByRole('button', { name: 'Try as customer' })).toBeVisible()
  await shot(page, '12_landing_phone')
})
