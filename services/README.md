# Services (Phase 6): Kafka infrastructure + inference workers

```
            S3 (RustFS)  <- images (claim check: events carry only object keys)
                 ^
orchestrator --(kyc.tasks.doc / .forgery / .face / .extraction)--> 4 workers --(kyc.results)--> orchestrator
 (Phase 7)                                                            \--(kyc.dlq: events that failed 3x)
```

- **Infrastructure in Docker** (`docker-compose.yml`): Kafka 4.4 (KRaft, no ZooKeeper), Kafka UI (kafbat),
  MongoDB 8.0, and RustFS as the S3-compatible store. MinIO's community images stopped in 2025, and the project
  was archived in 2026.
- **Workers run on the host** as Python processes, so TensorFlow can use the Metal GPU. Containerising them is
  Phase 9.
- **Ollama always runs on the host** (Docker on macOS has no GPU).

## 1. Start the infrastructure

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

## 2. Start the workers

```bash
ollama serve                  # if not already running (extraction-worker)
scripts/run_workers.sh        # all four; or: scripts/run_workers.sh doc face
tail -f logs/workers/*.log    # one line per message (application, status, latency) + a heartbeat every 30 s
```

Ctrl+C stops them all. Each worker finishes its current message, leaves its consumer group, and logs its counters.

| worker | topic | does | outputs (in `CheckResult.outputs`) |
|---|---|---|---|
| doc-worker | `kyc.tasks.doc` | blank-image gate, document classifier (reject below 0.77) | `doc_type`, `confidence`, `recognized`, `blank`, `top3` |
| forgery-worker | `kyc.tasks.forgery` | exact preprocessing of `forgery_detector.json`, tile scores, page score | `score`, `band` (pass / needs_review / forgery_suspected), `top_tile` box |
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

## 3. End-to-end smoke test

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
