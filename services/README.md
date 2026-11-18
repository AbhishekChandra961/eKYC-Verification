# Services: frontend, API, orchestrator, inference workers (Phases 6-8)

```
browser (React, frontend/) --HTTP--> api --(kyc.submitted)--> orchestrator --(kyc.tasks.doc|face, then forgery|extraction)--> 4 workers
                    ^  SSE   |                         |  ^                                                          |
                    |        v                         v  +----------------------(kyc.results)-------------------------+
                    |    MongoDB <------------------- decision engine (src/ekyc/decision.py) --(kyc.decided)
                    +--- applications, check_results, audit_log, users          S3 (RustFS): the images (events carry keys only)
```

- **Infrastructure in Docker** (`docker-compose.yml`): Kafka 4.4 (KRaft, no ZooKeeper), Kafka UI (kafbat),
  MongoDB 8.0, and RustFS as the S3-compatible store. MinIO's community images stopped in 2025, and the project
  was archived in 2026.
- **Services run on the host** as Python processes. Containerising them is Phase 9.
- **Ollama always runs on the host** (Docker on macOS has no GPU).

## Start the whole system (one place)

One-time setup:

```bash
cp .env.example .env                              # then fill in the secrets and the demo accounts
(cd frontend && npm install)                      # frontend packages (~420 MB in frontend/node_modules)
.venv/bin/python scripts/make_demo_samples.py     # demo_samples/: 6 synthetic test cases + what to type
```

Every time:

```bash
docker compose up -d        # Kafka, Kafka UI, MongoDB, S3 (RustFS)
ollama serve                # if it is not already running (the extraction worker needs it)
scripts/run_all.sh          # orchestrator + API + 4 workers + frontend; checks the above first; Ctrl+C stops all
```

| What | Where |
|---|---|
| Customer and officer portals | http://localhost:5173 (log in with `DEMO_CUSTOMER_*` / `DEMO_OFFICER_*` from `.env`) |
| API docs (try every endpoint) | http://localhost:8000/docs |
| Kafka UI | http://localhost:8080 |
| Logs | `logs/services/<name>.log` |
| Demo files and what to type | `demo_samples/README.md` |

- **Workers need about 30 s** to load their models after `run_all.sh` starts.
- **`EKYC_NO_FRONTEND=1 scripts/run_all.sh`** starts only the backend.
- **Open the frontend as `localhost`, not `127.0.0.1`.** The API allows CORS from `http://localhost:5173` only.

Tests:

```bash
.venv/bin/python -m pytest                          # Python: decision engine, orchestrator, API, workers
.venv/bin/python scripts/e2e_api_smoke.py           # API end to end + officer flow + security checks
cd frontend && npm run lint && npm run typecheck && npm test   # ESLint, TypeScript (strict), Vitest
cd frontend && npm run e2e                          # Playwright (Chromium) through the UI; screenshots in reports/phase8/
```

### API (FastAPI, `services/api/app.py`): thin, no model ever runs here

| Method | Path | Role | What it does |
|---|---|---|---|
| POST | `/auth/login` | - | form `username` (email) + `password` -> JWT (30 min) |
| POST | `/applications` | CUSTOMER | multipart: `full_name`, `date_of_birth`, `id_image`, `selfie` (JPEG/PNG, <= 10 MB, checked with Pillow) -> S3 + MongoDB + `kyc.submitted` -> **202** with the id |
| GET | `/applications`, `/applications/{id}` | CUSTOMER | own applications only (another customer's id -> 404); status, outcome, a neutral message, progress (checks completed / total, never their results), and what to retake (only for RESUBMIT_REQUIRED) |
| GET | `/applications/{id}/events` | CUSTOMER | Server-Sent Events: one `status` event per change until a final status (`?token=` accepted, since browser EventSource cannot send headers) |
| GET | `/officer/cases` | OFFICER | queue, filter `status` / `outcome`, highest risk score first |
| GET | `/officer/cases/{id}` | OFFICER | applicant data, every check result, decision + reasons with evidence, official summary, forgery top tile and tile grid (`forgery_heatmap`), 5-minute presigned image URLs, audit trail |
| POST | `/officer/cases/{id}/decision` | OFFICER | `{"action": "approve"\|"reject", "reason": "..."}` (reason mandatory); only from DECIDED (else 409); audited |
| GET | `/health` | - | MongoDB, S3, Kafka reachable |

- **Passwords and tokens:** passwords are hashed with argon2id (argon2-cffi); tokens are JWT (PyJWT, HS256).
- **Status codes:** a wrong role gives 403; a missing, invalid or expired token gives 401.
- **CORS:** allows `http://localhost:5173`.
- **Typed responses:** every endpoint has a Pydantic response model, so the OpenAPI schema describes it exactly.
  The frontend generates its TypeScript types from that schema (`cd frontend && npm run gen:api`, which runs
  `scripts/export_openapi.py`; no server needed).
- **Customers never see fraud signals.** `ApplicationView` has no scores, flags or risk fields; a test checks every
  key of the customer responses, and the frontend checks it again (`frontend/src/customer/customerStatus.test.tsx`).
- **Logs never contain names, dates of birth or document numbers.** They are masked (`K*** V***`), and
  `token=` is removed from access-log lines.

### Orchestrator (`services/orchestrator/main.py`, logic in `src/ekyc/orchestration.py`)

1. **On `kyc.submitted`:** the status goes SUBMITTED -> PROCESSING, and the doc and face tasks are published in
   parallel.
2. **On the doc result:**
   - an unusable document (blank or unrecognized) is decided at once as RESUBMIT_REQUIRED, and the other checks
     are skipped;
   - otherwise the forgery and extraction tasks are published, the latter with the classified `doc_type`.
3. **Fan-in:** every result is upserted by `(application_id, check_type)`. When all four are in, the decision
   engine runs, the decision and the template summary (the **official record**) are stored, the status goes to
   DECIDED, and `kyc.decided` is published.
4. **Timeouts:** a sweeper runs every 5 s and marks a check with no result as `timed_out` (extraction after 180 s,
   the others after 60 s). That leads to MANUAL_REVIEW.
5. **Officer decision:** an officer then moves DECIDED -> APPROVED or REJECTED. Every transition is written to the
   append-only `audit_log` (actor, time, from/to status, reason).
6. **At-least-once delivery:**
   - offsets are committed after the database write;
   - transitions are conditional, so a duplicate event cannot move an application twice;
   - audit entries have deterministic ids, so writing one twice keeps the first;
   - an invalid or repeatedly failing event goes to `kyc.dlq`.
7. **Optional LLM note:** `ORCHESTRATOR_LLM_NOTE=true` adds an "AI-assisted note" per case. It is off by default
   (it would load the 6-8 GB vision model).

### Decision engine (`src/ekyc/decision.py`): a pure function, thresholds read from `models/*.json`

| Check | Condition | Effect |
|---|---|---|
| doc | blank / almost black image | RESUBMIT_REQUIRED "image unreadable" (decided early) |
| doc | confidence < 0.77 (`doc_classifier.json`) | RESUBMIT_REQUIRED "unrecognized document" (early) |
| face | no face on the selfie / document | RESUBMIT_REQUIRED "retake the selfie / document photo" |
| face | score < 0.2597 (`face_config.json`) | MANUAL_REVIEW **high** |
| face | 0.2597 <= score < 0.556 (`face_config.json` `review_below`) | MANUAL_REVIEW medium |
| forgery | score >= 0.857383 (`forgery_detector.json`) | MANUAL_REVIEW **high** |
| forgery | 0.729 <= score < 0.857383 | MANUAL_REVIEW medium |
| extraction | status failed / timed out / skipped | MANUAL_REVIEW medium |
| extraction | a reliable rule fails (check digits, expiry, document number, date order) | MANUAL_REVIEW **high** |
| extraction | an MRZ name / birth-date / format rule fails | MANUAL_REVIEW medium |
| applicant | name differs (case-, diacritic- and order-insensitive; typed words on the document, or >= 0.85 similar) | MANUAL_REVIEW medium |
| applicant | date of birth differs from the document | MANUAL_REVIEW **high** |
| applicant | date of birth unreadable | MANUAL_REVIEW medium |
| extraction | document expired (as of `expiry_as_of`, default today) | **info** (74 % of the synthetic templates are expired); `expired_is_informational=False` -> RESUBMIT_REQUIRED |
| any check | did not complete (timed out / failed / missing) | MANUAL_REVIEW medium |
| - | nothing above | AUTO_APPROVED |

- **Precedence:**
  1. an unusable document;
  2. any high reason (a suspected fraud is never just bounced back for a retake);
  3. any retake reason;
  4. any medium reason;
  5. otherwise approved.
- **Risk score**, for sorting the queue, up to 100:
  - 50 per high reason, 20 per medium;
  - plus up to 10 from the forgery score and up to 10 from a weak face match.
- **Every reason carries `check_type` and its evidence values.** Dates of birth are never repeated in it.

## 1. Start the infrastructure (Phase 6)

```bash
cp .env.example .env          # then fill in KAFKA_CLUSTER_ID, MONGO_ROOT_PASSWORD, S3_ACCESS_KEY, S3_SECRET_KEY
docker compose up -d          # kafka, kafka-ui, mongo, s3 + the one-shot kafka-init and s3-init
docker compose ps -a          # 4 services "healthy", kafka-init and s3-init "Exited (0)"
```

The init containers create the 8 topics (3 partitions each) and the bucket `kyc-uploads`. Running them again
changes nothing: `docker compose run --rm kafka-init`.

| UI | URL | Login |
|---|---|---|
| Kafka UI | http://localhost:8080 | none (local only) |
| RustFS console | http://localhost:9001/rustfs/console/ | `S3_ACCESS_KEY` / `S3_SECRET_KEY` from `.env` |
| MongoDB shell | `docker exec -it ekyc-mongo mongosh -u ekyc -p` | `MONGO_ROOT_PASSWORD` |

**Viewing the topics in Kafka UI:** open http://localhost:8080, go to **Topics** and click e.g. `kyc.results`,
then the **Messages** tab. Each message shows its key (= `application_id`), partition, offset and the JSON
envelope. `kyc.dlq` shows dead letters with the error and the original event. **Consumers** lists the four
worker groups and their lag.

Stop: `docker compose down` (data kept in named volumes); full reset: `docker compose down -v`.

## 2. Start only the workers

```bash
ollama serve                  # if not already running (extraction-worker)
scripts/run_workers.sh        # all four; or: scripts/run_workers.sh doc face
tail -f logs/workers/*.log    # one line per message (application, status, latency) + a heartbeat every 30 s
```

Ctrl+C stops them all. Each worker finishes its current message, leaves its consumer group, and logs its counters.

| worker | topic | does | outputs (in `CheckResult.outputs`) |
|---|---|---|---|
| doc-worker | `kyc.tasks.doc` | blank-image gate, document classifier (reject below 0.77) | `doc_type`, `confidence`, `recognized`, `blank`, `top3` |
| forgery-worker | `kyc.tasks.forgery` | exact preprocessing of `forgery_detector.json`, tile scores, page score | `score`, `band` (pass / needs_review / forgery_suspected), `top_tile` box, `tiles` grid (every tile's position + score on the 1280 px page, ~2 KB; Phase 8, for the officer's heatmap) |
| face-worker | `kyc.tasks.face` | largest face on the ID page vs the selfie (YuNet + SFace) | `score`, `band` (match / needs_review / mismatch / no_face_found) |
| extraction-worker | `kyc.tasks.extraction` | Ollama qwen2.5vl:7b (prompt v2) + consistency rules | `fields`, `rules`, `strong_flags`, `review_flags` |

- **Bands:**
  - forgery: >= 0.857383 forgery_suspected, >= 0.729 needs_review, otherwise pass;
  - face: < 0.2597 mismatch, 0.2597-0.556 needs_review, >= 0.556 match.
- **Rule severities** (`consistency.RULE_SEVERITY`):
  - "strong": check digits, expiry date, document number, date order;
  - "review": the MRZ name and birth-date cross-checks, the MRZ format.
- **Extraction failures:** a failed extraction is a result with `status: "failed"`, not an error.
- **Threshold fix:** `models/forgery_detector.json` (gitignored) had the F1 threshold rounded up to 0.8574. It was
  corrected to the exact 0.857383, with a `fix_note`.

## 3. Workers-only smoke test (Phase 6)

```bash
.venv/bin/python scripts/e2e_workers_smoke.py
```

The script uploads two applications to S3 and publishes their tasks:
- a genuine test passport with a selfie of its own portrait;
- a forged test passport with a stranger's selfie;
- a task with a missing S3 key.

It waits for every result on `kyc.results` and prints a table. It also checks the DLQ and idempotency, and ends
with PASS/FAIL lines. The output is saved to `reports/phase6/`.

## Delivery guarantees (what the Phase 7 orchestrator relies on)

- **Partition key = `application_id`.** All events of one application stay in order on one partition.
- **At-least-once:**
  1. a worker publishes its result and waits until Kafka has stored it (`flush`);
  2. only then does it commit the task's offset.

  If the worker crashes in between, it processes the task again after the restart, so a result can arrive twice.
- **De-duplication in the worker:** a re-delivered event (same `event_id`) is skipped.
- **Idempotent store (orchestrator):** results are upserted by `(application_id, check_type)`, so the same check
  arriving twice leaves one record. The smoke test does exactly this in MongoDB:

```python
store.create_index([("application_id", 1), ("check_type", 1)], unique=True)
store.update_one({"application_id": app, "check_type": result.check_type},
                 {"$set": {"status": result.status, "outputs": result.outputs, ...},
                  "$addToSet": {"result_event_ids": event_id}}, upsert=True)
```

- **Retries and DLQ:** a failing task is retried 3 times (backoff 0.5 s, 1 s), then published to `kyc.dlq` with
  the error and the original event. An event that does not match its schema goes to the DLQ at once.

## Robustness lessons from the Phase 6 smoke runs

- **When the host is short of memory, macOS pages out Docker's VM, and the single Kafka node stalls.** It then
  misses its own controller heartbeat and fences itself: the consumer-offset partitions go offline, and clients
  see "Waiting for coordinator". Three fixes:
  - `KAFKA_BROKER_SESSION_TIMEOUT_MS=60000` lets the broker survive a 60 s stall (the default fences after 9 s);
  - a failed offset commit is logged, not fatal (the task is simply delivered again);
  - a worker waits up to 5 min for Kafka to acknowledge a result instead of dying.
- **Shutting down never hangs:** if leaving the consumer group takes more than 30 s, the worker exits anyway.
- **Tests never write to the real `kyc.*` topics:** the partition test uses a temporary topic.

## Memory (16 GB Mac)

- **Container limits:** Kafka 1 GB (heap 512 MB), Kafka UI 512 MB, MongoDB 768 MB (WiredTiger cache 0.25 GB),
  RustFS 512 MB.
- **Measured idle:** about 0.9 GB for all four containers together.
- **Docker Desktop's VM** keeps a file cache on top of that. Setting Settings → Resources → Memory to 4 GB is
  enough for this stack.
- **Workers:** the two TensorFlow workers need about 1-2 GB each once warm. Ollama's runner needs 6-8 GB while
  loaded; it is unloaded after 2 minutes idle, or at once above 8 GB.
- **The TensorFlow workers run on the CPU by default** (`EKYC_TF_DEVICE=gpu` switches them to Metal). Measured one
  page at a time, the CPU is faster: doc 88 vs 236 ms, forgery 507 vs 604 ms, warm-up 2.2 vs 5.3 s. It also keeps
  the GPU free for Ollama. When both TensorFlow and Ollama used Metal at once, pages took 100-160 s instead of
  under 1 s.
