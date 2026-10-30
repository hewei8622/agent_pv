"""Export investigation/1.0 schemas, or check drift without changing any file."""

import argparse
import json
from pathlib import Path

from pv_sim.investigation import CHOICE_ADAPTER, AgentContext, InvestigationTranscript


def schemas() -> dict[str, dict]:
    return {
        "agent_context": AgentContext.model_json_schema(),
        "investigation_choice": CHOICE_ADAPTER.json_schema(),
        "investigation_transcript": InvestigationTranscript.model_json_schema(),
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
    print("schema drift: " + ", ".join(mismatches) if mismatches else "investigation schemas match")
    return 4 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
