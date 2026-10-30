"""Private fixture validation and unchanged historical M1 configuration digest."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pv_sim.config import Config, load_config

ROOT = Path(__file__).resolve().parents[2]


def test_historical_m1_canonical_config_digest_is_unchanged():
    config = load_config(ROOT / "configs/pilot.toml")
    assert "m2" not in json.loads(config.canonical_json())
    # Accepted manifest's canonical digest (file bytes additionally have a newline).
    assert config.sha256() == "1e1bdbb3d236c7d891a5f73e70a355c4ca0e27732209b32120cc85d0d76c0e4c"


def test_development_config_expands_and_roundtrips_without_public_fault_fields():
    config = load_config(ROOT / "configs/dev.toml")
    assert config.m2 is not None
    assert config.pilot.numeric_noise and config.pilot.encoder_noise
    assert Config.model_validate_json(config.canonical_json()) == config
    from pv_sim.sensors import build_public_task

    public = build_public_task(config, "opaque").model_dump_json()
    for private in ("dropout_probability", "m2", "load_drop_commands", "jitter_s"):
        assert f'"{private}"' not in public


@pytest.mark.parametrize(
    "patch",
    [
        {"sensing": {"rgb": {"jitter_s": 0.102}}},
        {"sensing": {"numeric": {"extra_delay_s": 0.001}}},
        {"sensing": {"encoder": {"stale_after_s": 0.001}}},
        {"sensing": {"rgb": {"dropout_probability": 1.1}}},
        {"sensing": {"numeric": {"extra_delay_s": float("nan")}}},
        {"sensing": {"rgb": {"dropout_probability": True}}},
        {"sensing": {"rgb": {"unknown": 1}}},
        {"actuation": {"load_drop_commands": [1, 1]}},
        {"actuation": {"move_stall_commands": [True]}},
        {"actuation": {"load_extra_delay_s": [[1, 0.001]]}},
        {"actuation": {"load_extra_delay_s": [[1, 0.1], [1, 0.2]]}},
        {"view": {"screen_half_width_m": 0.05}},
        {"view": {"rail_locked": 1}},
    ],
)
def test_invalid_private_fixture_rejected(patch):
    raw = json.loads(load_config(ROOT / "configs/pilot.toml").canonical_json())
    raw["pilot"]["actuator_failures"] = True
    raw["m2"] = patch
    with pytest.raises(ValidationError):
        Config.model_validate_json(json.dumps(raw))


def test_actuator_fixture_must_be_explicitly_enabled():
    raw = json.loads(load_config(ROOT / "configs/pilot.toml").canonical_json())
    raw["m2"] = {"actuation": {"load_drop_commands": [1]}}
    with pytest.raises(ValidationError, match="actuator_failures"):
        Config.model_validate_json(json.dumps(raw))
