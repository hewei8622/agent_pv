"""M2 deterministic sensor fixtures; no new renderer invocation or policy pilot.

The retained M0 PNG tests encoding/transport preservation only. It is not visual
evidence for the M2 gate, which requires separately captured desktop fixtures.
"""

import base64
import dataclasses
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pv_sim.config import Config, load_config
from pv_sim.contracts import EncoderSample, RGBSample, ScalarSample
from pv_sim.engine import DynamicsSnapshot
from pv_sim.pv import OperatingPoint
from pv_sim.scheduler import Scheduler
from pv_sim.sensors import (
    SensorModel,
    build_public_task,
    make_encoder_sample,
    make_rgb_sample,
    make_scalar_samples,
)

ROOT = Path(__file__).resolve().parents[2]
POINT = OperatingPoint(1.8, 0.7, 1.26, 4.8, "generating")


def condition(*, numeric_noise=False, encoder_noise=False, **profiles):
    raw = load_config(ROOT / "configs/pilot.toml").model_dump()
    raw["m2"] = {"sensing": profiles}
    raw["pilot"].update(numeric_noise=numeric_noise, encoder_noise=encoder_noise)
    return Config.model_validate(raw)


@pytest.fixture
def snapshot():
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


@pytest.fixture
def retained_rgb():
    path = ROOT / "tests/fixtures/m0_agent_rgb.png"
    provenance = json.loads(path.with_suffix(".provenance.json").read_text())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == provenance["sha256"]
    with Image.open(path) as image:
        return np.asarray(image).copy()


@pytest.mark.parametrize("with_m2", [False, True])
def test_disabled_conditions_preserve_m1_records_exactly(snapshot, retained_rgb, with_m2):
    config = condition() if with_m2 else load_config(ROOT / "configs/pilot.toml")
    sensors = SensorModel(config, 7)
    assert sensors.capture_scalars(POINT, 28.0, 812.0, 123) == make_scalar_samples(
        config, POINT, 28.0, 812.0, 123
    )
    assert sensors.capture_encoder(snapshot) == make_encoder_sample(config, snapshot)
    assert sensors.capture_rgb(retained_rgb, "fixture", 500) == make_rgb_sample(
        config, retained_rgb, "fixture", 500
    )


def test_noise_is_capture_indexed_and_independent_of_extra_actions_and_sensor_calls(snapshot):
    config = condition(numeric_noise=True, encoder_noise=True)
    first = SensorModel(config, 108)
    expected = first.capture_scalars(POINT, 28.0, 812.0, 1000)
    encoder_expected = first.capture_encoder(snapshot)
    for tick in (900, 0, 501, 999, 50, 1000):
        first.capture_scalars(POINT, 21.0, 100.0, tick)
        first.delivery_tick("rgb", tick + 3, end_tick=tick + 6)
        first.capture_encoder(dataclasses.replace(snapshot, tick=tick, time_s=tick * 0.002))
    assert first.capture_scalars(POINT, 28.0, 812.0, 1000) == expected
    assert first.capture_encoder(snapshot) == encoder_expected
    assert SensorModel(config, 108).capture_scalars(POINT, 28.0, 812.0, 1000) == expected
    assert SensorModel(config, 109).capture_scalars(POINT, 28.0, 812.0, 1000) != expected
    # Turning off another measurement stream cannot change encoder errors.
    changed = SensorModel(condition(encoder_noise=True), 108)
    assert changed.capture_encoder(snapshot) == encoder_expected


def test_gaussian_channel_noise_has_declared_scale_and_no_shared_channel_error():
    sensors = SensorModel(condition(numeric_noise=True), 20261017)
    means = np.array((1.8, 0.7, 28.0, 812.0))
    sigmas = np.array((0.01, 0.005, 0.2, 5.0))
    samples = np.array(
        [
            [s.value for s in sensors.capture_scalars(POINT, 28.0, 812.0, tick * 50)]
            for tick in range(4096)
        ]
    )
    errors = (samples - means) / sigmas
    # Fixed-seed engineering distribution checks, not empirical sensor accuracy.
    assert np.max(np.abs(errors.mean(axis=0))) < 0.08
    assert np.max(np.abs(errors.std(axis=0) - 1)) < 0.08
    correlation = np.corrcoef(errors, rowvar=False)
    assert np.max(np.abs(correlation - np.eye(4))) < 0.08
    sample = sensors.capture_scalars(POINT, 28.0, 812.0, 0)
    assert tuple(s.sigma for s in sample) == tuple(sigmas)
    assert all(s.validity == "valid" for s in sample)


def test_encoder_noise_uses_position_uncertainty_and_omits_undeclared_rates(snapshot):
    sensors = SensorModel(condition(encoder_noise=True), 108)
    sample = sensors.capture_encoder(snapshot)
    assert (sample.slide_m, sample.yaw_rad, sample.pitch_rad) != snapshot.q
    assert (sample.slide_rate_m_s, sample.yaw_rate_rad_s, sample.pitch_rate_rad_s) == (
        None,
        None,
        None,
    )
    assert sample.sigma.model_dump() == {"slide_m": 0.0005, "yaw_rad": 0.001, "pitch_rad": 0.001}
    assert sample.t_capture_s == 0.15 and sample.t_deliver_s == 0.16
    assert EncoderSample.model_validate_json(sample.model_dump_json()) == sample
    for private in ("camera_position", "camera_rotation", "actuator", "setpoint", "seed"):
        assert private not in sample.model_dump_json()


def test_encoder_errors_have_declared_independent_axis_scales(snapshot):
    sensors = SensorModel(condition(encoder_noise=True), 20261017)
    positions = []
    for index in range(4096):
        tick = index * 25
        sample = sensors.capture_encoder(
            dataclasses.replace(snapshot, tick=tick, time_s=tick * 0.002)
        )
        positions.append((sample.slide_m, sample.yaw_rad, sample.pitch_rad))
    errors = (np.asarray(positions) - snapshot.q) / np.array((0.0005, 0.001, 0.001))
    # The same fixed engineering checks as the scalar model, not calibration claims.
    assert np.max(np.abs(errors.mean(axis=0))) < 0.08
    assert np.max(np.abs(errors.std(axis=0) - 1)) < 0.08
    assert np.max(np.abs(np.corrcoef(errors, rowvar=False) - np.eye(3))) < 0.08


def test_no_clipping_to_actuation_bounds_is_invented():
    raw = condition(numeric_noise=True).model_dump()
    raw["sensors"]["voltage_sigma_v"] = 1000.0
    sensors = SensorModel(Config.model_validate(raw), 108)
    values = [sensors.capture_scalars(POINT, 28.0, 812.0, tick)[0].value for tick in range(20)]
    assert min(values) < 0.2 and max(values) > 4.0
    assert sensors.capture_scalars(POINT, 28.0, 812.0, 0)[0].validity == "valid"


def test_integer_jitter_is_bounded_inclusive_and_scalar_batch_stays_simultaneous():
    sensors = SensorModel(condition(numeric={"extra_delay_s": 0.004, "jitter_s": 0.008}), 44)
    offsets = set()
    for tick in range(256):
        samples = sensors.capture_scalars(POINT, 28.0, 812.0, tick)
        assert len({s.t_capture_s for s in samples}) == 1
        assert len({s.t_deliver_s for s in samples}) == 1
        delivery = sensors.delivery_tick("numeric", tick)
        assert samples[0].t_deliver_s == delivery * 0.002
        offsets.add(delivery - tick)
    # Base 10 ticks + two extra ticks, with every integer jitter in [-4,+4].
    assert offsets == set(range(8, 17))


@pytest.mark.parametrize(
    "kind,threshold,expected",
    [
        ("numeric", 0.020, "valid"),
        ("numeric", 0.018, "stale"),
        ("encoder", 0.010, "valid"),
        ("encoder", 0.008, "stale"),
        ("rgb", 0.106, "valid"),
        ("rgb", 0.104, "stale"),
    ],
)
def test_stale_threshold_compares_original_capture_age_strictly(
    snapshot, retained_rgb, kind, threshold, expected
):
    sensors = SensorModel(condition(**{kind: {"stale_after_s": threshold}}), 7)
    if kind == "numeric":
        sample = sensors.capture_scalars(POINT, 28.0, 812.0, 75)[0]
    elif kind == "encoder":
        sample = sensors.capture_encoder(snapshot)
    else:
        sample = sensors.capture_rgb(retained_rgb, "fixture", 72)
    assert sample.validity == expected
    assert sample.t_capture_s == 0.15


def test_dropout_retains_capture_metadata_and_nulls_all_values(snapshot, retained_rgb):
    profile = {"dropout_probability": 1.0, "extra_delay_s": 0.2, "stale_after_s": 0.002}
    config = condition(
        numeric_noise=True,
        encoder_noise=True,
        **dict.fromkeys(("numeric", "encoder", "rgb"), profile),
    )
    sensors = SensorModel(config, 108)
    scalar = sensors.capture_scalars(POINT, 28.0, 812.0, 75)
    assert all(s.validity == "missing" and s.value is None for s in scalar)
    assert all(s.t_capture_s == 0.15 and s.t_deliver_s == 0.37 for s in scalar)
    assert scalar[0].sigma == 0.01
    assert ScalarSample.model_validate_json(scalar[0].model_dump_json()) == scalar[0]
    encoder = sensors.capture_encoder(snapshot)
    assert encoder.validity == "missing"
    assert all(
        getattr(encoder, field) is None
        for field in (
            "slide_m",
            "yaw_rad",
            "pitch_rad",
            "slide_rate_m_s",
            "yaw_rate_rad_s",
            "pitch_rate_rad_s",
        )
    )
    assert encoder.t_capture_s == 0.15 and encoder.t_deliver_s == 0.36
    rgb = sensors.capture_rgb(retained_rgb, "fixture", 72)
    assert rgb.validity == "missing" and rgb.png_base64 is None
    assert (rgb.t_start_s, rgb.t_capture_s, rgb.t_end_s) == (72 * 0.002, 75 * 0.002, 78 * 0.002)
    assert rgb.t_deliver_s == 0.456 and rgb.exposure.duration_s == 0.012
    assert RGBSample.model_validate_json(rgb.model_dump_json()) == rgb


def test_dropout_schedule_and_jitter_use_independent_purposes():
    profile = {"dropout_probability": 0.25, "jitter_s": 0.010}
    sensors = SensorModel(condition(numeric=profile), 44)
    no_drop = SensorModel(condition(numeric={"jitter_s": 0.010}), 44)
    missing = 0
    for tick in range(1024):
        samples = sensors.capture_scalars(POINT, 28.0, 812.0, tick)
        assert len({s.validity for s in samples}) == 1
        assert samples[0].t_deliver_s == no_drop.delivery_tick("numeric", tick) * 0.002
        missing += samples[0].validity == "missing"
    assert abs(missing / 1024 - 0.25) < 0.06


def test_delayed_stale_rgb_queue_preserves_midpoint_pixels_and_all_times(retained_rgb):
    sensors = SensorModel(condition(rgb={"extra_delay_s": 0.2, "stale_after_s": 0.2}), 108)
    expected = retained_rgb.copy()
    sample = sensors.capture_rgb(retained_rgb, "fixture", 500)
    clock = Scheduler(0.002, tick=503)
    clock.enqueue(656, sample, event_kind="rgb")
    retained_rgb[:] = 0  # Later caller/world changes cannot alter the capture.
    clock.tick = 655
    assert clock.deliver() == ()
    clock.tick = 656
    (delivered,) = clock.deliver()
    assert delivered is sample and sample.validity == "stale"
    assert (sample.t_start_s, sample.t_capture_s, sample.t_end_s, sample.t_deliver_s) == (
        1.0,
        1.006,
        1.012,
        1.312,
    )
    with Image.open(io.BytesIO(base64.b64decode(sample.png_base64))) as image:
        np.testing.assert_array_equal(np.asarray(image), expected)
    assert RGBSample.model_validate_json(sample.model_dump_json()) == sample


def test_private_transport_config_does_not_enter_public_task():
    baseline = build_public_task(condition(), "opaque")
    changed = build_public_task(
        condition(
            numeric_noise=True,
            encoder_noise=True,
            rgb={"dropout_probability": 0.75, "extra_delay_s": 0.2},
        ),
        "opaque",
    )
    assert baseline == changed


@pytest.mark.parametrize("seed", [-1, True, 1.5, "1"])
def test_sensor_model_rejects_invalid_seed_even_with_noise_disabled(seed):
    with pytest.raises(ValueError, match="nonnegative integer"):
        SensorModel(condition(), seed)


@pytest.mark.parametrize(
    "kind,capture,end",
    [
        ("unknown", 1, None),
        ("rgb", 1, None),
        ("rgb", 2, 1),
        ("numeric", 1, 2),
    ],
)
def test_transport_rejects_ambiguous_or_nonchronological_timing(kind, capture, end):
    with pytest.raises(ValueError):
        SensorModel(condition(), 1).delivery_tick(kind, capture, end)
