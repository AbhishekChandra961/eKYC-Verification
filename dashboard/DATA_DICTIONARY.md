# Dashboard data dictionary (Phase 9)

`scripts/export_dashboard_data.py` writes five CSV files to `dashboard/data/`. They are built from MongoDB, the
batch ground truth (`data/processed/batch/ground_truth.csv`, written by `scripts/simulate_batch.py`) and the saved
model reports in `reports/`. It also writes three pre-joined files to `dashboard/data/tableau/`, built from those
five, for the *Quick path* of `TABLEAU_GUIDE.md` ([last section](#tableau-pre-joined-files-for-the-quick-path)).

**The in-app dashboards (Phase 12)** read these three pre-joined files. `scripts/export_dashboard_snapshot.py` bundles
the columns they use, renamed to short keys, as `frontend/src/dashboards/snapshot.json`; the renaming is listed in the
script. Re-run it after every export. The same privacy guard runs there.

**Which applications.** Only the simulated batch (the applications in the ground-truth file), so the numbers match
`reports/phase9/batch_summary.md`. MongoDB also holds test runs (end-to-end and smoke tests, the demo-site
recordings): `--all` adds them, with `in_batch` false and `truth_class` `not_in_batch`.

**Privacy.** Tableau Public publishes every workbook publicly, so the files contain no personal data:
- **Left out:** names, dates of birth, document numbers, extracted fields, customer and user ids, e-mail
  addresses, S3 keys, and the officers' free-text reasons.
- **Pseudonyms:** application ids become `C0001`, `C0002`, … (numbered by submission time; the mapping is not
  saved) and officers become `officer_1`, ….
- **Reason texts** are fixed labels per reason code, because some stored messages contain document dates.
- **Synthetic data:** everything comes from SIDTD *test* templates (synthetic documents) and simulated selfies.
- **A guard:** the export stops if a column name looks like personal data.

**Conventions:**
- **Times** are UTC, written as `YYYY-MM-DD HH:MM:SS` (Tableau reads them as *Date & Time*).
- **Durations** carry their unit in the name (`_s`, `_ms`, `_min`).
- **Empty cell** = not applicable (e.g. no officer action yet).

**Relationships.** `case_id` links `applications` (one row per case) to `reasons`, `checks` and
`officer_actions` (many rows per case, or none). `model_metrics` stands alone.

## applications.csv: one row per application

| Column | Type | Meaning |
|---|---|---|
| `case_id` | text | Pseudonymous application id (`C0001`, …), in submission order. The key for the other tables. |
| `submitted_at` | date & time | When the customer submitted (API received the upload). |
| `decided_at` | date & time | When the system's decision engine decided (empty while the checks are running). |
| `closed_at` | date & time | When the application reached a closed status (APPROVED, REJECTED, RESUBMIT_REQUESTED); empty while open. |
| `doc_type` | text | Document type **as classified by the system** (e.g. `srb_passport`); `(not classified)` when the image was unusable. |
| `doc_type_label` | text | Readable name of `doc_type` (e.g. *Serbian passport*). |
| `system_outcome` | text | The system's decision: `AUTO_APPROVED`, `MANUAL_REVIEW` or `RESUBMIT_REQUIRED`; `(pending)` while running. |
| `final_status` | text | Status now. `SUBMITTED` / `PROCESSING` = checks running; `DECIDED` = **waiting for an officer** (manual review only); `APPROVED` (by the system or an officer), `REJECTED` (officer), `RESUBMIT_REQUESTED` (customer must start again) are closed. |
| `risk_level` | text | `low`, `medium`, `high`; `none` for a resubmission (no risk level); `(pending)` while running. |
| `risk_score` | number | 0-100, orders the officer queue. 50 per high reason, 20 per medium reason, plus up to 10 from the forgery score and up to 10 from a weak face match. |
| `decided_early` | true/false | True when the document image was unusable (blank / unrecognized) and the remaining checks were skipped. |
| `reason_count` | number | How many reasons the decision lists (including informational ones). |
| `time_to_decision_s` | number | Seconds from `submitted_at` to `decided_at`: the end-to-end automated latency. |
| `officer_action` | text | `approve`, `reject`, or `none` (no officer decision; an auto-approval or a resubmission never gets one). |
| `officer_wait_min` | number | Minutes from the system decision to the officer's decision (officer-decided cases only). |
| `awaiting_officer` | true/false | True when the case is in the officer queue right now (`final_status = DECIDED`). |
| `queue_age_min` | number | For waiting cases: minutes since the system decision, measured at the **latest event recorded in the export** (a submission or status change; `Data as of (UTC)` in `tableau/operations.csv`), not at export time. A re-export of unchanged data gives the same values. |
| `in_batch` | true/false | True for applications of the simulated batch (they have ground truth). Always true in the default export; `--all` adds the others (test runs, manual demo submissions) as false. |
| `doc_latency_ms` | number | Processing time of the document-classifier worker (model + image download), in ms. |
| `face_latency_ms` | number | Processing time of the face-matching worker, in ms. |
| `forgery_latency_ms` | number | Processing time of the forgery-detection worker, in ms. |
| `extraction_latency_ms` | number | Processing time of the LLM field-extraction worker (Ollama qwen2.5vl:7b), in ms. Empty when skipped. |
| `truth_scenario` | text | **Ground truth.** What was really submitted: `genuine`, `forged_own_selfie`, `genuine_wrong_details`, `stranger_selfie`, `unreadable`, `forged_stranger`; `not_in_batch` without ground truth. |
| `truth_class` | text | **Ground truth**, grouped: `legitimate` (should be approved), `fraud_or_mismatch` (must not be auto-approved), `unusable` (should be sent back), `not_in_batch`. |
| `truth_document` | text | The document really was `genuine`, `forged`, or `unusable` (not a readable document). |
| `truth_selfie` | text | The selfie shows the document's own portrait (`own`) or a different person (`stranger`). |
| `truth_details` | text | The typed name / date of birth were `correct`, `wrong_dob` or `wrong_name` (3 letters changed). |
| `truth_expected_outcome` | text | What an ideal system would decide: `AUTO_APPROVED` (legitimate), `MANUAL_REVIEW` (fraud or mismatch), `RESUBMIT_REQUIRED` (unusable). |
| `truth_forgery_type` | text | For forged documents: SIDTD forgery method, `Inpaint_and_Rewrite` (text re-drawn) or `Crop_and_Replace` (text pasted from another document). |
| `truth_altered_field` | text | For forged documents: the field that was edited (e.g. `surname`, `birth_date`). |
| `truth_unreadable_kind` | text | For unusable uploads: `blank_black`, `flat_white`, `very_dark_photo`, `not_a_document` (a portrait uploaded as the ID). |

## reasons.csv: one row per decision reason

| Column | Type | Meaning |
|---|---|---|
| `case_id` | text | The application (see `applications.case_id`). |
| `reason_code` | text | Stable code, e.g. `forgery_suspected`, `face_mismatch`, `dob_mismatch`, `rule_mrz_vs_surname`, `extraction_timed_out`. |
| `reason_label` | text | Readable label of the code (fixed text, no document data). |
| `effect` | text | What the reason does to the decision: `high` / `medium` (manual review at that risk level), `resubmit` (ask for new photos), `info` (no effect, e.g. an expired synthetic document). |
| `check_type` | text | The check that produced it: `doc`, `face`, `forgery`, `extraction`, or `applicant` (typed details vs the document). |
| `system_outcome` | text | The decision of the case (copied, for filtering without the relationship). |
| `risk_level` | text | The risk level of the case (copied); `none` for a resubmission. |

## checks.csv: one row per check of an application

| Column | Type | Meaning |
|---|---|---|
| `case_id` | text | The application. |
| `check_type` | text | `doc`, `face`, `forgery` or `extraction`. |
| `status` | text | `ok`, `failed` (ran, no usable result), `timed_out` (no result in time: 60 s, extraction 180 s), `skipped` (not possible, e.g. extraction without a document type). |
| `score` | number | doc: classifier confidence (0-1); face: cosine similarity (match from 0.556, mismatch below 0.2597); forgery: page score (review from 0.729, suspected from 0.857); extraction: number of failed consistency rules. Empty when the check did not succeed. |
| `band` | text | doc: `recognized` / `unrecognized` / `blank`; face: `match` / `needs_review` / `mismatch` / `no_face_found`; forgery: `pass` / `needs_review` / `forgery_suspected`; extraction: `all_rules_pass` / `review_flag` / `strong_flag`. For a failed check: its status. |
| `latency_ms` | number | The worker's processing time in ms. |
| `model_version` | text | JSON: model file and SHA-256 prefix (and device) that produced the result. |

## officer_actions.csv: one row per officer decision

| Column | Type | Meaning |
|---|---|---|
| `case_id` | text | The application. |
| `officer` | text | Pseudonymous officer (`officer_1`, …). In the simulated batch every decision is made by the simulated demo officer. |
| `action` | text | `approve` or `reject` (always with a mandatory reason, not exported). |
| `acted_at` | date & time | When the officer decided. |
| `system_decided_at` | date & time | When the system sent the case to review. |
| `wait_min` | number | Minutes the case waited for the officer. |
| `system_risk_level` | text | The system's risk level for the case (`medium` / `high`). |
| `system_risk_score` | number | The system's risk score. |
| `truth_class` | text | Ground truth of the case (see `applications.truth_class`). |
| `truth_scenario` | text | Ground-truth scenario (see `applications.truth_scenario`). |

The simulated officer decides from the ground truth: it rejects forgeries, impostors, wrong details and non-documents
and approves legitimate cases. Agreement with the truth is therefore 100 % by construction. The informative figure is
how often the officer **confirms the system's flag** (rejects) versus overturns it (approves a false alarm).

## model_metrics.csv: offline model evaluations (long format)

| Column | Type | Meaning |
|---|---|---|
| `model` | text | `Document classifier`, `Forgery detector`, `Face verification`, `Field extraction`. |
| `version` | text | Model version, e.g. `v1 whole image`, `v2 tiles`, `v3 tiles, equal history`, `SFace (production)`, `Siamese (showcase)`. |
| `version_order` | number | Sort order of the versions within a model (forgery v1 = 1, v2 = 2, v3 = 3). |
| `split` | text | Where it was measured: `val`, `test` (used once), `val (templates only)`, `LFW test`, `LFW faces`, `synthetic ID pairs`, `test (per field)`. |
| `metric` | text | What was measured, e.g. `document ROC-AUC`, `edit-hidden ROC-AUC (~0.5 or lower = no cue)`, `TAR at FAR 1 %`, `exact: surname`. |
| `value` | number | The value, 0-1 for rates and AUCs (seconds for latencies, as named in `metric`). |
| `source` | text | The report file the value was read from. |
| `note` | text | Context, e.g. why v1 was rejected. |

Shortcut checks (forgery): the **position-matched control AUC** compares tiles at the same page positions on genuine
and forged pages, with the edit tiles left out; ~0.5 means no hidden cue. The **edit-hidden ROC-AUC** scores the
documents with the edit tiles removed; ~0.5 or lower means the model needs the edit itself. v1's "localisation" is
the Grad-CAM pointing score (0 of 179); v2/v3 use "the top tile touches the edit".

## tableau/: pre-joined files for the Quick path

One file per dashboard, each its own data source (no relationships). They are built only from the five files above,
so they hold nothing more; the privacy guard also checks their column names.

Conventions:
- **Friendly values:** codes become readable labels, e.g. `AUTO_APPROVED` → *Auto-approved*, `high` → *High*,
  `fraud_or_mismatch` → *Fraud or mismatch*, `forged_own_selfie` → *Forged, own selfie*.
- **`(0/1)` columns:** 1 = yes, 0 = no, empty = does not apply. Their average is a rate and their sum a count
  (Tableau skips empty cells).
- **`Applications`** is 1 per application: its sum counts applications.
- **Durations** carry their unit in the name, e.g. `Time to decision (s)`.

### operations.csv: one row per application (dashboard 1)

| Column | From (`applications.csv` unless noted) |
|---|---|
| `Case`, `Submitted (UTC)`, `Decided by the system (UTC)`, `Closed (UTC)`, `Document type` | `case_id`, `submitted_at`, `decided_at`, `closed_at`, `doc_type_label` |
| `System outcome`, `Risk level`, `Scenario (truth)`, `Officer decision` | `system_outcome`, `risk_level`, `truth_scenario`, `officer_action`, as readable labels |
| `Outcome` | The guide's *Outcome (readable)*: Auto-approved, Approved by officer, Rejected by officer, Awaiting officer, Retake requested, In progress. |
| `Applications` | 1. |
| `Auto-approved (0/1)`, `Manual review (0/1)`, `Resubmit required (0/1)` | 1 when `system_outcome` is that outcome. The averages are the outcome rates. |
| `Time to decision (s)` | `time_to_decision_s`. |
| `Doc check (s)`, `Face check (s)`, `Forgery check (s)`, `Extraction check (s)` | `*_latency_ms` / 1000 (the guide's *Latency (s)*); empty when the check did not run. |
| `Funnel 1 Submitted` … `Funnel 5 Rejected by an officer` | The funnel steps, 1 or 0: every case; decided by the system; `MANUAL_REVIEW`; any officer decision; an officer rejection. |
| `Officer wait (min)` | `officer_wait_min`. |
| `Waiting for an officer (0/1)`, `Queue age (min)` | `awaiting_officer`, `queue_age_min`. |
| `Data as of (UTC)` | The moment the queue ages are measured at (the latest recorded event); the same on every row. |

### risk_fraud.csv: one row per decision reason (dashboard 2)

A case without any reason gets one row with `Reason` = *No reason*, so that every case is present. A case's labels
repeat on all its rows (so every filter works); **its numbers sit on its first row only** (empty on the others),
so sums and averages count each application once.

| Column | Meaning |
|---|---|
| `Case`, `Submitted (UTC)`, `Document type`, `System outcome`, `Outcome`, `Risk level` | As in `operations.csv`. |
| `Risk score band` | `risk_score` rounded down to a multiple of 10 (0, 10, … 100): the guide's `risk_score (bin)`. |
| `Truth class`, `Scenario (truth)`, `Forgery method (truth)` | `truth_class`, `truth_scenario` (readable), `truth_forgery_type`. |
| `System vs truth` | The guide's *System vs truth*, e.g. *Caught: sent to review*, *False alarm: sent to review*, *Missed: auto-approved*. |
| `Officer decision` | Approved, Rejected or No officer decision. |
| `Reason`, `Reason effect`, `Raised by` | `reasons.csv`: `reason_label`, `effect` (High, Medium, Resubmit, Info only) and `check_type` (Document classifier, Face match, Forgery detector, Field extraction, Typed details). |
| `Cases with this reason` | 1 on a reason row, empty on a *No reason* row: its sum is the guide's reason count. |
| `Applications`, `Risk score` | First row of the case only: 1, and `risk_score`. |
| `Fraud caught (0/1)`, `Missed fraud (0/1)` | For frauds and mismatches only (`truth_class = fraud_or_mismatch`): not auto-approved, or auto-approved. |
| `False alarm (0/1)` | For legitimate cases only: sent to manual review. |
| `Officer confirmed the flag (0/1)` | For officer-decided cases only: the officer rejected. |
| `Officer agrees with truth (0/1)` | For officer-decided cases with ground truth: rejected a fraud, mismatch or unusable image, or approved a legitimate case (100 % by construction, see above). |

### model_performance.csv: one row per metric (dashboard 3)

| Column | Meaning |
|---|---|
| `Model`, `Version`, `Version order`, `Split`, `Metric`, `Value`, `Note`, `Source` | As in `model_metrics.csv`. |
| `Used in chart` | Which chart of the guide's §6 draws the row: *Forgery story* (val; document PR-AUC, localisation, position-matched control), *Face verification* (LFW test; ROC-AUC, TAR at FAR 1 %, equal error rate), *Extraction per field*, or *Metrics table only*. |
| `Field`, `Match type` | Per-field extraction rows only: the field (e.g. `surname`) and *Exact* or *Normalized*. |
