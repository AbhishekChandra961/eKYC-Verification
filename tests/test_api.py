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


pytestmark = pytest.mark.skipif(not _mongo_up(), reason="MongoDB not running (docker compose up -d)")
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
    store.move(db, app_id, "DECIDED", "test", "done", {"decision": {"outcome": "RESUBMIT_REQUIRED", "risk_level": None,
               "risk_score": 0, "reasons": [{"code": "image_unreadable", "message": "Image unreadable", "effect": "resubmit"}]}})
    token = customer["Authorization"].split()[1]
    with client.stream("GET", f"/applications/{app_id}/events?token={token}") as r:  # the browser EventSource way
        body = "".join(r.iter_text())
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert events[-1]["status"] == "DECIDED" and events[-1]["outcome"] == "RESUBMIT_REQUIRED"
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
