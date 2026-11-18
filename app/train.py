import argparse
import json
import time

from app.model import MODEL_DIR, publish, train


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    if args.bootstrap and (MODEL_DIR / "current.json").exists():
        print("Existing model preserved")
        return
    model = train(args.seed if args.seed is not None else time.time_ns() % (2 ** 32))
    publish(model)
    print(json.dumps(model, indent=2))


if __name__ == "__main__":
    main()
