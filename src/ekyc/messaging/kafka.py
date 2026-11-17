"""Kafka producer and consumer helpers on confluent-kafka (the Python client built on librdkafka).

Delivery guarantee: AT-LEAST-ONCE. A worker commits a message's offset only after it has fully processed it
and its result is acknowledged by Kafka. A crash in between means the message is processed again after the
restart, so results must be idempotent (upsert by application_id + check_type).
"""

from __future__ import annotations

from confluent_kafka import Consumer, Producer

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
