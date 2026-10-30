"""Frozen limits and public schema exports must match the running interface."""

import json
from pathlib import Path

import pytest

from pv_sim.interaction import InteractionTranscript
from pv_sim.interaction_contracts import InformationReply, InteractionLimits, InteractionRequest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name,model",
    [
        ("interaction_request", InteractionRequest),
        ("information_reply", InformationReply),
        ("interaction_transcript", InteractionTranscript),
    ],
)
def test_interaction_export_matches_wire_model(name, model):
    assert (
        json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        == model.model_json_schema()
    )


def test_experiment_protocol_matches_runtime_caps():
    frozen = InteractionLimits.model_validate_json(
        (ROOT / "configs/interaction_protocol.json").read_text()
    )
    assert frozen == InteractionLimits()
