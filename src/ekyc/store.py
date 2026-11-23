"""MongoDB data layer shared by the orchestrator and the API (Phase 7). Synchronous pymongo: the orchestrator's
Kafka loop is synchronous, and FastAPI runs plain `def` endpoints in a thread pool, so one layer serves both.

Collections:
- users          one document per account (email, role CUSTOMER | OFFICER, argon2 password hash)
- applications   one document per KYC application: owner, status, applicant data, S3 keys, decision, summary
- check_results  one document per (application_id, check_type), UNIQUE: a result delivered twice is upserted
- audit_log      append-only: every status change with actor, time, from/to status and reason

Status lifecycle (Phase 9: only a case that needs a person stays open):

    SUBMITTED -> PROCESSING -> APPROVED            AUTO_APPROVED: closed by the system
                           -> RESUBMIT_REQUESTED  RESUBMIT_REQUIRED: closed; the customer starts a new application
                           -> DECIDED             MANUAL_REVIEW: waits for an officer
                                -> APPROVED | REJECTED   (officer, with a reason)

A transition only happens from an allowed previous status (an atomic conditional update), so duplicate events
cannot move an application twice; the audit entry of a transition has a deterministic id, so writing it again is
harmless.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.database import Database

from ekyc.messaging.settings import Settings, load_settings

STATUSES = ("SUBMITTED", "PROCESSING", "DECIDED", "APPROVED", "REJECTED", "RESUBMIT_REQUESTED")
CLOSED = ("APPROVED", "REJECTED", "RESUBMIT_REQUESTED")  # nothing changes any more
# to_status -> the statuses it may be reached from
ALLOWED = {"PROCESSING": ("SUBMITTED",),
           "DECIDED": ("PROCESSING",),  # MANUAL_REVIEW: now waits for an officer
           "APPROVED": ("PROCESSING", "DECIDED"),  # the system (AUTO_APPROVED) or an officer (from DECIDED)
           "REJECTED": ("DECIDED",),  # only an officer rejects
           "RESUBMIT_REQUESTED": ("PROCESSING",)}  # RESUBMIT_REQUIRED
# the system's outcome -> the status the orchestrator moves the application to
STATUS_FOR_OUTCOME = {"AUTO_APPROVED": "APPROVED", "MANUAL_REVIEW": "DECIDED", "RESUBMIT_REQUIRED": "RESUBMIT_REQUESTED"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def connect(settings: Settings | None = None, db_name: str | None = None) -> Database:
    s = settings or load_settings()
    db = MongoClient(s.mongo_uri, serverSelectionTimeoutMS=5000, tz_aware=True)[db_name or s.mongo_db]
    ensure_indexes(db)
    return db


def ensure_indexes(db: Database) -> None:
    db.users.create_index("email", unique=True)
    db.applications.create_index("application_id", unique=True)
    db.applications.create_index([("customer_id", ASCENDING), ("created_at", DESCENDING)])
    db.applications.create_index([("status", ASCENDING), ("decision.risk_score", DESCENDING)])
    db.check_results.create_index([("application_id", ASCENDING), ("check_type", ASCENDING)], unique=True)
    db.audit_log.create_index([("application_id", ASCENDING), ("at", ASCENDING)])


# ---------------------------------------------------------------- users

def upsert_user(db: Database, email: str, password_hash: str, role: str) -> dict:
    return db.users.find_one_and_update(
        {"email": email.lower()},
        {"$set": {"password_hash": password_hash, "role": role},
         "$setOnInsert": {"user_id": f"u-{uuid.uuid4().hex[:12]}", "created_at": now()}},
        upsert=True, return_document=ReturnDocument.AFTER, projection={"_id": False})


def find_user(db: Database, email: str | None = None, user_id: str | None = None) -> dict | None:
    query = {"email": email.lower()} if email else {"user_id": user_id}
    return db.users.find_one(query, projection={"_id": False})


# ---------------------------------------------------------------- audit

def audit(db: Database, application_id: str, actor: str, from_status: str | None, to_status: str, reason: str,
          at: datetime | None = None) -> None:
    """Append one audit entry. Its _id is deterministic (application + transition), so a repeated write (e.g. after
    a re-delivered event) keeps the first entry instead of adding a second."""
    entry_id = f"{application_id}:{from_status or 'NEW'}->{to_status}"
    db.audit_log.update_one({"_id": entry_id}, {"$setOnInsert": {
        "application_id": application_id, "actor": actor, "from_status": from_status, "to_status": to_status,
        "reason": reason, "at": at or now()}}, upsert=True)


def audit_trail(db: Database, application_id: str) -> list[dict]:
    return list(db.audit_log.find({"application_id": application_id}, projection={"_id": False}).sort("at", ASCENDING))


# ---------------------------------------------------------------- applications

def create_application(db: Database, customer_id: str, applicant: dict, document_key: str, selfie_key: str,
                       application_id: str | None = None, liveness_keys: dict | None = None) -> dict:
    """liveness_keys (Phase 13): {"left": key, "right": key} of the head-turn frames, or None (photo uploaded)."""
    app_id = application_id or f"app-{uuid.uuid4().hex[:16]}"
    doc = {"application_id": app_id, "customer_id": customer_id, "status": "SUBMITTED", "applicant": applicant,
           "document_key": document_key, "selfie_key": selfie_key, "liveness_keys": liveness_keys,
           "created_at": now(), "updated_at": now(),
           "pending": {}, "decision": None, "summary": None, "ai_note": None, "officer_decision": None}
    db.applications.insert_one(doc)
    audit(db, app_id, f"customer:{customer_id}", None, "SUBMITTED", "application submitted")
    doc.pop("_id", None)
    return doc


def get_application(db: Database, application_id: str) -> dict | None:
    return db.applications.find_one({"application_id": application_id}, projection={"_id": False})


def move(db: Database, application_id: str, to_status: str, actor: str, reason: str, set_fields: dict | None = None,
         from_statuses: tuple[str, ...] | None = None) -> bool:
    """Move an application to `to_status` if its current status allows it (atomic), write the audit entry, and
    return True. Returns False when the status did not allow it (e.g. a duplicate event after the move).
    from_statuses narrows ALLOWED further: an officer may approve only from DECIDED, never a case still PROCESSING."""
    allowed = from_statuses or ALLOWED[to_status]
    if not set(allowed) <= set(ALLOWED[to_status]):
        raise ValueError(f"{allowed} -> {to_status} is not an allowed transition")
    updated = db.applications.find_one_and_update(
        {"application_id": application_id, "status": {"$in": list(allowed)}},
        {"$set": {"status": to_status, "updated_at": now(), **(set_fields or {})}},
        projection={"status": True, "_id": False})  # the document BEFORE the update
    if updated is None:
        return False
    audit(db, application_id, actor, updated["status"], to_status, reason)
    return True


def set_fields(db: Database, application_id: str, values: dict, unset: list[str] | None = None) -> None:
    update = {"$set": {**values, "updated_at": now()}}
    if unset:
        update["$unset"] = {name: "" for name in unset}
    db.applications.update_one({"application_id": application_id}, update)


def list_cases(db: Database, status: str | None = None, outcome: str | None = None, limit: int = 100) -> list[dict]:
    """The officer queue: highest risk score first, then oldest first."""
    query = {}
    if status:
        query["status"] = status
    if outcome:
        query["decision.outcome"] = outcome
    fields = {"_id": False, "applicant": False, "pending": False, "summary": False, "ai_note": False}
    return list(db.applications.find(query, projection=fields)
                .sort([("decision.risk_score", DESCENDING), ("created_at", ASCENDING)]).limit(limit))


def due_applications(db: Database, at: datetime) -> list[dict]:
    """Applications still PROCESSING with at least one check past its deadline (for the timeout sweeper)."""
    return [a for a in db.applications.find({"status": "PROCESSING"}, projection={"_id": False})
            if any(deadline <= at for deadline in (a.get("pending") or {}).values())]


# ---------------------------------------------------------------- check results

def upsert_check(db: Database, application_id: str, check_type: str, status: str, outputs: dict | None = None,
                 error: str | None = None, model_versions: dict | None = None, latency_ms: float | None = None,
                 result_event_id: str | None = None, only_if_missing: bool = False) -> bool:
    """Store a check result: one document per (application_id, check_type). only_if_missing=True writes only when
    no result exists yet (the timeout sweeper must not overwrite a result that arrived). Returns whether it wrote."""
    query = {"application_id": application_id, "check_type": check_type}
    values = {"status": status, "outputs": outputs or {}, "error": error, "model_versions": model_versions or {},
              "latency_ms": latency_ms, "updated_at": now()}
    if only_if_missing:
        result = db.check_results.update_one(query, {"$setOnInsert": values}, upsert=True)
        return result.upserted_id is not None
    update = {"$set": values}
    if result_event_id:
        update["$addToSet"] = {"result_event_ids": result_event_id}
    db.check_results.update_one(query, update, upsert=True)
    return True


def get_checks(db: Database, application_id: str) -> dict[str, dict]:
    return {c["check_type"]: c for c in db.check_results.find({"application_id": application_id},
                                                              projection={"_id": False})}
