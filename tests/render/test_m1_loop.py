"""Required real-RGB partial B1 integration; independent of the three CLI pilots.

This test must run in the approved working graphics context. It has no skip,
placeholder renderer or numeric-only fallback. Stop after observed verification,
before executing finish: this is a short integration fixture, not a full pilot.
"""

import base64
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pv_sim.config import load_config
from pv_sim.env import PVEnv
from pv_sim.policies import ScanPolicy
from pv_sim.policy_runner import PolicyRunner

pytestmark = pytest.mark.render
ROOT = Path(__file__).resolve().parents[2]


def test_actual_rgb_scan_probe_and_new_operating_point_verification():
    config = load_config(ROOT / "configs/pilot.toml")
    env = PVEnv(config, enable_rendering=True)
    try:
        task, initial = env.reset(episode_id="render_loop_fixture")
        runner = PolicyRunner(ScanPolicy(), task)
        history = (initial,)
        decisions = []
        for expected in ("capture_rgb", "move_camera", "probe_voltage", "set_voltage", "wait"):
            decision = runner.decide(history)
            assert runner.last_failure is None
            assert decision.action.kind == expected
            decisions.append(decision)
            observation = env.step(decision.action)
            assert not observation.terminal
            assert observation.feedback[-1].code == "completed"
            history += (observation,)
        finish = runner.decide(history)
        assert finish.action.kind == "finish"
        assert finish.action.resolution == "unresolved"
        assert finish.predictions == () and finish.hypothesis_probabilities is None
        assert runner.last_failure is None
        assert not env.terminal_reason and env.time_s < 12.0
        frames = [frame for observation in history for frame in observation.rgb]
        assert len(frames) == 2
        arrays = []
        for frame in frames:
            assert frame.t_capture_s == pytest.approx((frame.t_start_s + frame.t_end_s) / 2)
            assert frame.t_end_s - frame.t_start_s == pytest.approx(0.012)
            assert frame.t_deliver_s - frame.t_end_s == pytest.approx(0.1)
            with Image.open(io.BytesIO(base64.b64decode(frame.png_base64))) as image:
                pixels = np.asarray(image).copy()
            assert pixels.shape == (480, 640, 3) and pixels.dtype == np.uint8
            assert pixels.std() > 1.0
            arrays.append(pixels)
        assert not np.array_equal(arrays[0], arrays[1])
        side = history[2]
        accepted = side.feedback[0].t_accepted_s
        assert frames[1].t_start_s >= accepted
        encoders = [m.sample for m in side.feedback[-1].measured_confirmation]
        assert encoders and abs(encoders[0].slide_m - 0.12) <= 0.002
        probe = history[3]
        points = [f for f in probe.feedback if f.code == "executing" and f.measured_confirmation]
        assert len(points) == 3
        measured = []
        for point in points:
            samples = {m.sample.channel: m.sample for m in point.measured_confirmation}
            voltage, current = samples["voltage_v"], samples["current_a"]
            assert voltage.t_capture_s == current.t_capture_s
            assert voltage in probe.scalars and current in probe.scalars
            measured.append((voltage.value * current.value, voltage.value))
        best_voltage = max(measured)[1]
        assert decisions[3].action.voltage_v == pytest.approx(best_voltage, abs=0.03)
        set_completed = history[4].feedback[-1].t_terminal_s
        assert any(
            s.channel == "voltage_v" and s.t_capture_s > set_completed for s in history[5].scalars
        )
        assert env.metrics()["core_only"] is False
        assert env.backend._renderer is not None
    finally:
        env.close()
