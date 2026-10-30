"""Short real MuJoCo/PV core sequences: no GL, fake backend or full pilot claim."""

import dataclasses
import json
import math
from pathlib import Path

import numpy as np
import pytest

from pv_sim.config import Config, load_config
from pv_sim.contracts import ACTION_ADAPTER, EncoderSample, ScalarSample
from pv_sim.env import PVEnv

ROOT = Path(__file__).resolve().parents[2]


class TickRecorder:
    """Keep actual orchestrator truth in memory for independent timing assertions."""

    def __init__(self):
        self.rows = []

    def start(self, config, seed, task):
        self.task = task

    def truth(self, row):
        self.rows.append(row)

    def observation(self, observation, *, tick):
        pass

    def action(self, action, tick):
        pass


@pytest.fixture
def config():
    return load_config(ROOT / "configs/pilot.toml")


@pytest.fixture
def core(config):
    trace = TickRecorder()
    env = PVEnv(config, enable_rendering=False, recorder=trace)
    task, initial = env.reset(episode_id="core_fixture")
    yield env, trace, task, initial
    assert env.backend._renderer is None  # No graphics created or silently substituted.
    assert env.time_s < 12.0  # Short invariant fixture, not a complete pilot run.
    env.close()


def command(action_id, kind, timeout_s=8.0, **fields):
    return dict(schema_version="1.0", action_id=action_id, kind=kind, timeout_s=timeout_s, **fields)


def terminal(observation):
    return next(
        f for f in reversed(observation.feedback) if f.code not in {"accepted", "executing"}
    )


def scalar_pairs(observation):
    voltage = {s.t_capture_s: s for s in observation.scalars if s.channel == "voltage_v"}
    current = {s.t_capture_s: s for s in observation.scalars if s.channel == "current_a"}
    assert voltage.keys() == current.keys()
    return [(voltage[t], current[t]) for t in sorted(voltage)]


def test_reset_and_wait_capture_integer_time_and_actual_pv_identity(core):
    env, trace, task, initial = core
    assert initial.t_deliver_s == 0.02
    assert {s.t_capture_s for s in initial.scalars} == {0.0}
    assert "rgb" not in task.sensors and not initial.rgb
    observation = env.step(ACTION_ADAPTER.validate_python(command(1, "wait", duration_s=0.5)))
    result = terminal(observation)
    assert result.code == "completed"
    assert result.t_accepted_s == 0.22
    assert result.t_terminal_s == 0.72
    assert env.tick == 360
    rows = {row["tick"]: row for row in trace.rows}
    for voltage, current in scalar_pairs(observation):
        capture_tick = round(voltage.t_capture_s / 0.002)
        assert capture_tick % 50 == 0
        assert voltage.t_deliver_s == (capture_tick + 10) * 0.002
        point = rows[capture_tick]["point"]
        assert voltage.value == point["voltage_v"]
        assert current.value == point["current_a"]
        assert voltage.value * current.value == pytest.approx(point["power_w"], abs=1e-10)
    for sample in observation.encoders:
        capture_tick = round(sample.t_capture_s / 0.002)
        assert capture_tick % 25 == 0
        assert sample.t_deliver_s == (capture_tick + 5) * 0.002
        assert (sample.slide_m, sample.yaw_rad, sample.pitch_rad) == rows[capture_tick]["dynamics"][
            "q"
        ]
    assert not observation.rgb and not observation.terminal
    assert env.metrics()["core_only"] is True


def test_move_is_finite_bounded_and_observably_settled(core):
    env, trace, _, _ = core
    target = (0.06, math.atan(0.06 / 0.45), 0.0)
    observation = env.step(
        command(
            1,
            "move_camera",
            slide_m=target[0],
            yaw_rad=target[1],
            pitch_rad=target[2],
            capture_after_settle=False,
        )
    )
    result = terminal(observation)
    assert result.code == "completed"
    assert result.t_terminal_s - result.t_accepted_s > 1.2  # Cannot traverse 6 cm instantaneously.
    measured = [
        m.sample for m in result.measured_confirmation if isinstance(m.sample, EncoderSample)
    ]
    assert len(measured) == 1 and measured[0] in observation.encoders
    np.testing.assert_allclose(
        (measured[0].slide_m, measured[0].yaw_rad, measured[0].pitch_rad),
        target,
        atol=0.001,
        rtol=0,
    )
    rows = [row for row in trace.rows if row["time_s"] >= result.t_accepted_s]
    assert any(0 < row["dynamics"]["q"][0] < target[0] for row in rows)
    rates = np.array((0.05, 0.5, 0.5))
    acceleration = np.array((0.20, 1.0, 1.0))
    previous = np.zeros(3)
    for row in rows:
        state = row["dynamics"]
        ramp_rate = np.asarray(state["setpoint_rate"])
        assert np.all(np.abs(ramp_rate) <= rates + 1e-12)
        assert np.all(np.abs(ramp_rate - previous) <= acceleration * 0.002 + 1e-12)
        previous = ramp_rate
        assert abs(state["q"][0]) <= 0.1501
        assert abs(state["q"][1]) <= math.pi / 4 + 0.001
        assert abs(state["q"][2]) <= math.pi / 6 + 0.001
    assert observation.remaining_budgets.slide_path_m < env.config.budgets.slide_path_m
    assert observation.remaining_budgets.rgb_frames == env.config.budgets.rgb_frames


def test_illegal_target_rejected_before_motion_but_decision_time_is_charged(core):
    env, _, _, _ = core
    before = env.backend.snapshot()
    observation = env.step(
        command(
            1, "move_camera", slide_m=0.151, yaw_rad=0.0, pitch_rad=0.0, capture_after_settle=False
        )
    )
    result = terminal(observation)
    assert result.code == "rejected" and result.reason in {"invalid_payload", "out_of_range"}
    assert result.t_accepted_s is None
    assert env.time_s == before.time_s + 0.2
    assert env.backend.snapshot().q == before.q
    assert env.backend.snapshot().setpoint == before.setpoint
    assert env.ledger.slide_path_m == 0.0
    assert env.ledger.voltage_points == 0 and env.ledger.decisions == 1


def test_load_delay_slew_and_measured_confirmation(core):
    env, trace, _, _ = core
    observation = env.step(command(1, "set_voltage", voltage_v=0.8))
    result = terminal(observation)
    assert result.code == "completed"
    due_tick = round((result.t_accepted_s + 0.1) / 0.002)
    for row in trace.rows:
        if row["tick"] < due_tick:
            assert row["applied_voltage_v"] == 1.8
    moved = [row for row in trace.rows if row["applied_voltage_v"] < 1.8]
    assert moved[0]["tick"] == due_tick
    previous = 1.8
    for row in moved:
        assert abs(row["applied_voltage_v"] - previous) <= 10.0 * 0.002 + 1e-12
        previous = row["applied_voltage_v"]
    assert env.applied_voltage_v == 0.8
    assert result.t_terminal_s >= result.t_accepted_s + 0.1 + 0.1 + 0.2
    confirmation = tuple(m.sample for m in result.measured_confirmation)
    assert {s.channel for s in confirmation} == {"voltage_v", "current_a"}
    assert confirmation[0].t_capture_s == confirmation[1].t_capture_s
    assert all(s in observation.scalars for s in confirmation)
    assert next(s.value for s in confirmation if s.channel == "voltage_v") == pytest.approx(0.8)
    for row in trace.rows:
        point = row["point"]
        assert point["power_w"] == point["voltage_v"] * point["current_a"]


def test_probe_delivers_three_settled_dwell_pairs_and_restores_prior_load(core):
    env, trace, _, _ = core
    observation = env.step(command(1, "probe_voltage", voltages_v=[0.8, 1.8, 3.0], dwell_s=0.5))
    result = terminal(observation)
    assert result.code == "completed"
    points = [f for f in observation.feedback if f.code == "executing" and f.measured_confirmation]
    assert len(points) == 3
    rows = {row["tick"]: row for row in trace.rows}
    captures = []
    stage_start = round(result.t_accepted_s / 0.002) + 1
    for expected, feedback in zip((0.8, 1.8, 3.0), points, strict=True):
        samples = tuple(m.sample for m in feedback.measured_confirmation)
        assert len(samples) == 2
        assert {s.channel for s in samples} == {"voltage_v", "current_a"}
        assert all(s in observation.scalars for s in samples)
        assert samples[0].t_capture_s == samples[1].t_capture_s
        voltage = next(s for s in samples if s.channel == "voltage_v")
        assert voltage.value == pytest.approx(expected, abs=1e-6)
        capture_tick = round(voltage.t_capture_s / 0.002)
        captures.append(capture_tick)
        assert rows[capture_tick]["applied_voltage_v"] == expected
        # A valid point reading must be at least 0.2 s after applied voltage settles.
        reached = next(
            row["tick"]
            for row in trace.rows
            if stage_start <= row["tick"] <= capture_tick
            and row["requested_voltage_v"] == expected
            and row["applied_voltage_v"] == expected
        )
        assert capture_tick - reached >= 100
        subsequent = [
            row
            for row in trace.rows
            if row["tick"] > reached and row["requested_voltage_v"] != expected
        ]
        assert subsequent[0]["tick"] - reached >= 100 + 250
        stage_start = subsequent[0]["tick"]
    assert captures == sorted(captures)
    restored = tuple(m.sample for m in result.measured_confirmation)
    assert next(s.value for s in restored if s.channel == "voltage_v") == pytest.approx(1.8)
    assert min(s.t_capture_s for s in restored) > captures[-1] * 0.002
    assert env.requested_voltage_v == 1.8 and env.applied_voltage_v == 1.8
    assert env.ledger.voltage_points == 3 and not env.disconnected


def test_idempotent_retry_preserves_time_and_budget_conflict_is_charged(core):
    env, _, _, _ = core
    payload = command(1, "set_voltage", voltage_v=0.8)
    first = env.step(payload)
    before = dataclasses.asdict(env.ledger), env.tick, env.backend.snapshot()
    retry = env.step(ACTION_ADAPTER.validate_python(payload))
    assert retry == first
    assert (dataclasses.asdict(env.ledger), env.tick, env.backend.snapshot()) == before
    conflict = env.step(command(1, "set_voltage", voltage_v=3.0))
    assert terminal(conflict).code == "rejected"
    assert terminal(conflict).reason == "command_conflict"
    assert env.ledger.decisions == 2 and env.ledger.voltage_points == 1
    assert env.tick == before[1] + 100
    assert env.requested_voltage_v == 0.8


def test_overbudget_probe_rejected_atomically(config):
    fields = config.model_dump()
    fields["budgets"]["voltage_points"] = 2
    env = PVEnv(Config.model_validate(fields), enable_rendering=False)
    try:
        env.reset(episode_id="budget_fixture")
        observation = env.step(command(1, "probe_voltage", voltages_v=[0.8, 1.8, 3.0], dwell_s=0.5))
        assert terminal(observation).reason == "budget"
        assert terminal(observation).code == "rejected"
        assert env.requested_voltage_v == 1.8 and env.applied_voltage_v == 1.8
        assert env.ledger.voltage_points == 0
        assert env.time_s == 0.22 and env.backend._renderer is None
    finally:
        env.close()


def test_probe_timeout_restores_with_bounded_cleanup_and_no_hidden_success(core):
    env, _, _, _ = core
    observation = env.step(
        command(1, "probe_voltage", timeout_s=0.25, voltages_v=[0.8, 1.8, 3.0], dwell_s=0.5)
    )
    result = terminal(observation)
    assert result.code == "timed_out" and result.reason == "tracking_timeout"
    assert result.t_terminal_s <= result.t_accepted_s + 0.25 + 2.0
    assert not [f for f in observation.feedback if f.code == "executing"]
    assert env.requested_voltage_v == 1.8
    assert env.applied_voltage_v == 1.8 or env.disconnected
    assert env._pending_load is None
    assert env.ledger.voltage_points == 3


def test_set_timeout_cancels_pending_command_and_disconnects(core):
    env, _, _, _ = core
    observation = env.step(command(1, "set_voltage", timeout_s=0.05, voltage_v=0.8))
    assert terminal(observation).code == "timed_out"
    assert env.disconnected and env._pending_load is None
    env.step(command(2, "wait", duration_s=0.5))
    assert env.applied_voltage_v == 1.8  # The cancelled delayed command never arrives later.
    assert env.point.mode == "disconnected" and env.point.current_a == 0.0


def test_move_timeout_brakes_at_reached_pose_without_teleport(core):
    env, _, _, _ = core
    observation = env.step(
        command(
            1,
            "move_camera",
            timeout_s=0.3,
            slide_m=0.12,
            yaw_rad=0.2,
            pitch_rad=0.0,
            capture_after_settle=False,
        )
    )
    assert terminal(observation).code == "timed_out"
    reached = env.backend.snapshot()
    assert 0 < reached.q[0] < 0.12
    env.step(command(2, "wait", duration_s=1.0))
    stopped = env.backend.snapshot()
    assert stopped.q[0] < 0.03  # At most the bounded braking distance after this short ramp.
    assert abs(stopped.qdot[0]) <= 0.005
    assert abs(stopped.qdot[1]) <= 0.02
    assert stopped.q != (0.12, 0.2, 0.0)


def test_safe_stop_reports_actual_disconnected_state_and_new_measurements(core):
    env, _, _, _ = core
    observation = env.step(command(1, "safe_stop", timeout_s=2.0))
    result = terminal(observation)
    assert result.code == "completed"
    assert observation.terminal and observation.terminal_reason == "safe_stop"
    assert env.disconnected and env.point.mode == "disconnected"
    assert env.point.current_a == 0.0 and env.point.power_w == 0.0
    confirmation = tuple(m.sample for m in result.measured_confirmation)
    currents = [s for s in confirmation if isinstance(s, ScalarSample) and s.channel == "current_a"]
    assert currents and all(
        s.value == 0.0 and s.t_capture_s > result.t_accepted_s for s in currents
    )
    assert any(isinstance(s, EncoderSample) for s in confirmation)
    assert env.metrics()["final_operating_point"]["current_a"] == 0.0


def test_finish_retains_load_and_charges_exact_two_second_verification_tail(core):
    env, _, _, _ = core
    before_time, before_energy = env.time_s, env.ledger.pv_energy_j
    observation = env.step(command(1, "finish", timeout_s=2.0, resolution="unresolved"))
    result = terminal(observation)
    assert result.code == "completed"
    assert result.t_terminal_s - result.t_accepted_s == 2.0
    assert env.time_s - before_time == pytest.approx(2.2)
    assert env.ledger.pv_energy_j > before_energy
    assert not env.disconnected and env.applied_voltage_v == 1.8
    assert observation.terminal and observation.terminal_reason == "finished"
    assert env.metrics()["verification_tail_complete"] is True
    assert any(s.t_capture_s > result.t_accepted_s for s in observation.scalars)


def test_move_timeout_returns_measured_stop_before_next_action(core):
    env, _, _, _ = core
    observation = env.step(
        command(
            1,
            "move_camera",
            timeout_s=0.3,
            slide_m=0.12,
            yaw_rad=0.2,
            pitch_rad=0.0,
            capture_after_settle=False,
        )
    )
    result = terminal(observation)
    assert result.code == "timed_out"
    assert result.t_terminal_s <= result.t_accepted_s + 0.3 + 2.0
    state = env.backend.snapshot()
    assert abs(state.qdot[0]) <= 0.005 and abs(state.qdot[1]) <= 0.02
    measured = [
        m.sample for m in result.measured_confirmation if isinstance(m.sample, EncoderSample)
    ]
    assert measured and measured[0].t_capture_s >= result.t_accepted_s + 0.3
    assert measured[0] in observation.encoders


def test_subtick_safe_stop_of_actual_moving_rig_does_not_freeze_motion(core):
    env, _, _, _ = core
    # Trusted safety fixture: build a real moving state through finite backend
    # servos, never write q or replace the backend. This is not policy authority.
    env.backend.command_joint_targets((0.12, 0.2, 0.0))
    env.step(command(1, "wait", duration_s=0.1))
    assert abs(env.backend.snapshot().qdot[0]) > 0.005
    observation = env.step(command(2, "safe_stop", timeout_s=0.001))
    result = terminal(observation)
    assert observation.terminal and observation.terminal_reason == "safe_stop"
    state = env.backend.snapshot()
    assert abs(state.qdot[0]) <= 0.005 and abs(state.qdot[1]) <= 0.02
    assert state.setpoint_rate == (0.0, 0.0, 0.0)
    assert env.point.current_a == 0.0 and env.disconnected
    assert result.code == "timed_out"
    assert result.t_terminal_s <= result.t_accepted_s + 0.001 + 2.0


def test_set_confirmation_timeout_cleans_up_even_after_physical_settle(core):
    env, _, _, _ = core
    # At this deadline the load has settled, but the next eligible 10 Hz
    # measurement has not yet arrived. Ack is not measured completion.
    observation = env.step(command(1, "set_voltage", timeout_s=0.4, voltage_v=0.8))
    result = terminal(observation)
    assert result.code == "timed_out"
    assert env.disconnected and env._pending_load is None
    assert env.point.current_a == 0.0
    assert result.t_terminal_s <= result.t_accepted_s + 0.4 + 2.0


def test_new_set_after_timeout_reconnects_and_verifies_actual_voltage(core):
    env, _, _, _ = core
    failed = env.step(command(1, "set_voltage", timeout_s=0.05, voltage_v=0.8))
    assert terminal(failed).code == "timed_out" and env.disconnected
    observation = env.step(command(2, "set_voltage", voltage_v=0.8))
    result = terminal(observation)
    assert result.code == "completed"
    assert not env.disconnected and env.point.mode == "generating"
    measured = [
        m.sample for m in result.measured_confirmation if isinstance(m.sample, ScalarSample)
    ]
    assert next(s.value for s in measured if s.channel == "voltage_v") == pytest.approx(0.8)
    assert next(s.value for s in measured if s.channel == "current_a") > 0.0


def test_malformed_positive_id_identical_retry_is_cached_without_overhead(core):
    env, _, _, _ = core
    payload = command(
        1, "move_camera", slide_m=0.151, yaw_rad=0.0, pitch_rad=0.0, capture_after_settle=False
    )
    first = env.step(payload)
    assert terminal(first).code == "rejected"
    before = dataclasses.asdict(env.ledger), env.tick, env.backend.snapshot()
    retry = env.step(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    assert retry == first
    assert (dataclasses.asdict(env.ledger), env.tick, env.backend.snapshot()) == before


def test_malformed_positive_id_different_payload_conflicts_and_charges_once(core):
    env, _, _, _ = core
    payload = command(
        1, "move_camera", slide_m=0.151, yaw_rad=0.0, pitch_rad=0.0, capture_after_settle=False
    )
    env.step(payload)
    before_tick = env.tick
    conflict = env.step({**payload, "slide_m": 0.152})
    assert terminal(conflict).code == "rejected"
    assert terminal(conflict).reason == "command_conflict"
    assert env.tick == before_tick + 100 and env.ledger.decisions == 2
    assert env.ledger.slide_path_m == 0.0


def test_explicit_backend_numerical_failure_stops_without_new_invalid_samples(core, monkeypatch):
    env, trace, _, _ = core
    before_tick = env.tick
    before_energy = env.ledger.pv_energy_j

    def nonfinite_dynamics():
        # Explicit failure-path injection only: this never supplies successful
        # dynamics, images or observations in place of the actual backend.
        raise FloatingPointError("test injection: nonfinite dynamics")

    monkeypatch.setattr(env.backend, "advance", nonfinite_dynamics)
    observation = env.step(command(1, "wait", duration_s=0.5))
    assert observation.terminal and observation.terminal_reason == "numerical_error"
    assert terminal(observation).code == "rejected"
    assert env.disconnected and env._pending_load is None
    assert env.tick == before_tick + 1
    assert env.ledger.pv_energy_j == before_energy
    assert not observation.scalars and not observation.encoders and not observation.rgb
    assert trace.rows[-1]["dynamics"] is None
    assert trace.rows[-1]["intervention"] == "nonfinite_dynamics"
    assert trace.rows[-1]["terminal_reason"] == "numerical_error"
    wire = observation.model_dump_json()
    assert "NaN" not in wire and "Infinity" not in wire
    stopped_tick = env.tick
    later = env.step(command(2, "wait", duration_s=0.5))
    assert later.terminal_reason == "numerical_error" and env.tick == stopped_tick
