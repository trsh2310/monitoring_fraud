import json
import random
import tempfile
import unittest
from pathlib import Path

from app.model import ModelStore, features, publish, sample, train


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = train(42)

    def test_probability_and_risk(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            publish(self.model, directory)
            store = ModelStore(directory)
            self.assertFalse(store.refresh())
            rng = random.Random(23)
            safe = [store.score(sample(rng)) for _ in range(100)]
            risky = [store.score(sample(rng, True)) for _ in range(100)]
            self.assertTrue(all(0 <= value <= 1 for value in safe + risky))
            self.assertGreater(sum(risky) / 100, 0.9)
            self.assertLess(sum(safe) / 100, 0.35)

    def test_hot_reload_and_invalid_model(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            publish(self.model, directory)
            store = ModelStore(directory)
            store.refresh()
            updated = {**self.model, "version": "next-version", "intercept": -2.0}
            publish(updated, directory)
            self.assertTrue(store.refresh())
            self.assertEqual(store.model["version"], "next-version")
            self.assertFalse(store.refresh())
            (directory / "current.json").write_text(json.dumps({**updated, "weights": []}))
            with self.assertRaises(ValueError):
                store.refresh()
            self.assertEqual(store.model, updated)

    def test_invalid_amount(self):
        row = sample(random.Random(4))
        for value in [-1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                features({**row, "amount": value})

    def test_previous_transaction_format(self):
        row = {"amount": 50, "transaction_time": "2026-11-11 14:30",
               "lat": 40.0, "lon": -74.0, "merchant_lat": 40.0, "merchant_lon": -74.0,
               "us_state": "NY", "merch": "market", "cat_id": "grocery"}
        self.assertEqual(features(row)[1:], [0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
