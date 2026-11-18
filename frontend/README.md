# SecureBank eKYC: frontend (Phase 8)

React 19 + Vite + TypeScript (strict) + MUI. Two portals in one app, chosen by the role in the login token:

- **Customer** (`/customer`): a four-step verification wizard (details, ID document, webcam selfie, review), a live
  status page, and *My applications*.
- **Officer** (`/officer`): the case queue (highest risk first) and the case page. The case page shows:
  - the ID image with a forgery heatmap next to the selfie;
  - the check cards and the extracted fields compared with what the applicant typed;
  - the decision and its evidence, the official summary and the audit trail;
  - Approve / Reject buttons, each with a mandatory reason.

SecureBank is a fictional brand; the logo is a generic shield icon.

## Run

The whole system starts with `scripts/run_all.sh`; see `services/README.md`. On its own:

```bash
npm install
npm run dev            # http://localhost:5173 (the API must run on http://127.0.0.1:8000)
```

- **API address:** `VITE_API_URL` sets it (see `.env.example`; copy it to `.env.local` to change it).
- **CORS:** the API only allows the origin `http://localhost:5173`, so open the app as `localhost`.

| Script | What it does |
|---|---|
| `npm run dev` / `build` / `preview` | Vite dev server / production build into `dist/` / serve the build |
| `npm run lint` | ESLint: TypeScript, React hooks (incl. React Compiler rules), jsx-a11y accessibility rules |
| `npm run typecheck` | `tsc -b` in strict mode |
| `npm test` | Vitest (jsdom): route guards, API client errors, customer status mapping, heatmap, queue, upload checks |
| `npm run e2e` | Playwright, Chromium (headless shell only): the full flow against the running system |
| `npm run gen:api` | Regenerate `src/api/schema.d.ts` from the API's OpenAPI schema (`openapi.json`, written by `scripts/export_openapi.py`; no server needed) |

The e2e test needs the following, and saves screenshots to `reports/phase8/screenshots/`:
- `scripts/run_all.sh` running;
- `scripts/make_demo_samples.py` run once;
- the browser: `npx playwright install --only-shell chromium` (~102 MB).

## Structure

```
src/
  api/client.ts          the ONLY module that calls the API (typed with the generated schema.d.ts); ApiError;
                         a 401 logs the user out
  auth/                  session (memory + sessionStorage), AuthProvider (login, logout, expiry timer),
                         RequireRole (route guard)
  customer/              customerStatus.ts (the customer-safe mapping), wizard steps, webcam, status page (SSE)
  officer/               queue, case page, heatmap (heatmap.ts = geometry), check cards, decision dialog
  components/ pages/     app shell (top bar, skip link), login, not found
e2e/kyc-flow.spec.ts     Playwright end-to-end flow
```

## Design decisions

- **Login token storage.** The JWT is kept in memory and mirrored to `sessionStorage`, so a reload keeps the user
  logged in within the tab, and closing the tab ends the session. **In production an httpOnly, Secure, SameSite
  cookie set by the API is the better choice.** JavaScript (and so an XSS bug) cannot read such a cookie. Here it
  would need cookie handling plus CSRF protection in the API, which is out of scope for the demo.
- **Auto-logout.** It happens on any 401 from the API, and also by a timer when the token expires (30 min).
- **Customers never see fraud signals.**
  - Every customer screen receives only a `CustomerStatus`. `toCustomerStatus()` builds it by copying a fixed
    whitelist of fields.
  - The API itself sends no scores to customers.
  - Three tests prove it:
    - the mapping is a whitelist;
    - a status page rendered with leaked fields shows none of them;
    - a scan finds no fraud-signal names in any customer source file.
  - The *what to retake* text is shown only for RESUBMIT_REQUIRED.
- **Live status uses Server-Sent Events** (`EventSource` with `?token=`, because browsers cannot add headers to it).
  - The stream is closed at a final status; otherwise EventSource would reconnect.
  - If the stream fails (network, expired token), the page polls instead.
  - A case under review is re-checked every 15 s for the officer's decision.
- **The selfie step is camera first**, using `getUserMedia`. The preview is mirrored like a mirror; the saved
  photo is not. If the camera is denied or missing, the page explains why and offers an upload instead. Upload is
  also always available.
- **Forgery heatmap.**
  - The model scores overlapping 224 px tiles (stride 112) on the page resized to 1280 px.
  - The page is cut along every tile edge, and each cell gets the highest score of the tiles covering it. Drawing
    the tiles themselves would stack transparent squares.
  - Colour: a single-hue sequential blue ramp, with near-zero cells left out so the document stays readable.
  - The highest-scoring tile is outlined, and the legend marks the review (0.729) and suspected (0.857)
    thresholds.
- **Accessibility.**
  - Every input has a label; status chips pair an icon with text, so colour is never the only signal.
  - The status palette is used only for borders and icons; text stays in ink colours, which keeps contrast at
    WCAG AA.
  - The step heading takes focus on each wizard step; there is a skip link; progress is announced in a live
    region; dialogs focus their first field.
- **Code splitting.** Each portal's pages load on demand.
- **Tool versions.**
  - TypeScript is pinned to 5.9 because typescript-eslint and openapi-typescript do not support TypeScript 7 yet
    (create-vite now defaults to TS 7 and oxlint).
  - `eslint-plugin-jsx-a11y` declares ESLint ≤ 9, so `package.json` has an `overrides` entry. It runs correctly on
    ESLint 10.
