import json
import math
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATES = ["CA", "NY", "TX", "FL", "WA"]
MERCHANTS = ["market", "travel", "electronics", "fuel", "cafe"]
CATEGORIES = ["grocery", "travel", "electronics", "fuel", "food"]
FEATURES = ["log_amount", "night", "distance", "electronics"]
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/models"))


def sample(rng, risky=False):
    category = rng.choice(CATEGORIES)
    return {
        "amount": round(rng.uniform(900, 2200) if risky else rng.lognormvariate(3.7, 0.9), 2),
        "hour": rng.randrange(0, 5) if risky else rng.randrange(24),
        "distance_km": rng.uniform(400, 1000) if risky else rng.expovariate(1 / 25),
        "us_state": rng.choice(STATES),
        "merch": MERCHANTS[CATEGORIES.index(category)],
        "cat_id": category,
    }


def event_time(value):
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def amount_of(data):
    return float(data["amount"] if "amount" in data else data["amt"])


def distance_of(data):
    if "distance_km" in data:
        return float(data["distance_km"])
    coords = [float(data[key]) for key in ("lat", "lon", "merchant_lat", "merchant_lon")]
    for value, limit in zip(coords, (90, 180, 90, 180)):
        if not math.isfinite(value) or abs(value) > limit:
            raise ValueError("Invalid coordinates")
    lat1, lon1, lat2, lon2 = map(math.radians, coords)
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, a))))


def features(data):
    amount = amount_of(data)
    distance = distance_of(data)
    hour = int(data["hour"]) if "hour" in data else event_time(data["transaction_time"]).hour
    if not math.isfinite(amount) or not math.isfinite(distance) or amount < 0 or distance < 0 or not 0 <= hour < 24:
        raise ValueError("Invalid transaction features")
    return [math.log1p(amount), float(hour < 5), distance / 100, float(data["cat_id"] == "electronics")]


def probability(weights, intercept, values):
    z = max(-700, min(700, intercept + sum(w * x for w, x in zip(weights, values))))
    return 1 / (1 + math.exp(-z))


def train(seed=42):
    from sklearn.linear_model import LogisticRegression

    rng = random.Random(seed)
    rows = [features(sample(rng, rng.random() < 0.12)) for _ in range(12000)]
    labels = [int(rng.random() < probability([1.15, 1.0, 0.75, 0.35], -8.2, row)) for row in rows]
    estimator = LogisticRegression(max_iter=500, random_state=seed).fit(rows, labels)
    return {
        "version": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8],
        "features": FEATURES,
        "weights": estimator.coef_[0].tolist(),
        "intercept": float(estimator.intercept_[0]),
        "threshold": 0.5,
        "seed": seed,
        "training_rows": len(rows),
    }


def validate(model):
    if model["features"] != FEATURES or len(model["weights"]) != len(FEATURES):
        raise ValueError("Incompatible model features")
    if not isinstance(model["version"], str) or not model["version"]:
        raise ValueError("Empty version")
    if not all(math.isfinite(x) for x in [*model["weights"], model["intercept"], model["threshold"]]):
        raise ValueError("Invalid model coefficients")
    if not 0 < model["threshold"] < 1:
        raise ValueError("Invalid threshold")
    return model


def publish(model, directory=MODEL_DIR):
    validate(model)
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f".{uuid.uuid4().hex}.json"
    staging.write_text(json.dumps(model, indent=2))
    os.replace(staging, directory / "current.json")


class ModelStore:
    def __init__(self, directory=MODEL_DIR):
        self.path = directory / "current.json"
        self.model = None
        self.signature = None

    def refresh(self):
        stat = self.path.stat()
        signature = (stat.st_mtime_ns, stat.st_ino, stat.st_size)
        if signature == self.signature:
            return False
        candidate = validate(json.loads(self.path.read_text()))
        changed = self.model is not None and candidate["version"] != self.model["version"]
        self.model = candidate
        self.signature = signature
        return changed

    def score(self, data):
        return probability(self.model["weights"], self.model["intercept"], features(data))
