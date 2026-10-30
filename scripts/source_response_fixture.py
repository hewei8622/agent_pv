"""Evaluator-only paired source fixture. It is not a policy or a public tool.

Real RGB is requested only with render=True. Core mode substitutes timed waits
for camera requests, preserving the physical timeline without inventing images.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image

from pv_sim.config import Config, load_config
from pv_sim.env import PVEnv

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "configs/source_response_protocol.json"


def protocol():
    return json.loads(PROTOCOL_PATH.read_text())


def fixture_config(changed):
    if type(changed) is not bool:
        raise ValueError("changed must be boolean")
    raw = load_config(ROOT / "configs/pilot.toml").model_dump(mode="json")
    expected = {
        "simulation": {"dt_s": 0.002, "decision_overhead_s": 0.2},
        "private_world": {
            "dni_w_m2": 800.0,
            "dhi_w_m2": 100.0,
            "source_direction": [0.0, 0.0, 1.0],
            "panel_normal": [0.0, 0.0, 1.0],
            "panel_size_m": [0.3, 0.2],
            "cell_area_m2": 0.0075,
            "transmission": [1.0] * 8,
            "series_resistance_ohm": 0.0,
            "ambient_temperature_c": 25.0,
            "initial_temperature_c": 25.0,
            "reflected_w_m2": 0.0,
        },
        "pv": {
            "initial_voltage_v": 1.8,
            "cells_per_substring": 4,
            "substrings_in_series": 2,
            "reference_irradiance_w_m2": 1000.0,
            "reference_temperature_c": 25.0,
            "isc_reference_a": 1.0,
            "isc_temperature_coefficient_per_k": 0.0005,
            "voc_reference_v": 0.6,
            "voc_temperature_coefficient_v_k": -0.002,
            "voc_log_irradiance_coefficient_v": 0.03,
        },
        "thermal": {"absorptance": 0.9, "heat_capacity_j_k": 30.0, "conductance_w_k": 0.6},
        "sensors": {"numeric_hz": 10.0, "numeric_latency_s": 0.02},
        "pilot": {"numeric_noise": False, "encoder_noise": False, "actuator_failures": False},
    }
    for group, fields in expected.items():
        for name, value in fields.items():
            if raw[group][name] != value:
                raise ValueError(f"frozen reference configuration changed: {group}.{name}")
    p = protocol()
    if (
        p["duration_s"],
        p["event_s"],
        p["initial_dni_w_m2"],
        p["changed_dni_w_m2"],
        p["dhi_w_m2"],
        p["voltage_v"],
        p["noise"],
    ) != (8.0, 2.0, 800.0, 400.0, 100.0, 1.8, False):
        raise ValueError("the frozen fixture changed; review and version the reference")
    raw["source_schedule"] = [{"time_s": 2.0, "dni_w_m2": 400.0}] if changed else None
    return Config.model_validate_json(json.dumps(raw))


class Trace:
    def __init__(self):
        self.rows, self.observations, self.actions, self.actuations = [], [], [], []

    def start(self, config, seed, task):
        self.config = config.model_dump(mode="json")
        self.config_hash = config.sha256()
        self.task = task.model_dump(mode="json")
        self.seed = seed

    def truth(self, row):
        self.rows.append(row)

    def observation(self, observation, *, tick):
        self.observations.append({"tick": tick, "payload": observation.model_dump(mode="json")})

    def action(self, action, tick):
        self.actions.append({"tick": tick, "payload": action})

    def actuation(self, payload, tick, *, action_id=None):
        self.actuations.append({"tick": tick, "action_id": action_id, "payload": payload})


def run_fixture(changed, *, render=False, trace=None):
    trace = trace if trace is not None else Trace()
    env = PVEnv(fixture_config(changed), enable_rendering=render, recorder=trace)
    try:
        env.reset(protocol()["seed"], episode_id="fixture_asset")
        # Frame 2 captures at1.906s and arrives at2.012s, across the source event.
        operations = [
            ("capture_rgb", {}),
            ("wait", {"duration_s": 1.168}),
            ("capture_rgb", {}),
            ("capture_rgb", {}),
            ("wait", {"duration_s": 3.288}),
            ("wait", {"duration_s": 1.8}),
        ]
        substitutions = {1: 0.112, 3: 0.112, 4: 0.3}
        for action_id, (kind, fields) in enumerate(operations, 1):
            if not render and kind == "capture_rgb":
                kind, fields = "wait", {"duration_s": substitutions[action_id]}
            observation = env.step(
                dict(
                    schema_version="1.0",
                    action_id=action_id,
                    kind=kind,
                    timeout_s=8.0,
                    **fields,
                )
            )
            if observation.feedback[-1].code != "completed":
                raise AssertionError(f"fixture action did not complete: {action_id}")
        if env.tick != 4000 or env.terminal_reason is not None:
            raise AssertionError("fixture duration or terminal state changed")
        return trace, asdict(env.ledger)
    finally:
        env.close()


def frames(trace):
    return [frame for obs in trace.observations for frame in obs["payload"]["rgb"]]


def pixels(frame):
    with Image.open(io.BytesIO(base64.b64decode(frame["png_base64"]))) as source:
        if source.size != (640, 480) or source.mode != "RGB":
            raise AssertionError("unexpected real camera image format")
        return np.asarray(source).copy()


def check_real_images(control, changed):
    a, b = frames(control), frames(changed)
    if len(a) != 3 or len(b) != 3:
        raise AssertionError("three new real images per fixture are required")
    expected_times = [(0.226, 0.332), (1.906, 2.012), (2.406, 2.512)]
    for group in (a, b):
        for frame, (capture, delivery) in zip(group, expected_times, strict=True):
            if abs(frame["t_capture_s"] - capture) > 1e-12:
                raise AssertionError("camera capture schedule changed")
            if abs(frame["t_deliver_s"] - delivery) > 1e-12 or frame["validity"] != "valid":
                raise AssertionError("camera delivery schedule changed")
    ac, bc = list(map(pixels, a)), list(map(pixels, b))
    for index in (1, 2):
        np.testing.assert_array_equal(ac[0], ac[index])
    for index in (0, 1):
        np.testing.assert_array_equal(ac[index], bc[index])
    # Fixed scene, source direction/material and pose: the real light is the sole change.
    decrease = float(ac[2].astype(float).mean() - bc[2].astype(float).mean())
    if decrease <= protocol()["tolerances"]["render_mean_decrease_code_values"]:
        raise AssertionError("real image does not show the expected source-light decrease")
    if float(bc[2].std()) <= 1.0:
        raise AssertionError("post-change image is blank")
    return {
        "images": 6,
        "unchanged_control_pixels_equal": True,
        "late_prechange_frame_preserved": True,
        "mean_brightness_decrease_code_values": decrease,
        "scope": "qualitative classic-renderer response; not calibrated radiometry",
    }


def write_trace(trace, public_dir, private_dir):
    public_dir.mkdir(parents=True, exist_ok=False)
    private_dir.mkdir(parents=True, exist_ok=False)
    (public_dir / "frames").mkdir()
    observations = json.loads(json.dumps(trace.observations))
    for obs in observations:
        for frame in obs["payload"]["rgb"]:
            raw = base64.b64decode(frame.pop("png_base64"))
            name = f"frames/{frame['frame_id']}.png"
            (public_dir / name).write_bytes(raw)
            frame.update(png_file=name, png_sha256=hashlib.sha256(raw).hexdigest())
    values = {
        public_dir / "task.json": trace.task,
        public_dir / "observations.json": observations,
        public_dir / "actions.json": trace.actions,
        private_dir / "config.json": trace.config,
        private_dir / "actuations.json": trace.actuations,
    }
    for path, value in values.items():
        path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    with (private_dir / "truth.jsonl").open("x") as file:
        for row in trace.rows:
            file.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
