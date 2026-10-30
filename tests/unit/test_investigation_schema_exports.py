"""Reviewable JSON schemas remain identical to the public runtime contracts."""

import json
from pathlib import Path

import pytest

from pv_sim.investigation import CHOICE_ADAPTER, AgentContext, InvestigationTranscript

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name,schema",
    [
        ("agent_context", AgentContext.model_json_schema()),
        ("investigation_choice", CHOICE_ADAPTER.json_schema()),
        ("investigation_transcript", InvestigationTranscript.model_json_schema()),
    ],
)
def test_investigation_export_matches_wire_model(name, schema):
    assert json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text()) == schema
