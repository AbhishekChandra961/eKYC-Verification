"""Tests of the orchestrator logic and the MongoDB store (Phase 7) against the real MongoDB of the docker-compose
stack, in a throw-away database (skipped when MongoDB is not running), with a fake Kafka producer."""

import json
import socket
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ekyc import decision, store
from ekyc.messaging.events import CheckResult, SubmittedPayload, Topics
from ekyc.messaging.settings import load_settings
from ekyc.orchestration import Orchestrator


def _mongo_up() -> bool:
    host, port = load_settings().mongo_host.split(":")
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, int(port))) == 0


# marker "services": needs the running docker-compose stack; CI deselects it (pytest -m "not services ...")
pytestmark = [pytest.mark.services,
              pytest.mark.skipif(not _mongo_up(), reason="MongoDB not running (docker compose up -d)")]
POLICY = decision.Policy(doc_min_confidence=0.77, forgery_review=0.729, forgery_suspected=0.857383,
                         face_mismatch_below=0.2597, face_review_below=0.556)
APPLICANT = {"full_name": "Krsto Velimirovic", "date_of_birth": "1974-08-15"}
GOOD = {
    "doc": {"doc_type": "srb_passport", "confidence": 0.99, "blank": False},
    "face": {"score": 0.92, "band": "match", "selfie_face": {"faces": 1},
             "liveness": {"status": "passed", "failures": [], "turn_deg": {"left": 28.0, "right": -27.0}}},
    "forgery": {"score": 0.40, "band": "pass"},
    "extraction": {"fields": {"surname": "VELIMIROVIĆ", "given_names": "KRSTO", "birth_date": "15.08.1974",
                              "expiry_date": "12.08.2030"}, "flags": []},
}


class FakeProducer:
    def __init__(self):
        self.sent = []

    def produce(self, topic, key, value, on_delivery=None, headers=None):
        self.sent.append((topic, json.loads(value)))

    def poll(self, timeout):
        return 0

    def flush(self, timeout=None):
        return 0

    def topics(self):
        return [t for t, _ in self.sent]


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


@pytest.fixture
def setup():
    client_db = store.connect(db_name=f"ekyc_test_{uuid.uuid4().hex[:8]}")
    producer, clock = FakeProducer(), Clock()
    orch = Orchestrator(client_db, producer, POLICY, clock=clock)
    app = store.create_application(client_db, "u-1", APPLICANT, "k/doc.jpg", "k/selfie.jpg")
    yield orch, client_db, producer, clock, app["application_id"]
    client_db.client.drop_database(client_db.name)


def result(check, outputs=None, status="ok"):
    return CheckResult(check_type=check, status=status, outputs=outputs if outputs is not None else GOOD[check],
                       latency_ms=10, task_event_id=uuid.uuid4(), worker=f"{check}-worker")


def test_head_turn_frames_reach_the_face_task(setup):
    """Phase 13: the orchestrator passes the two head-turn frame keys on to the face-worker (the others need none)."""
    orch, _, producer, _, app_id = setup
    orch.on_submitted(app_id, SubmittedPayload(document_key="k/doc.jpg", selfie_key="k/selfie.jpg",
                                               liveness_left_key="k/liveness_left.jpg",
                                               liveness_right_key="k/liveness_right.jpg"))
    face_task = [e for t, e in producer.sent if t == Topics.TASK_FACE][0]["payload"]
    assert (face_task["liveness_left_key"], face_task["liveness_right_key"]) == ("k/liveness_left.jpg", "k/liveness_right.jpg")
    doc_task = [e for t, e in producer.sent if t == Topics.TASK_DOC][0]["payload"]
    assert set(doc_task) == {"document_key"}


def test_full_flow_with_duplicates(setup):
    orch, db, producer, clock, app_id = setup
    submitted = SubmittedPayload(document_key="k/doc.jpg", selfie_key="k/selfie.jpg")
    orch.on_submitted(app_id, submitted)
    orch.on_submitted(app_id, submitted)  # re-delivered: no second set of tasks
    assert producer.topics() == [Topics.TASK_DOC, Topics.TASK_FACE]
    assert store.get_application(db, app_id)["status"] == "PROCESSING"

    orch.on_result(app_id, result("doc"), "e1")
    orch.on_result(app_id, result("doc"), "e1")  # duplicate result: nothing published twice
    sent = producer.topics()
    assert sent.count(Topics.TASK_FORGERY) == 1 and sent.count(Topics.TASK_EXTRACTION) == 1
    extraction_task = [e for t, e in producer.sent if t == Topics.TASK_EXTRACTION][0]
    assert extraction_task["payload"]["doc_type"] == "srb_passport"  # the classified type is passed on

    for check in ("face", "forgery", "extraction"):
        orch.on_result(app_id, result(check), f"e-{check}")
    orch.on_result(app_id, result("extraction"), "e-extraction-again")  # after the decision: harmless
    app = store.get_application(db, app_id)
    # Phase 9: an auto-approval closes the application (APPROVED by the system); it never waits for an officer
    assert app["status"] == "APPROVED" and app["decision"]["outcome"] == "AUTO_APPROVED"
    assert app["officer_decision"] is None
    assert "auto approved" in app["summary"] and producer.topics().count(Topics.DECIDED) == 1
    assert db.check_results.count_documents({"application_id": app_id}) == 4  # one record per check
    trail = store.audit_trail(db, app_id)
    assert [(a["from_status"], a["to_status"]) for a in trail] == [(None, "SUBMITTED"), ("SUBMITTED", "PROCESSING"),
                                                                   ("PROCESSING", "APPROVED")]
    assert trail[2]["reason"] == "decision AUTO_APPROVED (risk low)"
    assert trail[0]["actor"] == "customer:u-1" and trail[2]["actor"] == "system:orchestrator"


def test_unusable_document_is_decided_early(setup):
    orch, db, producer, clock, app_id = setup
    orch.on_submitted(app_id, SubmittedPayload(document_key="k/doc.jpg", selfie_key="k/selfie.jpg"))
    orch.on_result(app_id, result("doc", {"blank": True}), "e1")
    app = store.get_application(db, app_id)
    assert app["status"] == "RESUBMIT_REQUESTED" and app["decision"]["outcome"] == "RESUBMIT_REQUIRED"
    assert app["decision"]["early"] and store.audit_trail(db, app_id)[-1]["to_status"] == "RESUBMIT_REQUESTED"
    assert Topics.TASK_FORGERY not in producer.topics() and Topics.TASK_EXTRACTION not in producer.topics()
    orch.on_result(app_id, result("face"), "e2")  # arrives later: stored, decision unchanged
    assert store.get_application(db, app_id)["decision"]["outcome"] == "RESUBMIT_REQUIRED"
    assert store.get_application(db, app_id)["status"] == "RESUBMIT_REQUESTED"


def test_sweeper_times_out_a_missing_check(setup):
    orch, db, producer, clock, app_id = setup
    orch.on_submitted(app_id, SubmittedPayload(document_key="k/doc.jpg", selfie_key="k/selfie.jpg"))
    for check in ("doc", "face", "forgery"):
        orch.on_result(app_id, result(check), f"e-{check}")
    clock.t += timedelta(seconds=120)  # past the 60 s checks, within extraction's 180 s
    assert orch.sweep() == 0 and store.get_application(db, app_id)["status"] == "PROCESSING"
    clock.t += timedelta(seconds=90)  # now past 180 s
    assert orch.sweep() == 1
    app = store.get_application(db, app_id)
    assert app["status"] == "DECIDED" and app["decision"]["outcome"] == "MANUAL_REVIEW"
    assert [r["code"] for r in app["decision"]["reasons"]] == ["extraction_timed_out"]
    orch.on_result(app_id, result("extraction"), "late")  # the late result does not change the decision
    assert store.get_application(db, app_id)["decision"]["outcome"] == "MANUAL_REVIEW"


def test_doc_timeout_still_runs_forgery_and_skips_extraction(setup):
    orch, db, producer, clock, app_id = setup
    orch.on_submitted(app_id, SubmittedPayload(document_key="k/doc.jpg", selfie_key="k/selfie.jpg"))
    orch.on_result(app_id, result("face"), "e-face")
    clock.t += timedelta(seconds=61)
    orch.sweep()  # doc timed out -> forgery task, extraction marked skipped
    assert producer.topics().count(Topics.TASK_FORGERY) == 1 and Topics.TASK_EXTRACTION not in producer.topics()
    orch.on_result(app_id, result("forgery"), "e-forgery")
    app = store.get_application(db, app_id)
    assert app["decision"]["outcome"] == "MANUAL_REVIEW"
    assert {r["code"] for r in app["decision"]["reasons"]} == {"doc_timed_out", "extraction_skipped"}


def test_officer_transition_happens_once(setup):
    orch, db, producer, clock, app_id = setup
    db.applications.update_one({"application_id": app_id}, {"$set": {"status": "DECIDED"}})
    assert store.move(db, app_id, "REJECTED", "officer:u-9", "document tampered")
    assert not store.move(db, app_id, "APPROVED", "officer:u-9", "changed my mind")  # only from DECIDED
    assert store.get_application(db, app_id)["status"] == "REJECTED"
    assert store.audit_trail(db, app_id)[-1]["reason"] == "document tampered"


def test_manual_review_waits_for_an_officer_and_transitions_are_checked(setup):
    """Only MANUAL_REVIEW stays open (DECIDED). The officer may close it; the system can never reject, and an officer
    cannot approve a case that is still PROCESSING (from_statuses narrows the allowed transitions)."""
    orch, db, producer, clock, app_id = setup
    orch.on_submitted(app_id, SubmittedPayload(document_key="k/doc.jpg", selfie_key="k/selfie.jpg"))
    assert not store.move(db, app_id, "APPROVED", "officer:u-9", "too early", from_statuses=("DECIDED",))
    face_mismatch = {"score": 0.05, "band": "mismatch", "selfie_face": {"faces": 1}}
    for check in ("doc", "forgery", "extraction"):
        orch.on_result(app_id, result(check), f"e-{check}")
    orch.on_result(app_id, result("face", face_mismatch), "e-face")
    app = store.get_application(db, app_id)
    assert app["status"] == "DECIDED" and app["decision"]["outcome"] == "MANUAL_REVIEW"
    with pytest.raises(ValueError):
        store.move(db, app_id, "REJECTED", "system:orchestrator", "not allowed", from_statuses=("PROCESSING",))
    assert store.move(db, app_id, "APPROVED", "officer:u-9", "same person, old photo", from_statuses=("DECIDED",))
    assert [a["to_status"] for a in store.audit_trail(db, app_id)][-2:] == ["DECIDED", "APPROVED"]


def test_lifecycle_migration_closes_old_decided_applications(setup):
    """scripts/migrate_lifecycle.py: Phase 7/8 left every decided application in DECIDED."""
    import importlib.util
    from ekyc import config
    spec = importlib.util.spec_from_file_location("migrate_lifecycle", config.PROJECT_ROOT / "scripts" / "migrate_lifecycle.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    orch, db, producer, clock, app_id = setup
    ids = {outcome: store.create_application(db, "u-1", APPLICANT, "d", "s")["application_id"]
           for outcome in ("AUTO_APPROVED", "RESUBMIT_REQUIRED", "MANUAL_REVIEW")}
    for outcome, application_id in ids.items():  # the old lifecycle: always DECIDED
        db.applications.update_one({"application_id": application_id},
                                   {"$set": {"status": "DECIDED", "decision": {"outcome": outcome}}})
    assert migration.migrate(db, dry_run=True)["AUTO_APPROVED DECIDED -> APPROVED"] == 1
    assert store.get_application(db, ids["AUTO_APPROVED"])["status"] == "DECIDED"  # a dry run changes nothing
    counts = migration.migrate(db)
    assert counts == {"AUTO_APPROVED DECIDED -> APPROVED": 1, "RESUBMIT_REQUIRED DECIDED -> RESUBMIT_REQUESTED": 1,
                      "MANUAL_REVIEW stays DECIDED": 1}
    assert {o: store.get_application(db, i)["status"] for o, i in ids.items()} == {
        "AUTO_APPROVED": "APPROVED", "RESUBMIT_REQUIRED": "RESUBMIT_REQUESTED", "MANUAL_REVIEW": "DECIDED"}
    assert store.audit_trail(db, ids["AUTO_APPROVED"])[-1]["actor"] == "system:migration"
    assert migration.migrate(db)["AUTO_APPROVED DECIDED -> APPROVED"] == 0  # running it again is harmless
