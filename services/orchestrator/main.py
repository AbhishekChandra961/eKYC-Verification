"""orchestrator (Phase 7): consumes kyc.submitted + kyc.results, publishes the check tasks and kyc.decided, and
keeps the application state in MongoDB (logic: src/ekyc/orchestration.py).

At-least-once: a message's offset is committed only after its database write. A handler error is retried 3 times
(backoff); an invalid or still-failing event goes to kyc.dlq. Every 5 s the timeout sweeper runs.
ORCHESTRATOR_LLM_NOTE=true (in .env) adds an LLM "AI-assisted note" per case (default false: saves 6-8 GB).
Run: .venv/bin/python services/orchestrator/main.py
"""

import logging
import os
import signal
import threading
import time

from dotenv import dotenv_values
from pydantic import ValidationError

from ekyc import config, decision, store
from ekyc.messaging import health
from ekyc.messaging.events import CheckResult, DeadLetter, SubmittedPayload, Topics, make_event, parse_event
from ekyc.messaging.kafka import make_consumer, make_producer, publish, safe_commit, wait_delivered
from ekyc.messaging.retry import RetriesExhausted, RetryPolicy, run_with_retry
from ekyc.messaging.settings import load_settings
from ekyc.orchestration import Orchestrator

log = logging.getLogger("orchestrator")
SWEEP_EVERY_S = 5.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = load_settings()
    env = {**dotenv_values(config.PROJECT_ROOT / ".env"), **os.environ}
    ai_note = None
    if str(env.get("ORCHESTRATOR_LLM_NOTE", "false")).lower() == "true":
        from ekyc.extraction import OllamaExtractor
        ai_note = OllamaExtractor(host=settings.ollama_host, keep_alive="2m")
    db = store.connect(settings)
    producer = make_producer("orchestrator", settings)
    orchestrator = Orchestrator(db, producer, decision.load_policy(), ai_note=ai_note)
    consumer = make_consumer("orchestrator", [Topics.SUBMITTED, Topics.RESULTS], settings)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda s, f: (log.info("signal %s: stopping after the current message", signal.Signals(s).name),
                                         stop.set()))
    log.info("consuming %s + %s (LLM note: %s)", Topics.SUBMITTED, Topics.RESULTS, "on" if ai_note else "off")
    last_sweep = 0.0
    try:
        while not stop.is_set():
            if time.monotonic() - last_sweep >= SWEEP_EVERY_S:
                try:
                    orchestrator.sweep()
                except Exception:  # noqa: BLE001 - a failed sweep is retried at the next interval
                    log.exception("timeout sweep failed")
                last_sweep = time.monotonic()
            message = consumer.poll(1.0)
            health.beat()  # liveness for the container healthcheck (no-op on the host)
            if message is None:
                continue
            if message.error():
                log.warning("consumer error: %s", message.error())
                continue
            handle(orchestrator, producer, message)
            safe_commit(consumer, message, log)  # after the database write
    finally:
        watchdog = threading.Timer(30.0, lambda: os._exit(0))  # never hang on a stalled broker
        watchdog.daemon = True
        watchdog.start()
        consumer.close()
        producer.flush(10)
        watchdog.cancel()


def handle(orchestrator: Orchestrator, producer, message) -> None:
    topic, raw = message.topic(), message.value()
    try:
        if topic == Topics.SUBMITTED:
            event = parse_event(raw, SubmittedPayload)
            work = lambda: orchestrator.on_submitted(event.application_id, event.payload)  # noqa: E731
        else:
            event = parse_event(raw, CheckResult)
            work = lambda: orchestrator.on_result(event.application_id, event.payload, str(event.event_id))  # noqa: E731
    except (ValidationError, ValueError) as exc:
        dead_letter(producer, topic, raw, f"invalid event: {exc}", 1)
        return
    try:
        run_with_retry(work, RetryPolicy())
    except RetriesExhausted as exc:
        dead_letter(producer, topic, raw, str(exc), exc.attempts, event.application_id)


def dead_letter(producer, topic: str, raw: bytes, error: str, attempts: int, application_id: str = "unknown") -> None:
    letter = DeadLetter(source_topic=topic, worker="orchestrator", error=error[:2000], attempts=attempts,
                        original_event=raw.decode(errors="replace"))
    publish(producer, Topics.DLQ, make_event(application_id, letter))
    wait_delivered(producer, log)
    log.error("application %s: event from %s sent to %s: %s", application_id, topic, Topics.DLQ, error[:200])


if __name__ == "__main__":
    main()
