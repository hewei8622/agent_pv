import copy
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from pv_sim.config import Config, load_config

ROOT = Path(__file__).resolve().parents[2]


def test_complete_config_roundtrip(tmp_path):
    config = load_config(ROOT / "configs/pilot.toml")
    path = tmp_path / "config.json"
    path.write_text(config.canonical_json())
    assert load_config(path) == config
    assert load_config(path).sha256() == config.sha256()
    raw = json.loads(config.canonical_json())
    del raw["sensors"]["rgb_latency_s"]
    with pytest.raises(ValidationError):
        Config.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("camera", "width", "640"),
        ("camera", "width", True),
        ("camera", "slide_limits_m", [0.15, -0.15]),
        ("camera", "fovy_deg", 90),
        ("camera", "headlight", True),
        ("camera", "extra", 1),
        ("pv", "initial_voltage_v", 0.1),
        ("pv", "voltage_limits_v", [0.2, 9]),
        ("private_world", "dni_w_m2", 1201),
        ("private_world", "dhi_w_m2", -1),
        ("private_world", "ambient_temperature_c", 41),
        ("private_world", "source_direction", [0, 0, 2]),
        ("private_world", "cell_area_m2", 0.1),
        ("thermal", "heat_capacity_j_k", 0),
        ("thermal", "conductance_w_k", float("nan")),
        ("simulation", "dt_s", 0.001),
        ("sensors", "numeric_hz", 7),
        ("budgets", "rgb_frames", -1),
        ("budgets", "decisions", 2.5),
        ("pilot", "numeric_noise", True),
        ("pilot", "rgb_required", False),
    ],
)
def test_bad_config(section, field, value):
    raw = copy.deepcopy(tomllib.loads((ROOT / "configs/pilot.toml").read_text()))
    raw[section][field] = value
    with pytest.raises(ValidationError):
        Config.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("duration_s", [1e-15, 1e-12, 0.002, 0.006, 0.010, 0.014])
def test_exposure_without_positive_tick_aligned_midpoint_is_rejected(duration_s):
    raw = tomllib.loads((ROOT / "configs/pilot.toml").read_text())
    raw["sensors"]["rgb_exposure_s"] = duration_s
    with pytest.raises(ValidationError, match="exposure midpoint"):
        Config.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("duration_s", [0.004, 0.012, 0.020])
def test_exposure_with_tick_aligned_midpoint_is_accepted(duration_s):
    raw = tomllib.loads((ROOT / "configs/pilot.toml").read_text())
    raw["sensors"]["rgb_exposure_s"] = duration_s
    assert Config.model_validate_json(json.dumps(raw)).sensors.rgb_exposure_s == duration_s


def test_pilot_uses_authorized_12ms_exposure_and_2ms_tick():
    config = load_config(ROOT / "configs/pilot.toml")
    assert config.simulation.dt_s == 0.002
    assert config.sensors.rgb_exposure_s == 0.012


def test_cli_help_valid_and_invalid(tmp_path):
    command = [sys.executable, "-m", "pv_sim.cli"]
    help_result = subprocess.run(command + ["--help"], capture_output=True, text=True, timeout=10)
    assert help_result.returncode == 0
    assert "validate-config" in help_result.stdout
    result = subprocess.run(
        command + ["validate-config", "--config", "configs/pilot.toml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0 and "sha256=" in result.stdout
    path = tmp_path / "invalid.toml"
    path.write_text('private_secret = "CANARY_PRIVATE"')
    result = subprocess.run(
        command + ["validate-config", "--config", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "CANARY_PRIVATE" not in result.stderr and str(path) not in result.stderr
    assert subprocess.run(command + ["demo"], capture_output=True, timeout=10).returncode == 2


def test_generated_schemas_match():
    result = subprocess.run(
        [sys.executable, "scripts/export_schemas.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_explicitly_disabled_renderer_reports_block_not_success(tmp_path):
    # Deliberate negative test, not a renderer setup attempt. No fabricated success/skip.
    output = tmp_path / "disabled-renderer"
    result = subprocess.run(
        [sys.executable, "scripts/verify_environment.py", "--render", "--output", str(output)],
        cwd=ROOT,
        env={**os.environ, "MUJOCO_GL": "disable"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    report = json.loads((output / "environment.json").read_text())
    assert report["incomplete"] and report["checks"]["environment"] == "blocked"
    assert not (output / "agent_rgb.png").exists()
    assert (output / "failure.txt").exists()


def test_evidence_overwrite_refused(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "marker.txt"
    marker.write_text("retain original")
    result = subprocess.run(
        [sys.executable, "scripts/verify_environment.py", "--render", "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2 and marker.read_text() == "retain original"
