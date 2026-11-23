"""Tests of the API (Phase 7): FastAPI TestClient, a throw-away MongoDB database (skipped if MongoDB is not
running), and fake S3 / Kafka objects."""

import importlib.util
import io
import json
import os
import socket
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ekyc import config, security, store
from ekyc.messaging.settings import load_settings


def _mongo_up() -> bool:
    host, port = load_settings().mongo_host.split(":")
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, int(port))) == 0


# marker "services": needs the running docker-compose stack; CI deselects it (pytest -m "not services ...")
pytestmark = [pytest.mark.services,
              pytest.mark.skipif(not _mongo_up(), reason="MongoDB not running (docker compose up -d)")]
os.environ["EKYC_API_NO_AUTOCREATE"] = "1"
_spec = importlib.util.spec_from_file_location("ekyc_api_app", config.PROJECT_ROOT / "services" / "api" / "app.py")
api = importlib.util.module_from_spec(_spec)
sys.modules["ekyc_api_app"] = api
_spec.loader.exec_module(api)
SECRET = "test-secret-" + "x" * 40
USERS = {"CUSTOMER": ("cust@test", "cust-pass-1"), "OFFICER": ("off@test", "off-pass-1")}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = (Body, ContentType)

    def head_bucket(self, Bucket):
        return {}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"http://s3.test/{Params['Key']}?expires={ExpiresIn}"


class FakeProducer:
    def __init__(self):
        self.sent = []

    def produce(self, topic, key, value, on_delivery=None, headers=None):
        self.sent.append((topic, json.loads(value)))

    def poll(self, t):
        return 0

    def flush(self, t=None):
        return 0

    def list_topics(self, timeout):
        return {}


@pytest.fixture
def env():
    db = store.connect(db_name=f"ekyc_test_{uuid.uuid4().hex[:8]}")
    s3, producer = FakeS3(), FakeProducer()
    app = api.create_app(db=db, s3=s3, producer=producer, api_config=api.ApiConfig(jwt_secret=SECRET, max_upload_bytes=200_000),
                         seed=USERS)
    with TestClient(app) as client:
        yield client, db, s3, producer
    db.client.drop_database(db.name)


def login(client, role):
    email, password = USERS[role]
    r = client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200 and r.json()["role"] == role
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def jpeg(size=(300, 200), value=128):
    buffer = io.BytesIO()
    Image.new("RGB", size, (value, value, value)).save(buffer, "JPEG")
    return buffer.getvalue()


def submit(client, headers, **overrides):
    data = {"full_name": "Krsto Velimirovic", "date_of_birth": "1974-08-15"} | overrides.pop("data", {})
    files = {"id_image": ("id.jpg", jpeg(), "image/jpeg"), "selfie": ("selfie.jpg", jpeg(), "image/jpeg")} | overrides
    return client.post("/applications", data=data, files=files, headers=headers)


def test_login_and_submit(env):
    client, db, s3, producer = env
    assert client.post("/auth/login", data={"username": "cust@test", "password": "wrong"}).status_code == 401
    customer = login(client, "CUSTOMER")
    r = submit(client, customer)
    assert r.status_code == 202
    app_id = r.json()["application_id"]
    application = store.get_application(db, app_id)
    assert application["status"] == "SUBMITTED" and application["applicant"]["date_of_birth"] == "1974-08-15"
    assert set(s3.objects) == {f"{app_id}/document.jpg", f"{app_id}/selfie.jpg"}
    (topic, event), = producer.sent
    assert topic == "kyc.submitted" and event["application_id"] == app_id
    assert "Krsto" not in json.dumps(event) and "1974" not in json.dumps(event)  # no PII over Kafka
    view = client.get(f"/applications/{app_id}", headers=customer).json()
    assert view["status"] == "SUBMITTED" and view["outcome"] is None


@pytest.mark.parametrize("change, code", [
    ({"id_image": ("id.gif", b"GIF89a....", "image/gif")}, 415),
    ({"id_image": ("id.jpg", b"not an image at all", "image/jpeg")}, 422),
    ({"selfie": ("s.jpg", jpeg(size=(50, 50)), "image/jpeg")}, 422),  # too small
    ({"id_image": ("id.png", b"x" * 300_000, "image/png")}, 413),  # over the 200 kB test limit
    ({"data": {"date_of_birth": "2999-01-01"}}, 422),
    ({"data": {"full_name": "K"}}, 422),
])
def test_upload_validation(env, change, code):
    client, *_ = env
    assert submit(client, login(client, "CUSTOMER"), **change).status_code == code


def test_authorization_rules(env):
    client, db, *_ = env
    customer, officer = login(client, "CUSTOMER"), login(client, "OFFICER")
    app_id = submit(client, customer).json()["application_id"]
    assert client.get("/officer/cases", headers=customer).status_code == 403  # wrong role
    assert client.post("/applications", headers=officer, data={}).status_code in (403, 422)
    assert client.get(f"/applications/{app_id}", headers=officer).status_code == 403
    other = store.upsert_user(db, "other@test", security.hash_password("other-pass"), "CUSTOMER")
    other_token = security.create_token(other["user_id"], "CUSTOMER", SECRET)
    assert client.get(f"/applications/{app_id}", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
    assert client.get(f"/applications/{app_id}").status_code == 401  # no token
    assert client.get(f"/applications/{app_id}", headers={"Authorization": "Bearer garbage"}).status_code == 401
    expired = security.create_token(other["user_id"], "CUSTOMER", SECRET, minutes=1,
                                    now=datetime.now(timezone.utc) - timedelta(hours=1))
    assert client.get("/applications", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = security.create_token(other["user_id"], "OFFICER", "some-other-secret-" + "y" * 30)
    assert client.get("/officer/cases", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_events_stream_ends_at_a_final_status(env):
    client, db, *_ = env
    customer = login(client, "CUSTOMER")
    app_id = submit(client, customer).json()["application_id"]
    store.move(db, app_id, "PROCESSING", "test", "start")
    store.move(db, app_id, "RESUBMIT_REQUESTED", "test", "done", {"decision": {"outcome": "RESUBMIT_REQUIRED",
               "risk_level": None, "risk_score": 0,
               "reasons": [{"code": "image_unreadable", "message": "Image unreadable", "effect": "resubmit"}]}})
    token = customer["Authorization"].split()[1]
    with client.stream("GET", f"/applications/{app_id}/events?token={token}") as r:  # the browser EventSource way
        body = "".join(r.iter_text())
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert events[-1]["status"] == "RESUBMIT_REQUESTED" and events[-1]["outcome"] == "RESUBMIT_REQUIRED"
    assert events[-1]["retake"] == ["Image unreadable"]


def test_officer_queue_case_and_decision(env):
    client, db, *_ = env
    customer, officer = login(client, "CUSTOMER"), login(client, "OFFICER")
    ids = [submit(client, customer).json()["application_id"] for _ in range(2)]
    for app_id, score in zip(ids, (20.0, 99.0)):
        store.move(db, app_id, "PROCESSING", "test", "start")
        store.move(db, app_id, "DECIDED", "test", "done", {"decision": {"outcome": "MANUAL_REVIEW", "risk_level": "high",
                   "risk_score": score, "reasons": [{"code": "forgery_suspected", "effect": "high"}]}})
    queue = client.get("/officer/cases", params={"status": "DECIDED"}, headers=officer).json()
    assert [c["application_id"] for c in queue] == [ids[1], ids[0]]  # highest risk first
    detail = client.get(f"/officer/cases/{ids[1]}", headers=officer).json()
    assert detail["images"]["document_url"].startswith("http://s3.test/") and detail["application"]["applicant"]
    assert client.post(f"/officer/cases/{ids[1]}/decision", json={"action": "reject", "reason": "no"},
                       headers=officer).status_code == 422  # a reason is mandatory (min 5 characters)
    r = client.post(f"/officer/cases/{ids[1]}/decision", json={"action": "reject", "reason": "Surname edited."}, headers=officer)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    trail = r.json()["audit_trail"]
    assert trail[-1]["to_status"] == "REJECTED" and trail[-1]["actor"].startswith("officer:") and trail[-1]["reason"] == "Surname edited."
    assert client.post(f"/officer/cases/{ids[1]}/decision", json={"action": "approve", "reason": "second thoughts"},
                       headers=officer).status_code == 409
    assert client.get(f"/applications/{ids[1]}", headers=customer).json()["status"] == "REJECTED"


def test_health(env):
    client, *_ = env
    assert client.get("/health").json() == {"status": "ok", "mongo": True, "s3": True, "kafka": True}


def test_pii_masking_helpers():
    assert security.mask_name("Krsto Velimirović") == "K*** V***" and security.mask_dob("1974-08-15") == "****-**-**"
    assert security.mask_document_number("AK6995574") == "*******74"
    import logging
    record = logging.LogRecord("uvicorn.access", 20, "", 0, '%s "%s"', ("127.0.0.1", "GET /applications/a/events?token=abc.def"), None)
    security.RedactTokens().filter(record)
    assert "abc.def" not in record.getMessage() and "token=***" in record.getMessage()


def test_submission_is_logged_without_pii(env, caplog):
    client, *_ = env
    with caplog.at_level("INFO", logger="ekyc.api"):
        assert submit(client, login(client, "CUSTOMER")).status_code == 202
    lines = [r.getMessage() for r in caplog.records if r.name == "ekyc.api" and "submitted" in r.getMessage()]
    assert lines and "K*** V***" in lines[0] and "****-**-**" in lines[0]
    assert "Krsto" not in lines[0] and "1974" not in lines[0]


FORBIDDEN = ("score", "risk", "flag", "band", "rule", "evidence", "forgery", "face", "confidence", "reason")


def keys_of(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(keys_of(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_of(v) for v in value)) if value else set()
    return set()


def test_customer_progress_and_no_fraud_signals(env):
    client, db, *_ = env
    customer = login(client, "CUSTOMER")
    app_id = submit(client, customer).json()["application_id"]
    assert client.get(f"/applications/{app_id}", headers=customer).json()["progress"] == {"completed": 0, "total": 4}
    store.move(db, app_id, "PROCESSING", "test", "start")
    store.upsert_check(db, app_id, "doc", "ok", {"doc_type": "srb_passport", "confidence": 0.99})
    store.upsert_check(db, app_id, "face", "ok", {"score": 0.12, "band": "mismatch"})
    assert client.get(f"/applications/{app_id}", headers=customer).json()["progress"] == {"completed": 2, "total": 4}
    # a high-risk review that ALSO contains a retake reason: the customer learns nothing about it
    store.move(db, app_id, "DECIDED", "test", "done", {"decision": {"outcome": "MANUAL_REVIEW", "risk_level": "high",
               "risk_score": 100, "early": False, "reasons": [
                   {"code": "no_face_found", "message": "No face found on the selfie", "effect": "resubmit",
                    "check_type": "face", "evidence": {"selfie_faces": 0}},
                   {"code": "forgery_suspected", "message": "Forgery suspected", "effect": "high",
                    "check_type": "forgery", "evidence": {"score": 0.99}}]}})
    view = client.get(f"/applications/{app_id}", headers=customer).json()
    assert view["outcome"] == "MANUAL_REVIEW" and view["retake"] == [] and view["progress"] == {"completed": 4, "total": 4}
    for body in (view, client.get("/applications", headers=customer).json()):
        leaked = {k for k in keys_of(body) if any(word in k.lower() for word in FORBIDDEN)}
        assert not leaked, leaked
        assert "Forgery" not in str(body) and "0.99" not in str(body)


def test_early_resubmit_progress_and_retake(env):
    client, db, *_ = env
    customer = login(client, "CUSTOMER")
    app_id = submit(client, customer).json()["application_id"]
    store.move(db, app_id, "PROCESSING", "test", "start")
    store.upsert_check(db, app_id, "doc", "ok", {"blank": True})
    store.move(db, app_id, "RESUBMIT_REQUESTED", "test", "done", {"decision": {"outcome": "RESUBMIT_REQUIRED", "risk_level": None,
               "risk_score": 0, "early": True, "reasons": [{"code": "image_unreadable", "effect": "resubmit",
               "message": "Image unreadable: no document visible, please upload a new photo"}]}})
    view = client.get(f"/applications/{app_id}", headers=customer).json()
    assert view["progress"] == {"completed": 1, "total": 1} and view["retake"][0].startswith("Image unreadable")


def test_officer_case_includes_the_forgery_heatmap(env):
    client, db, *_ = env
    customer, officer = login(client, "CUSTOMER"), login(client, "OFFICER")
    app_id = submit(client, customer).json()["application_id"]
    tiles = {"size": 224, "count": 2, "xy": [[0, 0], [112, 0]], "scores": [0.1, 0.97]}
    store.upsert_check(db, app_id, "forgery", "ok", {"score": 0.97, "band": "forgery_suspected", "tiles": tiles,
                       "page_size_1280": [1280, 806], "original_size": [2167, 1364],
                       "top_tile": {"score": 0.97, "box_1280": [112, 0, 224, 224]}})
    heatmap = client.get(f"/officer/cases/{app_id}", headers=officer).json()["forgery_heatmap"]
    assert heatmap["tiles"] == tiles and heatmap["page_size_1280"] == [1280, 806] and heatmap["tile_size"] == 224
    # a result stored before Phase 8 has only a tile count: the case still opens, with the top tile only
    store.upsert_check(db, app_id, "forgery", "ok", {"score": 0.97, "tiles": 88, "page_size_1280": [1280, 806],
                       "top_tile": {"score": 0.97, "box_1280": [112, 0, 224, 224]}})
    heatmap = client.get(f"/officer/cases/{app_id}", headers=officer).json()["forgery_heatmap"]
    assert heatmap["tiles"] is None and heatmap["top_tile"]["box_1280"] == [112, 0, 224, 224]


def test_events_stream_reports_progress(env):
    client, db, *_ = env
    customer = login(client, "CUSTOMER")
    app_id = submit(client, customer).json()["application_id"]
    store.move(db, app_id, "PROCESSING", "test", "start")
    store.upsert_check(db, app_id, "doc", "ok", {"doc_type": "srb_passport"})
    store.move(db, app_id, "APPROVED", "system:orchestrator", "decision AUTO_APPROVED", {"decision": {
               "outcome": "AUTO_APPROVED", "risk_level": "low", "risk_score": 3, "early": False, "reasons": []}})
    with client.stream("GET", f"/applications/{app_id}/events", headers=customer) as r:
        events = [json.loads(line[6:]) for line in "".join(r.iter_text()).splitlines() if line.startswith("data: ")]
    assert events[-1]["progress"] == {"completed": 4, "total": 4} and events[-1]["message"] == "Your identity has been verified."
    assert events[-1]["status"] == "APPROVED"


def test_officer_acts_only_on_cases_awaiting_an_officer(env):
    """Phase 9 lifecycle: auto-approved and resubmit cases are closed by the system; only DECIDED (manual review)
    waits for an officer. An officer can neither decide a closed case nor one whose checks are still running."""
    client, db, *_ = env
    customer, officer = login(client, "CUSTOMER"), login(client, "OFFICER")
    auto, retake, running, review = [submit(client, customer).json()["application_id"] for _ in range(4)]
    for app_id in (auto, retake, running, review):
        store.move(db, app_id, "PROCESSING", "test", "start")
    store.move(db, auto, "APPROVED", "system:orchestrator", "decision AUTO_APPROVED (risk low)",
               {"decision": {"outcome": "AUTO_APPROVED", "risk_level": "low", "risk_score": 2, "reasons": []}})
    store.move(db, retake, "RESUBMIT_REQUESTED", "system:orchestrator", "decision RESUBMIT_REQUIRED",
               {"decision": {"outcome": "RESUBMIT_REQUIRED", "risk_level": None, "risk_score": 0, "reasons": []}})
    store.move(db, review, "DECIDED", "system:orchestrator", "decision MANUAL_REVIEW (risk medium)",
               {"decision": {"outcome": "MANUAL_REVIEW", "risk_level": "medium", "risk_score": 20, "reasons": []}})
    body = {"action": "approve", "reason": "Checked the document by hand."}
    for app_id in (auto, retake, running):
        assert client.post(f"/officer/cases/{app_id}/decision", json=body, headers=officer).status_code == 409
    queue = client.get("/officer/cases", params={"status": "DECIDED"}, headers=officer).json()
    assert [c["application_id"] for c in queue] == [review]  # the default queue holds only work for an officer
    assert client.post(f"/officer/cases/{review}/decision", json=body, headers=officer).status_code == 200
    views = {a["application_id"]: a for a in client.get("/applications", headers=customer).json()}
    assert views[auto]["message"] == "Your identity has been verified."
    assert views[review]["status"] == "APPROVED"
    assert views[review]["message"] == "Your identity has been verified by our compliance team."
    assert views[retake]["status"] == "RESUBMIT_REQUESTED" and views[running]["status"] == "PROCESSING"


# ------------------------------------------------------------------ Phase 13: head-turn frames for active liveness
def turn_frames():
    return {"liveness_left": ("left.jpg", jpeg(value=90), "image/jpeg"),
            "liveness_right": ("right.jpg", jpeg(value=160), "image/jpeg")}


def test_head_turn_frames_are_stored_and_published(env):
    client, db, s3, producer = env
    customer, officer = login(client, "CUSTOMER"), login(client, "OFFICER")
    r = submit(client, customer, **turn_frames())
    assert r.status_code == 202
    app_id = r.json()["application_id"]
    keys = {"left": f"{app_id}/liveness_left.jpg", "right": f"{app_id}/liveness_right.jpg"}
    assert store.get_application(db, app_id)["liveness_keys"] == keys
    assert set(s3.objects) == {f"{app_id}/document.jpg", f"{app_id}/selfie.jpg", *keys.values()}
    (_, event), = producer.sent
    assert event["payload"]["liveness_left_key"] == keys["left"] and event["payload"]["liveness_right_key"] == keys["right"]
    case = client.get(f"/officer/cases/{app_id}", headers=officer).json()
    assert case["application"]["liveness_keys"] == keys
    assert case["images"]["liveness_left_url"].startswith(f"http://s3.test/{keys['left']}")
    assert case["images"]["liveness_right_url"].startswith(f"http://s3.test/{keys['right']}")


def test_photo_upload_has_no_head_turn_frames(env):
    client, db, _, producer = env
    customer, officer = login(client, "CUSTOMER"), login(client, "OFFICER")
    app_id = submit(client, customer).json()["application_id"]
    assert store.get_application(db, app_id)["liveness_keys"] is None
    (_, event), = producer.sent
    assert event["payload"]["liveness_left_key"] is None and event["payload"]["liveness_right_key"] is None
    images = client.get(f"/officer/cases/{app_id}", headers=officer).json()["images"]
    assert images["liveness_left_url"] is None and images["liveness_right_url"] is None


@pytest.mark.parametrize("change, code", [
    ({"liveness_left": turn_frames()["liveness_left"]}, 422),  # one turn frame without the other
    ({"liveness_right": turn_frames()["liveness_right"]}, 422),
    ({**turn_frames(), "liveness_left": ("l.gif", b"GIF89a....", "image/gif")}, 415),
    ({**turn_frames(), "liveness_right": ("r.jpg", jpeg(size=(60, 60)), "image/jpeg")}, 422),  # too small
])
def test_head_turn_frame_validation(env, change, code):
    client, _, s3, producer = env
    assert submit(client, login(client, "CUSTOMER"), **change).status_code == code
    assert s3.objects == {} and producer.sent == []  # nothing stored or published for a refused submission


def test_a_client_side_liveness_verdict_is_ignored(env):
    """The browser sends only images; a form field claiming the check passed changes nothing."""
    client, db, _, producer = env
    r = submit(client, login(client, "CUSTOMER"), data={"liveness": "passed", "liveness_result": "passed"})
    assert r.status_code == 202
    application = store.get_application(db, r.json()["application_id"])
    assert application["liveness_keys"] is None and "liveness" not in application
    payload = producer.sent[0][1]["payload"]
    assert set(payload) == {"document_key", "selfie_key", "liveness_left_key", "liveness_right_key"}
    assert payload["liveness_left_key"] is None and payload["liveness_right_key"] is None
