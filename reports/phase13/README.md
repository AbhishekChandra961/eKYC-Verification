# Phase 13: smart selfie camera + active liveness

The selfie side's counterpart of the document forgery detector: a defence against the simplest presentation attack,
a photo held up to the camera. A simple challenge-response check, not certified presentation-attack detection (PAD).

## How it works

1. **Browser: the smart camera** (`frontend/src/customer/WebcamCapture.tsx`, `selfieGuidance.ts`).
   - **Guidance:** MediaPipe's BlazeFace detector checks about 10 frames a second, then shows one instruction at a
     time: *No face found*, *Only one person*, *Move closer*, *Move back a little*, *Centre your face*, *Too dark*.
   - **Captures:** when the frame is good, the camera captures "looking at the camera" automatically, then asks the
     customer to turn their head left, then right, capturing each turn automatically.
   - **Fallbacks:** a *Take it now* button appears after 12 s on a step, or for every step when the detector cannot
     load. Photo upload stays available (no camera, or permission denied).
2. **API:** `POST /applications` takes two optional files, `liveness_left` and `liveness_right` (both or neither;
   the selfie is the third frame).
   - They are stored in S3 like the selfie, and their keys travel with the face task.
   - No liveness *result* is ever accepted from the browser.
3. **Server: the face-worker** (`src/ekyc/liveness.py`) uses YuNet and SFace, the models it already had.
   - **Yaw:** estimated per frame from the 5 landmarks:
     `atan(nose offset from the eye-mouth midline / (0.5 x eye distance))`, after levelling the eyes.
   - **Rules:** each turn must be **>= 20 degrees** from the first frame, and that first frame must be frontal
     within 15 degrees.
   - **Same person:** all three frames must show one person, with an SFace cosine >= 0.2597 (the face check's
     threshold).
   - **Configurable:** `EKYC_LIVENESS_MIN_TURN_DEG`, `EKYC_LIVENESS_MAX_NEUTRAL_YAW_DEG`, `EKYC_LIVENESS_NOSE_DEPTH`.
4. **Decision engine** (`src/ekyc/decision.py`):
   - frames of different people -> **MANUAL_REVIEW high**;
   - any other liveness failure -> **RESUBMIT_REQUIRED**, telling the customer to retake the selfie and follow the
     prompts (neutral wording);
   - no frames (photo uploaded) -> **MANUAL_REVIEW medium**.

   Customers never see the values; officers see the three frames with the yaw, turn and similarity values.

## Evaluation (`scripts/evaluate_liveness.py` -> `liveness_eval.md` / `.json`, `liveness_examples.png`)

Every scenario runs through the production code: `FaceVerifier.liveness()`, with a JPEG round trip for the SIDTD
frames. Thresholds are the defaults; nothing was tuned on these results.

| Scenario | Frames | Result |
|---|---:|---|
| Genuine, **real** head turns (LFW: one person's frontal, left- and right-turned photos) | 42 | **41 passed**; 1 flagged as different people (SFace cosine below 0.2597 between two photos of the same man) |
| Genuine, **synthetic** +-28 degree turns (SIDTD test portraits) | 148 | **128 passed**; 20 retakes (the measured turn stayed under 20 degrees) |
| Static photo: 3 identical frames (SIDTD 148, LFW 42) | 190 | **all caught** (retake) |
| Printed photo tilted +-40 degrees (perspective warp) | 148 | **all caught** |
| Printed photo tilted +-55 degrees | 148 | **147 caught**; **1 passed** (both tilts measured over 20 degrees) |
| Different people, each turned the right way (SIDTD, synthetic turns) | 148 | **144 caught** (141 by the same-person rule, 3 by the turn rule); **4 passed** |
| Different people, real turns (LFW) | 42 | **all caught** (same-person rule) |

**How to read it:**

- **The real head turns are honest but not circular-free.** They are separate photos of one person, not one
  video, and the turned photos were *chosen* with the same yaw estimate (a 25-50 degree turn).
  - So this row tests the same-person rule on turned faces, not the turn rule.
  - No real head-turn video of anyone was available; the SIDTD faces are single synthetic portraits, hence the
    synthetic turns (`ekyc.liveness_sim`).
- **The 4 different-person passes** are SIDTD's look-alike generated portraits.
  - Phase 4 found SFace accepts 29.9 % of different-person SIDTD pairs at this threshold.
  - With real people (LFW) all 42 were caught.
- **A tilted printed photo** gives at most ~16 degrees for tilts up to 40 degrees: it has no nose depth.
  - At 55 degrees, 1 of 148 passed. A steeper tilt loses the face.
- **What it cannot catch:**
  - a replayed **video** of the real person turning their head;
  - a 3-D **mask**;
  - a **digitally injected** stream (a virtual camera playing a synthetic turn: the synthetic turns made here pass,
    which shows exactly this).
  - Real PAD adds texture/depth cues, randomised challenges and injection detection. This check is a deterrent
    against the cheapest attack.

## Browser vs server yaw (calibration, one-off)

BlazeFace (browser) and YuNet (server) place their keypoints differently, so the two estimates are not equal.

- **Measured:** both ran on the same 88 real LFW photos (yaw -66 to +32 degrees). The browser estimate is about
  **0.87 x the server's** (correlation 0.96).
- **Browser setting:** the browser therefore asks for a **20 degree** turn, which is about 23 degrees on the server
  (which needs 20). A turn the browser accepts clears the server's bar, without asking customers to turn further
  than needed.
- **Synthetic turns:** they respond differently (+35 degrees measured +22 in the browser and +35.5 / -28.2 on the
  server), so the fake webcam uses a 35 degree synthetic turn.

## Sizes (normal build)

Nothing extra loads on the first page: 520 kB, 165 kB gzipped, the same as Phase 12. The camera loads only when
**Turn on camera** is pressed:

| Asset | Raw | Gzipped |
|---|---|---|
| MediaPipe Tasks JS (`@mediapipe/tasks-vision` 1.2.2) | 153 kB | 44 kB |
| WebAssembly loader | 334 kB | 81 kB |
| WebAssembly runtime | 14.6 MB | 4.1 MB |
| BlazeFace short-range model (bundled, `frontend/src/vision/models/`) | 230 kB | – |

All of it is served by the site itself, with no CDN. nginx now gzips `application/wasm`.

## Something odd: MediaPipe's usage logging

The demo-site Playwright test (it fails on any request that leaves the site) caught MediaPipe Tasks posting usage
statistics to `https://odml.pa.googleapis.com/v1/log`.

- **What it sends:** task type, running mode and timings, no images. It sends every 60 s and when a task closes.
- **No switch:** the library has no option to turn it off.
- **The fix:** `frontend/src/vision/faceDetector.ts` answers requests to that one host locally with an error, and
  MediaPipe's logger then stops. The test now passes with no outside request.
- **Why it matters:** a bank's selfie step should not talk to third parties without disclosure.

## End-to-end runs (the whole system in host mode, 23 Nov 2026)

- **`scripts/e2e_api_smoke.py`: ALL PASSED** (`e2e_api_results.json`). It ran 7 applications in waves of three,
  plus the officer queue, case, rejection and audit trail, and 6 security checks.

  | Case | Outcome | Time |
  |---|---|---|
  | 1. Genuine passport, selfie and camera head-turn frames | **AUTO_APPROVED** in 27 s | liveness passed: turns +28.8 / -22.9 degrees, same person 0.52 / 0.61 |
  | 5. The same with a photo uploaded instead | **MANUAL_REVIEW medium** | `liveness_not_provided` |
  | 6. A static photo: the selfie three times | **RESUBMIT_REQUIRED** | turns 0 / 0 |
  | 7. Head turns of another person | **MANUAL_REVIEW high** | same person 0.01 / 0.12 |
  | 2. Forged, 3. blank, 4. wrong date of birth | high review / resubmit / high review | as before |

  - **The first attempt overloaded the system.** It submitted all seven at once, and one local LLM plus one forgery
    worker could not keep up: several checks overran their deadlines (forgery 60 s, extraction 180 s) and went to
    review, as designed. A presigned image download also timed out after 10 s.
  - **The fix:** the script now submits in waves of three and allows 60 s for the download.
  - **Still one timeout:** case 6 recorded a late forgery result, under heavy swap. Its outcome is unaffected (the
    liveness failure means a retake).
- **Playwright on the real system (`frontend/e2e/kyc-flow.spec.ts`): 4 of 4 passed.**
  - The genuine applicant used the smart camera with the head-turn fake webcam: **Verified in 37.0 s**. On the
    server: neutral yaw 0.7, turns +36.8 / -28.0 degrees, same person 0.37 / 0.41, face match 0.94.
  - The forged case: under review after 53.5 s; its officer page shows "No head-turn check".
  - The blank document: resubmit after 8.2 s.
  - Screenshot: `e2e/05_wizard_3_selfie_camera.png`, the camera asking for the left turn (used in the README).

## Screenshots

- `01_camera_check_turn_left.png`, `02_camera_check_done.png`, `03_camera_check_phone.png`: the demo site's
  *Try the camera check* page, driven by Chromium's fake webcam (a synthetic head turn of a demo portrait).
- `liveness_examples.png`: one SIDTD portrait through the synthetic-turn, static-photo and tilted-photo scenarios,
  with the measured yaw.
