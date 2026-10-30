"""Sensor projection tests, not a fresh renderer invocation or integrated pilot."""

import base64
import dataclasses
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from pv_sim.config import Config, load_config
from pv_sim.contracts import Observation, RGBSample, validate_observation_context
from pv_sim.engine import DynamicsSnapshot
from pv_sim.pv import OperatingPoint
from pv_sim.sensors import (
    build_public_task,
    make_encoder_sample,
    make_rgb_sample,
    make_scalar_samples,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config():
    return load_config(ROOT / "configs/pilot.toml")


@pytest.fixture
def captured_rgb():
    """Known real M0 frame used only as an encoding fixture; provenance is retained."""
    path = ROOT / "tests/fixtures/m0_agent_rgb.png"
    provenance = json.loads(path.with_suffix(".provenance.json").read_text())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == provenance["sha256"]
    with Image.open(path) as image:
        return np.asarray(image).copy()


@pytest.fixture
def snapshot():
    # Public projection fixture, deliberately not a MuJoCo execution claim.
    return DynamicsSnapshot(
        tick=75,
        time_s=0.15,
        q=(0.02, 0.1, -0.2),
        qdot=(0.03, 0.04, -0.05),
        camera_position_m=(8.0, 9.0, 10.0),
        camera_rotation=tuple(float(i) for i in range(9)),
        actuator_work_j=123.0,
        setpoint=(0.1, 0.2, 0.3),
        setpoint_rate=(0.4, 0.5, 0.6),
        actuator_force=(1.0, 2.0, 3.0),
    )


def test_task_projection_has_nominal_intrinsics_and_no_help(config):
    task = build_public_task(config, "episode_opaque")
    assert set(task.sensors) == {
        "voltage_v",
        "current_a",
        "temperature_c",
        "reference_w_m2",
        "encoders",
        "rgb",
    }
    assert set(task.available_actions) == {
        "move_camera",
        "set_voltage",
        "probe_voltage",
        "capture_rgb",
        "wait",
        "safe_stop",
        "finish",
    }
    assert task.available_help == ()
    assert task.allowed_adaptation == "none"
    assert "uninformed" in task.knowledge_condition
    calibration = task.nominal_calibration
    k = np.asarray(calibration.k).reshape(3, 3)
    focal = 240 / math.tan(math.pi / 8)
    np.testing.assert_allclose(k, ((focal, 0, 319.5), (0, focal, 239.5), (0, 0, 1)))
    # Homogeneous camera coordinates project to the principal point on the optical axis.
    pixel = k @ np.array((0.0, 0.0, 2.0))
    np.testing.assert_allclose(pixel[:2] / pixel[2], (319.5, 239.5))
    assert calibration.home_position_m == (0.0, -0.45, 0.35)
    assert calibration.camera_axes == "x_right_y_up_minus_z_forward"
    assert calibration.pixel_convention == "top_left_center_0_0_x_right_y_down"


def test_task_projection_is_independent_of_private_world_values(config):
    fields = config.model_dump()
    fields["private_world"].update(
        dni_w_m2=487.0, series_resistance_ohm=0.37, initial_temperature_c=41.0
    )
    changed = Config.model_validate(fields)
    assert build_public_task(config, "opaque") == build_public_task(changed, "opaque")
    public = build_public_task(changed, "opaque").model_dump_json()
    for forbidden in (
        "private_world",
        "series_resistance",
        "dni_w_m2",
        "initial_temperature",
        "seed",
        "scenario_family",
        "true_pose",
        "open_circuit_voltage",
    ):
        assert forbidden not in public


def test_numeric_core_task_explicitly_withholds_rgb(config):
    task = build_public_task(config, "core_test", enable_rendering=False)
    assert "rgb" not in task.sensors and "capture_rgb" not in task.available_actions
    assert "move_camera" in task.available_actions
    assert "core-test/numeric-only" in task.knowledge_condition
    assert "not an integrated RGB pilot" in task.knowledge_condition
    assert "request_help" not in task.available_actions


def test_scalar_capture_clock_and_nominal_uncertainty_are_preserved(config):
    point = OperatingPoint(1.8, 0.7, 1.26, 4.8, "generating")
    samples = make_scalar_samples(config, point, 28.0, 812.0, 123)
    assert tuple(s.channel for s in samples) == (
        "voltage_v",
        "current_a",
        "temperature_c",
        "reference_w_m2",
    )
    assert tuple(s.value for s in samples) == (1.8, 0.7, 28.0, 812.0)
    assert tuple(s.sigma for s in samples) == (0.01, 0.005, 0.2, 5.0)
    assert all(s.t_capture_s == 123 * 0.002 for s in samples)
    assert all(s.t_deliver_s == 133 * 0.002 for s in samples)
    assert all(s.validity == "valid" for s in samples)
    assert make_scalar_samples(config, point, 28.0, 812.0, 123) == samples
    assert all("open_circuit" not in s.model_dump_json() for s in samples)
    with pytest.raises(ValidationError):
        samples[0].value = 4.0


def test_encoder_uses_snapshot_tick_and_only_allowed_coordinates(config, snapshot):
    sample = make_encoder_sample(config, snapshot)
    assert (sample.slide_m, sample.yaw_rad, sample.pitch_rad) == snapshot.q
    assert (sample.slide_rate_m_s, sample.yaw_rate_rad_s, sample.pitch_rate_rad_s) == snapshot.qdot
    assert sample.t_capture_s == 75 * 0.002
    assert sample.t_deliver_s == 80 * 0.002
    assert sample.sigma.slide_m == 0.0005 and sample.sigma.yaw_rad == 0.001
    for forbidden in ("camera_position", "camera_rotation", "actuator", "setpoint"):
        assert forbidden not in sample.model_dump_json()
    with pytest.raises(ValueError, match="integer tick"):
        make_encoder_sample(config, dataclasses.replace(snapshot, time_s=0.151))


def test_rgb_encodes_supplied_real_fixture_and_exact_exposure_ticks(config, captured_rgb):
    sample = make_rgb_sample(config, captured_rgb, "frame_opaque", 500)
    assert sample.t_start_s == 500 * 0.002
    assert sample.t_capture_s == 503 * 0.002
    assert sample.t_end_s == 506 * 0.002
    assert sample.t_deliver_s == 556 * 0.002
    assert sample.exposure.duration_s == 0.012
    assert RGBSample.model_validate_json(sample.model_dump_json()) == sample
    with Image.open(io.BytesIO(base64.b64decode(sample.png_base64))) as decoded:
        np.testing.assert_array_equal(np.asarray(decoded), captured_rgb)
        assert not decoded.info
    # Later changes to the caller's array cannot change the saved sensor snapshot.
    previous = sample.model_dump_json()
    captured_rgb[:] = 0
    assert sample.model_dump_json() == previous
    for forbidden in ("private_path", "true_pose", "mask", "depth"):
        assert forbidden not in sample.model_dump_json()


def test_samples_validate_against_the_advertised_task(config, snapshot, captured_rgb):
    task = build_public_task(config, "episode_opaque")
    point = OperatingPoint(1.8, 0.7, 1.26, 4.8, "generating")
    observation = Observation(
        schema_version="1.0",
        episode_id=task.episode_id,
        sequence_id=0,
        t_deliver_s=1.112,
        scalars=make_scalar_samples(config, point, 28.0, 812.0, 75),
        encoders=(make_encoder_sample(config, snapshot),),
        rgb=(make_rgb_sample(config, captured_rgb, "frame_opaque", 500),),
        feedback=(),
        remaining_budgets=task.budgets,
        terminal=False,
        terminal_reason=None,
    )
    validate_observation_context(observation, task)
    numeric_task = build_public_task(config, task.episode_id, enable_rendering=False)
    with pytest.raises(ValueError, match="unadvertised RGB"):
        validate_observation_context(observation, numeric_task)


@pytest.mark.parametrize("bad_tick", [-1, 0.5, True, "1"])
def test_invalid_capture_tick_is_rejected(config, bad_tick):
    point = OperatingPoint(1.8, 0.7, 1.26, 4.8, "generating")
    with pytest.raises(ValueError, match="nonnegative integer"):
        make_scalar_samples(config, point, 28.0, 812.0, bad_tick)


@pytest.mark.parametrize(
    "shape,dtype", [((480, 640, 4), np.uint8), ((480, 640, 3), float), ((1, 1, 3), np.uint8)]
)
def test_wrong_rgb_format_is_rejected_without_coercion(config, shape, dtype):
    with pytest.raises(ValueError, match="uint8 RGB"):
        make_rgb_sample(config, np.zeros(shape, dtype=dtype), "frame_opaque", 0)
