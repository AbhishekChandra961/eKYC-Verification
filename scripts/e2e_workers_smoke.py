"""End-to-end smoke test of the Phase 6 workers over the real Kafka / S3 / MongoDB stack.

Needs: docker compose up -d, scripts/run_workers.sh (all four workers) and `ollama serve`.
    .venv/bin/python scripts/e2e_workers_smoke.py

Cases (application_id = e2e-<run>-<case>):
1. a genuine test template + a simulated selfie of ITS OWN portrait            -> expect pass / match
2. a forged test template + a simulated selfie of a DIFFERENT person's portrait -> expect forgery + mismatch
3. a doc task whose S3 key does not exist                                      -> retried 3x, then kyc.dlq
The script plays the orchestrator's part: it uploads the images, publishes the doc/forgery/face tasks, publishes
the extraction task once the doc result has given the document type, and collects everything from kyc.results.

Idempotency, two ways:
a. the SAME face event (same event_id) is published twice: the worker skips the duplicate -> one face result;
b. the doc task is re-sent with a NEW event_id (as an orchestrator retry would): two result events arrive, and
   the result store upserts them by (application_id, check_type) -> still ONE record. MongoDB collection
   ekyc.check_results plays the orchestrator's store here (Phase 7 will own it).
Results: a table on screen + reports/phase6/e2e_smoke_results.csv and e2e_smoke_summary.json.
"""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from confluent_kafka import Consumer
from confluent_kafka.admin import AdminClient
from PIL import Image
from pymongo import ASCENDING, MongoClient

from ekyc import config, face
from ekyc.messaging import storage
from ekyc.messaging.events import (CheckResult, DeadLetter, DocTask, ExtractionTask, FaceTask, ForgeryTask, Topics,
                                   make_event)
from ekyc.messaging.kafka import make_producer, publish
from ekyc.messaging.settings import load_settings

RUN = datetime.now().strftime("%m%d-%H%M%S")
TIMEOUT_S = 600
WORKER_GROUPS = ["doc-worker", "forgery-worker", "face-worker", "extraction-worker"]
REPORT_DIR = config.REPORTS_DIR / "phase6"


def workers_running(settings) -> dict[str, int]:
    admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap})
    futures = admin.describe_consumer_groups(WORKER_GROUPS)
    return {group: len(f.result().members) for group, f in futures.items()}


def portrait_selfie(image_path: str, doc_id: str, seed: int) -> bytes:
    """A simulated selfie: the document's annotated portrait, rotated/scaled/relit/blurred/JPEG'd (Phase 4)."""
    boxes = pd.read_csv(config.FIELDS_GT_CSV).query("field_name == 'photo'").set_index("doc_id")
    with Image.open(config.PROJECT_ROOT / image_path) as image:
        page = np.asarray(image.convert("RGB"))
    crop = face.crop_with_margin(page, boxes.loc[doc_id, ["x", "y", "w", "h"]].to_numpy())
    selfie, _ = face.simulate_selfie(crop, np.random.default_rng(seed))
    buffer = io.BytesIO()
    Image.fromarray(selfie).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def key_outputs(check: str, r: CheckResult) -> str:
    o = r.outputs
    if r.status == "failed":
        return f"FAILED: {(r.error or '')[:80]}"
    if check == "doc":
        return "blank image" if o.get("blank") else f"{o.get('doc_type') or 'unrecognized'} (confidence {o.get('confidence')})"
    if check == "forgery":
        return f"score {o['score']} -> {o['band']}; top tile {o['top_tile']['box_original']}"
    if check == "face":
        return f"score {o['score']} -> {o['band']}"
    if check == "extraction":
        n = sum(v is not None for v in o["fields"].values())
        return (f"{n} fields; strong flags {o['strong_flags'] or 'none'}; review flags {o['review_flags'] or 'none'}; "
                f"attempts {o['attempts']}")
    return json.dumps(o)[:80]


def main() -> int:
    settings = load_settings()
    running = workers_running(settings)
    print(f"run {RUN} | workers (consumer group members): {running}")
    if not all(running.values()):
        print("Start the workers first: scripts/run_workers.sh   (missing:", [g for g, n in running.items() if not n], ")")
        return 2

    # ---- the documents (test split; this is a smoke test, not an evaluation)
    manifest = pd.read_csv(config.MANIFEST_CSV)
    templates = manifest[(manifest["source"] == "template") & (manifest["split"] == "test")]
    genuine = templates[(templates["label"] == 0) & (templates["doc_type"] == "srb_passport")].iloc[0]
    rules = pd.read_csv(config.REPORTS_DIR / "phase5" / "rules_forged_mrz_val_test.csv", index_col=0)
    pick = rules[(rules["split"] == "test") & rules["altered"].isin(["surname", "document_number"])
                 & rules["caught via the altered field"]].index[0]
    forged = templates[templates["fake_name"] == pick].iloc[0]
    stranger = templates[(templates["label"] == 0) & (templates["doc_type"] == "lva_passport")].iloc[0]
    apps = {1: f"e2e-{RUN}-case1-genuine", 2: f"e2e-{RUN}-case2-forged", 3: f"e2e-{RUN}-case3-broken"}
    cases = {1: (genuine, portrait_selfie(genuine.image_path, genuine.doc_id, seed=1), f"genuine {genuine.doc_id}"),
             2: (forged, portrait_selfie(stranger.image_path, stranger.doc_id, seed=2),
                 f"forged {forged.fake_name} ({forged.ctype}, {forged.altered_field}) + selfie of {stranger.doc_id}")}

    s3 = storage.s3_client(settings)
    producer = make_producer("e2e-smoke", settings)
    collector = Consumer({"bootstrap.servers": settings.kafka_bootstrap, "group.id": f"e2e-smoke-{RUN}",
                          "auto.offset.reset": "earliest", "enable.auto.commit": False})
    collector.subscribe([Topics.RESULTS, Topics.DLQ])

    sent_at, events_out = {}, {}
    for case, (row, selfie, label) in cases.items():
        app = apps[case]
        storage.upload_bytes(s3, settings.s3_bucket, f"{app}/document.jpg", (config.PROJECT_ROOT / row.image_path).read_bytes())
        storage.upload_bytes(s3, settings.s3_bucket, f"{app}/selfie.jpg", selfie)
        print(f"case {case}: {label} -> s3://{settings.s3_bucket}/{app}/")
        for check, payload in (("doc", DocTask(document_key=f"{app}/document.jpg")),
                               ("forgery", ForgeryTask(document_key=f"{app}/document.jpg")),
                               ("face", FaceTask(document_key=f"{app}/document.jpg", selfie_key=f"{app}/selfie.jpg"))):
            event = make_event(app, payload)
            publish(producer, {"doc": Topics.TASK_DOC, "forgery": Topics.TASK_FORGERY, "face": Topics.TASK_FACE}[check], event)
            sent_at[(app, check)], events_out[(app, check)] = time.time(), event
    # case 3: a key that does not exist in the bucket
    publish(producer, Topics.TASK_DOC, make_event(apps[3], DocTask(document_key=f"{apps[3]}/no-such-object.jpg")))
    sent_at[(apps[3], "dlq")] = time.time()
    # idempotency a: the identical face event once more (same event_id = a re-delivery)
    publish(producer, Topics.TASK_FACE, events_out[(apps[1], "face")])
    # idempotency b: the doc task again with a NEW event_id (an orchestrator retry)
    publish(producer, Topics.TASK_DOC, make_event(apps[1], events_out[(apps[1], "doc")].payload))
    producer.flush(10)

    mongo = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)[settings.mongo_db]
    store = mongo["check_results"]
    store.create_index([("application_id", ASCENDING), ("check_type", ASCENDING)], unique=True)

    received, letters, extraction_sent = [], [], set()
    expected = {(apps[c], k) for c in (1, 2) for k in ("doc", "forgery", "face", "extraction")}
    start, quiet_until = time.time(), None
    while time.time() - start < TIMEOUT_S:
        msg = collector.poll(1.0)
        if msg is not None and not msg.error():
            data = json.loads(msg.value())
            app = data["application_id"]
            if app.startswith(f"e2e-{RUN}"):
                if msg.topic() == Topics.DLQ:
                    letters.append((app, DeadLetter.model_validate(data["payload"]), time.time()))
                else:
                    result = CheckResult.model_validate(data["payload"])
                    received.append((app, result, time.time(), data["event_id"]))
                    # the orchestrator's upsert: one record per (application_id, check_type), whatever arrives twice
                    store.update_one({"application_id": app, "check_type": result.check_type},
                                     {"$set": {"status": result.status, "outputs": result.outputs,
                                               "latency_ms": result.latency_ms, "updated_at": datetime.now(timezone.utc)},
                                      "$addToSet": {"result_event_ids": data["event_id"]}}, upsert=True)
                    if result.check_type == "doc" and app not in extraction_sent and result.status == "ok":
                        doc_type = result.outputs.get("doc_type") or result.outputs.get("predicted_type")
                        event = make_event(app, ExtractionTask(document_key=f"{app}/document.jpg", doc_type=doc_type))
                        publish(producer, Topics.TASK_EXTRACTION, event)
                        producer.flush(10)
                        extraction_sent.add(app)
                        sent_at[(app, "extraction")] = time.time()
        got = {(a, r.check_type) for a, r, _, _ in received}
        if expected <= got and letters and quiet_until is None:
            quiet_until = time.time() + 15  # keep listening a little: a duplicate face result would show up here
        if quiet_until and time.time() > quiet_until:
            break
    collector.close()

    # ---- report
    rows = []
    for app, r, at, event_id in received:
        case = next(c for c, a in apps.items() if a == app)
        rows.append({"case": case, "check_type": r.check_type, "status": r.status, "key outputs": key_outputs(r.check_type, r),
                     "worker latency ms": r.latency_ms, "end-to-end s": round(at - sent_at[(app, r.check_type)], 1),
                     "result event": event_id[:8]})
    table = pd.DataFrame(rows).sort_values(["case", "check_type"]).reset_index(drop=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 110)
    print("\n" + table.to_string(index=False))
    for app, letter, at in letters:
        print(f"\nDLQ: {app}: attempts {letter.attempts}, source {letter.source_topic}, worker {letter.worker}, "
              f"after {at - sent_at[(app, 'dlq')]:.1f} s\n     error: {letter.error[:160]}")

    face_results = [r for a, r, _, _ in received if a == apps[1] and r.check_type == "face"]
    doc_results = [r for a, r, _, _ in received if a == apps[1] and r.check_type == "doc"]
    record = store.find_one({"application_id": apps[1], "check_type": "doc"})
    checks = {
        "all 8 checks answered": expected <= {(a, r.check_type) for a, r, _, _ in received},
        "broken task in kyc.dlq after 3 attempts": any(app == apps[3] and letter.attempts == 3 for app, letter, _ in letters),
        "duplicate face event processed once": len(face_results) == 1,
        "re-sent doc task: 2 result events": len(doc_results) == 2,
        "... but 1 stored record (upsert)": store.count_documents({"application_id": apps[1], "check_type": "doc"}) == 1
        and len(record["result_event_ids"]) == 2,
        "1 stored record per (application, check)": all(
            store.count_documents({"application_id": a, "check_type": k}) == 1 for a, k in expected),
    }
    print()
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(REPORT_DIR / "e2e_smoke_results.csv", index=False)
    (REPORT_DIR / "e2e_smoke_summary.json").write_text(json.dumps({
        "run": RUN, "applications": apps, "cases": {c: v[2] for c, v in cases.items()}, "checks": checks,
        "dead_letters": [{"application_id": a, "attempts": letter.attempts, "error": letter.error} for a, letter, _ in letters],
        "results": rows}, indent=2, default=str))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
