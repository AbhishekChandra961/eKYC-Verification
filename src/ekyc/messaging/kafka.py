"""Kafka producer and consumer helpers on confluent-kafka (the Python client built on librdkafka).

Delivery guarantee: AT-LEAST-ONCE. A worker commits a message's offset only after it has fully processed it
and its result is acknowledged by Kafka. A crash in between means the message is processed again after the
restart, so results must be idempotent (upsert by application_id + check_type).
"""

from __future__ import annotations

import logging
import time

from confluent_kafka import Consumer, KafkaException, Producer

from ekyc.messaging.events import Envelope, to_json
from ekyc.messaging.settings import Settings, load_settings


def partition_key(event: Envelope) -> bytes:
    """The partition key is the application_id: all events of one application go to the same partition, so
    they are read in the order they were written (a result never overtakes its task's earlier events)."""
    return event.application_id.encode()


def producer_config(settings: Settings, client_id: str) -> dict:
    return {
        "bootstrap.servers": settings.kafka_bootstrap,
        "client.id": client_id,
        "acks": "all",  # the write counts only when the broker has stored it
        "enable.idempotence": True,  # the producer's own retries never write a message twice
        "partitioner": "murmur2_random",  # same key -> partition mapping as the Java clients (and Kafka UI)
        "linger.ms": 5,
    }


def make_producer(client_id: str, settings: Settings | None = None) -> Producer:
    return Producer(producer_config(settings or load_settings(), client_id))


def publish(producer: Producer, topic: str, event: Envelope, on_delivery=None) -> None:
    """Send one envelope, keyed by its application_id. Delivery is asynchronous: call producer.flush() before
    relying on it (the worker does, before it commits the offset of the task it answered)."""
    producer.produce(topic, key=partition_key(event), value=to_json(event), on_delivery=on_delivery,
                     headers={"event_type": event.event_type, "schema_version": str(event.schema_version)})
    producer.poll(0)  # serve delivery callbacks of earlier messages


def consumer_config(settings: Settings, group_id: str) -> dict:
    return {
        "bootstrap.servers": settings.kafka_bootstrap,
        "group.id": group_id,  # workers of the same type share the partitions of their topic
        "enable.auto.commit": False,  # commit by hand, after processing (at-least-once)
        "auto.offset.reset": "earliest",  # a new group starts at the oldest message, so nothing is skipped
        "max.poll.interval.ms": 900_000,  # 15 min: a slow LLM extraction must not look like a dead consumer
        "session.timeout.ms": 90_000,  # tolerate a worker starved of CPU/memory for a while (16 GB Mac)
    }


def make_consumer(group_id: str, topics: list[str], settings: Settings | None = None) -> Consumer:
    consumer = Consumer(consumer_config(settings or load_settings(), group_id))
    consumer.subscribe(topics)
    return consumer


def wait_delivered(producer: Producer, log: logging.Logger, limit_s: float = 300.0) -> None:
    """Block until Kafka has acknowledged everything produced so far. A broker that stalls for a while (Phase 6: the
    Docker VM paged out under memory pressure) is waited for, with a warning every 10 s, up to librdkafka's own
    delivery timeout (5 min); then RuntimeError (the caller does not commit, so the input is processed again)."""
    start = time.monotonic()
    while (remaining := producer.flush(10)) > 0:
        waited = time.monotonic() - start
        if waited >= limit_s:
            raise RuntimeError(f"{remaining} message(s) not acknowledged by Kafka after {waited:.0f} s")
        log.warning("waiting for Kafka to acknowledge %d message(s) (%.0f s so far)", remaining, waited)


def safe_commit(consumer: Consumer, message, log: logging.Logger) -> bool:
    """Commit a message's offset. A failed commit is NOT fatal: the work is done and stored; at worst the message
    is delivered again, and every consumer here handles duplicates. Returns whether the commit succeeded."""
    try:
        consumer.commit(message=message, asynchronous=False)
        return True
    except KafkaException as exc:
        log.warning("offset commit failed (%s); the message may be delivered again (handled idempotently)",
                    exc.args[0] if exc.args else exc)
        return False
