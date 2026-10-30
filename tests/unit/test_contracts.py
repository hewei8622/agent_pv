import ast
import base64
import copy
import io
import json
import math
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image, PngImagePlugin
from pydantic import ValidationError

from pv_sim.contracts import (
    ACTION_ADAPTER,
    Decision,
    Observation,
    Prediction,
    PublicTask,
    RGBSample,
    ScalarSample,
    validate_decision_context,
    validate_observation_context,
)


def wire(model, payload):
    return model.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "kind,fields",
    [
        ("move_camera", dict(slide_m=0.15, yaw_rad=0.0, pitch_rad=0.0, capture_after_settle=True)),
        ("set_voltage", dict(voltage_v=1.8)),
        ("probe_voltage", dict(voltages_v=[0.8, 1.8, 3.0], dwell_s=0.5)),
        ("capture_rgb", {}),
        ("wait", dict(duration_s=0.5)),
        ("request_help", dict(measurement="rear_inspection")),
        ("safe_stop", {}),
        ("finish", dict(resolution="unresolved")),
    ],
)
def test_all_action_variants_roundtrip(kind, fields):
    raw = dict(schema_version="1.0", action_id=1, timeout_s=8.0, kind=kind, **fields)
    result = ACTION_ADAPTER.validate_json(json.dumps(raw))
    assert json.loads(result.model_dump_json()) == raw
    assert ACTION_ADAPTER.validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0"),
        ("action_id", 0),
        ("action_id", True),
        ("action_id", 1.5),
        ("action_id", "1"),
        ("kind", "execute_python"),
        ("timeout_s", 0),
        ("timeout_s", 15.01),
        ("slide_m", 0.151),
        ("slide_m", -0.151),
        ("slide_m", "0.1"),
        ("slide_m", True),
        ("yaw_rad", math.pi / 4 + 1e-8),
        ("pitch_rad", -math.pi / 6 - 1e-8),
        ("slide_m", float("nan")),
        ("yaw_rad", float("inf")),
        ("pitch_rad", -float("inf")),
        ("capture_after_settle", 1),
        ("capture_after_settle", "true"),
        ("filename", "/private/canary"),
        ("true_pose", [0, 0, 0]),
        ("units", "cm"),
    ],
)
def test_malformed_action_rejected(action, field, value):
    action[field] = value
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_json(json.dumps(action))


@pytest.mark.parametrize(
    "voltages,dwell",
    [
        ([], 0.5),
        ([1] * 4, 0.5),
        ([0.19], 0.5),
        ([4.01], 0.5),
        ([1.0], 0.19),
        ([1.0], 2.01),
        (["1.8"], 0.5),
        ([float("nan")], 0.5),
    ],
)
def test_bad_probe(voltages, dwell):
    raw = dict(
        schema_version="1.0",
        action_id=1,
        kind="probe_voltage",
        timeout_s=8.0,
        voltages_v=voltages,
        dwell_s=dwell,
    )
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_json(json.dumps(raw))


def test_valid_records_and_deep_immutability(task, observation, decision):
    obs, dec = wire(Observation, observation), wire(Decision, decision)
    for record in (task, obs, dec):
        assert type(record).model_validate_json(record.model_dump_json()) == record
    with pytest.raises(ValidationError):
        dec.action.slide_m = 0
    with pytest.raises(TypeError):
        obs.scalars[0] = None
    with pytest.raises(ValidationError):
        obs.scalars[0].value = 0
    validate_decision_context(dec, task, (obs,))
    validate_observation_context(obs, task)


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", float("nan")),
        ("sigma", -1),
        ("value", None),
        ("t_deliver_s", -1),
        ("true_cell_irradiance", 900),
    ],
)
def test_bad_scalar(scalar, field, value):
    scalar[field] = value
    with pytest.raises(ValidationError):
        wire(ScalarSample, scalar)


def test_missing_and_stale_semantics(scalar):
    scalar.update(value=None, sigma=None, validity="missing")
    assert wire(ScalarSample, scalar).value is None
    scalar.update(value=0.0)
    with pytest.raises(ValidationError):
        wire(ScalarSample, scalar)
    scalar.update(value=1.8, validity="stale", t_deliver_s=5.0)
    sample = wire(ScalarSample, scalar)
    assert sample.t_deliver_s - sample.t_capture_s == 5.0
    scalar.update(t_capture_s=6.0)
    with pytest.raises(ValidationError):
        wire(ScalarSample, scalar)


@pytest.mark.parametrize(
    "key",
    [
        "seed",
        "scenario_family",
        "true_pose",
        "reward",
        "score",
        "masks",
        "future_events",
        "private_path",
    ],
)
def test_truth_fields_rejected_every_boundary(task, observation, decision, key):
    for model, raw in (
        (PublicTask, task.model_dump(mode="json")),
        (Observation, observation),
        (Decision, decision),
    ):
        raw = copy.deepcopy(raw)
        raw[key] = "CANARY_PRIVATE"
        with pytest.raises(ValidationError):
            wire(model, raw)


def test_absent_sensors_and_future_references_rejected(task, observation, decision):
    public = task.model_dump(mode="json")
    public["sensors"].remove("voltage_v")
    restricted = wire(PublicTask, public)
    with pytest.raises(ValueError, match="unadvertised"):
        validate_observation_context(wire(Observation, observation), restricted)
    decision["evidence_refs"] = [99]
    with pytest.raises(ValueError, match="past observation"):
        validate_decision_context(wire(Decision, decision), task, ())
    observation["scalars"][0]["t_deliver_s"] = 100
    with pytest.raises(ValidationError):
        wire(Observation, observation)


def test_unadvertised_actions_and_narrower_limits(task, decision):
    public = task.model_dump(mode="json")
    public["limits"]["slide_m"] = [0, 0]
    with pytest.raises(ValueError, match="advertised limits"):
        validate_decision_context(wire(Decision, decision), wire(PublicTask, public), ())
    public["available_actions"].remove("move_camera")
    with pytest.raises(ValueError, match="action unavailable"):
        validate_decision_context(wire(Decision, decision), wire(PublicTask, public), ())


def test_prediction_and_belief_validation(decision, task):
    prediction = dict(
        query_id="q1",
        action_id=1,
        channel="current_a",
        horizon_s=0.5,
        mean=0.3,
        sigma=0.01,
        status="predicted",
    )
    wire(Prediction, prediction)
    for field, bad in (
        ("sigma", 0),
        ("mean", float("nan")),
        ("interval_90", [2, 1]),
        ("status", "not_predictable"),
        ("channel", "true_irradiance"),
    ):
        with pytest.raises(ValidationError):
            wire(Prediction, {**prediction, field: bad})
    decision["hypothesis_probabilities"] = [
        dict(hypothesis="h_a", probability=0.6),
        dict(hypothesis="h_b", probability=0.4),
    ]
    validate_decision_context(wire(Decision, decision), task, ())
    decision["hypothesis_probabilities"][1]["probability"] = 0.5
    with pytest.raises(ValidationError):
        wire(Decision, decision)


def image_record(task, metadata=False):
    image = Image.new(
        "RGB", (640, 480), (30, 60, 90)
    )  # payload-validation fixture, not render evidence
    out = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("private_path", "CANARY_PRIVATE")
    image.save(out, format="PNG", pnginfo=info)
    return dict(
        frame_id="frame_opaque",
        camera_id="agent_rgb",
        width=640,
        height=480,
        encoding="png_rgb8",
        png_base64=base64.b64encode(out.getvalue()).decode(),
        calibration_id="nominal_v1",
        k=task.nominal_calibration.k,
        exposure=dict(duration_s=0.01, approximation="midpoint_snapshot"),
        t_start_s=0.0,
        t_capture_s=0.005,
        t_end_s=0.01,
        t_deliver_s=0.11,
        validity="valid",
    )


def test_png_payload_metadata_and_times(task):
    payload = image_record(task)
    wire(RGBSample, payload)
    with pytest.raises(ValidationError):
        wire(RGBSample, image_record(task, metadata=True))
    for field, bad in (
        ("png_base64", "not-base64"),
        ("png_base64", None),
        ("width", 320),
        ("t_capture_s", 0.006),
        ("t_deliver_s", 0.001),
    ):
        with pytest.raises(ValidationError):
            wire(RGBSample, {**payload, field: bad})


@settings(max_examples=100, derandomize=True, deadline=None)
@given(st.floats(min_value=-0.15, max_value=0.15, allow_nan=False, allow_infinity=False))
def test_valid_slide_property(slide):
    raw = dict(
        schema_version="1.0",
        action_id=1,
        kind="move_camera",
        timeout_s=8.0,
        slide_m=slide,
        yaw_rad=0.0,
        pitch_rad=0.0,
        capture_after_settle=False,
    )
    assert ACTION_ADAPTER.validate_json(json.dumps(raw)).slide_m == slide


def test_no_private_module_imports():
    root = Path(__file__).resolve().parents[2] / "src/pv_sim/contracts.py"
    tree = ast.parse(root.read_text())
    forbidden = {"env", "engine", "config", "evaluation", "scenarios", "calibration"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not forbidden.intersection((node.module or "").split("."))
        elif isinstance(node, ast.Import):
            assert all(not forbidden.intersection(x.name.split(".")) for x in node.names)
