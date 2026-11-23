"""Tests for the messaging layer (Phase 6): envelope round-trip, partition key, retry/backoff and the worker's
DLQ / de-duplication logic with fake Kafka and S3 objects. One integration test uses the real broker when the
docker-compose stack is running (skipped otherwise)."""

import json
import socket
import uuid

import pytest
from pydantic import ValidationError

from ekyc.messaging import events, kafka, retry
from ekyc.messaging.events import CheckResult, DocTask, ExtractionTask, FaceTask, Topics, make_event, parse_event
from ekyc.messaging.worker import Outcome, PermanentError, Worker


# ------------------------------------------------------------------ envelope
def test_envelope_round_trip():
    event = make_event("app-1", FaceTask(document_key="app-1/doc.jpg", selfie_key="app-1/selfie.jpg"))
    raw = events.to_json(event)
    back = parse_event(raw, FaceTask)
    assert back == event and back.event_type == "task.face" and back.schema_version == 1
    assert isinstance(back.payload, FaceTask) and back.payload.selfie_key == "app-1/selfie.jpg"
    assert json.loads(raw)["application_id"] == "app-1"  # plain JSON for Kafka UI / other languages


@pytest.mark.parametrize("change, payload_type", [
    (lambda d: d.update(event_type="task.face"), DocTask),  # wrong event type for this topic
    (lambda d: d.update(schema_version=99), DocTask),  # written by newer code
    (lambda d: d["payload"].update(extra="x"), DocTask),  # unknown payload field
    (lambda d: d.update(application_id=""), DocTask),  # empty partition key
    (lambda d: d.update(payload={"document_key": "k"}), FaceTask),  # FaceTask needs selfie_key
])
def test_invalid_events_are_rejected(change, payload_type):
    data = json.loads(events.to_json(make_event("app-1", DocTask(document_key="k"))))
    change(data)
    with pytest.raises((ValidationError, ValueError)):
        parse_event(json.dumps(data), payload_type)


def test_head_turn_frame_keys_come_together():
    """Phase 13: both head-turn frame keys or neither (None = photo uploaded); older events without them still parse."""
    both = FaceTask(document_key="d", selfie_key="s", liveness_left_key="l", liveness_right_key="r")
    assert parse_event(events.to_json(make_event("app-1", both)), FaceTask).payload.liveness_right_key == "r"
    assert FaceTask(document_key="d", selfie_key="s").liveness_left_key is None
    with pytest.raises(ValidationError):
        FaceTask(document_key="d", selfie_key="s", liveness_left_key="l")
    with pytest.raises(ValidationError):
        events.SubmittedPayload(document_key="d", selfie_key="s", liveness_right_key="r")
    old = {"event_id": str(uuid.uuid4()), "application_id": "app-1", "event_type": "task.face", "schema_version": 1,
           "created_at": "2026-11-18T08:00:00Z", "payload": {"document_key": "d", "selfie_key": "s"}}  # before Phase 13
    assert parse_event(json.dumps(old), FaceTask).payload.liveness_left_key is None


def test_extraction_task_needs_a_known_doc_type():
    assert ExtractionTask(document_key="k", doc_type="srb_passport").doc_type == "srb_passport"
    with pytest.raises(ValidationError):
        ExtractionTask(document_key="k", doc_type="usa_passport")


# ------------------------------------------------------------------ partition key
class FakeProducer:
    def __init__(self):
        self.messages = []

    def produce(self, topic, key, value, on_delivery=None, headers=None):
        self.messages.append({"topic": topic, "key": key, "value": value, "headers": headers})

    def poll(self, timeout):
        return 0

    def flush(self, timeout=None):
        return 0  # everything delivered


def test_partition_key_is_the_application_id():
    producer = FakeProducer()
    event = make_event("app-42", DocTask(document_key="k"))
    kafka.publish(producer, Topics.TASK_DOC, event)
    sent = producer.messages[0]
    assert kafka.partition_key(event) == b"app-42" and sent["key"] == b"app-42"
    assert sent["headers"] == {"event_type": "task.doc", "schema_version": "1"}
    config = kafka.producer_config(kafka.load_settings(), "test")
    assert config["acks"] == "all" and config["enable.idempotence"] and config["partitioner"] == "murmur2_random"
    assert not kafka.consumer_config(kafka.load_settings(), "g")["enable.auto.commit"]  # manual commits


def _kafka_up() -> bool:
    host, port = kafka.load_settings().kafka_bootstrap.split(":")
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, int(port))) == 0


@pytest.mark.services
@pytest.mark.skipif(not _kafka_up(), reason="Kafka not running (docker compose up -d)")
def test_same_application_always_lands_on_the_same_partition():
    from confluent_kafka.admin import AdminClient, NewTopic

    # a throw-away topic: tests must never write into the real kyc.* topics that services read
    topic = f"pytest.partitioning.{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": kafka.load_settings().kafka_bootstrap})
    admin.create_topics([NewTopic(topic, num_partitions=3, replication_factor=1)])[topic].result(10)
    try:
        producer = kafka.make_producer("pytest")
        partitions = {}

        def record(err, msg):
            assert err is None
            partitions.setdefault(msg.key().decode(), set()).add(msg.partition())

        for app in ("pytest-app-a", "pytest-app-b", "pytest-app-c"):
            for _ in range(3):
                kafka.publish(producer, topic, make_event(app, DocTask(document_key="k")), on_delivery=record)
        assert producer.flush(10) == 0
        assert all(len(p) == 1 for p in partitions.values())  # each application: one partition, every time
    finally:
        admin.delete_topics([topic])[topic].result(10)


# ------------------------------------------------------------------ retry
def test_retry_backoff_then_success():
    calls, waits = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("S3 briefly unreachable")
        return "done"

    assert retry.run_with_retry(flaky, retry.RetryPolicy(), sleep=waits.append) == ("done", 3)
    assert waits == [0.5, 1.0]  # exponential backoff


def test_retry_gives_up_and_permanent_errors_are_not_retried():
    waits = []
    with pytest.raises(retry.RetriesExhausted) as info:
        retry.run_with_retry(lambda: 1 / 0, retry.RetryPolicy(max_attempts=3), sleep=waits.append)
    assert info.value.attempts == 3 and isinstance(info.value.last_error, ZeroDivisionError) and len(waits) == 2

    def hopeless():
        raise PermanentError("cannot be fixed by retrying")

    with pytest.raises(retry.RetriesExhausted) as info:
        retry.run_with_retry(hopeless, sleep=waits.append)
    assert info.value.attempts == 1


# ------------------------------------------------------------------ worker logic
class ToyWorker(Worker):
    check_type, task_topic, payload_type = "doc", Topics.TASK_DOC, DocTask

    def __init__(self, failures=0, outcome=None):
        super().__init__(producer=FakeProducer(), retry=retry.RetryPolicy(base_delay=0))
        self.failures, self.calls, self.outcome = failures, 0, outcome or Outcome({"doc_type": "alb_id"})

    def load(self):
        pass

    def handle(self, payload):
        self.calls += 1
        if self.calls <= self.failures:
            raise KeyError(f"NoSuchKey: {payload.document_key}")
        return self.outcome

    def sent(self, topic):
        return [json.loads(m["value"]) for m in self.producer.messages if m["topic"] == topic]


def task(app="app-1", event_id=None):
    return events.to_json(make_event(app, DocTask(document_key=f"{app}/doc.jpg"), event_id=event_id))


def test_worker_publishes_one_result():
    w = ToyWorker()
    w.process(task())
    (result,) = w.sent(Topics.RESULTS)
    assert result["application_id"] == "app-1" and result["event_type"] == "check.result"
    payload = CheckResult.model_validate(result["payload"])
    assert payload.check_type == "doc" and payload.status == "ok" and payload.outputs == {"doc_type": "alb_id"}
    assert payload.latency_ms >= 0 and payload.worker == "doc-worker"


def test_worker_retries_then_dead_letters_with_the_original_event():
    w = ToyWorker(failures=99)
    raw = task("app-bad")
    w.process(raw)
    assert w.calls == 3 and w.sent(Topics.RESULTS) == []
    (letter,) = w.sent(Topics.DLQ)
    assert letter["application_id"] == "app-bad" and letter["payload"]["attempts"] == 3
    assert "NoSuchKey" in letter["payload"]["error"] and letter["payload"]["original_event"] == raw.decode()


def test_worker_recovers_from_a_transient_error():
    w = ToyWorker(failures=2)
    w.process(task())
    assert w.calls == 3 and len(w.sent(Topics.RESULTS)) == 1 and w.sent(Topics.DLQ) == []


def test_invalid_event_goes_straight_to_the_dlq():
    w = ToyWorker()
    w.process(b"{not json")
    assert w.calls == 0 and w.sent(Topics.DLQ)[0]["payload"]["attempts"] == 1


def test_duplicate_event_is_processed_once():
    w, event_id = ToyWorker(), uuid.uuid4()
    w.process(task(event_id=event_id))
    w.process(task(event_id=event_id))  # Kafka re-delivered the same event
    assert w.calls == 1 and len(w.sent(Topics.RESULTS)) == 1 and w.stats["duplicates"] == 1


def test_failed_outcome_is_a_result_not_an_error():
    w = ToyWorker(outcome=Outcome({}, status="failed", error="extraction failed"))
    w.process(task())
    (result,) = w.sent(Topics.RESULTS)
    assert result["payload"]["status"] == "failed" and result["payload"]["error"] == "extraction failed"
    assert w.sent(Topics.DLQ) == [] and w.stats["failed"] == 1


def test_a_failed_offset_commit_does_not_stop_the_worker():
    from confluent_kafka import KafkaError, KafkaException

    class Message:
        def __init__(self, raw):
            self.raw = raw

        def value(self):
            return self.raw

        def error(self):
            return None

    class FlakyConsumer:
        def __init__(self, messages, worker):
            self.messages, self.worker, self.commits = list(messages), worker, 0

        def poll(self, timeout):
            if not self.messages:
                self.worker._stop = True
                return None
            return self.messages.pop(0)

        def commit(self, message, asynchronous):
            self.commits += 1
            if self.commits == 1:  # the group session lapsed while the first task was processed
                raise KafkaException(KafkaError(KafkaError._WAIT_COORD))

        def close(self):
            pass

    w = ToyWorker()
    w.consumer, w.s3 = FlakyConsumer([Message(task("app-1")), Message(task("app-2"))], w), object()
    w.load = lambda: None
    w.run()  # must not raise
    assert w.stats["processed"] == 2 and w.stats["commit_failures"] == 1 and w.consumer.commits == 2


def test_worker_waits_for_a_stalled_broker_instead_of_dying():
    class SlowProducer(FakeProducer):
        def __init__(self):
            super().__init__()
            self.flushes = 0

        def flush(self, timeout=None):
            self.flushes += 1
            return 1 if self.flushes < 3 else 0  # not acknowledged for two rounds, then fine

    w = ToyWorker()
    w.producer = SlowProducer()
    w.process(task())
    assert w.stats["processed"] == 1 and w.producer.flushes == 3
    w.producer.flushes = -10**6  # never acknowledged
    with pytest.raises(RuntimeError, match="not acknowledged"):
        w.wait_delivered(limit_s=0)
