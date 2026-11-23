"""eKYC API (Phase 7, FastAPI). THIN: it stores uploads, records applications and publishes kyc.submitted; it never
runs a model. Run: .venv/bin/uvicorn app:app --app-dir services/api --port 8000   (docs: http://localhost:8000/docs)

Roles: CUSTOMER (submits and follows own applications) and OFFICER (works the review queue). Login gives a JWT;
role checks are FastAPI dependencies. Demo accounts come from .env (DEMO_CUSTOMER_*, DEMO_OFFICER_*).
"""


import io
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal

import jwt
from dotenv import dotenv_values
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from ekyc import config, security, store
from ekyc.decision import REQUIRED_CHECKS
from ekyc.messaging import storage
from ekyc.messaging.events import SubmittedPayload, Topics, make_event
from ekyc.messaging.kafka import make_producer, publish, wait_delivered
from ekyc.messaging.settings import Settings, load_settings

log = logging.getLogger("ekyc.api")
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}
# the checks are over: the SSE stream ends here (DECIDED = under review; the officer's decision comes later)
FINAL = ("DECIDED", *store.CLOSED)
CUSTOMER_MESSAGES = {"AUTO_APPROVED": "Your identity has been verified.",
                     "MANUAL_REVIEW": "Your application is being reviewed by our compliance team.",
                     "RESUBMIT_REQUIRED": "We could not complete the check. Please submit new photos.",
                     "OFFICER_APPROVED": "Your identity has been verified by our compliance team.",
                     "REJECTED": "We could not verify your identity. Please contact support."}


@dataclass
class ApiConfig:
    jwt_secret: str
    jwt_minutes: float = 30.0
    max_upload_bytes: int = 10 * 1024 * 1024
    presign_seconds: int = 300
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)


def config_from_env() -> tuple[ApiConfig, dict]:
    env = {**dotenv_values(config.PROJECT_ROOT / ".env"), **os.environ}
    if not env.get("JWT_SECRET"):
        raise RuntimeError("JWT_SECRET is not set (see .env.example)")
    origins = tuple(o.strip() for o in (env.get("API_CORS_ORIGINS") or "http://localhost:5173").split(",") if o.strip())
    return ApiConfig(jwt_secret=env["JWT_SECRET"], jwt_minutes=float(env.get("JWT_EXPIRE_MINUTES") or 30),
                     max_upload_bytes=int(float(env.get("API_MAX_UPLOAD_MB") or 10) * 1024 * 1024),
                     cors_origins=origins), env


# ---------------------------------------------------------------- response models (also the OpenAPI examples)

# DECIDED = waiting for an officer (MANUAL_REVIEW only); APPROVED, REJECTED and RESUBMIT_REQUESTED are closed
Status = Literal["SUBMITTED", "PROCESSING", "DECIDED", "APPROVED", "REJECTED", "RESUBMIT_REQUESTED"]
Outcome = Literal["AUTO_APPROVED", "MANUAL_REVIEW", "RESUBMIT_REQUIRED"]

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Literal["CUSTOMER", "OFFICER"]
    expires_in: int = Field(description="seconds")


class SubmitResponse(BaseModel):
    application_id: str = Field(examples=["app-3f2a9c1d7e4b5a60"])
    status: Status = Field(examples=["SUBMITTED"])
    status_url: str
    events_url: str


class Progress(BaseModel):
    """How far the checks are, WITHOUT their results (customer-safe)."""
    completed: int = Field(examples=[2])
    total: int = Field(examples=[4])


class ApplicationView(BaseModel):
    """What a customer sees: status, outcome, a neutral message, progress and (only for RESUBMIT_REQUIRED) what to
    photograph again. NEVER fraud signals: no forgery/face scores, rule flags, risk level or score (CLAUDE.md)."""
    application_id: str
    status: Status
    outcome: Outcome | None = None
    message: str | None = None
    retake: list[str] = Field(default_factory=list, description="what to photograph again (RESUBMIT_REQUIRED only)")
    progress: Progress
    created_at: datetime
    updated_at: datetime


class OfficerDecision(BaseModel):
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=5, max_length=1000, examples=["Surname on the page differs from the MRZ; document edited."])


# Officer-side models. They mirror what MongoDB stores; they exist so the OpenAPI schema (and the TypeScript types
# generated from it for the frontend, Phase 8) describe the responses exactly. Check `outputs` stay free-form
# dictionaries: each worker has its own output shape (documented in services/README.md).
RiskLevel = Literal["low", "medium", "high"]


class ReasonOut(BaseModel):
    code: str = Field(examples=["forgery_suspected"])
    message: str = ""
    effect: Literal["resubmit", "high", "medium", "info"]
    check_type: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class DecisionOut(BaseModel):
    outcome: Outcome
    risk_level: RiskLevel | None = None
    risk_score: float = 0.0
    reasons: list[ReasonOut] = Field(default_factory=list)
    decided_at: datetime | None = None
    early: bool = False


class CheckOut(BaseModel):
    check_type: str
    status: Literal["ok", "failed", "timed_out", "skipped"]
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    latency_ms: float | None = None
    model_versions: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None


class AuditEntry(BaseModel):
    application_id: str
    actor: str = Field(examples=["officer:u-ccb28e961558"])
    from_status: Status | None
    to_status: Status
    reason: str
    at: datetime


class Applicant(BaseModel):
    full_name: str
    date_of_birth: str


class OfficerDecisionRecord(BaseModel):
    action: Literal["approve", "reject"]
    reason: str
    officer_id: str
    at: datetime


class LivenessKeys(BaseModel):
    """S3 keys of the two head-turn frames (Phase 13); the selfie is the third frame, looking at the camera."""
    left: str
    right: str


class CaseApplication(BaseModel):
    application_id: str
    customer_id: str
    status: Status
    applicant: Applicant
    document_key: str
    selfie_key: str
    liveness_keys: LivenessKeys | None = Field(None, description="None: a photo was uploaded (no head-turn frames)")
    doc_type: str | None = None
    created_at: datetime
    updated_at: datetime
    decision: DecisionOut | None = None
    officer_decision: OfficerDecisionRecord | None = None


class TopTile(BaseModel):
    score: float
    box_1280: list[int] = Field(description="x, y, width, height on the page resized to 1280 px (longest side)")
    box_original: list[int] | None = None


class TileGrid(BaseModel):
    size: int = Field(description="tile side in px on the 1280 px page")
    count: int
    xy: list[list[int]] = Field(description="top-left corner of every tile on the 1280 px page")
    scores: list[float]


class Heatmap(BaseModel):
    page_size_1280: list[int] = Field(description="width, height of the 1280 px page the tiles are placed on")
    original_size: list[int] | None = None
    tile_size: int = 224
    tiles: TileGrid | None = Field(None, description="None for results stored before the grid was added (Phase 8)")
    top_tile: TopTile | None = None
    thresholds: dict[str, float] | None = None


class CaseImages(BaseModel):
    document_url: str
    selfie_url: str
    liveness_left_url: str | None = Field(None, description="head turned to the customer's left (Phase 13)")
    liveness_right_url: str | None = Field(None, description="head turned to the customer's right (Phase 13)")
    expires_in: int = Field(description="seconds the presigned links stay valid")


class CaseDetail(BaseModel):
    application: CaseApplication
    checks: dict[str, CheckOut]
    decision: DecisionOut | None = None
    summary: str | None = Field(None, description="template summary: the official record")
    ai_note: str | None = Field(None, description="optional LLM note; must be shown as AI-assisted")
    forgery_top_tile: TopTile | None = None
    forgery_heatmap: Heatmap | None = None
    images: CaseImages
    audit_trail: list[AuditEntry]


class CaseRow(BaseModel):
    application_id: str
    status: Status
    doc_type: str | None = None
    outcome: Outcome | None = None
    risk_level: RiskLevel | None = None
    risk_score: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None = None


class OfficerDecisionResult(BaseModel):
    application_id: str
    status: Status
    audit_trail: list[AuditEntry]


# ---------------------------------------------------------------- the app

def create_app(db=None, s3=None, producer=None, settings: Settings | None = None, api_config: ApiConfig | None = None,
               seed: dict | None = None) -> FastAPI:
    """Dependencies are injectable (tests pass fakes); by default they come from .env."""
    settings = settings or load_settings()
    env = {}
    if api_config is None:
        api_config, env = config_from_env()
    state = {"db": db, "s3": s3, "producer": producer, "s3_public": s3}  # s3_public: presigns links for browsers

    def startup() -> None:
        state["db"] = state["db"] if state["db"] is not None else store.connect(settings)
        state["s3"] = state["s3"] or storage.s3_client(settings)
        state["s3_public"] = state["s3_public"] or storage.s3_client(settings, public=True)
        state["producer"] = state["producer"] or make_producer("api", settings)
        accounts = seed if seed is not None else {"CUSTOMER": (env.get("DEMO_CUSTOMER_EMAIL"), env.get("DEMO_CUSTOMER_PASSWORD")),
                                                  "OFFICER": (env.get("DEMO_OFFICER_EMAIL"), env.get("DEMO_OFFICER_PASSWORD"))}
        for role, (email, password) in accounts.items():
            if email and password:
                user = store.find_user(state["db"], email=email)
                if user is None or not security.verify_password(user["password_hash"], password):
                    store.upsert_user(state["db"], email, security.hash_password(password), role)
                log.info("demo %s account ready", role.lower())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        startup()  # connections + demo accounts, once when the server starts
        yield

    app = FastAPI(title="eKYC verification API", version="0.9.0", lifespan=lifespan,
                  description="Customer onboarding (ID document + selfie) and the compliance officer's review queue. "
                              "Log in via **POST /auth/login** (or the Authorize button), then try the endpoints.")
    app.add_middleware(CORSMiddleware, allow_origins=list(api_config.cors_origins), allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    logging.getLogger("uvicorn.access").addFilter(security.RedactTokens())
    ekyc_log = logging.getLogger("ekyc")  # uvicorn only configures its own loggers: show ours too (masked, no PII)
    if not ekyc_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        ekyc_log.addHandler(handler)
        ekyc_log.setLevel(logging.INFO)

    # ------------------------------------------------------------ auth dependencies
    bearer = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

    def current_user(header_token: Annotated[str | None, Depends(bearer)],
                     token: Annotated[str | None, Query(include_in_schema=False)] = None) -> dict:
        raw = header_token or token  # ?token= only for the SSE stream (EventSource cannot send headers)
        failure = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token",
                                headers={"WWW-Authenticate": "Bearer"})
        if not raw:
            raise failure
        try:
            claims = security.decode_token(raw, api_config.jwt_secret)
        except jwt.InvalidTokenError:
            raise failure from None
        user = store.find_user(state["db"], user_id=claims["sub"])
        if user is None or user["role"] != claims["role"]:
            raise failure
        return user

    def require(role: str):
        def check(user: Annotated[dict, Depends(current_user)]) -> dict:
            if user["role"] != role:
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role.lower()} role required")
            return user
        return check

    Customer = Annotated[dict, Depends(require("CUSTOMER"))]
    Officer = Annotated[dict, Depends(require("OFFICER"))]

    def own_application(application_id: str, user: dict) -> dict:
        application = store.get_application(state["db"], application_id)
        if application is None or application["customer_id"] != user["user_id"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")  # do not reveal others' ids
        return application

    # ------------------------------------------------------------ endpoints
    @app.get("/health", tags=["system"])
    def health() -> dict:
        checks = {}
        for name, probe in (("mongo", lambda: state["db"].command("ping")),
                            ("s3", lambda: state["s3"].head_bucket(Bucket=settings.s3_bucket)),
                            ("kafka", lambda: state["producer"].list_topics(timeout=2))):
            try:
                probe()
                checks[name] = True
            except Exception:  # noqa: BLE001 - health only reports
                checks[name] = False
        return {"status": "ok" if all(checks.values()) else "degraded", **checks}

    @app.post("/auth/login", response_model=Token, tags=["auth"])
    def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
        user = store.find_user(state["db"], email=form.username)
        if user is None or not security.verify_password(user["password_hash"], form.password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong email or password")
        token = security.create_token(user["user_id"], user["role"], api_config.jwt_secret, api_config.jwt_minutes)
        return Token(access_token=token, role=user["role"], expires_in=int(api_config.jwt_minutes * 60))

    async def read_image(upload: UploadFile, what: str) -> tuple[bytes, str]:
        if upload.content_type not in ALLOWED_TYPES:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"{what}: only JPEG or PNG images are accepted")
        data = await upload.read(api_config.max_upload_bytes + 1)
        if len(data) > api_config.max_upload_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                f"{what}: larger than {api_config.max_upload_bytes // 1024 // 1024} MB")
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()  # a real, undamaged image file of the declared kind
                size = image.size
        except (UnidentifiedImageError, OSError, SyntaxError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{what}: not a readable image") from None
        if min(size) < 100:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{what}: image too small ({size[0]}x{size[1]})")
        return data, ALLOWED_TYPES[upload.content_type]

    @app.post("/applications", status_code=status.HTTP_202_ACCEPTED, response_model=SubmitResponse, tags=["customer"],
              summary="Submit an ID document and a selfie (+ the two head-turn frames from the camera)")
    async def submit(user: Customer,
                     full_name: Annotated[str, Form(min_length=2, max_length=120, examples=["Krsto Velimirovic"])],
                     date_of_birth: Annotated[date, Form(examples=["1974-08-15"])],
                     id_image: Annotated[UploadFile, File(description="photo or scan of the ID document (JPEG/PNG)")],
                     selfie: Annotated[UploadFile, File(description="selfie (JPEG/PNG): with the camera, the frame "
                                                                    "looking at the camera")],
                     liveness_left: Annotated[UploadFile | None, File(
                         description="Phase 13, optional: the camera frame with the head turned to the customer's "
                                     "left (JPEG/PNG). Send both turn frames or neither (photo upload).")] = None,
                     liveness_right: Annotated[UploadFile | None, File(
                         description="Phase 13, optional: the frame with the head turned to the customer's right")] = None,
                     ) -> SubmitResponse:
        """Only images are accepted: the browser's own camera guidance is never trusted, the face-worker decides
        whether the head-turn frames show a live turn (src/ekyc/liveness.py)."""
        if not date(1900, 1, 1) <= date_of_birth <= date.today():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "date_of_birth is not plausible")
        if (liveness_left is None) != (liveness_right is None):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "liveness_left and liveness_right must be sent together (or neither)")
        document, doc_ext = await read_image(id_image, "id_image")
        selfie_bytes, selfie_ext = await read_image(selfie, "selfie")
        turns = {}
        for side, upload in (("left", liveness_left), ("right", liveness_right)):
            if upload is not None:
                turns[side] = (*await read_image(upload, f"liveness_{side}"), upload.content_type)
        application_id = f"app-{os.urandom(8).hex()}"
        keys = (f"{application_id}/document{doc_ext}", f"{application_id}/selfie{selfie_ext}")
        storage.upload_bytes(state["s3"], settings.s3_bucket, keys[0], document, id_image.content_type)
        storage.upload_bytes(state["s3"], settings.s3_bucket, keys[1], selfie_bytes, selfie.content_type)
        liveness_keys = {side: f"{application_id}/liveness_{side}{ext}" for side, (_, ext, _) in turns.items()} or None
        for side, (data, _, content_type) in turns.items():
            storage.upload_bytes(state["s3"], settings.s3_bucket, liveness_keys[side], data, content_type)
        store.create_application(state["db"], user["user_id"], {"full_name": full_name.strip(),
                                                                "date_of_birth": date_of_birth.isoformat()},
                                 keys[0], keys[1], application_id=application_id, liveness_keys=liveness_keys)
        publish(state["producer"], Topics.SUBMITTED, make_event(application_id, SubmittedPayload(
            document_key=keys[0], selfie_key=keys[1], liveness_left_key=(liveness_keys or {}).get("left"),
            liveness_right_key=(liveness_keys or {}).get("right"))))
        wait_delivered(state["producer"], log, limit_s=30)
        log.info("application %s submitted by %s (applicant %s, dob %s)", application_id, user["user_id"],
                 security.mask_name(full_name), security.mask_dob())
        return SubmitResponse(application_id=application_id, status="SUBMITTED",
                              status_url=f"/applications/{application_id}",
                              events_url=f"/applications/{application_id}/events")

    def customer_progress(application: dict) -> Progress:
        """Checks finished out of the checks needed: a count only, never which check found what."""
        done = state["db"].check_results.count_documents({"application_id": application["application_id"]})
        decision = application.get("decision") or {}
        if application["status"] in FINAL:  # finished: an early decision needed fewer checks
            total = done if decision.get("early") else max(done, len(REQUIRED_CHECKS))
            return Progress(completed=total, total=total)
        return Progress(completed=min(done, len(REQUIRED_CHECKS)), total=len(REQUIRED_CHECKS))

    def message_key(application: dict) -> str | None:
        status, outcome = application["status"], (application.get("decision") or {}).get("outcome")
        if status == "REJECTED":
            return "REJECTED"
        if status == "APPROVED":  # by the system (auto) or by an officer after a review
            return "OFFICER_APPROVED" if application.get("officer_decision") else "AUTO_APPROVED"
        return outcome  # DECIDED -> MANUAL_REVIEW, RESUBMIT_REQUESTED -> RESUBMIT_REQUIRED, still running -> None

    def customer_view(application: dict) -> ApplicationView:
        decision = application.get("decision") or {}
        outcome = decision.get("outcome")
        # only a resubmission tells the customer what to retake; a case under review says nothing about why
        retake = ([r["message"] for r in decision.get("reasons", []) if r["effect"] == "resubmit"]
                  if application["status"] == "RESUBMIT_REQUESTED" else [])
        return ApplicationView(application_id=application["application_id"], status=application["status"],
                               outcome=outcome, message=CUSTOMER_MESSAGES.get(message_key(application)), retake=retake,
                               progress=customer_progress(application),
                               created_at=application["created_at"], updated_at=application["updated_at"])

    @app.get("/applications", response_model=list[ApplicationView], tags=["customer"])
    def my_applications(user: Customer) -> list[ApplicationView]:
        docs = state["db"].applications.find({"customer_id": user["user_id"]}, projection={"_id": False}).sort("created_at", -1)
        return [customer_view(a) for a in docs]

    @app.get("/applications/{application_id}", response_model=ApplicationView, tags=["customer"])
    def my_application(application_id: str, user: Customer) -> ApplicationView:
        return customer_view(own_application(application_id, user))

    @app.get("/applications/{application_id}/events", tags=["customer"],
             summary="Server-Sent Events: one 'status' event per change, until a final status")
    def application_events(application_id: str, user: Customer, request: Request) -> StreamingResponse:
        own_application(application_id, user)

        def stream():
            last, started, last_ping = None, time.monotonic(), time.monotonic()
            while time.monotonic() - started < 600:
                view = customer_view(store.get_application(state["db"], application_id))
                current = (view.status, view.outcome, view.progress.completed)
                if current != last:
                    last = current
                    yield f"event: status\ndata: {view.model_dump_json()}\n\n"
                    if view.status in FINAL:
                        return
                elif time.monotonic() - last_ping > 15:
                    yield ": keep-alive\n\n"
                    last_ping = time.monotonic()
                time.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------ officer
    @app.get("/officer/cases", response_model=list[CaseRow], tags=["officer"],
             summary="The review queue, highest risk first")
    def cases(officer: Officer, status_filter: Annotated[Status | None, Query(alias="status", examples=["DECIDED"])] = None,
              outcome: Annotated[Outcome | None, Query(examples=["MANUAL_REVIEW"])] = None,
              limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[CaseRow]:
        rows = []
        for c in store.list_cases(state["db"], status_filter, outcome, limit):
            d = c.get("decision") or {}
            rows.append(CaseRow(application_id=c["application_id"], status=c["status"], doc_type=c.get("doc_type"),
                                outcome=d.get("outcome"), risk_level=d.get("risk_level"), risk_score=d.get("risk_score"),
                                reason_codes=[r["code"] for r in d.get("reasons", [])], created_at=c["created_at"],
                                updated_at=c["updated_at"], decided_at=d.get("decided_at")))
        return rows

    @app.get("/officer/cases/{application_id}", response_model=CaseDetail, tags=["officer"],
             summary="Everything about one case, with short-lived image links")
    def case(application_id: str, officer: Officer) -> dict:
        application = store.get_application(state["db"], application_id)
        if application is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
        checks = store.get_checks(state["db"], application_id)
        forgery = (checks.get("forgery") or {}).get("outputs") or {}
        presign = lambda key: state["s3_public"].generate_presigned_url(  # noqa: E731
            "get_object", Params={"Bucket": settings.s3_bucket, "Key": key}, ExpiresIn=api_config.presign_seconds)
        log.info("officer %s opened case %s", officer["user_id"], application_id)
        heatmap = None
        if forgery.get("page_size_1280"):  # tile positions are on the 1280 px page; the UI scales them to the image
            grid = forgery.get("tiles") if isinstance(forgery.get("tiles"), dict) else None  # Phase 7 stored a count
            heatmap = {"page_size_1280": forgery["page_size_1280"], "original_size": forgery.get("original_size"),
                       "tile_size": (grid or {}).get("size", 224), "tiles": grid, "top_tile": forgery.get("top_tile"),
                       "thresholds": forgery.get("thresholds")}
        return {"application": {k: v for k, v in application.items() if k not in ("pending",)},
                "checks": checks, "decision": application.get("decision"), "summary": application.get("summary"),
                "ai_note": application.get("ai_note"),
                "forgery_top_tile": forgery.get("top_tile"), "forgery_heatmap": heatmap,
                "images": {"document_url": presign(application["document_key"]),
                           "selfie_url": presign(application["selfie_key"]),
                           **{f"liveness_{side}_url": presign(key)
                              for side, key in (application.get("liveness_keys") or {}).items()},
                           "expires_in": api_config.presign_seconds},
                "audit_trail": store.audit_trail(state["db"], application_id)}

    @app.post("/officer/cases/{application_id}/decision", response_model=OfficerDecisionResult, tags=["officer"],
              summary="Approve or reject (reason required)")
    def officer_decision(application_id: str, body: OfficerDecision, officer: Officer) -> dict:
        if store.get_application(state["db"], application_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
        to_status = "APPROVED" if body.action == "approve" else "REJECTED"
        moved = store.move(state["db"], application_id, to_status, f"officer:{officer['user_id']}", body.reason,
                           {"officer_decision": {"action": body.action, "reason": body.reason,
                                                 "officer_id": officer["user_id"], "at": store.now()}},
                           from_statuses=("DECIDED",))  # never a case that is still running or already closed
        if not moved:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "only a case awaiting an officer (status DECIDED) can be approved or rejected")
        log.info("officer %s %sd case %s", officer["user_id"], body.action, application_id)
        return {"application_id": application_id, "status": to_status,
                "audit_trail": store.audit_trail(state["db"], application_id)}

    return app


app = create_app() if os.environ.get("EKYC_API_NO_AUTOCREATE") != "1" else None
