import argparse
import json
import os
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["normal", "fraud", "paused"])
parser.add_argument("--tps", type=float, default=10)
args = parser.parse_args()
if not 0 < args.tps <= 100:
    parser.error("tps must be between 0 and 100")
path = Path("/control/scenario.tmp")
path.write_text(json.dumps({"mode": args.mode, "tps": args.tps}))
os.replace(path, path.with_name("scenario.json"))
print(f"Scenario: {args.mode}, target TPS: {args.tps}")
