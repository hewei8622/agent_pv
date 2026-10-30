"""Deterministic F4 action fixtures: genuine short dynamics, no graphics/pilots."""

import dataclasses
import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from pv_sim.config import Config, load_config
from pv_sim.contracts import EncoderSample, ScalarSample
from pv_sim.env import PVEnv, SafetyStopError
from pv_sim.recorder import Recorder
from pv_sim.replay import replay

ROOT = Path(__file__).resolve().parents[2]


def command(action_id, kind, timeout_s=2.0, **fields):
    return dict(schema_version="1.0", action_id=action_id, kind=kind, timeout_s=timeout_s, **fields)


def terminal(observation):
    return next(
        f for f in reversed(observation.feedback) if f.code not in {"accepted", "executing"}
    )


def configured(*, actuation=None, sensing=None, view=None, budgets=None):
    fields = load_config(ROOT / "configs/pilot.toml").model_dump(mode="json")
    fields["m2"] = {"actuation": actuation or {}, "sensing": sensing or {}, "view": view or {}}
    fields["pilot"]["actuator_failures"] = bool(actuation)
    if budgets:
        fields["budgets"].update(budgets)
    return Config.model_validate_json(json.dumps(fields))


class Trace:
    def __init__(self):
        self.rows = []
        self.events = []

    def start(self, config, seed, task):
        pass

    def truth(self, row):
        self.rows.append(row)

    def action(self, action, tick):
        pass

    def observation(self, observation, *, tick):
        pass

    def actuation(self, payload, tick, *, action_id=None):
        self.events.append({"tick": tick, "action_id": action_id, **payload})


@contextmanager
def fixture(config, *, rgb_capability=False):
    trace = Trace()
    env = PVEnv(config, enable_rendering=rgb_capability, recorder=trace)
    try:
        env.reset(seed=20261017, episode_id="m2_action_fixture")
        yield env, trace
    finally:
        assert env.backend._renderer is None
        assert env.time_s < 12.0
        env.close()


def test_delayed_load_separates_acknowledgement_application_and_fresh_measurement():
    config = configured(actuation={"load_extra_delay_s": [[1, 0.4]]})
    with fixture(config) as (env, trace):
        observation = env.step(command(1, "set_voltage", voltage_v=0.8))
        accepted, result = observation.feedback[0], terminal(observation)
        assert accepted.code == "accepted" and not accepted.measured_confirmation
        assert result.code == "completed"
        issued = next(e for e in trace.events if e["kind"] == "load_issued")
        applied = next(e for e in trace.events if e["kind"] == "load_applied")
        assert issued["tick"] == round(accepted.t_accepted_s / 0.002)
        assert applied["tick"] == issued["tick"] + 250 == issued["due_tick"]
        assert issued["command_number"] == applied["command_number"] == 1
        before = [row for row in trace.rows if row["tick"] < applied["tick"]]
        assert all(row["applied_voltage_v"] == 1.8 for row in before)
        assert any(row["requested_voltage_v"] == 0.8 for row in before)
        changed = [row for row in trace.rows if row["applied_voltage_v"] < 1.8]
        assert changed[0]["tick"] == applied["tick"]
        prior = 1.8
        for row in changed:
            assert abs(row["applied_voltage_v"] - prior) <= 0.02 + 1e-12
            prior = row["applied_voltage_v"]
        samples = tuple(m.sample for m in result.measured_confirmation)
        assert {s.channel for s in samples} == {"voltage_v", "current_a"}
        assert all(
            s.validity == "valid" and s.t_capture_s > applied["tick"] * 0.002 for s in samples
        )
        assert all(s in observation.scalars for s in samples)
        assert next(s.value for s in samples if s.channel == "voltage_v") == pytest.approx(0.8)
        assert env.ledger.voltage_points == 1


def test_dropped_load_never_claims_applied_target_and_retry_is_idempotent():
    config = configured(actuation={"load_drop_commands": [1]})
    with fixture(config) as (env, trace):
        payload = command(4, "set_voltage", timeout_s=0.6, voltage_v=0.8)
        observation = env.step(payload)
        result = terminal(observation)
        assert observation.feedback[0].code == "accepted"
        assert result.code == "timed_out" and result.reason == "tracking_timeout"
        assert env.applied_voltage_v == 1.8 and env.requested_voltage_v == 0.8
        assert env.disconnected and env.point.current_a == 0.0
        assert [e["kind"] for e in trace.events] == [
            "load_issued",
            "load_dropped",
            "load_disconnected",
        ]
        assert all(row["applied_voltage_v"] == 1.8 for row in trace.rows)
        currents = [
            m.sample for m in result.measured_confirmation if m.sample.channel == "current_a"
        ]
        assert currents and currents[0].value == 0.0
        assert currents[0].t_capture_s > result.t_accepted_s + payload["timeout_s"]
        wire = observation.model_dump_json()
        assert all(secret not in wire for secret in ("load_dropped", "load_drop_commands", "F4"))
        before = (
            env.tick,
            dataclasses.asdict(env.ledger),
            env.backend.snapshot(),
            list(trace.events),
        )
        assert env.step(json.dumps(payload, sort_keys=True)) == observation
        assert (
            env.tick,
            dataclasses.asdict(env.ledger),
            env.backend.snapshot(),
            trace.events,
        ) == before
        conflict = env.step({**payload, "voltage_v": 3.0})
        assert terminal(conflict).reason == "command_conflict"
        prior = env.step(command(3, "set_voltage", voltage_v=3.0))
        assert terminal(prior).reason == "command_conflict"
        assert env._load_command_count == 1 and env.ledger.voltage_points == 1
        assert env.ledger.decisions == 3 and env.tick == before[0] + 200


def test_delayed_command_is_cancelled_at_timeout_and_cannot_apply_during_later_wait():
    config = configured(actuation={"load_extra_delay_s": [[1, 1.0]]})
    with fixture(config) as (env, trace):
        observation = env.step(command(1, "set_voltage", timeout_s=0.3, voltage_v=0.8))
        assert terminal(observation).code == "timed_out"
        assert env.disconnected and env._pending_load is None
        later = env.step(command(2, "wait", duration_s=1.5))
        assert not later.rgb and env.ledger.rgb_frames == 0
        assert env.applied_voltage_v == 1.8 and env.point.current_a == 0.0
        assert any(e["kind"] == "load_cancelled" for e in trace.events)
        assert not any(e["kind"] == "load_applied" for e in trace.events)


@pytest.mark.parametrize("restore_fault", ["drop", "delay"])
def test_probe_restore_failure_uses_one_cleanup_tail_and_measured_disconnection(restore_fault):
    faults = (
        {"load_drop_commands": [2]}
        if restore_fault == "drop"
        else {"load_extra_delay_s": [[2, 8.0]]}
    )
    with fixture(configured(actuation=faults)) as (env, trace):
        observation = env.step(
            command(1, "probe_voltage", timeout_s=1.0, voltages_v=[0.8], dwell_s=0.2)
        )
        result = terminal(observation)
        assert result.code == "timed_out" and result.reason == "tracking_timeout"
        assert result.t_terminal_s <= result.t_accepted_s + 1.0 + 2.0
        assert env.disconnected and env.point.current_a == 0.0
        assert env._pending_load is None and env.requested_voltage_v == 1.8
        assert env.applied_voltage_v == 0.8
        assert env.ledger.voltage_points == 1 and env._load_command_count == 2
        points = [f for f in observation.feedback if f.code == "executing"]
        assert len(points) == 1
        restored = tuple(m.sample for m in result.measured_confirmation)
        assert next(s.value for s in restored if s.channel == "current_a") == 0.0
        assert all(s.t_capture_s > result.t_accepted_s + 1.0 for s in restored)
        assert not any(
            e["kind"] == "load_applied" and e["command_number"] == 2 for e in trace.events
        )
        after = env.step(command(2, "wait", duration_s=0.5))
        assert not after.terminal and env.disconnected and env.point.current_a == 0.0


def test_dropped_probe_point_restores_previous_requested_load_without_false_point_feedback():
    with fixture(configured(actuation={"load_drop_commands": [1]})) as (env, trace):
        observation = env.step(
            command(1, "probe_voltage", timeout_s=0.5, voltages_v=[0.8, 3.0], dwell_s=0.2)
        )
        result = terminal(observation)
        assert result.code == "timed_out"
        assert not any(f.code == "executing" for f in observation.feedback)
        assert env.requested_voltage_v == env.applied_voltage_v == 1.8
        assert not env.disconnected and env.ledger.voltage_points == 2
        assert env._load_command_count == 2
        assert [e["command_number"] for e in trace.events if e["kind"] == "load_applied"] == [2]
        assert next(
            m.sample.value for m in result.measured_confirmation if m.sample.channel == "voltage_v"
        ) == pytest.approx(1.8, abs=1e-10, rel=0)


def test_stalled_move_keeps_actual_pose_and_cannot_claim_settled_frame_then_recovers():
    config = configured(actuation={"move_stall_commands": [1]})
    # Advertise RGB to test the move's own settled-view guard. The inhibited
    # motion must never reach the render method or create a graphics context.
    with fixture(config, rgb_capability=True) as (env, trace):
        payload = command(
            1,
            "move_camera",
            timeout_s=0.5,
            slide_m=0.06,
            yaw_rad=0.1,
            pitch_rad=0.0,
            capture_after_settle=True,
        )
        observation = env.step(payload)
        result = terminal(observation)
        assert result.code == "timed_out" and result.reason == "tracking_timeout"
        assert not observation.rgb and env.ledger.rgb_frames == 0
        assert env.backend.snapshot().q == (0.0, 0.0, 0.0)
        assert env.ledger.slide_path_m == 0.0
        assert len(trace.rows) == env.tick + 1
        encoder = next(
            m.sample for m in result.measured_confirmation if isinstance(m.sample, EncoderSample)
        )
        assert (encoder.slide_m, encoder.yaw_rad, encoder.pitch_rad) == (0.0, 0.0, 0.0)
        assert encoder.t_capture_s >= result.t_accepted_s + 0.5
        assert any(e["kind"] == "move_inhibited" for e in trace.events)
        assert not any(e["kind"] == "move_command_applied" for e in trace.events)
        before = env.tick, env._move_command_count, dataclasses.asdict(env.ledger)
        assert env.step(payload) == observation
        assert (env.tick, env._move_command_count, dataclasses.asdict(env.ledger)) == before
        recovered = env.step(
            {**payload, "action_id": 2, "timeout_s": 3.0, "capture_after_settle": False}
        )
        assert terminal(recovered).code == "completed"
        np.testing.assert_allclose(env.backend.snapshot().q, (0.06, 0.1, 0.0), atol=0.001, rtol=0)
        assert env._move_command_count == 2 and env.ledger.slide_path_m > 0


@pytest.mark.parametrize("profile", [{"dropout_probability": 1.0}, {"stale_after_s": 0.01}])
def test_missing_or_stale_numeric_data_cannot_verify_applied_load(profile):
    with fixture(configured(sensing={"numeric": profile})) as (env, trace):
        observation = env.step(command(1, "set_voltage", timeout_s=0.6, voltage_v=0.8))
        result = terminal(observation)
        assert any(e["kind"] == "load_applied" for e in trace.events)
        assert result.code == "timed_out" and result.reason == "sensor_unavailable"
        assert not result.measured_confirmation
        assert env.disconnected and env.point.current_a == 0.0
        assert observation.scalars and all(s.validity != "valid" for s in observation.scalars)
        assert env.time_s <= result.t_accepted_s + 0.6 + 2.0


def test_missing_encoder_stop_confirmation_is_bounded_incomplete_and_blocks_resume():
    config = configured(
        actuation={"move_stall_commands": [1]}, sensing={"encoder": {"dropout_probability": 1.0}}
    )
    with fixture(config) as (env, _):
        with pytest.raises(SafetyStopError, match="measured stop"):
            env.step(
                command(
                    1,
                    "move_camera",
                    timeout_s=0.4,
                    slide_m=0.06,
                    yaw_rad=0.1,
                    pitch_rad=0.0,
                    capture_after_settle=False,
                )
            )
        assert env.time_s == pytest.approx(0.02 + 0.2 + 0.4 + 2.0)
        assert env.terminal_reason is None and env.backend.snapshot().q == (0.0, 0.0, 0.0)
        before = env.tick, dataclasses.asdict(env.ledger)
        with pytest.raises(SafetyStopError, match="reset is required"):
            env.step(command(2, "wait", duration_s=0.1))
        assert (env.tick, dataclasses.asdict(env.ledger)) == before


def test_rail_locked_direct_action_rejected_before_motion_and_fault_counter():
    config = configured(view={"rail_locked": True}, actuation={"move_stall_commands": [1]})
    with fixture(config) as (env, trace):
        assert env.task.limits.slide_m == (0.0, 0.0)
        observation = env.step(
            command(
                1,
                "move_camera",
                slide_m=0.01,
                yaw_rad=0.0,
                pitch_rad=0.0,
                capture_after_settle=False,
            )
        )
        result = terminal(observation)
        assert result.code == "rejected" and result.reason == "out_of_range"
        assert env._move_command_count == 0 and not trace.events
        assert env.backend.snapshot().q == (0.0, 0.0, 0.0)
        assert env.ledger.decisions == 1 and env.time_s == 0.22


def test_safe_stop_remains_available_with_non_time_budgets_exhausted():
    config = configured(
        budgets={
            "rgb_frames": 0,
            "voltage_points": 0,
            "decisions": 0,
            "slide_path_m": 0.0,
            "angular_path_rad": 0.0,
        }
    )
    with fixture(config) as (env, _):
        observation = env.step(command(1, "safe_stop"))
        result = terminal(observation)
        assert result.code == "completed" and observation.terminal_reason == "safe_stop"
        assert env.disconnected and env.point.current_a == 0.0
        assert any(isinstance(m.sample, EncoderSample) for m in result.measured_confirmation)
        assert any(isinstance(m.sample, ScalarSample) for m in result.measured_confirmation)
        assert env.ledger.voltage_points == env.ledger.rgb_frames == 0


def test_exhausted_decision_fallback_with_missing_feedback_is_one_bounded_stop():
    config = configured(budgets={"decisions": 0}, sensing={"numeric": {"dropout_probability": 1.0}})
    with fixture(config) as (env, _):
        with pytest.raises(SafetyStopError, match="measured stop confirmation"):
            env.step(command(1, "wait", duration_s=0.1))
        assert env.time_s == pytest.approx(0.02 + 0.2 + 2.0)
        assert env.disconnected and env.terminal_reason is None
        assert env.ledger.decisions == 1 and env._stop_failed


def test_private_actuation_evidence_is_excluded_from_public_recording(tmp_path):
    recorder = Recorder(tmp_path / "m2_private_events", tmp_path / "private")
    env = PVEnv(
        configured(actuation={"load_drop_commands": [1]}), enable_rendering=False, recorder=recorder
    )
    try:
        env.reset(episode_id="opaque")
        env.step(command(1, "set_voltage", timeout_s=0.3, voltage_v=0.8))
        recorder.finish(env.metrics())
        events = [
            json.loads(line)
            for line in (recorder.private_dir / "actuation.jsonl").read_text().splitlines()
        ]
        assert [e["payload"]["kind"] for e in events] == [
            "load_issued",
            "load_dropped",
            "load_disconnected",
        ]
        assert all(e["action_id"] == 1 for e in events)
        public = "".join(p.read_text() for p in recorder.public_dir.glob("*.json*"))
        assert "load_drop_commands" not in public and "load_dropped" not in public
        manifest = json.loads(recorder.manifest_path.read_text())
        assert manifest["capture_namespace"] == "pv-sim/capture-streams/v1"
        assert env.backend._renderer is None
    finally:
        env.close()
        recorder.close()


def test_terminal_rejection_is_cached_without_extra_decisions_or_time():
    with fixture(configured()) as (env, _):
        env.step(command(1, "safe_stop"))
        payload = command(2, "set_voltage", voltage_v=0.8)
        rejected = env.step(payload)
        assert terminal(rejected).code == "rejected"
        before = env.tick, dataclasses.asdict(env.ledger), env.backend.snapshot()
        assert env.step(payload) == rejected
        assert (env.tick, dataclasses.asdict(env.ledger), env.backend.snapshot()) == before
        assert env._load_command_count == 0


def test_zero_latency_reset_delivers_real_tick_zero_samples_without_advancing():
    fields = configured().model_dump(mode="json")
    fields["sensors"].update(numeric_latency_s=0.0, encoder_latency_s=0.0)
    env = PVEnv(Config.model_validate_json(json.dumps(fields)), enable_rendering=False)
    try:
        _, observation = env.reset(episode_id="zero_latency")
        assert env.tick == 0 and env.time_s == 0.0
        assert len(observation.scalars) == 4 and len(observation.encoders) == 1
        assert all(
            s.t_capture_s == s.t_deliver_s == 0.0
            for s in observation.scalars + observation.encoders
        )
        assert env._latest_encoder == observation.encoders[0]
        assert env.backend._renderer is None
    finally:
        env.close()


def test_dropped_reconnect_to_stored_voltage_cannot_claim_load_completion():
    with fixture(configured(actuation={"load_drop_commands": [2]})) as (env, _):
        first = env.step(command(1, "set_voltage", timeout_s=0.05, voltage_v=0.8))
        assert terminal(first).code == "timed_out" and env.disconnected
        assert env.applied_voltage_v == 1.8
        second = env.step(command(2, "set_voltage", timeout_s=0.5, voltage_v=1.8))
        assert terminal(second).code == "timed_out"
        assert env.disconnected and env.point.current_a == 0.0
        assert not any(f.code == "completed" for f in second.feedback)


@pytest.mark.parametrize(
    "kind,fields",
    [
        (
            "move_camera",
            {"slide_m": 0.0, "yaw_rad": 0.2, "pitch_rad": 0.0, "capture_after_settle": False},
        ),
        (
            "move_camera",
            {"slide_m": 0.0, "yaw_rad": 0.0, "pitch_rad": 0.2, "capture_after_settle": False},
        ),
        ("set_voltage", {"voltage_v": 0.8}),
        ("probe_voltage", {"voltages_v": [1.8, 3.0], "dwell_s": 0.2}),
    ],
)
def test_direct_requests_obey_each_advertised_limit_before_any_command(kind, fields):
    with fixture(configured()) as (env, trace):
        # A restricted public capability condition is authoritative even for
        # trusted callers that invoke step directly, without PolicyRunner.
        limits = env.task.limits.model_copy(
            update={
                "yaw_rad": (-0.1, 0.1),
                "pitch_rad": (-0.1, 0.1),
                "voltage_v": (1.0, 2.0),
            }
        )
        env.task = env.task.model_copy(update={"limits": limits})
        observation = env.step(command(1, kind, **fields))
        assert terminal(observation).reason == "out_of_range"
        assert terminal(observation).t_accepted_s is None
        assert env._load_command_count == env._move_command_count == 0
        assert env.ledger.voltage_points == 0 and not trace.events


def test_composed_noise_delay_and_load_drop_recording_replays_exactly(tmp_path):
    fields = configured(
        actuation={"load_drop_commands": [1]},
        sensing={
            "numeric": {"extra_delay_s": 0.04, "jitter_s": 0.01},
            "encoder": {"jitter_s": 0.006},
        },
    ).model_dump(mode="json")
    fields["pilot"].update(numeric_noise=True, encoder_noise=True)
    config = Config.model_validate_json(json.dumps(fields))
    recorder = Recorder(tmp_path / "m2_composed_source", tmp_path / "private")
    env = PVEnv(config, enable_rendering=False, recorder=recorder)
    try:
        _, initial = env.reset(seed=426, episode_id="opaque_replay")
        failed = env.step(command(1, "set_voltage", timeout_s=0.4, voltage_v=0.8))
        recovered = env.step(command(2, "set_voltage", timeout_s=1.5, voltage_v=0.8))
        assert terminal(failed).code == "timed_out"
        assert terminal(recovered).code == "completed"
        assert env.time_s < 3.0 and env.backend._renderer is None
        assert not initial.rgb and not failed.rgb and not recovered.rgb
        recorder.finish(env.metrics())
    finally:
        env.close()
        recorder.close()
    report = replay(recorder.manifest_path, tmp_path / "m2_composed_replay", tmp_path / "private")
    assert report["status"] == "passed" and report["core_only"]
    assert not report["rendered_gate_satisfied"]
    assert report["actuation_comparison"]["passed"]
    assert report["truth_comparison"]["passed"] and report["metrics_comparison"]["passed"]
    assert all(item["maximum_numeric_absolute_error"] == 0.0 for item in report["observations"])
