import json
import logging
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from app.common import consumer, now, producer, send
from app.model import ModelStore, amount_of, event_time

TOTAL = Counter("fraud_processed_total", "Successfully published scores")
FRAUD = Counter("fraud_flagged_total", "Flagged transactions")
LATENCY = Histogram("fraud_processing_seconds", "Scoring and Kafka publication time", buckets=(.001, .005, .01, .025, .05, .1, .25, .5, 1, 5))
SCORES = Histogram("fraud_score", "Predicted fraud probability", buckets=tuple(i / 20 for i in range(21)))
RATIO = Gauge("fraud_ratio", "Fraud share since process start")
LAST = Gauge("fraud_last_processed_timestamp_seconds", "Time of last successfully published score")
AGE = Histogram("fraud_event_age_seconds", "Event age at score publication", buckets=(.05, .1, .25, .5, 1, 2, 5, 10, 30, 60))
ERRORS = Counter("fraud_errors_total", "Processing failures", ["stage"])
UPDATES = Counter("fraud_model_updates_total", "Hot model switches", ["version"])
LOADED = Gauge("fraud_model_loaded_timestamp_seconds", "Model activation time", ["version"])
ACTIVE = Gauge("fraud_model_active", "Currently active model", ["version"])
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def main():
    start_http_server(8000)
    store = ModelStore()
    store.refresh()
    ACTIVE.labels(store.model["version"]).set(1)
    UPDATES.labels(store.model["version"]).inc(0)
    LOADED.labels(store.model["version"]).set(0)
    for stage in ("model_reload", "validation"):
        ERRORS.labels(stage).inc(0)
    LAST.set(time.time())
    incoming = consumer("fraud-scorer", "transactions")
    outgoing = producer()
    total = flagged = 0
    while True:
        old_version = store.model["version"]
        try:
            if store.refresh():
                version = store.model["version"]
                ACTIVE.labels(old_version).set(0)
                ACTIVE.labels(version).set(1)
                UPDATES.labels(version).inc()
                LOADED.labels(version).set(time.time())
                logging.info("Activated model %s -> %s", old_version, version)
        except (OSError, ValueError, KeyError, TypeError):
            ERRORS.labels("model_reload").inc()
            logging.exception("Keeping previous model")
        message = incoming.poll(0.2)
        if message is None:
            continue
        if message.error():
            raise RuntimeError(message.error())
        started = time.perf_counter()
        try:
            payload = json.loads(message.value())
            data = payload["data"]
            score = store.score(data)
            created_at = event_time(data["transaction_time"])
            if not isinstance(payload["transaction_id"], str) or not payload["transaction_id"]:
                raise ValueError("Invalid transaction_id")
            result = {
                "transaction_id": payload["transaction_id"], "score": score,
                "fraud_flag": int(score >= store.model["threshold"]),
                "model_version": store.model["version"], "scored_at": now(),
                "transaction_time": created_at.isoformat(), "amt": amount_of(data),
                "us_state": str(data["us_state"]), "merch": str(data["merch"]), "cat_id": str(data["cat_id"]),
            }
        except (ValueError, TypeError, KeyError):
            ERRORS.labels("validation").inc()
            logging.exception("Invalid transaction sent to dead letter topic")
            send(outgoing, "transactions_dlq", {"raw": message.value().decode(errors="replace")}, str(message.offset()))
            incoming.commit(message=message, asynchronous=False)
            continue
        send(outgoing, "scores", result, result["transaction_id"])
        incoming.commit(message=message, asynchronous=False)
        total += 1
        flagged += result["fraud_flag"]
        TOTAL.inc()
        FRAUD.inc(result["fraud_flag"])
        RATIO.set(flagged / total)
        LATENCY.observe(time.perf_counter() - started)
        SCORES.observe(score)
        AGE.observe(max(0, time.time() - created_at.timestamp()))
        LAST.set(time.time())


if __name__ == "__main__":
    main()
