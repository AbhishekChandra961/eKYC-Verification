# Viva and interview preparation

These are the likely examiner and interviewer questions, with point-wise answers. Bold marks the keywords to say
out loud. Every number matches `reports/` and the [project report](report/REPORT.md).

**Abbreviations used:**
- **Metrics:**
  - **PR-AUC / ROC-AUC:** area under the precision-recall / ROC curve;
  - **FAR / FRR:** false accept / false reject rate;
  - **EER:** equal error rate;
  - **TAR:** true accept rate;
  - **CER:** character error rate.
- **Patterns:** **DLQ** is the dead-letter queue; **SSE** is Server-Sent Events.
- **Domain:** **MRZ** is the machine-readable zone; **PII** is personally identifiable information.

**Contents:**
1. [Data and leakage](#1-data-and-leakage)
2. [CNNs and transfer learning](#2-cnns-and-transfer-learning)
3. [Shortcut learning](#3-shortcut-learning)
4. [Forgery detection](#4-forgery-detection)
5. [Face verification](#5-face-verification)
6. [GenAI / LLM extraction](#6-genai--llm-extraction)
7. [Kafka and backend design](#7-kafka-and-backend-design)
8. [Decision engine and risk](#8-decision-engine-and-risk)
9. [Security and privacy](#9-security-and-privacy)
10. [Limitations and future work](#10-limitations-and-future-work)
11. [Analytics dashboards](#11-analytics-dashboards)
12. [Selfie liveness](#12-selfie-liveness)

**The 30-second pitch:** "A digital KYC prototype with four independent AI checks:
- document type;
- forgery, with a heatmap;
- face match;
- LLM field extraction with MRZ rules.

A transparent decision engine combines them and never auto-rejects. It runs as Kafka microservices with a React front
end. The key lesson came from forgery detection: my first model scored PR-AUC 0.976 but had learned how the files were
made, not the edits; I diagnosed and removed two shortcuts. End to end, it caught 67 of 68 frauds in a 150-application
batch, at the cost of sending a third of legitimate applications to review."

---

## 1. Data and leakage

**Q1. Why did you split by document group and not by image?**
- **Near-duplicates:** one document appears as a template, as several forgeries and as up to 20 **video frames**. An
  image-level split puts copies of the same document in train *and* test, which is **data leakage**.
- **Group** = a genuine document + every forgery derived from it + all their frames, so a test document is truly
  **unseen**.
- **Result:** 927 groups, split **70/15/15** (649/139/139), **stratified by document type**, seed 42; an automated
  check confirms no group crosses splits.

**Q2. How did you build the groups?**
- The parent of each forgery comes from the forgery's JSON **`src`** field, **not the file name**: 72
  Crop_and_Replace file names name the *donor* document.
- If a forgery uses a second document (`second_src`), **union-find** merges both documents into one group.

**Q3. How did you handle class imbalance?**
- **Class weights** from the training split: genuine **0.79**, forged **1.37**.
- **Metrics that respect imbalance:** precision, recall, F1, **PR-AUC** and the confusion matrix, **never accuracy
  alone**.
- **PR-AUC's chance level** equals the positive share (0.544 on forgery validation pages), so it is always reported
  against that.

**Q4. Why did you choose thresholds on validation and not on test?**
- **Test = one look.** Choosing a threshold on test turns the test set into training data, and the reported number
  becomes **optimistically biased**.
- **Procedure:**
  - thresholds (0.729, 0.857, 0.77, 0.2597) were chosen on **validation** or training pairs and **frozen**;
  - the test run happened once, in a fresh session;
  - the code was first dry-run with `SPLIT="val"` to prove it reproduces validation exactly.
- **Consequence I accepted:** the face FAR on test was **2.2 %**, not the 1 % target, and I **did not re-tune** it.

**Q5. What data quirks did you find, and why do they matter?**
- **Colour format:** 500 genuine templates are **CMYK** files while all forgeries are RGB, so a model reading raw
  files could learn the format. Fix: train only from a **resized RGB cache**.
- **Tiny edits:** a median **0.4 %** of the image (about 11 px tall at 512 px), so whole-page downscaling erases them.
  Hence the **tiles**.
- **Blank frames:** 62 clip frames are black (bad auto-crop); they are flagged and excluded.

## 2. CNNs and transfer learning

**Q6. Why EfficientNetB0?**
- **Compound scaling** (depth, width and resolution balanced) gives strong ImageNet accuracy at only **about 5.3 M
  parameters**: it trains on a 16 GB laptop.
- **Native 224 px input**, which matches both the classifier input and the forgery tiles.
- **Transfer learning:** ImageNet features (edges, textures, layouts) transfer to documents, so little data and
  little training time are needed.

**Q7. What does "frozen backbone, then fine-tune" mean?**
- **Stage 1:** only the new head (pooling → dropout → softmax or sigmoid) trains, and the backbone weights stay
  fixed. It is fast and stable.
- **Stage 2:** the top backbone layers are unfrozen with a **100× lower learning rate** to adapt the features.
- **For the classifier, stage 1 won** (validation macro F1 0.9900 vs 0.9896), selected by a **rule fixed in advance**:
  the frozen features already capture the layout.

**Q8. Why keep BatchNormalization layers frozen during fine-tuning?**
- **BN statistics** (running mean and variance) are estimated from **small batches** on new data and become noisy;
  unfreezing them can **wreck the pretrained features**.
- **What happened:** stage 2 of the classifier went **NaN** on the Apple GPU. Since then every fine-tuning run used
  **frozen BN**, **gradient clipping** (`clipnorm=1.0`), **TerminateOnNaN** and **checkpointing on the best validation
  metric**.

**Q9. Why Keras/TensorFlow and not PyTorch?**
- **Apple Silicon GPU:** **tensorflow-metal** gave GPU training on the M5. TensorFlow 2.18.1 is pinned for
  tensorflow-metal 1.2.0.
- **One framework end to end:** the same `.keras` models are loaded by the workers, with no conversion step.
- **Readability:** Keras' high-level API (`keras.applications.EfficientNetB0`, `fit`, callbacks) is short and easy to
  explain line by line, which was a project rule.
- **Honest trade-off:** PyTorch has MPS support and a larger research ecosystem. For transfer learning with standard
  backbones the choice makes little difference, and consistency mattered more.

**Q10. How does the classifier reject unknown documents, and where does that fail?**
- **Rule:** if the **max softmax probability is below 0.77**, report "unrecognized document". 1.48 % of test images
  fall below it.
- **Weakness:** softmax is **overconfident** outside the training distribution, so **16.5 % of LFW face photos
  passed**.
- **Mitigation:** the decision engine **never trusts one check**; blank-image detection, face detection and
  extraction complement it.

## 3. Shortcut learning

**Q11. What is shortcut learning? What was your example?**
- **Definition:** a model solves the benchmark with a **spurious cue** that correlates with the label, not with the
  intended feature (Geirhos et al., 2020).
- **Mine:** forgery **v1** scored **PR-AUC 0.976** on validation, but it learned **how the files were made**:
  1. every forged clip frame is a PNG from a separate recording, so the **label equals the recording style**;
  2. genuine templates are **JPEG quality 92** and forged ones **quality 75**.

**Q12. How did you detect the shortcut?**
- **Breakdown by source:** PR-AUC was **0.999 on clip frames** but **0.591 on templates**, where chance is 0.544.
- **Grad-CAM:** the heat lay on the altered field for **0 of 179** forged templates. It sat on faces and backgrounds.
- **Lesson:** an aggregate metric can hide that the model works on only one data source.

**Q13. What is the position-matched negative control, and why wasn't the plain control enough?**
- **Plain control:** compare tiles *away from the edit* on forged pages with genuine tiles. AUC near 0.5 means "no
  page-level cue", and v2 passed it (0.49).
- **Blind spot:** off-edit tiles come from *other parts* of the page than edit tiles; text areas were under-sampled.
- **Position-matched control:** compare tiles at the **same positions** on genuine and forged pages, with edit tiles
  excluded. It exposed v2: **0.584** overall and **0.713 on est_id**.

**Q14. What is the "edit-hidden ROC-AUC"?**
- Score each forged page **with its edit tiles removed**.
- **About 0.5** → the model cannot tell forged from genuine pages without seeing the edit (good).
- **v2: 0.583** (failed the limit of 0.58); **v3: 0.403** (passed).

**Q15. What was v2's residual cue, and how did v3 fix it?**
- **Cause:** **compression history**. Forged originals were saved at quality 75 at their original size. On types
  that are **enlarged** to 1280 px (est_id, fin_id, svk_id, grc_passport), the stretched **8×8 JPEG block pattern**
  survives.
- **Proof:** giving v2's genuine pages the same history doubled its false alarms (**5 → 11** of 150).
- **v3 fix:** every genuine page first gets the same **quality-75 save at its original size**, so both classes share
  an **identical history**. The production worker applies exactly this preprocessing to every upload.

**Q16. v3 scores lower on validation than v2. Why is that the better model?**
- **v2's higher score was partly the cue:** validation ROC-AUC 0.974 → **0.939**, and false alarms at recall 0.90 rose
  **5 → 32**.
- **v3 passes all three pre-registered stop rules:** position-matched control **0.491**, highest type 0.514, and
  edit-hidden **0.403**.
- **Test (one look):** **ROC-AUC 0.976, PR-AUC 0.984**, and the top tile on the edit for **95.3 %** of forged pages
  (a random tile touches it **10.8 %** of the time).
- **The principle:** I prefer an **honest lower number** over an inflated one; a model that relies on a cue fails
  silently in production.

## 4. Forgery detection

**Q17. How does the tile model work?**
- **Page:** RGB, longest side **1280 px**, quality-75 history (as above).
- **Tiles:** **224 px** with **stride 112** (50 % overlap); EfficientNetB0 outputs a **sigmoid per tile**.
- **Labels:** 1 = the tile shows the edit, 0 = clean, −1 = ignored (partial overlap).
- **Page score** = the **highest tile score**. The tile grid becomes the officer's **heatmap**.

**Q18. Why the max tile score and not the mean of the top 3?**
- **The pre-registered rule** was the top-3 mean, *unless validation preferred another option*.
- **Validation:** max **0.9632** vs top-3 **0.9629** PR-AUC, a **practical tie**, so the rule picked the max.
- **Why max makes sense:** an edit is **small and local** (often one or two tiles), so averaging dilutes it. The max
  also matches the heatmap's **top tile**, which is easy to explain to an officer.
- **Risk:** max is more sensitive to **one noisy tile**, which is why its threshold sits higher.

**Q19. How did you choose 0.729 and 0.857, and why two thresholds?**
- **0.729** = the lowest threshold with **recall ≥ 0.90** on validation; it becomes "**needs review**" (medium).
- **0.857383** = the **best F1** on validation; it becomes "**forgery suspected**" (high).
- **Two levels** make a **risk policy**, not a binary verdict.
- **Test check:** at 0.729, recall **0.968** and precision 0.840; at 0.857, recall **0.937** and precision **0.908**.

**Q20. Why don't you auto-reject on a high forgery score?**
- **False alarms are real:** 12.2 % of genuine test pages score ≥ 0.857, concentrated on **est_id**.
- **Accountability:** a wrongful rejection harms a customer and must be explainable, so a human decides, with a
  **mandatory reason** that is audited.

**Q21. What is the model's weak spot, and how did you mitigate it?**
- **Crop_and_Replace:** real printed text pasted from another document has no pixel artefacts to find. The model
  caught **7 of 22** on validation and **14 of 18** on test.
- **Mitigation:** **field-consistency rules**. Model **or** rules catches **71 %** of Crop_and_Replace (17 of 24) vs
  **46 %** for the model alone. In the batch, all 4 Crop_and_Replace forgeries went to review.

**Q22. Where do the bracketed confidence intervals come from?**
- A **bootstrap**: pages are resampled with replacement **within each class** many times, and the metric is
  recomputed; the 2.5th-97.5th percentiles give the **95 % interval**.
- **Test ROC-AUC 0.976 [0.959, 0.989]:** the interval shows how much a 338-page test set can move.

## 5. Face verification

**Q23. Explain FAR, FRR, EER, TAR and ROC-AUC.**
- **FAR:** share of **impostor** pairs wrongly accepted. In KYC this is the **costly error** (fraud gets in).
- **FRR:** share of **genuine** pairs wrongly rejected (friction for honest customers). **TAR = 1 − FRR**.
- **EER:** the operating point where FAR = FRR (SFace on LFW test: **1.6 %**).
- **ROC-AUC:** the probability that a random genuine pair scores higher than a random impostor pair
  (threshold-free; **0.997**).

**Q24. How did you set the face threshold?**
- **Rule:** the highest TAR with **FAR ≤ 1 %** on the 2,200 **LFW development (training) pairs**, which gives cosine
  **0.2597**.
- **Test (one look):** **FAR 2.2 %**, FRR 1.4 %, TAR at FAR 1 % = **98.4 %**. Not re-tuned, as a matter of principle.

**Q25. Why is your Siamese network so much worse than SFace?**
- **Data:** about **1,900 training pairs** cannot teach a face embedding from scratch. SFace was trained on millions
  of faces with a **hypersphere (margin) loss**.
- **Result:** Siamese test ROC-AUC **0.779**, EER **30 %**, so it is a **showcase only** and never used in the
  pipeline.
- **The point:** to show the deep-learning mechanics (shared weights, contrastive pairs) and to justify using a
  **pretrained** model in production.

**Q26. Does the LFW threshold work on ID portraits?**
- **No.** On synthetic ID portraits, **29.9 %** of *different-document* pairs were accepted: SIDTD's generated faces
  look alike, and some are reused.
- **Policy:** scores **0.2597-0.556** count as "**needs review**". The 0.556 boundary kept FAR ≤ 1 % on the portrait
  pairs.
- **Batch evidence:** the one missed fraud was a stranger's selfie scoring **0.63**, above the band. The fix needs
  **real selfie-ID calibration data**.

**Q27. What happens if no face is found?**
- **Never accept:** the customer is asked to **retake** the photo (or the case goes to review).
- **Fairness note:** YuNet missed one **dark, low-contrast** portrait (est_id_64), so per-group error rates must be
  measured on real data.

## 6. GenAI / LLM extraction

**Q28. Why a vision LLM instead of classic OCR?**
- **Layout understanding:** it returns **named fields** (surname, birth date and so on) for 10 document layouts
  without a template per type.
- **Structured output:** **JSON in a fixed schema** of 13 fields, validated with **Pydantic**.
- **Trade-off:** it is weaker than dedicated OCR on the **MRZ** (normalized line accuracy **76.7 % / 65.0 %**), so a
  dedicated MRZ reader is the first future-work item.

**Q29. Why a local LLM (Ollama) instead of a cloud API?**
- **Privacy and compliance:** identity documents are **sensitive PII**. Sending them to a third party raises
  data-protection, **data-residency** and vendor-risk issues for a bank.
- **Cost and availability:** no per-call cost, and it works offline.
- **Cost of the choice:** about **20-30 s** per document on a laptop and lower accuracy than frontier models. The
  cloud path exists behind the same interface but is **off by default**.

**Q30. How do you make LLM output reliable?**
- **Constrained output:** a fixed schema, **temperature 0**, and **Pydantic validation**; invalid answers are retried
  (at most twice).
- **Guardrails:**
  - **`num_predict` capped** (512 tokens) and a **repeat penalty** (1.05): the model once looped on MRZ `<` fillers;
  - **request timeouts**, and a fixed context size;
  - **unloading** the model if memory grows.
- **The LLM is never the sole decider:** **deterministic rules** check what it extracts.

**Q31. How did you evaluate extraction?**
- **Ground truth:** SIDTD's **VIA annotations** of the genuine templates.
- **Metrics:**
  - **exact match** (84.1 %);
  - **normalized match** (95.2 %: case, spaces, punctuation and date formats);
  - **CER** (1.8 %);
  - **valid JSON** (99.3 %).
- **Prompt tuning on 30 validation documents only**, then frozen and run **once** on 148 test documents.

**Q32. How do MRZ check digits work?**
- **ICAO 9303:** each character gets a value (digits as themselves, A-Z = 10-35, `<` = 0). Values are multiplied by
  the repeating weights **7, 3, 1**, summed, and the sum **mod 10** is the check digit.
- **Rules:** check digits for the document number, birth date, expiry date and composite; **cross-checks** of MRZ
  against the printed fields.
- **On ground truth:** all **400** MRZs are valid, and every rule false-flags at most **0.75 %**.

**Q33. Did the LLM ever hallucinate?**
- **Yes:** an LLM-written officer summary once added an **unsupported interpretation**.
- **Response:** the **template-generated summary** is the official record; the LLM text appears only as a labelled
  "**AI-assisted note**", off by default.
- **On extraction:** **23 of 60** genuine MRZ passports got a rule flag from **reading errors**, so MRZ *name*
  mismatches are only "needs review".

## 7. Kafka and backend design

**Q34. Why event-driven with Kafka instead of one API calling the models?**
- **Decoupling:** the API stays **thin and responsive** (202 Accepted), and slow models (the LLM takes 30 s) never
  block a web request.
- **Independent scaling and failure:** one worker per model, scaled through **consumer groups** (up to the partition
  count). A crashed worker resumes from its committed offset.
- **Durable log:** events survive restarts and can be **replayed**.

**Q35. Orchestration or choreography: why orchestration?**
- **Orchestration:** a central **orchestrator** sends the tasks and collects the results (**fan-out/fan-in**).
- **Why:** the "are all four checks done?" logic, the **timeouts**, the **single decision** and a **single audit
  writer** all live in one place.
- **Choreography** would spread completion tracking across services, which makes it harder to reason about and to
  audit.
- **Trade-off:** the orchestrator is a critical component, but it is stateless (state lives in MongoDB) and
  restartable.

**Q36. What is the claim-check pattern?**
- **Images go to S3; events carry only the object keys.**
- **Why:** Kafka messages stay small (images can be MBs), images are stored once, and access to them is controlled
  separately.

**Q37. How do you guarantee correctness with at-least-once delivery?**
- **At-least-once:** offsets are committed **after** processing, so a crash means **redelivery**, not loss.
- **Idempotency:** results are **upserted** under a **unique index (application_id, check_type)**. A duplicate result
  overwrites itself and is harmless.
- **Ordering:** **partition key = application_id**, so one application's events stay in order.
- **Status changes** are **conditional atomic updates** (`find_one_and_update` with the expected previous status).

**Q38. What happens when a worker fails?**
- **Transient errors:** retries with **exponential backoff**.
- **Permanent errors** (or an invalid event): the original event goes to the **DLQ** (`kyc.dlq`) with the error, for
  inspection and replay.
- **Silence:** the **timeout sweeper** marks a missing result `timed_out`, and the case goes to **manual review**
  (seen in the batch during a 60 s Kafka stall).

**Q39. Why pymongo instead of Beanie (an async ODM)?**
- **The workers are synchronous** Kafka consumer loops, so an async ODM would add an event loop and the Motor driver
  for no benefit.
- **One small shared layer** (`src/ekyc/store.py`): explicit queries, explicit **conditional updates** and
  **indexes**, easy to read in a viva.
- **Trade-off:** no declarative models in the database layer. **Pydantic** still validates events and API payloads.

**Q40. Why RustFS instead of MinIO for S3?**
- **MinIO stopped publishing community Docker images in October 2025**, so a pinned, maintained image was needed.
- **RustFS** is **S3-compatible** (boto3 works unchanged) and Apache-licensed, with a pinned version (1.0.6).
- **The code only depends on the S3 API**, so swapping in AWS S3 or MinIO is a configuration change.

## 8. Decision engine and risk

**Q41. How does the decision engine work, and why rule-based instead of a learned meta-model?**
- **A pure function:** four check results + typed details → **outcome, risk level, risk score, reasons with
  evidence**.
- **Precedence:**
  1. an unusable image → **RESUBMIT**;
  2. any **high** reason → **MANUAL_REVIEW** (high);
  3. another resubmit reason → **RESUBMIT**;
  4. any **medium** reason → review (medium);
  5. otherwise → **AUTO_APPROVED**.
- **Why rules:** **explainable** and **auditable** (regulators and officers can read them), **unit-tested**, and
  there is **no labelled real outcome data** to train a meta-model on.
- **Thresholds** come from the model JSONs, so there is one source of truth.

**Q42. Why does the system never auto-reject?**
- **Asymmetric harm:** a wrongful rejection denies a person a bank account. A human must own that decision, with a
  **mandatory reason** and an **audit trail**.
- **Model uncertainty:** with synthetic training data, an automatic rejection would not be defensible.

**Q43. How is the risk score computed, and what is it for?**
- **50 per high reason + 20 per medium**, plus up to **10** from the forgery score and up to **10** from a weak face
  score, **capped at 100**.
- **It only orders the officer queue** (highest risk first); it does not decide the outcome.

**Q44. How do you read the batch result: 98.5 % caught but 63 % manual review?**
- **Safety is high:** **67 of 68** frauds were not auto-approved, and all **45** forgeries went to review.
- **Efficiency is low:** only **48 of 75** legitimate applications were auto-approved. The **27 false alarms** come
  from the forgery model (15) and the MRZ given-names rule (10).
- **The trade-off is deliberate** (fail safe). Next: an MRZ OCR, per-type calibration and real data to cut reviews.
- **Honesty:** nothing was tuned on the batch, and the simulated officer used ground truth, so it shows the
  **workflow**, not human accuracy.

## 9. Security and privacy

**Q45. Why can't customers see fraud signals?**
- **Gaming:** scores and rule names teach a fraudster which attempt came closest (an **oracle attack**).
- **Implementation:**
  - the customer API returns a **whitelisted status object** (outcome + neutral reason);
  - a **unit test scans the customer code** and fails on fraud-signal names.
- **Officers see everything:** scores, rules, the heatmap and the audit trail.

**Q46. How do authentication and authorization work?**
- **JWT bearer tokens** with roles **CUSTOMER / OFFICER**, a **30-minute expiry**, and **argon2** password hashing.
- **Role checks** are FastAPI dependencies (a customer calling officer endpoints gets **403**).
- **Ownership:** another customer's application returns **404**, which hides that it exists.
- **SSE caveat:** a browser's `EventSource` cannot send headers, so the status stream accepts `?token=`. Mitigations:
  the short expiry and a **log filter** (`RedactTokens`) that strips `token=` from access-log lines. A production fix
  is a short-lived, stream-only token or an HttpOnly cookie.

**Q47. How do you handle PII?**
- **Logs:** names and dates of birth are **masked**. **Images:** private bucket, **presigned links that expire**.
- **Analytics:** pseudonymous ids (`C0001`), with a **guard that rejects PII-like columns** in the dashboard export.
- **Data:** synthetic documents only, the local LLM, and **secrets in `.env`** (gitignored).

## 10. Limitations and future work

**Q48. What is the biggest limitation?**
- **Synthetic data:** 10 European document types as flat scans, with generated faces. **No real documents, no phone
  photos, no Indian IDs**, so every threshold needs **recalibration** on real, consented data.
- **Also:**
  - **no liveness or anti-spoofing** (a printed photo could pass the face check);
  - a **63 % manual-review rate**;
  - a **single** Kafka broker and LLM.

**Q49. What would you change to deploy this in an Indian bank?**
- **Data and models:** Indian documents (Aadhaar, PAN, passport) with consented real samples; **liveness detection**;
  recalibrated thresholds; **per-group fairness** metrics.
- **Compliance:** the RBI KYC Master Direction (including video-based KYC), DPDP Act data handling, **audit
  retention**, and model risk management with documented validation.
- **Engineering:**
  - replicated Kafka and MongoDB, and GPU inference for extraction;
  - monitoring with drift alerts per document type;
  - learning risk weights from officer decisions, with a human in the loop.

**Q50. If you had one more month, what would you do first?**
1. A **dedicated MRZ OCR**: it removes most false alarms (the given-names rule caused 10 of 27).
2. **Forgery training on phone photos and recaptures**, plus more Crop_and_Replace examples.
3. **Real selfie-ID calibration** for the face threshold, and a liveness check.

## 11. Analytics dashboards

**Q51. Why build the dashboards in the app instead of Tableau?**
- **Reproducible:** Tableau Desktop is GUI-only. Its workbook format is undocumented (a generated workbook was
  rejected), so the dashboards could not be built from code. Power BI Desktop runs only on Windows.
- **Tested:** in the app, the dashboards are code. Tests check their numbers on every push, and they deploy with the
  demo site.
- **The Tableau path still exists:** the CSVs and `dashboard/TABLEAU_GUIDE.md` remain as an optional extra.
- **The library: MUI X Charts.**
  - It is from the MUI team, for the MUI version the app uses, so it shares the theme.
  - Legends, tooltips and keyboard navigation are built in.
  - It loads only when a dashboard opens: a 132 KB gzipped chunk; other pages are unchanged.

**Q52. How do you avoid double counting?**
- **The problem:** `risk_fraud.csv` has **one row per decision reason**, and a case can have several reasons.
- **The rule:** a case's own numbers (applications, risk score, the 0/1 columns) sit on its **first row only**. Every
  case-level chart (the risk-score histogram, system vs truth, the KPIs) uses those rows (`caseRows()`).
- **Reasons** are counted as **distinct cases** per reason.
- **Tested:** a unit test builds a case with three reasons and checks that it counts once; on the real data the
  histogram sums to 150, not to the 260 rows.

**Q53. How do you know the dashboard numbers are right?**
- **Same functions:** a **Vitest self-check** computes the headline numbers from the bundled snapshot with the same
  functions the charts use.
- **Compared with the report:** it checks them against `reports/phase9/batch_summary.json`. 150 applications,
  auto-approval 32.7 %, manual review 62.7 %, resubmit 4.7 %, 67/68 caught, 27 false alarms, and the whole
  confusion table.
- **Snapshot in sync:** a pytest test fails if the snapshot is out of date with the CSVs.
- **Rates** are averages of pre-computed 0/1 columns, where empty means "does not apply". For example, the catch rate
  averages over the 68 frauds only.
- **Percentiles** use the same interpolation as numpy and pandas.

## 12. Selfie liveness

**Q54. How does your liveness check work, and why does a printed photo fail it?**
- **The challenge:** the camera captures three frames: looking at the camera (the selfie), head turned **left**,
  head turned **right**.
- **Yaw from five landmarks:** the server takes YuNet's 5 landmarks per frame, levels the eyes, and computes
  **yaw = atan(nose offset from the eye-mouth midline / (0.5 × eye distance))**.
- **Why:**
  - the **nose tip sticks out** about half an eye distance, so a real head turn moves it sideways relative to the
    eyes and mouth;
  - a **flat photo has no depth**: tilting it moves everything together, and only perspective adds a few degrees.
- **Rules:** each turn must reach **20 degrees** from a frontal first frame, and **SFace** must see the **same
  person** in all three (cosine >= 0.2597).
- **Evaluation:**
  - all **190 static-photo** attacks and all **148 printed photos tilted 40 degrees** were caught (at most ~16
    degrees measured);
  - at a 55-degree tilt, **1 of 148** passed;
  - **41 of 42** real LFW head turns passed.

**Q55. Why does the server decide, and what does the browser's face detector do?**
- **Never trust the client.** Anyone can change JavaScript or call the API directly. The browser therefore sends
  only images, and the API accepts no liveness result (a test checks this).
- **The browser only guides:**
  - MediaPipe's BlazeFace runs on the device and gives instant feedback (*Move closer*, *Too dark*, *Turn your head
    to the left*);
  - it captures the frames automatically, so customers send usable photos the first time.
- **Calibrated to the server:** the browser's estimate was ~0.87 × the server's on 88 real LFW photos, so it asks
  for 20 degrees (~23 on the server).
- **Privacy:**
  - the model and the WebAssembly runtime are served by the app (no CDN);
  - a Playwright test caught MediaPipe sending **usage logs to Google**, so the app blocks that one host;
  - nothing leaves the browser except the submitted images.

**Q56. Is this presentation-attack detection? What can fool it, and how did you test it without real videos?**
- **No, not certified PAD (ISO/IEC 30107):** it is a simple challenge-response check, a deterrent against the
  cheapest attack.
- **What could fool it:**
  - a **replayed video** of the person turning;
  - a **3-D mask**;
  - a **digitally injected** camera stream. My own synthetic head turns pass the check, which demonstrates this.
- **What production would add:**
  - passive PAD (texture, moiré, depth);
  - randomised challenges (order, blinking);
  - camera-injection detection;
  - calibration on real, consented videos.
- **How I tested without videos:**
  - **real 3-D turns** from LFW, as separate photos of one person, chosen by the same yaw estimate, so that row
    mainly tests the same-person rule;
  - **synthetic 2.5-D rotations** of SIDTD portraits;
  - simulated **static** and **tilted-photo** attacks;
  - **different-person** frames: 144 of 148 caught on SIDTD's look-alike portraits, all 42 on LFW.
- **Decision rules:**
  - liveness failed → **retake**;
  - different people → **high-risk review**;
  - photo uploaded instead of the camera → **medium review**.

