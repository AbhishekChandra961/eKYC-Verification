// One end-to-end flow through the real system, saving a screenshot of every main screen for the report:
//   customer: genuine sample (webcam) -> "Verified"; forged sample (upload) -> "Under review"; blank -> "Please resubmit"
//   officer:  queue -> the forged case -> heatmap -> reject with a reason -> audit trail
import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..', '..')
const samplesDir = path.join(root, 'demo_samples')
const shots = path.join(root, 'reports', 'phase8', 'screenshots')

interface Sample { name: string; id_image: string; selfie: string; full_name: string; date_of_birth: string }
const samples: Record<string, Sample> = Object.fromEntries(
  (JSON.parse(readFileSync(path.join(samplesDir, 'manifest.json'), 'utf8')) as Sample[]).map((s) => [s.name, s]))

function account(role: 'CUSTOMER' | 'OFFICER') {
  const email = process.env[`DEMO_${role}_EMAIL`]
  const password = process.env[`DEMO_${role}_PASSWORD`]
  if (!email || !password) throw new Error(`DEMO_${role}_EMAIL / DEMO_${role}_PASSWORD missing in .env`)
  return { email, password }
}

async function shot(page: Page, name: string, fullPage = true) {
  await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage, animations: 'disabled' })
}

async function login(page: Page, role: 'CUSTOMER' | 'OFFICER') {
  const { email, password } = account(role)
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page).toHaveURL(role === 'OFFICER' ? /\/officer$/ : /\/customer$/)
}

async function fillDetailsAndDocument(page: Page, sample: Sample, screenshots: boolean) {
  await page.getByRole('link', { name: 'Verify my identity' }).first().click()
  await expect(page.getByRole('heading', { name: /Step 1 of 4/ })).toBeVisible()
  await page.getByLabel('Full name').fill(sample.full_name)
  await page.getByLabel('Date of birth').fill(sample.date_of_birth)
  if (screenshots) await shot(page, '03_wizard_1_details')
  await page.getByRole('button', { name: 'Continue' }).click()

  await expect(page.getByRole('heading', { name: /Step 2 of 4/ })).toBeVisible()
  await page.getByLabel('ID document photo').setInputFiles(path.join(samplesDir, sample.id_image))
  await expect(page.getByAltText('Preview of your ID document')).toBeVisible()
  if (screenshots) await shot(page, '04_wizard_2_document')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: /Step 3 of 4/ })).toBeVisible()
}

async function reviewAndSubmit(page: Page, screenshots: boolean): Promise<{ applicationId: string; submittedAt: number }> {
  await expect(page.getByRole('heading', { name: /Step 4 of 4/ })).toBeVisible()
  await page.getByRole('checkbox').check()
  if (screenshots) await shot(page, '06_wizard_4_review')
  const submittedAt = Date.now()
  await page.getByRole('button', { name: 'Submit' }).click()
  await expect(page).toHaveURL(/\/customer\/applications\/app-[0-9a-f]+$/)
  return { applicationId: page.url().split('/').pop() ?? '', submittedAt }
}

async function resultAlert(page: Page, title: string, timeout = 240_000) {
  const alert = page.getByRole('alert').filter({ hasText: title })
  await expect(alert).toBeVisible({ timeout })
  return alert
}

/** The customer must never see fraud signals, whatever the outcome. */
async function expectNoFraudSignals(page: Page) {
  await expect(page.locator('main')).not.toContainText(/score|forgery|risk|flag|mismatch|confidence/i)
}

test.describe.configure({ mode: 'serial' })
let forgedId = ''

test('customer: genuine sample with a webcam selfie is verified', async ({ page }) => {
  await page.goto('/login')
  await shot(page, '01_login')
  await login(page, 'CUSTOMER')
  await shot(page, '02_my_applications_before')
  await fillDetailsAndDocument(page, samples.genuine_1, true)

  await page.getByRole('button', { name: 'Turn on camera' }).click()
  await expect(page.getByRole('button', { name: 'Take photo' })).toBeVisible()
  await page.waitForFunction(() => (document.querySelector('video')?.videoWidth ?? 0) > 0)
  await shot(page, '05_wizard_3_selfie_camera')
  await page.getByRole('button', { name: 'Take photo' }).click()
  await expect(page.getByAltText('Your selfie')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()

  const { applicationId, submittedAt } = await reviewAndSubmit(page, true)
  await expect(page.getByText(/of 4 checks complete/).first()).toBeVisible()
  await shot(page, '07_status_verifying')
  await resultAlert(page, 'Verified')
  console.log(`genuine ${applicationId}: Verified after ${((Date.now() - submittedAt) / 1000).toFixed(1)} s`)
  await expectNoFraudSignals(page)
  await shot(page, '08_status_verified')
  await page.setViewportSize({ width: 390, height: 844 })
  await shot(page, '16_mobile_status_verified')
  await page.setViewportSize({ width: 1366, height: 900 })
})

test('customer: forged sample with a stranger selfie goes to review', async ({ page }) => {
  await login(page, 'CUSTOMER')
  await fillDetailsAndDocument(page, samples.forged_1, false)
  await page.getByRole('button', { name: 'Upload a photo instead' }).click()
  await page.getByLabel('Selfie photo').setInputFiles(path.join(samplesDir, samples.forged_1.selfie))
  await expect(page.getByAltText('Preview of your selfie')).toBeVisible()
  await shot(page, '05b_wizard_3_selfie_upload')
  await page.getByRole('button', { name: 'Continue' }).click()

  const { applicationId, submittedAt } = await reviewAndSubmit(page, false)
  forgedId = applicationId
  await resultAlert(page, 'Under review by our team')
  console.log(`forged ${applicationId}: Under review after ${((Date.now() - submittedAt) / 1000).toFixed(1)} s`)
  await expectNoFraudSignals(page)
  await shot(page, '09_status_under_review')
})

test('customer: a blank image is sent back for a retake', async ({ page }) => {
  await login(page, 'CUSTOMER')
  await fillDetailsAndDocument(page, samples.blank, false)
  await page.getByRole('button', { name: 'Upload a photo instead' }).click()
  await page.getByLabel('Selfie photo').setInputFiles(path.join(samplesDir, samples.blank.selfie))
  await page.getByRole('button', { name: 'Continue' }).click()
  const { applicationId, submittedAt } = await reviewAndSubmit(page, false)
  const alert = await resultAlert(page, 'Please resubmit', 60_000)
  console.log(`blank ${applicationId}: Please resubmit after ${((Date.now() - submittedAt) / 1000).toFixed(1)} s`)
  await expect(alert.getByRole('link', { name: 'Start again' })).toBeVisible()
  await expectNoFraudSignals(page)
  await shot(page, '10_status_resubmit')
  await page.getByRole('link', { name: 'Back to my applications' }).click()
  await expect(page.getByRole('table', { name: 'My applications' })).toBeVisible()
  await shot(page, '11_my_applications')
})

test('officer: opens the forged case, sees the heatmap and rejects it', async ({ page }) => {
  expect(forgedId, 'the forged application from the previous test').not.toBe('')
  await login(page, 'OFFICER')
  await expect(page.getByRole('link', { name: forgedId })).toBeVisible()
  await expect(page.getByTestId('case-row').first()).toContainText('High risk') // highest risk first
  await expect(page.getByTestId('case-row').filter({ hasText: forgedId })).toContainText('High risk')
  await shot(page, '12_officer_queue')

  await page.getByRole('link', { name: forgedId }).click()
  await expect(page.getByRole('heading', { name: new RegExp(forgedId) })).toBeVisible()
  const heatmap = page.getByTestId('forgery-heatmap')
  await expect(heatmap).toBeVisible()
  await expect(page.getByTestId('forgery-top-tile')).toBeVisible()
  expect(await heatmap.locator('rect').count()).toBeGreaterThan(2)
  await expect(page.getByText('Forgery suspected').first()).toBeVisible()
  await expect(page.getByText('Official summary')).toBeVisible()
  await page.locator('figure').first().screenshot({ path: path.join(shots, '14_case_heatmap.png'), animations: 'disabled' })
  await shot(page, '13_case_detail')

  await page.getByRole('button', { name: 'Reject' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Reject' }).click() // no reason yet: refused
  await expect(dialog.getByText(/Please give a reason/)).toBeVisible()
  await dialog.getByLabel(/Reason/).fill('Surname area edited (heatmap top tile) and the selfie does not match the ID photo.')
  await shot(page, '15_reject_dialog', false)
  await dialog.getByRole('button', { name: 'Reject' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Decided → Rejected')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await shot(page, '17_case_rejected_audit')
})
