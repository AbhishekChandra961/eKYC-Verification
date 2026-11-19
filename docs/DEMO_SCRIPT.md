# Demo video: script and shot list (about 4.5 minutes)

**Story:**
- **Customer:** an honest customer is verified in under a minute; a forged attempt and a blank photo are caught
  without revealing anything to the customer.
- **Officer:** sees the evidence, including the forgery heatmap, and makes an audited decision.
- **Under the hood:** Kafka and a dashboard; then the architecture.

The narration is written to be spoken; about 140 words a minute.

## Before recording (checklist)

- [ ] Quit heavy apps. Check `docker ps` and memory: Ollama needs 6-8 GB.
- [ ] `docker compose up -d`, then `ollama serve` (or the Ollama app), then `./scripts/run_all.sh` (host mode).
- [ ] **Warm up the LLM:** submit one genuine sample once before recording, so the first extraction does not include
      the model loading time.
- [ ] `demo_samples/` exists (`.venv/bin/python scripts/make_demo_samples.py`); keep `demo_samples/README.md` open on
      a second screen for the names and dates to type.
- [ ] **Browser:**
  - a Chrome window at about 1366×900, zoom 100 %;
  - for a webcam selfie that *matches* the ID, start Chrome with the fake webcam (command in
    `demo_samples/README.md`); otherwise use **Upload a photo instead**.
- [ ] **Tabs ready:** http://localhost:5173 (customer), a second browser profile or private window for the officer,
      http://localhost:8080 (Kafka UI), the Tableau Public dashboards, and `docs/report/figures/architecture.png`
      full screen.
- [ ] Recorder: QuickTime (File → New Screen Recording) or OBS, 1080p, with the microphone checked.
- [ ] **Waiting times:** the genuine case takes about 30-45 s and the forged one up to about 80 s. Record the waits
      and **cut them** in editing, or speed them up, keeping the live progress steps visible.

## Shot list

| # | Time | Shot | On screen | Say |
|---|---|---|---|---|
| 0 | 0:00-0:20 | Title | README top or a title card: "eKYC Verification: layered AI checks for digital onboarding" | "Banks must verify who you are before you open an account. Online, that means a photo of your ID and a selfie, and that invites forged documents and impersonation. This is my capstone: a digital KYC system with four AI checks, built as event-driven microservices." |
| 1 | 0:20-1:20 | Customer happy path | Log in as the demo customer → **Verify my identity** → step 1 name and date of birth (genuine_1) → step 2 upload `genuine_1_id.jpg` → step 3 webcam selfie → step 4 review → submit → the status page moves Submitted → Verifying → **Verified** | "I log in as a customer and type my details. I upload my ID and take a selfie. When I submit, four checks run in parallel: the document type, a forgery detector, a face match, and a local vision language model that reads the fields and checks the machine-readable zone. The status updates live... and I'm verified, in about half a minute." |
| 2 | 1:20-1:50 | Forged attempt | New application with `forged_1_id.jpg` (an edited surname) and `forged_1_selfie_stranger.jpg` → status → **Under review** | "Now a fraudster: a document with an edited surname, and someone else's face. Notice what the customer sees: just 'under review'. No scores, no hints. Showing fraud signals would teach an attacker which attempt came closest." |
| 3 | 1:50-2:05 | Blank image | New application with `blank_id.jpg` → **Please resubmit** within about a second | "And an unusable photo is caught immediately: the customer is simply asked to retake it. The other checks don't even run." |
| 4 | 2:05-2:30 | Officer queue | Log in as the officer → the case queue, sorted by risk, with the forged case on top (high risk) | "Here is the bank officer's view. Only doubtful cases come here, sorted by a risk score. The system never rejects anyone on its own: a person always makes that call." |
| 5 | 2:30-3:05 | Case detail + heatmap | Open the forged case: ID and selfie side by side, the check results, the **forgery heatmap** toggle with its top tile overlapping the edited surname line, face score below the threshold, MRZ name rule flags | "The officer sees all the evidence. The forgery model scores the page tile by tile: the highest-scoring tile overlaps the surname line that was edited. Tiles are 224 pixels, so it marks the area, not the exact word. The face match fails, and the name in the machine-readable zone disagrees with the printed name." |
| 6 | 3:05-3:30 | Reject + audit trail | **Reject** → type a reason ("Surname edited and selfie does not match") → confirm → the audit trail: SUBMITTED → PROCESSING → DECIDED → REJECTED, with actors and times | "Rejecting requires a written reason, and every step is in an append-only audit trail: who did what, and when. That is what a regulator or a complaints team needs." |
| 7 | 3:30-3:50 | Kafka UI | http://localhost:8080 → Topics: `kyc.submitted`, `kyc.tasks.*`, `kyc.results`, `kyc.decided`, `kyc.dlq` → open a message in `kyc.submitted` → consumer groups with lag 0 | "Under the hood, everything flows through Kafka. Events carry only storage keys, never the images: the claim-check pattern. Each check is its own worker. Failures are retried, then parked in a dead-letter queue, and a sweeper sends any late check to manual review." |
| 8 | 3:50-4:20 | Tableau dashboard | The **Risk & fraud** dashboard (system vs truth), then a glance at **Operations** and **Model performance** | "I ran 150 applications through the live system. 67 of the 68 frauds and mismatches were stopped, and every forged document went to review. The honest cost: a third of genuine customers also went to review, mostly because of model false alarms and misread passport codes. That's the next thing to improve." |
| 9 | 4:20-4:45 | Architecture + close | `docs/report/figures/architecture.png` full screen | "To sum up: four layered checks, an explainable decision engine and a human in the loop, built on Kafka, FastAPI and React, with a privacy-first local LLM. My biggest lesson: my first forgery model scored 98 % but had learned how the files were saved, not the forgeries. Proving *what* a model learned matters as much as the score. Thank you." |

## Backup footage (recorded with Playwright)

If a live shot goes wrong, use the automatically recorded clips in `reports/phase10/video/` (gitignored, about 14 MB
in total, 1366×900 WebM). They were recorded on 19 Nov 2026 in host mode, headed, with `slowMo` 350 ms.

| File | Shows | Matches shot |
|---|---|---|
| `01_customer_genuine_webcam_verified.webm` | login, the four-step wizard with a webcam selfie, live status → Verified (42.9 s to decision) | 1 |
| `02_customer_forged_stranger_under_review.webm` | forged document + stranger selfie → Under review (81.6 s) | 2 |
| `03_customer_blank_resubmit.webm` | blank image → Please resubmit (1.2 s) | 3 |
| `04_officer_heatmap_reject_audit.webm` | officer queue → case detail with the heatmap → reject with a reason → audit trail | 4-6 |

**Re-record (whole system running in host mode):**

```bash
cd frontend
npm run record                     # playwright.record.config.ts: headed, slowMo, video on; 4 tests, about 6 minutes
cd ../reports/phase10/video/raw    # one folder per test, each with video.webm; rename as in the table above
```

The recording uses the same end-to-end test as `npm run e2e`, and it writes its screenshots to a temporary folder so
that `reports/phase8/screenshots/` stays unchanged. The first headed run needs the full Chromium build:
`npx playwright install chromium` (about 380 MB, once).

## Editing notes

- **Cut the waits** in shots 1 and 2 to about 5 s each; leave the progress steps visible so the cut is honest.
- **Captions:** add the numbers on screen in shot 8 (67/68, 45/45, 27 of 75 to review).
- **Shot 5:** zoom in on the heatmap's top tile and the face-score bar.
- **Keep it under 5 minutes.** If it runs long, shorten shot 7 (Kafka UI) first.
