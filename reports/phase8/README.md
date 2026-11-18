# Phase 8: frontend screenshots

Taken by the Playwright end-to-end test (`cd frontend && npm run e2e`) against the running system, with the
synthetic demo samples from `scripts/make_demo_samples.py`. Chromium headless, 1366 × 900 (one phone view at
390 × 844).

| File | Screen |
|---|---|
| `01_login.png` | Login (one page for both roles) |
| `02_my_applications_before.png` | Customer home: My applications |
| `03_wizard_1_details.png` | Wizard step 1: full name and date of birth |
| `04_wizard_2_document.png` | Wizard step 2: ID document upload (drag and drop or file picker), preview, photo tips |
| `05_wizard_3_selfie_camera.png` | Wizard step 3: live camera with face guide (Chromium fake camera playing the genuine selfie) |
| `05b_wizard_3_selfie_upload.png` | Wizard step 3: upload fallback |
| `06_wizard_4_review.png` | Wizard step 4: review and consent |
| `07_status_verifying.png` | Status page while verifying: progress as a count of checks only |
| `08_status_verified.png` | Result: Verified (genuine passport + own selfie) |
| `09_status_under_review.png` | Result: Under review by our team (forged passport + stranger's selfie; nothing about why) |
| `10_status_resubmit.png` | Result: Please resubmit, with what to do and Start again (blank image) |
| `11_my_applications.png` | My applications after the three submissions |
| `12_officer_queue.png` | Officer case queue: highest risk first, risk chips, waiting time |
| `13_case_detail.png` | Case page of the forged application (full page) |
| `14_case_heatmap.png` | Forgery heatmap over the ID image, top tile outlined, legend with the 0.729 / 0.857 thresholds |
| `15_reject_dialog.png` | Reject dialog with the mandatory reason |
| `16_mobile_status_verified.png` | Phone width (390 px): customer result page |
| `17_case_rejected_audit.png` | Case after rejection: officer decision and the audit trail |

The e2e run behind these screenshots (17 Nov 2026) took 23-25 s per application to reach "Verified" or "Under
review", and 1.0 s to reach "Please resubmit" for the blank image (decided early, without the other checks).
