"""Required real M2 camera delivery fixtures for the approved desktop context.

No saved image substitutes for a new render. The evaluator retains each actual
midpoint image and pose, then checks the packet delivered after camera movement.
Diagnostic delivery-pose images are evaluator-only and never policy observations.
These short fixtures are not complete policy pilots and have no skip fallback.
"""

import base64
import dataclasses
import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pv_sim.config import Config, load_config
from pv_sim.engine import DynamicsSnapshot
from pv_sim.env import PVEnv

pytestmark = pytest.mark.render
ROOT = Path(__file__).resolve().parents[2]


class CaptureTrace:
    """Evaluator-only evidence; no truth or rendering hook reaches the policy."""

    def __init__(self):
        self.rows = []
        self.observations = []
        self.actions = []

    def start(self, config, seed, task):
        self.config_hash = config.sha256()
        self.seed = seed

    def truth(self, row):
        self.rows.append(row)

    def observation(self, observation, *, tick):
        value = observation.model_dump(mode="json")
        for image in value["rgb"]:
            payload = image.pop("png_base64")
            image["png_sha256"] = (
                hashlib.sha256(base64.b64decode(payload)).hexdigest() if payload else None
            )
        self.observations.append({"tick": tick, "observation": value})

    def action(self, action, tick):
        self.actions.append({"tick": tick, "action": action})


def command(action_id, kind, timeout_s=8.0, **fields):
    return dict(schema_version="1.0", action_id=action_id, kind=kind, timeout_s=timeout_s, **fields)


def config_for(profile):
    raw = load_config(ROOT / "configs/pilot.toml").model_dump()
    raw["m2"] = {"sensing": {"rgb": profile}}
    return Config.model_validate(raw)


def save_evidence(tmp_path, name, trace, captures, diagnostic=()):
    root = Path(os.environ.get("PV_M2_RENDER_EVIDENCE_DIR", str(tmp_path)))
    destination = root / "sensor_delivery" / name
    destination.mkdir(parents=True, exist_ok=False)
    images = []
    for index, (snapshot, pixels) in enumerate(captures + list(diagnostic)):
        filename = f"image_{index:02d}.png"
        path = destination / filename
        with path.open("xb") as file:
            Image.fromarray(pixels).save(file, format="PNG")
        images.append(
            {
                "file": filename,
                "role": "actual_midpoint_capture"
                if index < len(captures)
                else "evaluator_only_delivery_pose",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "snapshot": dataclasses.asdict(snapshot),
            }
        )
    timeline = {
        "evidence": "new real MuJoCo renders and evaluator-only timing trace",
        "config_sha256": trace.config_hash,
        "seed": trace.seed,
        "images": images,
        "actions": trace.actions,
        "observations": trace.observations,
        "truth": [
            {"tick": row["tick"], "time_s": row["time_s"], "dynamics": row["dynamics"]}
            for row in trace.rows
        ],
    }
    with (destination / "timeline.json").open("x") as file:
        json.dump(timeline, file, indent=2, allow_nan=False)


@pytest.mark.parametrize("stale", [False, True], ids=["late_valid", "late_stale"])
def test_late_frame_keeps_original_capture_after_timeout_and_actual_move(
    tmp_path, monkeypatch, stale
):
    config = config_for({"extra_delay_s": 0.8, "stale_after_s": 0.2 if stale else None})
    trace = CaptureTrace()
    env = PVEnv(config, enable_rendering=True, recorder=trace)
    captures, diagnostic = [], []
    real_render = env.backend.render_rgb

    def record_render(snapshot):
        pixels = real_render(snapshot)
        captures.append((snapshot, pixels.copy()))
        return pixels

    monkeypatch.setattr(env.backend, "render_rgb", record_render)
    try:
        env.reset(61, episode_id="m2_late_rgb")
        first = env.step(command(1, "capture_rgb", timeout_s=0.2))
        assert first.feedback[-1].code == "timed_out"
        assert first.feedback[-1].reason == "sensor_unavailable"
        assert first.rgb == () and env.ledger.rgb_frames == 1
        assert len(captures) == 1
        original_snapshot, original_pixels = captures[0]
        assert original_snapshot.tick == 113  # 10 reset + 100 overhead + 3 midpoint ticks.
        moved = env.step(
            command(
                2,
                "move_camera",
                slide_m=0.06,
                yaw_rad=0.0,
                pitch_rad=0.0,
                capture_after_settle=False,
            )
        )
        assert moved.feedback[-1].code == "completed"
        assert len(moved.rgb) == 1 and len(captures) == 1
        packet = moved.rgb[0]
        assert packet.frame_id == "frame_000001"
        assert packet.validity == ("stale" if stale else "valid")
        assert (packet.t_start_s, packet.t_capture_s, packet.t_end_s, packet.t_deliver_s) == (
            110 * 0.002,
            113 * 0.002,
            116 * 0.002,
            566 * 0.002,
        )
        assert first.t_deliver_s < packet.t_deliver_s <= moved.t_deliver_s
        with Image.open(io.BytesIO(base64.b64decode(packet.png_base64))) as image:
            np.testing.assert_array_equal(np.asarray(image), original_pixels)
        delivery_row = next(row for row in trace.rows if row["tick"] == 566)
        delivery_snapshot = DynamicsSnapshot(**delivery_row["dynamics"])
        assert delivery_snapshot.q[0] - original_snapshot.q[0] > 0.005
        current = env.backend.snapshot()
        assert abs(current.q[0] - 0.06) < 0.001
        delivery_pixels = real_render(delivery_snapshot)
        diagnostic.append((delivery_snapshot, delivery_pixels.copy()))
        assert env.backend.snapshot() == current
        assert not np.array_equal(delivery_pixels, original_pixels)
        assert env.ledger.rgb_frames == 1
        waited = env.step(command(3, "wait", duration_s=0.5))
        assert waited.rgb == () and len(captures) == 1 and env.ledger.rgb_frames == 1
        assert env.time_s < 6.0 and not env.terminal_reason
    finally:
        try:
            if hasattr(trace, "config_hash"):
                save_evidence(
                    tmp_path, "late_stale" if stale else "late_valid", trace, captures, diagnostic
                )
        finally:
            env.close()


def test_dropped_real_capture_keeps_timing_null_payload_charge_and_no_free_wait_frame(
    tmp_path, monkeypatch
):
    trace = CaptureTrace()
    env = PVEnv(config_for({"dropout_probability": 1.0}), enable_rendering=True, recorder=trace)
    captures = []
    real_render = env.backend.render_rgb

    def record_render(snapshot):
        pixels = real_render(snapshot)
        captures.append((snapshot, pixels.copy()))
        return pixels

    monkeypatch.setattr(env.backend, "render_rgb", record_render)
    try:
        env.reset(61, episode_id="m2_dropped_rgb")
        observation = env.step(command(1, "capture_rgb", timeout_s=0.5))
        assert len(captures) == 1 and captures[0][0].tick == 113
        assert captures[0][1].std() > 1.0
        assert observation.feedback[-1].code == "timed_out"
        assert observation.feedback[-1].reason == "sensor_unavailable"
        (packet,) = observation.rgb
        assert packet.validity == "missing" and packet.png_base64 is None
        assert (packet.t_start_s, packet.t_capture_s, packet.t_end_s, packet.t_deliver_s) == (
            110 * 0.002,
            113 * 0.002,
            116 * 0.002,
            166 * 0.002,
        )
        assert env.ledger.rgb_frames == 1 and observation.remaining_budgets.rgb_frames == 19
        wait = env.step(command(2, "wait", duration_s=0.8))
        assert wait.feedback[-1].code == "completed" and wait.rgb == ()
        assert len(captures) == 1 and env.ledger.rgb_frames == 1
        assert env.time_s < 2.0 and not env.terminal_reason
    finally:
        try:
            if hasattr(trace, "config_hash"):
                save_evidence(tmp_path, "dropped", trace, captures)
        finally:
            env.close()
