"""Export frozen public JSON Schemas, or check for drift without writing."""

import argparse
import json
from pathlib import Path

from pv_sim.config import Config
from pv_sim.contracts import ACTION_ADAPTER, Decision, Observation, PublicTask


def schemas() -> dict[str, dict]:
    return {
        "action": ACTION_ADAPTER.json_schema(),
        "public_task": PublicTask.model_json_schema(),
        "observation": Observation.model_json_schema(),
        "decision": Decision.model_json_schema(),
        "private_scenario": Config.model_json_schema(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "schemas"
    if not args.check:
        root.mkdir(exist_ok=True)
    mismatches = []
    for name, schema in schemas().items():
        content = json.dumps(schema, indent=2, sort_keys=True, allow_nan=False) + "\n"
        path = root / f"{name}.schema.json"
        if args.check:
            if not path.exists() or path.read_text() != content:
                mismatches.append(name)
        else:
            path.write_text(content)
    print("schema drift: " + ", ".join(mismatches) if mismatches else "public schemas match")
    return 4 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
