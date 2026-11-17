"""The event envelope and payloads exchanged over Kafka (Phase 6).

Every message is an Envelope: who it belongs to (application_id, also the partition key), what it is
(event_type + schema_version), a unique event_id (for de-duplication), when it was made, and a typed payload.
Events carry S3 object KEYS, never image bytes (claim-check pattern): images stay in the object store.

    event = make_event("app-123", DocTask(document_key="app-123/document.jpg"))
    raw = to_json(event)                              # bytes for Kafka
    same = parse_event(raw, DocTask)                  # validates envelope AND payload type
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ekyc import config

SCHEMA_VERSION = 1


class Topics:
    """Topic names (CLAUDE.md, Phase 6 design). Partition key everywhere: application_id."""
    SUBMITTED = "kyc.submitted"  # api -> orchestrator
    TASK_DOC = "kyc.tasks.doc"  # orchestrator -> doc-worker
    TASK_FORGERY = "kyc.tasks.forgery"  # orchestrator -> forgery-worker
    TASK_FACE = "kyc.tasks.face"  # orchestrator -> face-worker
    TASK_EXTRACTION = "kyc.tasks.extraction"  # orchestrator -> extraction-worker
    RESULTS = "kyc.results"  # workers -> orchestrator, one event per check
    DECIDED = "kyc.decided"  # orchestrator -> api
    DLQ = "kyc.dlq"  # events no worker could process
    ALL = (SUBMITTED, TASK_DOC, TASK_FORGERY, TASK_FACE, TASK_EXTRACTION, RESULTS, DECIDED, DLQ)


CheckType = Literal["doc", "forgery", "face", "extraction"]


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an unexpected field is an error, not silently ignored


class DocTask(_Payload):
    document_key: str = Field(min_length=1, description="S3 key of the ID-document image")


class ForgeryTask(_Payload):
    document_key: str = Field(min_length=1)


class FaceTask(_Payload):
    document_key: str = Field(min_length=1)
    selfie_key: str = Field(min_length=1)


class ExtractionTask(_Payload):
    document_key: str = Field(min_length=1)
    doc_type: str = Field(description="from the doc classifier (doc-worker result)")

    @field_validator("doc_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in config.DOC_TYPES:
            raise ValueError(f"unknown doc_type {value!r}")
        return value


class CheckResult(_Payload):
    """What a worker publishes on kyc.results. The orchestrator stores it keyed by (application_id, check_type),
    so a result that arrives twice (at-least-once delivery) overwrites itself instead of adding a duplicate."""
    check_type: CheckType
    status: Literal["ok", "failed"]  # "failed": the check ran but could not produce a result (e.g. extraction)
    outputs: dict[str, Any] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)
    latency_ms: float
    error: str | None = None
    task_event_id: uuid.UUID  # the task event this result answers
    worker: str


class DeadLetter(_Payload):
    """An event that could not be processed, with the reason; the original event is kept as raw text (it may
    not even be valid JSON)."""
    source_topic: str
    worker: str
    error: str
    attempts: int
    original_event: str


P = TypeVar("P", bound=BaseModel)


class Envelope(BaseModel, Generic[P]):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    application_id: str = Field(min_length=1)
    event_type: str
    schema_version: int = SCHEMA_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: P


EVENT_TYPES: dict[type[BaseModel], str] = {DocTask: "task.doc", ForgeryTask: "task.forgery", FaceTask: "task.face",
                                           ExtractionTask: "task.extraction", CheckResult: "check.result",
                                           DeadLetter: "dead_letter"}
TASK_TOPIC: dict[str, str] = {"doc": Topics.TASK_DOC, "forgery": Topics.TASK_FORGERY, "face": Topics.TASK_FACE,
                              "extraction": Topics.TASK_EXTRACTION}


def make_event(application_id: str, payload: BaseModel, event_id: uuid.UUID | None = None) -> Envelope:
    """Wrap a payload in an envelope; event_type follows from the payload's class."""
    extra = {"event_id": event_id} if event_id else {}
    return Envelope[type(payload)](application_id=application_id, event_type=EVENT_TYPES[type(payload)],
                                   payload=payload, **extra)


def to_json(event: Envelope) -> bytes:
    return event.model_dump_json().encode()


def parse_event(raw: bytes | str, payload_type: type[P]) -> Envelope[P]:
    """Validate raw JSON as an Envelope whose payload is `payload_type` (raises pydantic.ValidationError, or
    ValueError for a wrong event_type / newer schema)."""
    event = Envelope[payload_type].model_validate_json(raw)
    if event.event_type != EVENT_TYPES[payload_type]:
        raise ValueError(f"expected event_type {EVENT_TYPES[payload_type]!r}, got {event.event_type!r}")
    if event.schema_version > SCHEMA_VERSION:
        raise ValueError(f"schema_version {event.schema_version} is newer than this code ({SCHEMA_VERSION})")
    return event
