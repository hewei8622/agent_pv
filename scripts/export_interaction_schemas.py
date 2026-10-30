"""Export the separate interaction/1.0 JSON schemas without changing legacy exports."""

import json
from pathlib import Path

from pv_sim.interaction import InteractionTranscript
from pv_sim.interaction_contracts import InformationReply, InteractionRequest

ROOT = Path(__file__).resolve().parents[1]


def main():
    models = {
        "interaction_request": InteractionRequest,
        "information_reply": InformationReply,
        "interaction_transcript": InteractionTranscript,
    }
    for name, model in models.items():
        (ROOT / "schemas" / f"{name}.schema.json").write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        )


if __name__ == "__main__":
    main()
