import json
import os
from datetime import datetime, timezone

from confluent_kafka import Consumer, Producer


def now():
    return datetime.now(timezone.utc).isoformat()


def consumer(group, topic):
    client = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        "group.id": group,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    client.subscribe([topic])
    return client


def producer():
    return Producer({
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        "enable.idempotence": True,
        "delivery.timeout.ms": 30000,
    })


def send(client, topic, value, key):
    errors = []
    client.produce(topic, key=key, value=json.dumps(value),
                   on_delivery=lambda error, message: errors.append(error) if error else None)
    if client.flush(35) or errors:
        raise RuntimeError(f"Kafka delivery failed: {errors}")
