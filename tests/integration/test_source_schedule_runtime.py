"""Short source-event invariants on actual MuJoCo dynamics, without any GL call.

The light probe raises before rendering and never produces a substitute image.
Actual RGB validation belongs to the separate desktop-render gate.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from pv_sim.config import Config, load_config
from pv_sim.env import PVEnv
from pv_sim.recorder import Recorder
from pv_sim.replay import replay

ROOT = Path(__file__).resolve().parents[2]


def config(*, schedule=True, latency=0.02):
    raw = json.loads(load_config(ROOT / "configs/pilot.toml").canonical_json())
    if schedule:
        raw["source_schedule"] = [{"time_s": 2.0, "dni_w_m2": 400.0}]
    raw["sensors"]["numeric_latency_s"] = latency
    return Config.model_validate_json(json.dumps(raw))


def test_source_boundary_integrates_old_interval_then_captures_new_state():
    changed = PVEnv(config(), enable_rendering=False)
    control = PVEnv(config(schedule=False), enable_rendering=False)
    try:
        changed.reset(episode_id="source_step")
        control.reset(episode_id="source_control")
        changed._advance_to(999)
        control._advance_to(999)
        prior_temperature = changed.temperature_c
        prior_absorbed = changed.ledger.absorbed_j
        assert changed.optics.irradiance_w_m2 == (900,) * 8
        assert changed.point == control.point
        changed._tick()
        control._tick()
        assert changed.tick == control.tick == 1000
        # Identical entire history through [1.998, 2.000]: no retroactive heat,
        # energy, temperature jump, or change to the interval's production.
        assert changed.temperature_c == control.temperature_c
        assert changed.ledger.absorbed_j == control.ledger.absorbed_j
        assert changed.ledger.pv_energy_j == control.ledger.pv_energy_j
        assert changed.ledger.potential_energy_j == control.ledger.potential_energy_j
        assert changed.temperature_c > prior_temperature
        assert changed.ledger.absorbed_j - prior_absorbed == pytest.approx(
            0.9 * 0.06 * 900 * 0.002, abs=1e-12
        )
        # Endpoint t=2 is right-continuous: the source and electrical quantities
        # have changed while temperature remains continuous.
        assert changed.scene.source.dni_w_m2 == changed.backend.scene.source.dni_w_m2 == 400
        assert changed.optics.scene is changed.scene
        assert changed.optics.irradiance_w_m2 == (500,) * 8
        assert changed.optics.reference_w_m2 == 500
        assert changed.applied_voltage_v == control.applied_voltage_v == 1.8
        assert changed.point.voltage_v == pytest.approx(1.8, abs=1e-14, rel=0)
        assert control.point.voltage_v == pytest.approx(1.8, abs=1e-14, rel=0)
        assert changed.point.current_a < control.point.current_a
        np.testing.assert_allclose(changed.backend.model.light_diffuse[0], (0.4,) * 3)
        np.testing.assert_allclose(changed.backend.model.light_ambient[0], (0.1,) * 3)
        assert changed.backend.snapshot() == control.backend.snapshot()
        absorbed_at_event = changed.ledger.absorbed_j
        changed._tick()
        control._tick()
        assert changed.ledger.absorbed_j - absorbed_at_event == pytest.approx(
            0.9 * 0.06 * 500 * 0.002, abs=1e-12
        )
        assert changed.temperature_c < control.temperature_c
        assert changed.ledger.pv_energy_j < control.ledger.pv_energy_j
        assert changed.backend._renderer is None and control.backend._renderer is None
    finally:
        changed.close()
        control.close()


def test_queued_scalar_capture_before_change_keeps_original_value_and_timing():
    env = PVEnv(config(latency=0.2), enable_rendering=False)
    try:
        env.reset(episode_id="source_delayed")
        env._advance_to(950)
        original = {
            sample.channel: sample
            for _, _, _, sample in env.clock._queue
            if hasattr(sample, "channel") and sample.t_capture_s == 950 * 0.002
        }
        assert original["reference_w_m2"].value == 900
        env._advance_to(1100)
        observed = env._observation()
        delivered = {
            sample.channel: sample
            for sample in observed.scalars
            if sample.t_capture_s == 950 * 0.002
        }
        assert delivered == original
        assert all(sample.t_deliver_s == 1050 * 0.002 for sample in delivered.values())
        endpoint = {
            sample.channel: sample for sample in observed.scalars if sample.t_capture_s == 2.0
        }
        assert endpoint["reference_w_m2"].value == 500
        assert endpoint["current_a"].value < delivered["current_a"].value
        assert endpoint["voltage_v"].value == pytest.approx(1.8, abs=1e-14, rel=0)
        assert delivered["voltage_v"].value == pytest.approx(1.8, abs=1e-14, rel=0)
        assert all(sample.t_deliver_s == 2.2 for sample in endpoint.values())
        assert env.backend._renderer is None
    finally:
        env.close()


def test_reset_restarts_source_and_rejects_frozen_schedule_mutation():
    env = PVEnv(config(), enable_rendering=False)
    try:
        task, initial = env.reset(19, episode_id="source_reset")
        env._advance_to(1010)
        end_state = (env.temperature_c, env.point, env.optics.irradiance_w_m2, env.metrics())
        with pytest.raises(ValidationError, match="frozen"):
            env.config.source_schedule[0].time_s = 3.0
        repeated_task, repeated_initial = env.reset(19, episode_id="source_reset")
        assert (repeated_task, repeated_initial) == (task, initial)
        assert env.scene.source.dni_w_m2 == env.backend.scene.source.dni_w_m2 == 800
        np.testing.assert_allclose(env.backend.model.light_diffuse[0], (0.8,) * 3)
        env._advance_to(1010)
        repeated_state = (env.temperature_c, env.point, env.optics.irradiance_w_m2, env.metrics())
        assert repeated_state == end_state
        assert env.backend._renderer is None
        env.backend.reset()
        assert env.backend.tick == 0 and env.backend.scene.source.dni_w_m2 == 800
        np.testing.assert_allclose(env.backend.model.light_diffuse[0], (0.8,) * 3)
    finally:
        env.close()


def test_historical_snapshot_selects_its_source_and_restores_live_light_on_failure():
    env = PVEnv(config(), enable_rendering=False)
    try:
        env.reset(episode_id="source_light_probe")
        env._advance_to(999)
        before = env.backend.snapshot()
        env._advance_to(1000)
        after = env.backend.snapshot()
        captured = []

        class CaptureLightProbe(Exception):
            pass

        class NeverRender:
            def update_scene(self, data, **kwargs):
                captured.append((data.time, env.backend.model.light_diffuse[0].copy()))
                raise CaptureLightProbe("stopped before render; no image produced")

            def close(self):
                pass

        assert env.backend._renderer is None
        env.backend._renderer = NeverRender()
        for snapshot, expected in ((before, 0.8), (after, 0.4), (before, 0.8)):
            with pytest.raises(CaptureLightProbe):
                env.backend.render_rgb(snapshot)
            assert captured[-1][0] == snapshot.time_s
            np.testing.assert_allclose(captured[-1][1], (expected,) * 3)
            np.testing.assert_allclose(env.backend.model.light_diffuse[0], (0.4,) * 3)
            assert env.backend.scene.source.dni_w_m2 == 400
            assert env.backend.snapshot() == after
    finally:
        env.close()


def test_source_change_recorded_actions_replay_and_schedule_remains_private(tmp_path):
    recorder = Recorder(tmp_path / "runs" / "source-step", tmp_path / "private")
    env = PVEnv(config(), enable_rendering=False, recorder=recorder)
    try:
        env.reset(31, episode_id="source_replay")
        env.step(dict(
            schema_version="1.0", action_id=1, kind="wait", timeout_s=3.0, duration_s=1.9
        ))
        assert env.tick > 1000 and env.scene.source.dni_w_m2 == 400
        env.step(dict(schema_version="1.0", action_id=2, kind="safe_stop", timeout_s=3.0))
        recorder.finish(env.metrics())
        assert env.backend._renderer is None
    finally:
        env.close()
        recorder.close()
    for path in recorder.public_dir.glob("*.json*"):
        assert "source_schedule" not in path.read_text()
        assert "dni_w_m2" not in path.read_text()
    report = replay(
        recorder.manifest_path, tmp_path / "runs" / "source-replayed",
        private_root=tmp_path / "private",
    )
    assert report["status"] == "passed"
    assert report["truth_comparison"]["passed"]
    assert report["metrics_comparison"]["passed"]
    assert report["core_only"] and not report["rendered_gate_satisfied"]
    assert not report["policy_requeried"]
    assert all(item["frames_compared"] == 0 for item in report["observations"])
    original = [json.loads(line)["payload"] for line in
                (recorder.private_dir / "truth.jsonl").read_text().splitlines()]
    repeated = [json.loads(line)["payload"] for line in
                (tmp_path / "private/source-replayed/truth.jsonl").read_text().splitlines()]
    assert original == repeated
    assert original[999]["irradiance_w_m2"] == [900] * 8
    assert original[1000]["irradiance_w_m2"] == [500] * 8
