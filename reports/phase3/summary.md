# Phase 3 summary: document classifier and forgery detector

Data: the SIDTD templates (synthetic European IDs, 10 document types) and clip frames, split by document group
70/15/15 (Phase 2). Each test split was used once. Sources: `reports/phase3/*.json` and the notebooks
`02_doc_classifier`, `03_forgery_detector` (v1), `archive/03b_forgery_tiles_v2` (v2) and `03b_forgery_tiles`
(v3, including the test run in its section 8).

## Results

| Model | Split | Data | PR-AUC | ROC-AUC | Other key numbers | Verdict |
|---|---|---|---|---|---|---|
| Doc classifier (EfficientNetB0, frozen, 224 px) | test | 1,962 templates + clip frames | – | – | accuracy 99.29 %, macro F1 0.993; 16.5 % of LFW faces pass as a document | accepted |
| Forgery v1 (whole image, EfficientNetB0, 512 px) | val | 2,109 templates + clip frames | 0.976 | 0.986 | templates only: PR-AUC 0.59 (random 0.54), ROC-AUC 0.53-0.57; Grad-CAM on the edit 0 of 179 | rejected: shortcuts |
| Forgery v2 (224 px tiles of 1280 px templates) | val | 329 templates | 0.983 | 0.974 | position-matched control 0.584 (est_id 0.713); edit-hidden ROC-AUC 0.583; 5 of 150 false alarms | rejected: compression cue |
| Forgery v3 (tiles, equal compression history) | val | 329 templates | 0.963 | 0.939 | control 0.491, edit-hidden 0.403; at 0.729: recall 0.905, 32 of 150 false alarms; top tile on the edit 93.3 % | accepted |
| **Forgery v3, final** | **test (once)** | 338 templates | **0.984** [0.974, 0.992] | **0.976** [0.959, 0.989] | at 0.729: recall 0.968, precision 0.840, 35 of 148 false alarms; at 0.857: recall 0.937, precision 0.908, 18 false alarms; control 0.484, edit-hidden 0.459; top tile on the edit 95.3 % | final |

Brackets: 95 % bootstrap intervals (pages resampled within each class). Thresholds 0.729 and 0.857 were chosen on
validation (recall >= 0.90 and best F1) and frozen before the test run.

## The shortcut story

- **v1 looked excellent and was not.** Validation PR-AUC was 0.976, but on templates alone it was near chance, and
  Grad-CAM never pointed at the edit (0 of 179). The models had learned the data's origin, not the edits:
  - clip frames: every forged frame is a PNG from a separate recording;
  - templates: genuine files are JPEG quality 92, forged ones quality 75.
- **Fix 1 (v2):** templates only, every page re-saved at quality 75 at 1280 px, and an EfficientNet scoring 224 px
  tiles, so the small edited field fills a real part of the input. Validation ROC-AUC 0.974, and the top tile lay
  on the edit for 93.9 % of forged pages.
- **A plain negative control said "clean", but it had a blind spot.** Tiles away from the edit come from different
  places of the page than the edit tiles. Comparing tiles *at the same position* (the position-matched control)
  exposed a remaining cue: 0.584 overall, 0.713 on est_id.
- **The cause was compression history, not quality.** Forged originals had been saved at quality 75 at their
  original size. On the four document types that are enlarged to 1280 px, that old block pattern survives. Giving
  v2's genuine pages the same history doubled its false alarms (5 to 11 of 150).
- **Fix 2 (v3):** every genuine page first gets the same quality-75 save at original size; quality and file sizes
  are then equal across classes. All stop rules (fixed before training) pass. The honest validation ROC-AUC is
  0.939, and the single test run gives 0.976.
- **Lesson:** a high score is not evidence that a model learned the right thing. Every forgery model here is
  checked by localisation (does the top tile sit on the edit?), the position-matched control and the edit-hidden
  ROC-AUC, not by PR-AUC alone.

## Known limitations

- **Scope:** trained and tested only on flat synthetic templates of 10 European document types. Not validated on
  phone photos, real documents or Indian IDs. Clip frames cannot be used for forgery work (label = recording).
- **Crop_and_Replace** (real printed text pasted from another document) is the weak spot: 7 of 22 caught on
  validation and 14 of 18 on test, 21 of 40 overall. A field-consistency rule is planned for Phases 5 and 7.
- **False alarms:** at 0.729, 23.6 % of genuine test pages are flagged (12.2 % at 0.857). They concentrate on
  est_id (11 of 15 genuine test pages), as on validation. Policy: 0.729-0.857 "needs review", >= 0.857
  "forgery suspected", never auto-reject on this score.
- **Compression-history sensitivity:** v3 scores genuine pages higher when their file history differs from
  training (validation false alarms 32 to 48). Production must apply exactly the preprocessing in
  `models/forgery_detector.json`, and the thresholds must be re-checked on real uploads.
- **Small groups:** per-type and per-field numbers rest on 13-50 pages, so their intervals are wide. The
  Crop_and_Replace swing between validation and test shows how much a split can move them.
- **Residual per-type differences:** the position-matched control is just above 0.5 on lva_passport (test 0.538
  [0.509, 0.566]) and below 0.5 on alb_id and esp_id in both splits. All are within the limits, with causes not
  traced.
- **Doc classifier:** high accuracy on known document types, but it does not reliably reject non-documents (16.5 %
  of LFW faces pass its confidence threshold). The decision engine must combine it with other checks.
- **Threshold storage:** `models/forgery_detector.json` stores the best-F1 threshold rounded up to 0.8574 (exact
  value 0.85738). The decision engine should use the policy values 0.729 and 0.857, which reproduce the validation
  results exactly.
