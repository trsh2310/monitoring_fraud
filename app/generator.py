import json
import logging
import random
import time
import uuid
from pathlib import Path

from app.common import now, producer, send
from app.model import sample

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def main():
    client = producer()
    rng = random.Random()
    control = Path("/control/scenario.json")
    count = 0
    while True:
        config = json.loads(control.read_text()) if control.exists() else {"mode": "normal", "tps": 10}
        if config["mode"] == "paused":
            time.sleep(0.2)
            continue
        started = time.monotonic()
        data = sample(rng, config["mode"] == "fraud" or rng.random() < 0.04)
        data["transaction_time"] = now()
        key = str(uuid.uuid4())
        send(client, "transactions", {"transaction_id": key, "data": data}, key)
        count += 1
        if count % 100 == 0:
            logging.info("Published %s transactions, mode=%s", count, config["mode"])
        time.sleep(max(0, 1 / config["tps"] - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
