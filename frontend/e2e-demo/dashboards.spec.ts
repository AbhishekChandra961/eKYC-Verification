// The analytics dashboards on the demo site (Phase 12): public (no login), three tabs over the bundled batch snapshot,
// filters, table views, phone width, and the officer portal's Analytics tab. Screenshots for the README go to
// reports/phase12/. Every request must stay on the site itself (no CDN, no API).
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const shots = path.resolve(import.meta.dirname, '..', '..', 'reports', 'phase12')
mkdirSync(shots, { recursive: true })

function watchRequests(page: Page, site: string): string[] {
  const outside: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (!url.startsWith(site) && !url.startsWith('data:') && !url.startsWith('blob:')) outside.push(url)
  })
  return outside
}

async function shot(page: Page, name: string, fullPage = true) {
  await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage, animations: 'disabled' })
}

const kpi = (page: Page, label: string) => page.getByTestId('kpi').filter({ has: page.getByRole('heading', { name: label, exact: true }) })

/** Every chart card of the dashboard has drawn something: bars of the chart library, the reason bar list, or the
 *  highlight table's cells. */
async function expectChartsDrawn(page: Page, cards: number) {
  const all = page.getByTestId('chart-card')
  await expect(all).toHaveCount(cards)
  for (let i = 0; i < cards; i++) {
    const drawn = all.nth(i).locator('.MuiBarChart-element, [data-testid="reason-list"] li, [data-testid="confusion-table"] td')
    await expect(drawn.first()).toBeVisible()
  }
}

async function expectMeta(page: Page) {
  const meta = page.getByTestId('dashboard-meta')
  await expect(meta).toContainText('Synthetic data')
  await expect(meta).toContainText('Batch snapshot')
  await expect(meta).toContainText('Data as of 18 Nov 2026, 09:36 UTC')
}

test.describe.configure({ mode: 'serial' })

test('landing page links the public dashboards; Operations renders with the report numbers', async ({ page, baseURL }) => {
  const outside = watchRequests(page, new URL(baseURL ?? '').origin)
  await page.goto('./')
  await page.getByRole('link', { name: /^Dashboards/ }).click()
  await expect(page).toHaveURL(/#\/dashboards$/)
  await expect(page.getByRole('heading', { name: 'Analytics dashboards' })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Operations' })).toHaveAttribute('aria-selected', 'true')
  await expectMeta(page)

  await expect(kpi(page, 'Applications')).toContainText('150')
  await expect(kpi(page, 'Auto-approval rate')).toContainText('32.7%')
  await expect(kpi(page, 'Manual-review rate')).toContainText('62.7%')
  await expect(kpi(page, 'Resubmit rate')).toContainText('4.7%')
  await expect(kpi(page, 'Median time to decision')).toContainText('77.2 s')
  await expectChartsDrawn(page, 4)

  // a chart's table view shows the same numbers
  const funnelCard = page.getByTestId('chart-card').filter({ hasText: 'Outcome funnel' })
  await funnelCard.getByRole('button', { name: 'Table' }).click()
  await expect(funnelCard.getByRole('table')).toContainText('Rejected by an officer56')
  await funnelCard.getByRole('button', { name: 'Hide table' }).click()
  await shot(page, '01_dashboard_operations')

  // the filters apply to every chart of the dashboard
  await page.getByRole('combobox', { name: 'Document type' }).click()
  await page.getByRole('option', { name: 'Estonian ID card' }).click()
  await expect(page.getByTestId('filter-count')).toHaveText('10 of 150 applications')
  await expect(kpi(page, 'Applications')).toContainText('10')
  await expect(kpi(page, 'Manual-review rate')).toContainText('90.0%')
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page.getByTestId('filter-count')).toHaveText('All 150 applications')
  expect(outside).toEqual([])
})

test('Risk & fraud: catch rate, false alarms and the system-vs-truth highlight table', async ({ page, baseURL }) => {
  const outside = watchRequests(page, new URL(baseURL ?? '').origin)
  await page.goto('./#/dashboards')
  await page.getByRole('tab', { name: 'Risk & fraud' }).click()
  await expect(page).toHaveURL(/#\/dashboards\/risk-fraud$/)
  await expectMeta(page)
  await expect(kpi(page, 'Fraud caught')).toContainText('67 of 68')
  await expect(kpi(page, 'Missed frauds')).toContainText('1')
  await expect(kpi(page, 'False alarms')).toContainText('27')
  const matrix = page.getByTestId('confusion-table')
  await expect(matrix.locator('[data-verdict="Correct: approved"]')).toContainText('48')
  await expect(matrix.locator('[data-verdict="False alarm: sent to review"]')).toContainText('27')
  await expect(matrix.locator('[data-verdict="Missed: auto-approved"]')).toContainText('1')
  await expect(matrix.locator('[data-verdict="Caught: sent to review"]')).toContainText('67')
  await expect(matrix.locator('[data-verdict="Correct: resubmit"]')).toContainText('7')
  await expectChartsDrawn(page, 4)
  await expect(page.getByTestId('reason-list').getByRole('listitem').filter({ hasText: 'Forgery suspected' })).toContainText('51')
  await shot(page, '02_dashboard_risk_fraud')

  // filter by outcome: the waiting cases are all medium risk
  await page.getByRole('combobox', { name: 'Outcome' }).click()
  await page.getByRole('option', { name: 'Awaiting officer' }).click()
  await expect(page.getByTestId('filter-count')).toHaveText('28 of 150 applications')
  await expect(kpi(page, 'Flag confirmed by officer')).toContainText('–') // no officer decision among them
  expect(outside).toEqual([])
})

test('Model performance: the forgery shortcut story, face, extraction and the metrics table', async ({ page, baseURL }) => {
  const outside = watchRequests(page, new URL(baseURL ?? '').origin)
  await page.goto('./#/dashboards/model-performance')
  await expect(page.getByRole('tab', { name: 'Model performance' })).toHaveAttribute('aria-selected', 'true')
  await expectMeta(page)
  await expect(page.getByTestId('filter-bar')).toHaveCount(0) // offline evaluations: the batch filters do not apply
  const story = page.getByTestId('forgery-story')
  await expect(story.getByRole('listitem')).toHaveCount(3)
  await expect(story).toContainText('Rejected: shortcuts. The best-looking PR-AUC (0.976)')
  await expect(story).toContainText('Accepted: every shortcut check passes (control 0.4908)')
  await expect(page.getByTestId('metrics-table').locator('tbody tr')).toHaveCount(83)
  await expectChartsDrawn(page, 3)
  await shot(page, '03_dashboard_model_performance')
  expect(outside).toEqual([])
})

test('phone width: no sideways page scroll, every dashboard still drawn', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const [tab, name, cards] of [['', 'operations', 4], ['/risk-fraud', 'risk_fraud', 4], ['/model-performance', 'model_performance', 3]] as const) {
    await page.goto(`./#/dashboards${tab}`)
    await expectMeta(page)
    await expectChartsDrawn(page, cards)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `${name}: page wider than the screen`).toBeLessThanOrEqual(0)
    await shot(page, `04_dashboard_${name}_phone`)
  }
})

test('officer portal: the same dashboards as the "Analytics" tab', async ({ page }) => {
  await page.goto('./')
  await page.getByRole('button', { name: 'Try as officer' }).click()
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Analytics' }).click()
  await expect(page).toHaveURL(/#\/officer\/analytics$/)
  await expect(page.getByRole('link', { name: 'Analytics' })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('link', { name: 'Case queue' })).not.toHaveAttribute('aria-current', 'page')
  await expectMeta(page)
  await expect(kpi(page, 'Applications')).toContainText('150')
  await page.getByRole('tab', { name: 'Risk & fraud' }).click()
  await expect(page).toHaveURL(/#\/officer\/analytics\/risk-fraud$/)
  await expect(kpi(page, 'Fraud caught')).toContainText('67 of 68')
})
