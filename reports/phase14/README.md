# Phase 14: visual polish and subtle motion

The UI got a richer palette, softer depth and quiet motion. There were no changes to functionality, data or the
API: every existing test passes unchanged, and the Playwright tests run with the motion switched off.

## Library choice: none (CSS + canvas)

The effects asked for are all native to the browser:
- **CSS animations**, on `transform` / `opacity`, which the compositor runs without layout work:
  - entrance fades and direction-aware slides;
  - small pops, a pulse and nudging arrows;
  - a self-drawing checkmark (`stroke-dashoffset`);
  - hover lifts and button press feedback.
- **Canvas:** the two drawn effects, the dot field and the celebration, are canvas work in any library.

An animation library such as Motion would add about 15-35 kB gzipped to the customer bundle for things CSS already
does; it pays off for layout and exit animations and gestures, which this UI does not need. So the motion is:
- CSS keyframes and classes in one place (`frontend/src/theme.ts`);
- three small hooks (`src/motion/useReducedMotion.ts`, `useTilt.ts`, `motionLevel.ts`);
- four components: `DotField.tsx`, `Celebration.tsx`, `AnimatedCheck.tsx` and `ProgressRing.tsx`.

## Bundle impact (no new dependency)

| Build | First page (raw / gzip) | All JS + CSS (gzip) |
|---|---|---|
| Normal app, before | 520.1 kB / 165.3 kB | 473.6 kB |
| Normal app, after | 528.1 kB / 168.2 kB (+2.9 kB gzip) | 478.7 kB (+5.0 kB) |
| Demo site, before | 465.1 kB / 147.6 kB | 492.8 kB |
| Demo site, after | 473.2 kB / 150.3 kB (+2.7 kB gzip) | 497.5 kB (+4.8 kB) |

The first page includes the theme's keyframes and the dot field: the login and landing pages, which use it, load
first.

## Reduced motion and tests

- **One CSS rule** (`theme.ts`) turns every animation and transition off when the system asks for reduced motion.
  In its place:
  - the dot field becomes a static dotted gradient;
  - the tilt and the celebration are not used;
  - the checkmark appears already drawn.
- **Tests run static:** both test configs (`playwright.config.ts`, `playwright.demo.config.ts`) emulate
  `prefers-reduced-motion: reduce`, so the tests stay deterministic. Vitest's jsdom cannot say, and is treated as
  "reduce".
- **The showcase is the exception** (`playwright.showcase.config.ts`, `npm run showcase`): it runs with motion on,
  for the screenshots, the recordings and the performance run.

## Where the motion is

- **Landing page (demo site) and login page (real app):** the canvas dot field.
  - The dots drift, faint lines join close dots, and dots move gently away from the mouse.
  - It is not used anywhere else, never on the camera screens, where MediaPipe needs the CPU.
- **Customer wizard:**
  - steps slide in from the direction you move;
  - a gradient progress bar fills under the stepper, and the active step icon pops.
- **Smart camera** (display only; the capture logic in `selfieGuidance.ts` is unchanged):
  - the face-guide oval pulses gently while searching, then turns solid green with a soft glow when the face is
    good;
  - the current step's chip shows a progress ring: the "hold still" count, then how far the head has turned towards
    the 20 degree target;
  - the direction arrows nudge;
  - "Head-turn photos taken" / "challenge completed" get a drawn checkmark.
- **Status page:**
  - one marker per check pops in as each completes (counts only, never which check);
  - "Verified" gets a drawn checkmark and a 1.6 s confetti burst with no sound. It plays only for a result the
    customer watched arrive, not when an old application is reopened.
- **Hover:**
  - landing cards and dashboard KPI tiles lift and tilt towards the mouse (at most 3 degrees, mouse only);
  - officer check cards only lift.
  - Buttons lift slightly on hover and press in (scale 0.98) on click.
- **Officer portal: restrained.** A `MotionLevel` context set in `AppRoutes.tsx` turns the tilt off there: hover lifts
  and smooth transitions only, and no moving background.
- **Pages:** each page fades up gently on arrival. On the dashboards only the tab panel does, so the shared filters
  survive tab switches.

## Performance of the dot field (`perf.json`)

Headless Chromium on the development laptop (Apple M5, 16 GB, under memory pressure with other projects' containers
running), 5 s with the mouse moving over the page:

| | Frames | Mean / p95 frame | Frames > 20 ms | Main thread busy | Dot field draw per frame |
|---|---:|---|---:|---:|---:|
| Desktop 1366x900, dot field (80 dots) | 290 | 17.2 / 16.8 ms | 2.1 % | 5.3 % | 0.065 ms |
| Desktop, static background (reduced motion) | 299 | 16.7 / 16.7 ms | 0.3 % | 3.1 % | – |
| Phone 390x844, dot field (36 dots) | 300 | 16.7 / 16.7 ms | 0 % | 4.2 % | 0.030 ms |

**What keeps it light:**
- the dot count is capped (one per 16,000 px², at most 80, or 36 on small screens);
- the lines are batched into four strokes per frame (by transparency);
- the layout is read only on resize; the mouse position comes from the event;
- the pixel ratio is capped at 2;
- drawing stops when the tab is hidden.

The first run of the same test had no slow frames at all (16.7 / 16.8 ms, 5.2 % busy, 0.043 ms per draw).

## Accessibility

- **Lint clean** (ESLint with jsx-a11y).
- **Every animation is decorative** (`aria-hidden`) and has a text equivalent: the step text, the "x of 4 checks
  complete" line, the "Verified" title.
- **Visible keyboard focus:** a 3 px ring with an offset on every focusable element, white on the top bar.
  - A new demo-site Playwright test tabs through the landing page and checks each focused control draws a ring of at
    least 2 px.
  - It caught that MUI buttons remove the browser outline (they rely on a faint ripple), so the ring is now drawn
    through MUI's ButtonBase.
- **Contrast** (WCAG 2.x ratios; AA needs 4.5 for text, 3 for focus rings and large text):

  | Pair | Ratio |
  |---|---:|
  | white on the primary `#0b4f9c` | 8.04 |
  | white on the gradient start `#083a70` | 11.35 |
  | white on the accent / gradient end `#0b7285` | 5.59 |
  | white on the button gradient top `#1559a8` | 6.94 |
  | primary on the page `#f4f7fb` | 7.48 |
  | ink on the page | 18.32 |
  | secondary ink `#52514e` on the page / on a white card | 7.39 / 7.94 |
  | focus ring `#3d78bd` on the page / on white | 4.23 / 4.55 |
  | success text `#1e6b34` on white | 6.55 |
  | warning hint `#8a5300` on white | 6.33 |

  The status colours (approved / review / resubmit / rejected) keep their meaning, with an icon and a label.

## End-to-end runs (the whole system in host mode, 23 Nov 2026)

- **`scripts/e2e_api_smoke.py`: ALL PASSED** (`e2e_api_results.json`): 7 cases, the officer flow, and 6 security
  checks.
  - With the other projects' containers stopped, no check timed out.
  - The genuine applicant with head turns was auto-approved in 29.4 s; the static photo became a clean retake.
- **Playwright on the real system: 4 of 4 passed**, run with reduced motion, as all test runs are:
  - the genuine applicant through the smart camera: Verified in 25.5 s;
  - the forged case: under review after 64.3 s;
  - the blank document: resubmit after 2.1 s;
  - the officer rejection with its audit trail.
- **The first attempt failed in the third test.** The laptop was crawling right after an LLM extraction (filling
  the login form took 18-28 s), and the test clicked "Verify my identity" while the login page was still finishing
  its own redirect, which undid the click.
  - The login helper (`frontend/e2e/kyc-flow.spec.ts`) now waits for the home page's heading before going on.
  - No app code changed.
- **`e2e/`:** the four real-system screenshots the README shows (smart camera, resubmit, forgery heatmap, rejection
  with audit trail), now in the Phase 14 look.

## Screenshots and recordings

- `before/` and `after/`: the same 12 screens, before and after this phase. They come from the showcase run on the
  demo build; the login page comes from the real app's dev server. `after/06a_status_celebration.png` catches the
  celebration mid-flight.
- `video/` (gitignored, like the Phase 10 footage; regenerate with `npm run showcase`), 1280 x 800 WebM:
  - `01_landing_dot_field.webm`: the background with the mouse moving, then a card lifting;
  - `02_liveness_challenge.webm`: the guide, the turns with their progress rings, the checkmark;
  - `03_verified_celebration.webm`: a demo replay ending in "Verified".
