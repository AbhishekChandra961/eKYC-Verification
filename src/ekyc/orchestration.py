"""The orchestrator's logic (Phase 7): fan-out of checks, fan-in of results, the decision, timeouts.

    kyc.submitted --> on_submitted: PROCESSING; publish doc + face tasks (in parallel)
    kyc.results   --> on_result: store the result (upsert by application_id + check_type), then
                      doc result unusable (blank / unrecognized) -> decide at once (RESUBMIT_REQUIRED);
                      doc result fine -> publish forgery + extraction tasks (with the classified doc_type);
                      all required checks present -> decide, store, publish kyc.decided; the status becomes
                      APPROVED (AUTO_APPROVED), RESUBMIT_REQUESTED (RESUBMIT_REQUIRED) or DECIDED (MANUAL_REVIEW,
                      the only outcome that waits for an officer)
    every few s   --> sweep: a check without a result after its deadline becomes "timed_out" (-> MANUAL_REVIEW)

Every handler is idempotent: a re-delivered event finds the status already moved or the result already stored.
The Kafka loop itself (consume, commit after the DB write) is in services/orchestrator/main.py.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pymongo.database import Database

from ekyc import decision as engine
from ekyc import store
from ekyc.messaging.events import (CheckResult, DecidedPayload, DocTask, ExtractionTask, FaceTask, ForgeryTask,
                                   SubmittedPayload, Topics, make_event)
from ekyc.messaging.kafka import publish, wait_delivered

log = logging.getLogger("orchestrator")
ACTOR = "system:orchestrator"


@dataclass
class Orchestrator:
    db: Database
    producer: object  # confluent_kafka.Producer (or a fake in tests)
    policy: engine.Policy
    timeouts_s: dict = field(default_factory=lambda: {"doc": 60, "face": 60, "forgery": 60, "extraction": 180})
    ai_note: object | None = None  # an Extractor with complete_text(); None = no LLM note (default, saves memory)
    clock: object = store.now

    # ------------------------------------------------------------------ helpers
    def _deadlines(self, checks: list[str]) -> dict:
        at = self.clock()
        return {f"pending.{c}": at + timedelta(seconds=self.timeouts_s[c]) for c in checks}

    def _send(self, topic: str, application_id: str, payload) -> None:
        publish(self.producer, topic, make_event(application_id, payload))

    # ------------------------------------------------------------------ kyc.submitted
    def on_submitted(self, application_id: str, payload: SubmittedPayload) -> None:
        app = store.get_application(self.db, application_id)
        if app is None:
            log.warning("submitted event for unknown application %s ignored", application_id)
            return
        if app["status"] != "SUBMITTED":
            return  # duplicate event: the checks were already started
        self._send(Topics.TASK_DOC, application_id, DocTask(document_key=payload.document_key))
        self._send(Topics.TASK_FACE, application_id, FaceTask(document_key=payload.document_key,
                                                              selfie_key=payload.selfie_key))
        wait_delivered(self.producer, log)  # tasks stored in Kafka before the status says so
        store.move(self.db, application_id, "PROCESSING", ACTOR, "checks started: doc, face",
                   self._deadlines(["doc", "face"]))
        log.info("application %s: PROCESSING (doc + face tasks published)", application_id)

    # ------------------------------------------------------------------ kyc.results
    def on_result(self, application_id: str, result: CheckResult, result_event_id: str) -> None:
        store.upsert_check(self.db, application_id, result.check_type, result.status, result.outputs, result.error,
                           result.model_versions, result.latency_ms, result_event_id)
        app = store.get_application(self.db, application_id)
        if app is None or app["status"] != "PROCESSING":
            return  # unknown, or already decided (a late or duplicate result is stored but changes nothing)
        store.set_fields(self.db, application_id, {}, unset=[f"pending.{result.check_type}"])
        if result.check_type == "doc":
            self._after_doc(app, result)
        self.try_decide(application_id)

    def _after_doc(self, app: dict, result: CheckResult) -> None:
        application_id = app["application_id"]
        if app.get("second_wave"):
            return  # duplicate doc result: forgery + extraction were already requested
        doc_check = {"status": result.status, "outputs": result.outputs}
        if engine.needs_early_resubmit(doc_check, self.policy):
            self.decide(application_id, early=True)
            return
        checks = ["forgery"]
        self._send(Topics.TASK_FORGERY, application_id, ForgeryTask(document_key=app["document_key"]))
        doc_type = result.outputs.get("doc_type") if result.status == "ok" else None
        if doc_type:
            checks.append("extraction")
            self._send(Topics.TASK_EXTRACTION, application_id,
                       ExtractionTask(document_key=app["document_key"], doc_type=doc_type))
        else:  # no document type (doc check failed / timed out): extraction cannot run
            store.upsert_check(self.db, application_id, "extraction", "skipped", error="no document type",
                               only_if_missing=True)
        wait_delivered(self.producer, log)
        store.set_fields(self.db, application_id, {"second_wave": True, "doc_type": doc_type, **self._deadlines(checks)})
        log.info("application %s: doc %s -> %s published", application_id, doc_type or result.status, " + ".join(checks))

    # ------------------------------------------------------------------ fan-in + decision
    def try_decide(self, application_id: str) -> bool:
        checks = store.get_checks(self.db, application_id)
        if all(c in checks for c in engine.REQUIRED_CHECKS):
            return self.decide(application_id)
        return False

    def decide(self, application_id: str, early: bool = False) -> bool:
        app = store.get_application(self.db, application_id)
        checks = store.get_checks(self.db, application_id)
        result = engine.decide({k: {"status": c["status"], "outputs": c.get("outputs"), "error": c.get("error")}
                                for k, c in checks.items()}, app["applicant"], self.policy, today=self.clock().date())
        summary = engine.official_summary(application_id, result, checks)
        values = {"decision": result.to_dict() | {"decided_at": self.clock(), "early": early}, "summary": summary,
                  "pending": {}}
        if self.ai_note is not None:  # optional, OFF by default: an "AI-assisted note" next to the official record
            from ekyc.extraction import summarize_case
            values["ai_note"] = summarize_case({"case_id": application_id, "decision": result.outcome,
                                                "reasons": [r.message for r in result.reasons]}, self.ai_note)
        # only a manual review stays open (DECIDED, for an officer); the other outcomes close the application
        to_status = store.STATUS_FOR_OUTCOME[result.outcome]
        reason = f"decision {result.outcome}" + (f" (risk {result.risk_level})" if result.risk_level else "")
        if not store.move(self.db, application_id, to_status, ACTOR, reason + (" - early, document unusable" if early else ""),
                          values, from_statuses=("PROCESSING",)):
            return False  # already decided (duplicate)
        self._send(Topics.DECIDED, application_id, DecidedPayload(outcome=result.outcome, risk_level=result.risk_level,
                                                                  risk_score=result.risk_score,
                                                                  reason_codes=[r.code for r in result.reasons]))
        wait_delivered(self.producer, log)
        log.info("application %s: %s, %s (risk %s, score %s)", application_id, to_status, result.outcome,
                 result.risk_level, result.risk_score)
        return True

    # ------------------------------------------------------------------ timeouts
    def sweep(self) -> int:
        """Mark every check past its deadline as timed_out (only if no result arrived meanwhile) and decide where
        that completes the set. Returns how many checks timed out."""
        at: datetime = self.clock()
        timed_out = 0
        for app in store.due_applications(self.db, at):
            application_id = app["application_id"]
            for check, deadline in (app.get("pending") or {}).items():
                if deadline > at:
                    continue
                if store.upsert_check(self.db, application_id, check, "timed_out",
                                      error=f"no result within {self.timeouts_s[check]} s", only_if_missing=True):
                    timed_out += 1
                    log.warning("application %s: %s check timed out", application_id, check)
                store.set_fields(self.db, application_id, {}, unset=[f"pending.{check}"])
                if check == "doc" and not app.get("second_wave"):
                    # without a doc result there is no document type: run forgery, skip extraction
                    self._after_doc(app, CheckResult(check_type="doc", status="failed", latency_ms=0,
                                                     task_event_id=uuid.UUID(int=0), worker="orchestrator-sweeper"))
            self.try_decide(application_id)
        return timed_out
