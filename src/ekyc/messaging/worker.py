"""Base class of the inference workers (Phase 6). A worker reads tasks from one topic and publishes one
CheckResult per task on kyc.results.

For every message, in this order:
1. parse and validate the envelope (an invalid event goes straight to kyc.dlq: retrying cannot fix it);
2. skip it if this event_id was already processed (a re-delivered duplicate);
3. handle(): download the images from S3 and run the model, retried with backoff on errors; when the retries
   are used up, the original event goes to kyc.dlq with the error;
4. publish the result and WAIT until Kafka has stored it (flush);
5. only then commit the offset. A crash before step 5 means the task is processed again: at-least-once.

Logs: one line per message (application, status, latency) and a heartbeat line every heartbeat_s seconds.
No extracted personal data is logged (PII). Ctrl+C or SIGTERM finishes the current message, then stops.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from ekyc.messaging import storage
from ekyc.messaging.events import CheckResult, DeadLetter, Topics, make_event, parse_event
from ekyc.messaging import kafka as kafka_helpers
from ekyc.messaging.kafka import make_consumer, make_producer, publish
from ekyc.messaging.retry import PermanentError, RetriesExhausted, RetryPolicy, run_with_retry
from ekyc.messaging.settings import Settings, load_settings


@dataclass
class Outcome:
    """What handle() returns. status "failed" = the check ran but produced no usable result (it is still a
    result, not an error: the orchestrator decides what it means, e.g. manual review)."""
    outputs: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None


class Worker(ABC):
    check_type: str  # "doc" | "forgery" | "face" | "extraction"
    task_topic: str
    payload_type: type[BaseModel]

    def __init__(self, settings: Settings | None = None, consumer=None, producer=None, s3=None,
                 retry: RetryPolicy = RetryPolicy(), heartbeat_s: float = 30.0, seen_capacity: int = 10_000):
        self.name = f"{self.check_type}-worker"
        self.log = logging.getLogger(self.name)
        self.settings = settings or load_settings()
        self.consumer, self.producer, self.s3 = consumer, producer, s3  # injected in tests, created in run()
        self.retry, self.heartbeat_s = retry, heartbeat_s
        self._seen: OrderedDict[str, None] = OrderedDict()  # recently processed event_ids (de-duplication)
        self._seen_capacity = seen_capacity
        self._stop = False
        self.stats = {"processed": 0, "failed": 0, "dead_lettered": 0, "duplicates": 0, "last_latency_ms": None}

    # ------------------------------------------------------------------ to implement per worker
    @abstractmethod
    def load(self) -> None:
        """Load the model(s) once, before consuming."""

    @abstractmethod
    def handle(self, payload: BaseModel) -> Outcome:
        """Process one task payload. Raise on errors worth retrying; raise PermanentError for hopeless ones."""

    def model_versions(self) -> dict[str, str]:
        return {}

    # ------------------------------------------------------------------ helpers for handle()
    def fetch(self, key: str) -> bytes:
        """Download an object from the upload bucket."""
        return storage.download_bytes(self.s3, self.settings.s3_bucket, key)

    # ------------------------------------------------------------------ the loop
    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)  # not one line per Ollama request
        self.log.info("loading model(s)")
        self.load()
        self.s3 = self.s3 or storage.s3_client(self.settings)
        self.producer = self.producer or make_producer(self.name, self.settings)
        self.consumer = self.consumer or make_consumer(self.name, [self.task_topic], self.settings)
        signal.signal(signal.SIGINT, self._request_stop)
        signal.signal(signal.SIGTERM, self._request_stop)
        self.log.info("consuming %s as group %s", self.task_topic, self.name)
        last_beat = time.monotonic()
        try:
            while not self._stop:
                message = self.consumer.poll(1.0)
                if time.monotonic() - last_beat >= self.heartbeat_s:
                    self.log.info("heartbeat %s", self.stats)
                    last_beat = time.monotonic()
                if message is None:
                    continue
                if message.error():
                    self.log.warning("consumer error: %s", message.error())
                    continue
                self.process(message.value())
                self.commit(message)
        finally:
            self.log.info("stopping: %s", self.stats)
            # leave the group cleanly, so the partitions are handed over at once; but never hang on a stalled
            # broker: after 30 s the process exits anyway (every finished task is already committed)
            watchdog = threading.Timer(30.0, lambda: (self.log.warning("close timed out; exiting"), os._exit(0)))
            watchdog.daemon = True
            watchdog.start()
            self.consumer.close()
            self.producer.flush(10)
            watchdog.cancel()

    def commit(self, message) -> None:
        """Commit the offset (after the result is stored). A failed commit is NOT fatal: the result is already in
        Kafka; at worst the task is delivered again and its duplicate result is absorbed by the idempotent upsert.
        (Seen in Phase 6: under heavy memory pressure the group session lapsed -> "Waiting for coordinator".)"""
        if not kafka_helpers.safe_commit(self.consumer, message, self.log):
            self.stats["commit_failures"] = self.stats.get("commit_failures", 0) + 1

    def _request_stop(self, signum, frame) -> None:
        self.log.info("signal %s: finishing the current message, then stopping", signal.Signals(signum).name)
        self._stop = True

    def process(self, raw: bytes) -> None:
        """Steps 1-4 for one raw message (the caller commits the offset afterwards)."""
        try:
            event = parse_event(raw, self.payload_type)
        except (ValidationError, ValueError) as exc:
            self.dead_letter(raw, f"invalid event: {exc}", attempts=1)
            return
        event_id = str(event.event_id)
        if event_id in self._seen:
            self.stats["duplicates"] += 1
            self.log.info("duplicate event %s for %s skipped (already processed)", event_id, event.application_id)
            return
        start = time.perf_counter()
        try:
            outcome, attempts = run_with_retry(lambda: self.handle(event.payload), self.retry)
        except RetriesExhausted as exc:
            self.dead_letter(raw, str(exc), exc.attempts, application_id=event.application_id)
            self._remember(event_id)
            return
        latency_ms = (time.perf_counter() - start) * 1000
        result = CheckResult(check_type=self.check_type, status=outcome.status, outputs=outcome.outputs,
                             model_versions=self.model_versions(), latency_ms=round(latency_ms, 1),
                             error=outcome.error, task_event_id=event.event_id, worker=self.name)
        publish(self.producer, Topics.RESULTS, make_event(event.application_id, result))
        self.wait_delivered()  # the offset is committed only after this
        self._remember(event_id)
        self.stats["processed"] += 1
        self.stats["failed"] += outcome.status == "failed"
        self.stats["last_latency_ms"] = round(latency_ms)
        self.log.info("application %s: %s %s in %.0f ms (attempts %d)", event.application_id, self.check_type,
                      outcome.status, latency_ms, attempts)

    def wait_delivered(self, limit_s: float = 300.0) -> None:
        """Block until Kafka has acknowledged everything sent so far. A broker that stalls for a while (seen in
        Phase 6: the Docker VM paged out under memory pressure) is waited for, with a warning every 10 s, up to
        librdkafka's own delivery timeout (5 min). Only then does the worker give up (exception -> no commit, so
        the task is delivered again after a restart)."""
        kafka_helpers.wait_delivered(self.producer, self.log, limit_s)

    def dead_letter(self, raw: bytes, error: str, attempts: int, application_id: str = "unknown") -> None:
        letter = DeadLetter(source_topic=self.task_topic, worker=self.name, error=error[:2000], attempts=attempts,
                            original_event=raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw))
        publish(self.producer, Topics.DLQ, make_event(application_id, letter))
        self.wait_delivered()
        self.stats["dead_lettered"] += 1
        self.log.error("application %s: sent to %s after %d attempt(s): %s", application_id, Topics.DLQ, attempts,
                       error[:200])

    def _remember(self, event_id: str) -> None:
        self._seen[event_id] = None
        if len(self._seen) > self._seen_capacity:
            self._seen.popitem(last=False)  # forget the oldest


__all__ = ["Outcome", "PermanentError", "Worker"]
