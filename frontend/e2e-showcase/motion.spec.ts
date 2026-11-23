// Phase 14: is the dot field smooth, and what does the motion look like? (motion ON in this config)
//  - performance: frame intervals (requestAnimationFrame), the dot field's own draw time per frame (data-draw-ms) and
//    the main thread's busy share (Chrome DevTools Protocol: TaskDuration), with the mouse moving over the page, on
//    the landing page with the dot field vs the same page with reduced motion (static background) -> reports/phase14/perf.json
//  - recordings for the demo video -> reports/phase14/video/ (gitignored): the landing background, the liveness
//    challenge, the "Verified" celebration.
import { expect, test, type Browser, type BrowserContextOptions, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const out = path.resolve(import.meta.dirname, '..', '..', 'reports', 'phase14')
const videos = path.join(out, 'video')
mkdirSync(videos, { recursive: true })
const SITE = 'http://localhost:4176/eKYC-Verification/'

/** Moves the mouse around the screen for `ms` (the dot field reacts to it). */
async function wander(page: Page, ms: number, width = 1366, height = 900) {
  const end = Date.now() + ms
  let i = 0
  while (Date.now() < end) {
    const a = (i++ / 12) * Math.PI
    await page.mouse.move(width / 2 + Math.cos(a) * width * 0.35, height / 2 + Math.sin(a * 0.7) * height * 0.3, { steps: 12 })
  }
}

interface Measure { frames: number; meanFrameMs: number; p95FrameMs: number; slowFrameShare: number; mainThreadBusy: number; drawMs: number | null }

async function measure(browser: Browser, reducedMotion: 'reduce' | 'no-preference', viewport: { width: number; height: number }): Promise<Measure> {
  const context = await browser.newContext({ viewport, reducedMotion, baseURL: SITE })
  const page = await context.newPage()
  await page.goto('./')
  await expect(page.getByRole('button', { name: 'Try as customer' })).toBeVisible()
  await page.waitForTimeout(1500) // settle: first draws, fonts
  const cdp = await context.newCDPSession(page)
  await cdp.send('Performance.enable')
  const metric = async () => {
    const { metrics } = await cdp.send('Performance.getMetrics')
    return Object.fromEntries(metrics.map((m) => [m.name, m.value])) as Record<string, number>
  }
  const before = await metric()
  const [times] = await Promise.all([
    page.evaluate(() => new Promise<number[]>((resolve) => {
      const stamps: number[] = []
      const start = performance.now()
      const tick = (t: number) => { stamps.push(t); if (t - start < 5000) requestAnimationFrame(tick); else resolve(stamps) }
      requestAnimationFrame(tick)
    })),
    wander(page, 5000, viewport.width, viewport.height),
  ])
  const after = await metric()
  const drawMs = await page.evaluate(() => {
    const value = (document.querySelector('[data-testid="dot-field"]') as HTMLCanvasElement | null)?.dataset.drawMs
    return value ? Number(value) : null
  })
  await context.close()
  const intervals = times.slice(1).map((t, i) => t - times[i]).sort((a, b) => a - b)
  const mean = intervals.reduce((a, b) => a + b, 0) / intervals.length
  return {
    frames: intervals.length, meanFrameMs: +mean.toFixed(2), p95FrameMs: +intervals[Math.floor(intervals.length * 0.95)].toFixed(2),
    slowFrameShare: +(intervals.filter((v) => v > 20).length / intervals.length).toFixed(4),
    mainThreadBusy: +((after.TaskDuration - before.TaskDuration) / (after.Timestamp - before.Timestamp)).toFixed(4),
    drawMs,
  }
}

test('dot field performance (desktop and phone; vs a static background)', async ({ browser }) => {
  test.setTimeout(120_000)
  const desktop = { width: 1366, height: 900 }
  const phone = { width: 390, height: 844 }
  const result = {
    note: 'Headless Chromium on the development laptop (Apple M5, 16 GB, under memory pressure), 5 s with the mouse moving. ' +
      'frame = requestAnimationFrame interval; slow = > 20 ms; mainThreadBusy = share of wall time the renderer main thread ' +
      'was busy (CDP TaskDuration); drawMs = the dot field\'s own average draw time per frame.',
    desktopDotField: await measure(browser, 'no-preference', desktop),
    desktopStaticBackground: await measure(browser, 'reduce', desktop),
    phoneDotField: await measure(browser, 'no-preference', phone),
  }
  writeFileSync(path.join(out, 'perf.json'), JSON.stringify(result, null, 1) + '\n')
  console.log(JSON.stringify(result, null, 1))
  expect(result.desktopDotField.drawMs).not.toBeNull()
  expect(result.desktopDotField.drawMs ?? 99).toBeLessThan(4) // a small share of a 16.7 ms frame
  expect(result.desktopDotField.p95FrameMs).toBeLessThan(25)
})

async function record(browser: Browser, name: string, run: (page: Page) => Promise<void>, options: BrowserContextOptions = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'no-preference',
    baseURL: SITE, permissions: ['camera'], recordVideo: { dir: videos, size: { width: 1280, height: 800 } }, ...options })
  const page = await context.newPage()
  await run(page)
  const video = page.video()
  await context.close()
  await video?.saveAs(path.join(videos, `${name}.webm`))
  await video?.delete()
}

test('recordings for the demo video', async ({ browser }) => {
  test.setTimeout(180_000)
  await record(browser, '01_landing_dot_field', async (page) => {
    await page.goto('./')
    await expect(page.getByRole('button', { name: 'Try as customer' })).toBeVisible()
    await page.waitForTimeout(1500)
    await wander(page, 7000, 1280, 800)
    const card = page.getByRole('button', { name: 'Try as customer' })
    await card.hover() // the card lifts and tilts
    await page.waitForTimeout(1200)
  })
  await record(browser, '02_liveness_challenge', async (page) => {
    await page.goto('./#/camera-check')
    await page.getByRole('button', { name: 'Turn on camera' }).click()
    await expect(page.getByTestId('camera-check-done')).toBeVisible({ timeout: 45_000 })
    await page.waitForTimeout(1800) // the checkmark draws itself
  })
  await record(browser, '03_verified_celebration', async (page) => {
    await page.goto('./')
    await page.getByRole('button', { name: 'Try as customer' }).click()
    await page.getByRole('link', { name: 'Verify my identity' }).first().click()
    await page.getByRole('button', { name: /Serbian passport, genuine/ }).click()
    for (let step = 0; step < 3; step++) {
      await page.waitForTimeout(500)
      await page.getByRole('button', { name: 'Continue' }).click()
    }
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Submit' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'Verified' })).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(2200)
  })
})
