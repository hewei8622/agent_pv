"""Private source schedule validation; no graphics, policies or empirical claim."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from pv_sim.config import Config, load_config
from pv_sim.scene import Scene
from pv_sim.sensors import build_public_task

ROOT = Path(__file__).resolve().parents[2]


def configured(schedule):
    raw = json.loads(load_config(ROOT / "configs/pilot.toml").canonical_json())
    raw["source_schedule"] = schedule
    return Config.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("name", ["pilot.toml", "dev.toml"])
def test_absent_schedule_preserves_existing_canonical_config(name):
    base = load_config(ROOT / "configs" / name)
    assert base.source_schedule is None
    assert "source_schedule" not in json.loads(base.canonical_json())
    raw = json.loads(base.canonical_json())
    raw["source_schedule"] = None
    assert Config.model_validate_json(json.dumps(raw)).sha256() == base.sha256()
    assert base.source_dni_at_tick(0) == base.source_dni_at_tick(30000) == 800


def test_private_schedule_roundtrip_right_continuity_and_public_boundary():
    schedule = [{"time_s": 2.0, "dni_w_m2": 400.0}, {"time_s": 3.0, "dni_w_m2": 0.0}]
    config = configured(schedule)
    assert Config.model_validate_json(config.canonical_json()) == config
    assert config.sha256() != configured(None).sha256()
    assert [config.source_dni_at_tick(t) for t in (0, 999, 1000, 1499, 1500, 30000)] == [
        800, 800, 400, 400, 0, 0
    ]
    assert json.loads(config.canonical_json())["source_schedule"] == schedule
    assert build_public_task(config, "opaque") == build_public_task(configured(None), "opaque")
    with pytest.raises(ValidationError, match="frozen"):
        config.source_schedule[0].dni_w_m2 = 600
    with pytest.raises(ValidationError, match="frozen"):
        config.source_schedule = ()


@pytest.mark.parametrize(
    "schedule",
    [
        [],
        [{"time_s": 0.0, "dni_w_m2": 400}],
        [{"time_s": -2.0, "dni_w_m2": 400}],
        [{"time_s": 1e-320, "dni_w_m2": 400}],
        [{"time_s": 2.001, "dni_w_m2": 400}],
        [{"time_s": 60.0, "dni_w_m2": 400}],
        [{"time_s": 1e308, "dni_w_m2": 400}],
        [{"time_s": float("inf"), "dni_w_m2": 400}],
        [{"time_s": float("nan"), "dni_w_m2": 400}],
        [{"time_s": True, "dni_w_m2": 400}],
        [{"time_s": "2.0", "dni_w_m2": 400}],
        [{"time_s": 2.0, "dni_w_m2": -1}],
        [{"time_s": 2.0, "dni_w_m2": 1201}],
        [{"time_s": 2.0, "dni_w_m2": float("inf")}],
        [{"time_s": 2.0, "dni_w_m2": float("nan")}],
        [{"time_s": 2.0, "dni_w_m2": True}],
        [{"time_s": 2.0, "dni_w_m2": 400, "dhi_w_m2": 50}],
        [{"time_s": 2.0, "dni_w_m2": 400}, {"time_s": 2.0, "dni_w_m2": 300}],
        [{"time_s": 3.0, "dni_w_m2": 400}, {"time_s": 2.0, "dni_w_m2": 300}],
    ],
)
def test_invalid_schedule_is_rejected(schedule):
    with pytest.raises(ValidationError):
        configured(schedule)


@pytest.mark.parametrize("tick", [-1, 0.5, True, float("inf")])
def test_source_lookup_requires_integer_tick(tick):
    with pytest.raises(ValueError, match="tick"):
        configured(None).source_dni_at_tick(tick)


def test_scene_magnitude_update_preserves_geometry_and_other_optics():
    before = Scene.from_config(configured(None))
    after = before.with_source_dni(400)
    assert before.source.dni_w_m2 == 800 and after.source.dni_w_m2 == 400
    assert before.cells is after.cells
    assert before.source.direction == after.source.direction
    assert before.source.dhi_w_m2 == after.source.dhi_w_m2 == 100
    assert before.source.reflected_w_m2 == after.source.reflected_w_m2 == 0
    assert before.reference_position_m == after.reference_position_m
    assert before.screen == after.screen
    with pytest.raises(FrozenInstanceError):
        after.source.dni_w_m2 = 500


@pytest.mark.parametrize("dni", [-1, 1201, True, "400", float("nan"), float("inf")])
def test_scene_magnitude_rejects_invalid_values(dni):
    with pytest.raises(ValueError, match="DNI"):
        Scene.from_config(configured(None)).with_source_dni(dni)
