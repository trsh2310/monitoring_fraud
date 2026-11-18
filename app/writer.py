import json
import logging
import os
import time

import psycopg2
from prometheus_client import Counter, Histogram, start_http_server

from app.common import consumer

TOTAL = Counter("writer_scores_total", "New scores committed to PostgreSQL")
FRAUD = Counter("writer_fraud_total", "New flagged scores committed to PostgreSQL")
LATENCY = Histogram("writer_write_seconds", "Database transaction duration", buckets=(.001, .005, .01, .025, .05, .1, .25, .5, 1, 5))
SCORES = Histogram("writer_score", "Persisted score distribution", buckets=tuple(i / 20 for i in range(21)))
ERRORS = Counter("writer_errors_total", "Database write failures")
DUPLICATES = Counter("writer_duplicates_total", "Replayed scores ignored")
SQL = """
INSERT INTO scores (transaction_id, score, fraud_flag, model_version, transaction_time,
                    scored_at, amt, us_state, merch, cat_id)
VALUES (%(transaction_id)s, %(score)s, %(fraud_flag)s, %(model_version)s, %(transaction_time)s,
        %(scored_at)s, %(amt)s, %(us_state)s, %(merch)s, %(cat_id)s)
ON CONFLICT (transaction_id) DO NOTHING RETURNING transaction_id
"""
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def main():
    start_http_server(8001)
    incoming = consumer("scores-writer", "scores")
    connection = psycopg2.connect(os.environ["DATABASE_URL"])
    while True:
        message = incoming.poll(1)
        if message is None:
            continue
        if message.error():
            raise RuntimeError(message.error())
        data = json.loads(message.value())
        started = time.perf_counter()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(SQL, data)
                    inserted = cursor.fetchone() is not None
        except psycopg2.Error:
            ERRORS.inc()
            logging.exception("Write failed; offset stays uncommitted")
            raise
        LATENCY.observe(time.perf_counter() - started)
        if inserted:
            TOTAL.inc()
            FRAUD.inc(data["fraud_flag"])
            SCORES.observe(data["score"])
        else:
            DUPLICATES.inc()
        incoming.commit(message=message, asynchronous=False)


if __name__ == "__main__":
    main()
