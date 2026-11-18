"""Reset the demo system to an empty state (Phase 9), e.g. before scripts/simulate_batch.py.

    .venv/bin/python scripts/reset_demo_data.py          # shows what will be deleted, asks for confirmation
    .venv/bin/python scripts/reset_demo_data.py --yes    # no question (for scripts)

What it does:
1. MongoDB (database MONGO_DB): deletes every document in applications, check_results and audit_log (decisions are
   stored inside the application documents), and in users; then re-creates the demo accounts from .env
   (DEMO_CUSTOMER_*, DEMO_OFFICER_*). Indexes are kept.
2. S3: deletes every object in the upload bucket (the bucket itself stays).
3. Kafka: deletes the eight kyc.* topics and the consumer groups, then creates the topics again, empty
   (3 partitions each, like kafka-init in docker-compose.yml).

It refuses to run while a service is still connected (a consumer group is active): stop scripts/run_all.sh (or the
app containers) first. It never touches data/ or models/: the batch ground truth in data/processed/batch/ stays, and
simulate_batch.py --new starts a fresh batch.
"""

from __future__ import annotations

import argparse
import sys
import time

from confluent_kafka.admin import AdminClient, NewTopic
from dotenv import dotenv_values

from ekyc import config, security, store
from ekyc.messaging import storage
from ekyc.messaging.events import Topics
from ekyc.messaging.settings import load_settings

COLLECTIONS = ("applications", "check_results", "audit_log", "users")
PARTITIONS = 3


def active_groups(admin: AdminClient) -> list[str]:
    groups = admin.list_consumer_groups(request_timeout=10).result().valid
    return [g.group_id for g in groups if str(g.state).split(".")[-1] not in ("EMPTY", "DEAD")]


def s3_keys(s3, bucket: str) -> list[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        keys += [o["Key"] for o in page.get("Contents", [])]
    return keys


def reset_kafka(admin: AdminClient) -> None:
    existing = set(admin.list_topics(timeout=10).topics)
    to_delete = [t for t in Topics.ALL if t in existing]
    if to_delete:
        for future in admin.delete_topics(to_delete, operation_timeout=30).values():
            future.result()
    groups = [g.group_id for g in admin.list_consumer_groups(request_timeout=10).result().valid]
    if groups:  # inactive groups only (checked before); their committed offsets would point into the old topics
        for future in admin.delete_consumer_groups(groups, request_timeout=30).values():
            future.result()
    # topic deletion finishes in the background: retry the creation until the old topics are really gone
    for attempt in range(30):
        pending = [t for t in Topics.ALL if t not in admin.list_topics(timeout=10).topics]
        if not pending:
            break
        futures = admin.create_topics([NewTopic(t, num_partitions=PARTITIONS, replication_factor=1) for t in pending])
        for topic, future in futures.items():
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - "marked for deletion" until the broker has finished
                if attempt == 29:
                    raise RuntimeError(f"could not create {topic}: {exc}") from exc
        time.sleep(1)
    print(f"  kafka: {len(Topics.ALL)} topics re-created empty ({PARTITIONS} partitions each), "
          f"{len(groups)} consumer groups deleted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()
    settings = load_settings()
    env = dotenv_values(config.PROJECT_ROOT / ".env")
    db = store.connect(settings)
    s3 = storage.s3_client(settings)
    admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap})

    busy = active_groups(admin)
    if busy:
        print(f"services are still running (active consumer groups: {', '.join(busy)}). Stop scripts/run_all.sh "
              "or the app containers first.")
        return 1
    keys = s3_keys(s3, settings.s3_bucket)
    counts = {c: db[c].count_documents({}) for c in COLLECTIONS}
    print(f"This deletes, in database '{db.name}': " + ", ".join(f"{n} {c}" for c, n in counts.items()))
    print(f"  + {len(keys)} objects in bucket '{settings.s3_bucket}' + all messages in {len(Topics.ALL)} Kafka topics.")
    print("  data/ and models/ are not touched.")
    if not args.yes and input("Type 'reset' to continue: ").strip() != "reset":
        print("cancelled, nothing changed")
        return 1

    for name in COLLECTIONS:
        db[name].delete_many({})
    print(f"  mongo: emptied {', '.join(COLLECTIONS)}")
    for start in range(0, len(keys), 1000):  # DeleteObjects takes at most 1000 keys per call
        s3.delete_objects(Bucket=settings.s3_bucket,
                          Delete={"Objects": [{"Key": k} for k in keys[start:start + 1000]], "Quiet": True})
    print(f"  s3: deleted {len(keys)} objects, {len(s3_keys(s3, settings.s3_bucket))} left")
    reset_kafka(admin)

    seeded = []
    for role, prefix in (("CUSTOMER", "DEMO_CUSTOMER"), ("OFFICER", "DEMO_OFFICER")):
        email, password = env.get(f"{prefix}_EMAIL"), env.get(f"{prefix}_PASSWORD")
        if email and password:
            store.upsert_user(db, email, security.hash_password(password), role)
            seeded.append(f"{role.lower()} {email}")
    print(f"  users: re-seeded {', '.join(seeded) or 'none (DEMO_* not set in .env)'}")
    print("done: the system is empty. Next: scripts/run_all.sh, then scripts/simulate_batch.py --new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
