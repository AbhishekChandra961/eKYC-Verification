# Building the eKYC dashboard in Tableau Public (step by step)

This guide assumes you have never used Tableau. You build three dashboards from the CSV files in `dashboard/data/`:

1. **Operations:** how much work the system does, and how fast.
2. **Risk & fraud:** what the system flags, and whether it is right (compared with the ground truth).
3. **Model performance:** the offline evaluations, including the forgery v1 → v2 → v3 shortcut story.

> **Tableau Public publishes publicly.** Anything you save to Tableau Public can be seen by anyone on the internet.
> These files are safe to publish: the data is **synthetic** (SIDTD test documents and simulated selfies) and
> **PII-free**. There are no names, dates of birth, document numbers or real ids (see `DATA_DICTIONARY.md`).
> Never connect Tableau Public to real customer data.

## 0. Before you start

1. **Export fresh data** (the system's MongoDB must be running: `docker compose up -d`):

   ```bash
   .venv/bin/python scripts/export_dashboard_data.py
   ```

   It writes `applications.csv`, `reasons.csv`, `checks.csv`, `officer_actions.csv` and `model_metrics.csv` to
   `dashboard/data/`. `DATA_DICTIONARY.md` explains every column.
2. **Install Tableau Public** (free): <https://public.tableau.com/app/discover> → *Create* → *Download Tableau
   Public*. Create a free Tableau Public account (you need it to save).
3. **Vocabulary you will meet:**
   - *Dimension*: a category, e.g. `system_outcome`.
   - *Measure*: a number Tableau adds up, e.g. `risk_score`.
   - *Shelf*: Columns / Rows / Filters, and the *Marks* card (Color, Size, Label, Tooltip).
   - *Sheet*: one chart.
   - *Dashboard*: a page that arranges several sheets.

**Field names.** Tableau may show `system_outcome` as **System Outcome**: it replaces underscores and capitalises.
The formulas below use the CSV names. When you type a formula, type `[` and pick the field from the list that
appears, and Tableau inserts the name exactly as it shows it.

## 1. Connect the data

### 1.1 The operations data (four related tables)

1. Open Tableau Public. On the start page, under **Connect → To a File**, click **Text file** and open
   `dashboard/data/applications.csv`.
2. The *Data Source* page opens with `applications.csv` on the canvas. In the left pane, under *Files*, you see the
   other CSVs.
3. **Drag `reasons.csv` onto the canvas**, next to `applications.csv`. A line (a "noodle") joins them: this is a
   **relationship**.
   - In the panel that opens, make sure the fields are **`case_id` = `case_id`**.
   - Tableau usually picks this pair by itself; if not, choose it.
4. Do the same for **`checks.csv`** and **`officer_actions.csv`**. Each must be related to **`applications.csv`**,
   not to each other, so you get a star:

   ```
   reasons ─┐
   checks  ─┼── applications (one row per case)
   officer_actions ─┘
   ```

   - **Why relationships and not joins:** `applications` has one row per case, while `reasons` and `checks` have
     several. A join would repeat each application once per reason and inflate the counts.
   - A relationship keeps every table at its own level of detail. Tableau combines them only for the fields a
     chart uses.
5. **Check the data types.** Click `applications.csv` on the canvas and look at the type icon above each column in
   the grid:
   - `submitted_at`, `decided_at`, `closed_at` must be **Date & Time** (calendar-and-clock icon). If one is
     *String*, click its icon and choose *Date & Time*.
   - `risk_score`, `time_to_decision_s`, `queue_age_min`, `officer_wait_min` and the `*_latency_ms` columns must
     be **Number (decimal)**.
   - `decided_early`, `awaiting_officer`, `in_batch` should be **Boolean**.
   - In `officer_actions.csv`, `acted_at` and `system_decided_at` must be **Date & Time**.
6. Rename the data source (top left, double-click `applications`) to **eKYC operations**.

### 1.2 The model metrics (a separate data source)

1. Menu **Data → New Data Source → Text file**, and open `dashboard/data/model_metrics.csv`.
2. Rename the data source to **Model metrics**. It has no relationship to the operations data, and needs none.

## 2. Calculated fields (exact formulas)

Create each one with **Analysis → Create Calculated Field…**:
1. Make sure the right data source is selected in the Data pane.
2. Type the name.
3. Paste the formula.
4. Click OK. The green check under the editor must say *The calculation is valid*.

### 2.1 In "eKYC operations"

| Name | Formula | Format |
|---|---|---|
| Applications | `COUNTD([case_id])` | number |
| Auto-approval rate | `SUM(IF [system_outcome] = "AUTO_APPROVED" THEN 1 ELSE 0 END) / COUNTD([case_id])` | percentage, 0 decimals |
| Manual-review rate | `SUM(IF [system_outcome] = "MANUAL_REVIEW" THEN 1 ELSE 0 END) / COUNTD([case_id])` | percentage |
| Resubmit rate | `SUM(IF [system_outcome] = "RESUBMIT_REQUIRED" THEN 1 ELSE 0 END) / COUNTD([case_id])` | percentage |
| Median time to decision (s) | `MEDIAN([time_to_decision_s])` | number, 0 decimals |
| Waiting for an officer | `SUM(IF [awaiting_officer] THEN 1 ELSE 0 END)` | number |
| Oldest waiting case (min) | `MAX([queue_age_min])` | number, 0 decimals |
| Latency (s) | `[latency_ms] / 1000` (use the `latency_ms` of **checks.csv**) | number, 1 decimal |
| p95 latency (s) | `PERCENTILE([Latency (s)], 0.95)` | number, 1 decimal |
| Funnel 1 Submitted | `COUNTD([case_id])` | number |
| Funnel 2 Decided by the system | `COUNTD(IF [system_outcome] <> "(pending)" THEN [case_id] END)` | number |
| Funnel 3 Sent to an officer | `COUNTD(IF [system_outcome] = "MANUAL_REVIEW" THEN [case_id] END)` | number |
| Funnel 4 Decided by an officer | `COUNTD(IF [officer_action] <> "none" THEN [case_id] END)` | number |
| Funnel 5 Rejected by an officer | `COUNTD(IF [officer_action] = "reject" THEN [case_id] END)` | number |
| Outcome (readable) | see below | - |
| System vs truth | see below | - |
| Fraud catch rate | `SUM(IF [truth_class] = "fraud_or_mismatch" AND [system_outcome] <> "AUTO_APPROVED" THEN 1 ELSE 0 END) / SUM(IF [truth_class] = "fraud_or_mismatch" THEN 1 ELSE 0 END)` | percentage |
| Missed frauds | `SUM(IF [truth_class] = "fraud_or_mismatch" AND [system_outcome] = "AUTO_APPROVED" THEN 1 ELSE 0 END)` | number |
| False-alarm rate | `SUM(IF [truth_class] = "legitimate" AND [system_outcome] = "MANUAL_REVIEW" THEN 1 ELSE 0 END) / SUM(IF [truth_class] = "legitimate" THEN 1 ELSE 0 END)` | percentage |
| Flag confirmed by officer | `SUM(IF [action] = "reject" THEN 1 ELSE 0 END) / COUNT([action])` (fields of **officer_actions.csv**) | percentage |
| Officer agrees with truth | `SUM(IF ([action] = "reject" AND [truth_class (officer_actions.csv)] <> "legitimate") OR ([action] = "approve" AND [truth_class (officer_actions.csv)] = "legitimate") THEN 1 ELSE 0 END) / COUNT([action])` | percentage |

**Outcome (readable)**: one label per final state, used for colour:

```
IF [final_status] = "APPROVED" AND [system_outcome] = "AUTO_APPROVED" THEN "Auto-approved"
ELSEIF [final_status] = "APPROVED" THEN "Approved by officer"
ELSEIF [final_status] = "REJECTED" THEN "Rejected by officer"
ELSEIF [final_status] = "DECIDED" THEN "Awaiting officer"
ELSEIF [final_status] = "RESUBMIT_REQUESTED" THEN "Retake requested"
ELSE "In progress"
END
```

**System vs truth**: what the system decided, compared with what was really submitted:

```
IF [truth_class] = "not_in_batch" THEN "No ground truth"
ELSEIF [truth_class] = "legitimate" AND [system_outcome] = "AUTO_APPROVED" THEN "Correct: approved"
ELSEIF [truth_class] = "legitimate" AND [system_outcome] = "MANUAL_REVIEW" THEN "False alarm: sent to review"
ELSEIF [truth_class] = "legitimate" THEN "Legitimate, asked to resubmit"
ELSEIF [truth_class] = "fraud_or_mismatch" AND [system_outcome] = "AUTO_APPROVED" THEN "Missed: auto-approved"
ELSEIF [truth_class] = "fraud_or_mismatch" AND [system_outcome] = "MANUAL_REVIEW" THEN "Caught: sent to review"
ELSEIF [truth_class] = "fraud_or_mismatch" THEN "Caught: asked to resubmit"
ELSEIF [truth_class] = "unusable" AND [system_outcome] = "RESUBMIT_REQUIRED" THEN "Correct: resubmit"
ELSE "Unusable, not sent back"
END
```

- **Where the officer fields come from:** in the two officer formulas, `[action]` and `truth_class` must be the
  fields of **officer_actions.csv**. Tableau names the duplicate `truth_class (officer_actions.csv)`; pick it from
  the list.
- **Officer agrees with truth is 100 % by construction,** because the simulated officer decides from the truth.
- **Flag confirmed by officer is the informative one.** It is the share of flagged cases the officer rejected; the
  rest were false alarms.

**Risk score bins:** in the Data pane, right-click `risk_score` → **Create → Bins…** → size of bins **10** → OK. This
creates `risk_score (bin)`.

### 2.2 In "Model metrics"

| Name | Formula |
|---|---|
| Field | `SPLIT([metric], ": ", 2)` (the field name of the per-field extraction rows) |
| Match type | `SPLIT([metric], ":", 1)` (`exact` or `normalized`) |
| Value | `AVG([value])` (one value per row; AVG just takes it) |

## 3. Colours (use the same everywhere)

| Category | Hex | Used for |
|---|---|---|
| Good | `#0ca30c` | Auto-approved, Approved by officer, Correct: approved, Correct: resubmit, Caught |
| Warning | `#fab219` | Awaiting officer, MANUAL_REVIEW, medium risk, effect *medium*, False alarm |
| Serious | `#ec835a` | Retake requested, RESUBMIT_REQUIRED, effect *resubmit* |
| Critical | `#d03b3b` | Rejected by officer, high risk, effect *high*, Missed: auto-approved |
| Neutral | `#a8a7a0` | In progress, effect *info*, No ground truth, low-signal categories |
| Measure (one hue) | `#2a78d6` | every single-measure bar (counts, latencies, risk score histogram) |
| Comparison series 1-3 | `#2a78d6`, `#eb6834`, `#1baf7a` | the forgery metrics chart (3 metrics), SFace vs Siamese (2) |
| Text | `#0b0b0b` / `#52514e` | titles / secondary text |
| Accent (titles, KPI numbers) | `#0b3d6e` | SecureBank navy, as in the frontend |

**Setting a colour:**
1. Drag a field to **Color**.
2. Click the colour legend's ▾ → **Edit Colors…**.
3. Select an item on the left, then **double-click** it to open the colour picker.
4. Type the hex code.

**Status colours always come with a label.** Put the same field on **Label** too, or keep the legend visible, so
that colour is never the only cue (colour-blind readers, printouts). **Use one colour for categories that have no
meaning**, such as document types: ten hues would not be readable.

## 4. Dashboard 1: Operations

Create each sheet with the **New Worksheet** tab at the bottom, and name the tab as shown in bold.

1. **KPI Applications**
   1. Drag `Applications` to **Text** on the Marks card.
   2. Click Text → **…** and write `<Applications>` on line 1 (large, navy `#0b3d6e`, 28 pt) and *Applications* on
      line 2 (10 pt, `#52514e`).
   3. Make three more KPI sheets the same way:
      - **KPI Auto-approval rate** (`Auto-approval rate`);
      - **KPI Manual-review rate** (`Manual-review rate`);
      - **KPI Median time to decision** (`Median time to decision (s)`, text *s*).
2. **Outcome funnel**
   1. Drag **Measure Values** to **Columns**.
   2. On the *Measure Values* card, remove every measure except the five `Funnel …` fields.
   3. Drag **Measure Names** to **Rows**, then drag the rows into the order 1 → 5 (or sort A → Z: the numbers in
      the names give the order).
   4. Set Color to `#2a78d6` and drag Measure Values to **Label**.
   5. Result: Submitted → Decided by the system → Sent to an officer → Decided by an officer → Rejected.
3. **Outcomes by document type**
   1. Rows: `doc_type_label`. Columns: `Applications`. Color: `Outcome (readable)`, with the colours of §3.
   2. Sort descending (toolbar sort icon).
   3. Optional: Columns → right-click `Applications` → **Quick Table Calculation → Percent of Total** → **Compute
      Using → Outcome (readable)**, which gives 100 % stacked bars.
4. **Latency per check**
   1. Rows: `check_type` (of checks.csv). Columns: `Latency (s)` → right-click → **Measure → Median**.
   2. Drag `p95 latency (s)` to Columns as well. Then right-click its axis → **Dual Axis**, and right-click again
      → **Synchronize Axis**.
   3. Marks: set the median to *Bar* (`#2a78d6`) and the p95 to *Circle* (`#0b3d6e`).
   4. Title: *Worker processing time (median bar, 95th percentile dot)*.
   5. Extraction (the LLM) dominates: in the Phase 9 batch the medians were 29 s for extraction, 6 s for forgery
      and under 2 s for doc and face. They were measured on a 16 GB laptop under heavy swap, so they are slower
      than the unloaded Phase 7 figures.
5. **Queue age**
   1. Filters: `awaiting_officer` = True.
   2. Rows: `case_id`. Columns: `queue_age_min` (SUM). Color: `risk_level` (high `#d03b3b`, medium `#fab219`).
   3. Sort descending, and add Label = `queue_age_min`.
   4. Title: *Cases waiting for an officer (minutes since the system decision, at export time)*.
6. **Dashboard:** click **New Dashboard** (bottom), name it **Operations**.
   1. Size (left pane): **Fixed**, 1200 × 900 (or *Automatic*).
   2. Drag a **Horizontal** container to the top, and put the four KPI sheets in it.
   3. Below it, drag a second horizontal container with **Outcome funnel** and **Outcomes by document type**, and
      a third with **Latency per check** and **Queue age**.
   4. Add a title text object: *eKYC operations (synthetic test data)*.
7. **Filters:**
   1. On the *Outcomes by document type* sheet, right-click `doc_type_label` in the Data pane → **Show Filter**.
   2. Do the same for `submitted_at` (choose *Range of Dates*) and `truth_scenario`.
   3. On each filter card's ▾ menu, choose **Apply to Worksheets → All Using This Data Source**.
   4. Arrange the filter cards in one row under the title.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ eKYC operations (synthetic test data)     [doc type] [date range] [scenario] │
├────────────┬────────────┬────────────┬───────────────────────────────────┤
│ 150        │ 33 %       │ 63 %       │ 77 s                               │
│ Applications│ Auto-approved│ Manual review│ Median time to decision        │
├────────────┴────────────┴─┬──────────┴───────────────────────────────────┤
│ Outcome funnel            │ Outcomes by document type (stacked)          │
├───────────────────────────┼──────────────────────────────────────────────┤
│ Latency per check         │ Queue age (waiting cases)                    │
└───────────────────────────┴──────────────────────────────────────────────┘
```
(The numbers are those of the Phase 9 batch; a new export gives its own.)

## 5. Dashboard 2: Risk & fraud

1. **Reason frequencies**
   1. Rows: `reason_label` (reasons.csv). Columns: `COUNTD([case_id (reasons.csv)])`: drag `case_id` of
      reasons.csv, then right-click it → **Measure → Count (Distinct)**.
   2. Color: `effect` (high `#d03b3b`, medium `#fab219`, resubmit `#ec835a`, info `#a8a7a0`).
   3. Sort descending.
   4. Optional filter: `effect` ≠ info (informational reasons, such as an expired synthetic document, do not change
      the decision).
2. **Risk score distribution**
   1. Columns: `risk_score (bin)`. Rows: `Applications`. Color `#2a78d6`.
   2. Filters: `risk_level` excluding `none` and `(pending)`.
   3. How to read it:
      - auto-approvals score under 10;
      - medium-risk cases 20-50 (20 per medium reason);
      - high-risk cases 50 and more (one high reason alone gives 50 points, plus up to 10 each from the forgery
        score and a weak face match).
3. **System decision vs ground truth**
   1. Filters: `in_batch` = True.
   2. Rows: `truth_class`. Columns: `system_outcome`. Marks: **Square**.
   3. Color: `System vs truth` (Correct / Caught `#0ca30c`, False alarm `#fab219`, Missed `#d03b3b`, others
      `#a8a7a0`). Label: `Applications`.
   4. This is the confusion table. Read it per row:
      - **legitimate:** how many genuine customers were approved at once, and how many were sent to an officer
        (false alarms);
      - **fraud_or_mismatch:** how many were caught, and how many slipped through (missed);
      - **unusable:** whether bad images were sent back.
4. **KPI sheets:** `Fraud catch rate`, `Missed frauds`, `False-alarm rate` (as in §4.1, with *Critical* red for
   *Missed frauds*).
5. **Outcome per scenario**
   1. Rows: `truth_scenario`. Columns: `Applications`. Color: `system_outcome`.
   2. It shows *which* scenarios get through. In the Phase 9 batch the only miss was an impostor selfie whose
      synthetic portrait resembled the document's (face score 0.63). Crop_and_Replace forgeries are the known weak
      spot of the pixel model.
6. **Officer agreement**
   1. Uses officer_actions.csv. Rows: `system_risk_level`. Columns: `Flag confirmed by officer`.
   2. Label it, and add `Officer agrees with truth` as a KPI tile with the note *simulated officer: decides from the
      ground truth*.
   3. The officer works the queue from the top (highest risk first). In the batch, all decided cases are therefore
      high risk, and the medium-risk cases are the ones still waiting (see *Queue age*).
7. **Dashboard Risk & fraud:**
   - top row: the KPI tiles;
   - left: the confusion table (large);
   - right: reason frequencies;
   - bottom: the risk score distribution and the outcome per scenario.
   - Filters: as in §4.7 (`doc_type_label`, `submitted_at`, `truth_scenario`), applied to all sheets of the data
     source.

## 6. Dashboard 3: Model performance (data source "Model metrics")

1. **Metrics table**
   1. Rows: `model`, `version`, `split`, `metric`. Marks: **Text** = `Value` (format: number, 3 decimals).
   2. Show the filters for `model` and `split`.
   3. This is the full record of the offline evaluations. The test split was used once per model.
2. **Forgery v1 → v2 → v3 (the shortcut story)**
   1. Filters:
      - `model` = Forgery detector;
      - `split` = val;
      - `metric` in *document PR-AUC*, *localisation (heat on the edit)*, *position-matched control AUC (~0.5 =
        no cue)*.
   2. Columns: `version` (right-click → Sort → by field `version_order`, ascending), then `metric`. Rows: `Value`.
   3. Color: `metric` (`#2a78d6`, `#eb6834`, `#1baf7a`). Label: `Value`.
   4. **Reference line:** right-click the value axis → **Add Reference Line** → Constant **0.5**, label *0.5 = no
      hidden cue*.
   5. **Annotations:** right-click a v1 bar → **Annotate → Area**:
      - v1: *rejected: shortcuts (high score, but the heat is never on the edit)*;
      - v2: *rejected: compression cue (control 0.58)*;
      - v3: *accepted: every check passes*.
   6. The story: v1's headline score (0.976) looked best but was a shortcut (0 % localisation). v2 fixed the
      localisation but still had a hidden compression cue (control 0.584). v3 scores a little lower (0.963) and
      honestly (control 0.491). On the one test run it scores PR-AUC 0.984.
3. **Face verification**
   1. Filters: `model` = Face verification, `split` = LFW test, and `metric` in *ROC-AUC*, *TAR at FAR 1 %*,
      *equal error rate*.
   2. Columns: `metric`. Rows: `Value`. Color: `version` (SFace `#2a78d6`, Siamese `#eb6834`), side by side.
   3. Add a text box: *On synthetic ID portraits SFace accepts 30 % of different-person pairs at the LFW threshold,
      so scores below 0.556 go to manual review* (row *share of different people accepted*).
4. **Extraction per field**
   1. Filters: `split` = test (per field).
   2. Rows: `Field` (sort by Value, descending). Columns: `Value`. Color: `Match type` (exact `#2a78d6`,
      normalized `#1baf7a`).
   3. The MRZ lines are the weak point.
5. **Dashboard Model performance:**
   - left half: the forgery story chart;
   - right: the face chart above the extraction chart;
   - bottom: the metrics table;
   - filter: `model` (applied to the metrics table only).

## 7. Tooltips, then publish

1. **Tooltips:** on each sheet, click **Tooltip** on the Marks card and write one plain sentence, e.g.
   `<Applications> applications of type <doc_type_label> ended as <Outcome (readable)>`.
2. **Tabs:** File → **Workbook Locale** is fine as is. Check each dashboard in **Presentation Mode** (F7).
3. **Save:** **File → Save to Tableau Public As…**, sign in and give it a name, e.g. *SecureBank eKYC: synthetic
   operations dashboard*.
   - Tableau Public stores a copy of the data inside the workbook.
   - The workbook is **public**: share its link in the report.
4. **Refresh after a new batch:**
   1. Run `scripts/export_dashboard_data.py` again.
   2. In Tableau, **Data → eKYC operations → Refresh** (and *Model metrics*).
   3. Save to Tableau Public again.

   Tableau Public cannot connect live to MongoDB, so the CSV export is the bridge.

## 8. Checklist

- [ ] All four CSVs related to `applications` by `case_id`; `model_metrics` a separate data source.
- [ ] Date fields are *Date & Time*, booleans are *Boolean*.
- [ ] KPI numbers match `reports/phase9/batch_summary.md`. For example, the auto-approval rate equals AUTO_APPROVED
      / applications in its *System outcome mix* table.
- [ ] Status colours as in §3, each with a label or legend; one hue for plain counts.
- [ ] Filters apply to all worksheets of their data source.
- [ ] Titles say what the chart shows and that the data is synthetic.
