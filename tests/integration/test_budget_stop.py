"""Travel-guard fault fixtures with actual MuJoCo dynamics; no GL or pilot runs.

The ledger injection deliberately reaches a guard normally prevented by the
conservative action gate. It changes no q/qdot, servo gains, or sensor values.
"""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest

from pv_sim.config import Config, load_config
from pv_sim.contracts import EncoderSample, ScalarSample
from pv_sim.env import PVEnv, SafetyStopError

ROOT = Path(__file__).resolve().parents[2]
RATE_LIMITS = np.asarray((0.005, 0.02, 0.02))  # Frozen ADR 0008 measured-stop criteria.


def command(action_id, kind="wait", timeout_s=8.0, **fields):
    return dict(schema_version="1.0", action_id=action_id, kind=kind, timeout_s=timeout_s, **fields)


class BudgetTrace:
    """Record every actual tick, with one explicit evaluator-side budget injection."""

    def __init__(self):
        self.rows = []
        self.env = None
        self.inject_tick = None
        self.resource = None
        self.offset = 0.0

    def start(self, config, seed, task):
        pass

    def action(self, action, tick):
        pass

    def observation(self, observation, *, tick):
        pass

    def truth(self, row):
        self.rows.append(row)
        if row["tick"] == self.inject_tick:
            if self.resource == "slide":
                previous = self.env.ledger.slide_path_m
                self.env.ledger.slide_path_m = self.env.config.budgets.slide_path_m + 0.001
                self.offset = self.env.ledger.slide_path_m - previous
            else:
                previous = self.env.ledger.yaw_path_rad
                self.env.ledger.yaw_path_rad = self.env.config.budgets.angular_path_rad + 0.001
                self.offset = self.env.ledger.yaw_path_rad - previous

    def arm(self, resource, *, after_accept_ticks=25):
        self.resource = resource
        overhead = round(self.env.config.simulation.decision_overhead_s / 0.002)
        self.inject_tick = self.env.tick + overhead + after_accept_ticks - 1
        return self.inject_tick + 1


@pytest.fixture
def moving_core():
    config = load_config(ROOT / "configs/pilot.toml")
    trace = BudgetTrace()
    env = PVEnv(config, enable_rendering=False, recorder=trace)
    trace.env = env
    env.reset(episode_id="budget_stop_fixture")
    # Start a genuine finite trajectory from the evaluator, then advance it
    # through the same world clock. This is a short action-integrity fixture.
    env.backend.command_joint_targets((0.15, 0.7, 0.5))
    env.step(command(1, duration_s=0.2))
    assert env.backend.snapshot().qdot[0] > 0.04
    assert env.backend.snapshot().qdot[1] > 0.3
    yield env, trace
    assert env.backend._renderer is None
    assert env.time_s < 8.0
    env.close()


def _result(observation):
    return next(
        f for f in reversed(observation.feedback) if f.code not in ("accepted", "executing")
    )


def _assert_confirmed_budget_stop(
    env, trace, observation, trigger_tick, *, expected_code="cancelled"
):
    state = env.backend.snapshot()
    print(
        {
            "trigger_tick": trigger_tick,
            "final_tick": env.tick,
            "actual_rate": state.qdot,
            "terminal": observation.terminal_reason,
            "feedback": _result(observation).code,
        }
    )
    assert observation.terminal and observation.terminal_reason == "safe_stop"
    assert np.all(np.abs(state.qdot) <= RATE_LIMITS)
    assert state.setpoint_rate == (0.0, 0.0, 0.0)
    assert env.disconnected and env.point.current_a == 0.0
    assert env._pending_load is None and env._pending_rgb is None
    assert not env._verification_tail_complete
    assert _result(observation).code == expected_code
    assert _result(observation).reason == "budget"
    assert not any(f.code == "completed" for f in observation.feedback)
    assert trigger_tick < env.tick <= trigger_tick + 1000
    assert env.ledger.elapsed_s == env.tick * 0.002
    assert len(trace.rows) == env.tick + 1  # Exactly one recorded state per actual tick.

    rows = {row["tick"]: row for row in trace.rows}
    after = [row for row in trace.rows if row["tick"] > trigger_tick]
    assert all(row["disconnected"] and row["point"]["current_a"] == 0.0 for row in after)
    assert state.q != (0.15, 0.7, 0.5)  # Stopped at reached pose, never the requested endpoint.
    for row in trace.rows[-100:]:
        assert np.all(np.abs(row["dynamics"]["qdot"]) <= RATE_LIMITS)
        assert row["dynamics"]["setpoint_rate"] == (0.0, 0.0, 0.0)
    samples = tuple(m.sample for m in _result(observation).measured_confirmation)
    encoders = [sample for sample in samples if isinstance(sample, EncoderSample)]
    scalars = [sample for sample in samples if isinstance(sample, ScalarSample)]
    assert len(encoders) == 1
    assert {sample.channel for sample in scalars} == {"voltage_v", "current_a"}
    for sample in samples:
        assert sample.t_capture_s > trigger_tick * 0.002
        assert sample.t_deliver_s <= observation.t_deliver_s
    assert encoders[0] in observation.encoders
    assert all(sample in observation.scalars for sample in scalars)
    measured = encoders[0]
    captured = rows[round(measured.t_capture_s / 0.002)]["dynamics"]
    assert (measured.slide_m, measured.yaw_rad, measured.pitch_rad) == captured["q"]
    assert next(s.value for s in scalars if s.channel == "current_a") == 0.0
    assert all(sample.t_capture_s == scalars[0].t_capture_s for sample in scalars)

    # Independent absolute-path integration includes all braking travel exactly
    # once; subtract only the deliberately injected ledger offset.
    positions = [row["dynamics"]["q"] for row in trace.rows]
    actual = tuple(
        math.fsum(abs(b[axis] - a[axis]) for a, b in zip(positions, positions[1:]))
        for axis in range(3)
    )
    charged = (
        env.ledger.slide_path_m - (trace.offset if trace.resource == "slide" else 0.0),
        env.ledger.yaw_path_rad - (trace.offset if trace.resource == "angular" else 0.0),
        env.ledger.pitch_path_rad,
    )
    np.testing.assert_allclose(charged, actual, rtol=0, atol=1e-10)


@pytest.mark.parametrize("resource", ["slide", "angular"])
def test_actual_budget_overrun_brakes_and_confirms_before_terminal(moving_core, resource):
    env, trace = moving_core
    trigger = trace.arm(resource)
    payload = command(2, duration_s=1.0)
    observation = env.step(payload)
    _assert_confirmed_budget_stop(env, trace, observation, trigger)
    before = dataclasses.asdict(env.ledger), env.tick, env.backend.snapshot()
    assert env.step(payload) == observation  # Retrying the cancelled action remains idempotent.
    assert (dataclasses.asdict(env.ledger), env.tick, env.backend.snapshot()) == before


@pytest.mark.parametrize(
    "kind,fields",
    [
        ("wait", {"duration_s": 0.1}),
        ("set_voltage", {"voltage_v": 0.8}),
        ("probe_voltage", {"voltages_v": [0.8, 1.8, 3.0], "dwell_s": 0.2}),
        ("finish", {"resolution": "unresolved"}),
        (
            "move_camera",
            {"slide_m": 0.12, "yaw_rad": 0.5, "pitch_rad": 0.3, "capture_after_settle": False},
        ),
    ],
)
def test_budget_stop_cancels_each_running_action_without_continuing_it(moving_core, kind, fields):
    env, trace = moving_core
    # For Wait the trigger is exactly its completion tick. It must still be
    # cancelled, rather than pass a time-only completion check during cleanup.
    trigger = trace.arm("slide", after_accept_ticks=50 if kind == "wait" else 25)
    observation = env.step(command(2, kind, **fields))
    _assert_confirmed_budget_stop(env, trace, observation, trigger)
    if kind in ("set_voltage", "probe_voltage"):
        assert env.applied_voltage_v == 1.8  # Cancelled before delayed load application.


def test_horizon_can_interrupt_budget_braking_without_claiming_safe_stop(moving_core):
    env, trace = moving_core
    trigger = trace.arm("angular")
    env._horizon = trigger + 10  # Controlled short-horizon protection fixture.
    observation = env.step(command(2, duration_s=1.0))
    assert observation.terminal_reason == "horizon"
    assert env.tick == env._horizon
    assert np.any(np.abs(env.backend.snapshot().qdot) > RATE_LIMITS)
    assert _result(observation).code == "cancelled" and _result(observation).reason == "budget"
    assert env.disconnected and not env._verification_tail_complete
    assert not any(f.code == "completed" for f in observation.feedback)


def test_guard_during_decision_overhead_rejects_before_acceptance(moving_core):
    env, trace = moving_core
    trigger = trace.arm("slide", after_accept_ticks=-50)
    observation = env.step(command(2, "set_voltage", voltage_v=0.8))
    _assert_confirmed_budget_stop(env, trace, observation, trigger, expected_code="rejected")
    assert _result(observation).t_accepted_s is None
    assert not any(f.code == "accepted" for f in observation.feedback)
    assert env.ledger.voltage_points == 0 and env.applied_voltage_v == 1.8


def test_unconfirmed_budget_stop_is_bounded_error_and_cannot_resume():
    fields = load_config(ROOT / "configs/pilot.toml").model_dump()
    # A deterministic delivery-delay fixture, not fabricated sensor readings.
    # Braking succeeds, but new V/I cannot arrive within the unchanged 2s tail.
    fields["sensors"]["numeric_latency_s"] = 3.0
    trace = BudgetTrace()
    env = PVEnv(Config.model_validate(fields), enable_rendering=False, recorder=trace)
    trace.env = env
    try:
        env.reset(episode_id="budget_stop_unconfirmed")
        env.backend.command_joint_targets((0.15, 0.7, 0.5))
        env.step(command(1, duration_s=0.2))
        trigger = trace.arm("slide")
        with pytest.raises(SafetyStopError, match="bounded measured confirmation"):
            env.step(command(2, duration_s=1.0))
        assert env.tick == trigger + 1000
        assert env.terminal_reason is None  # No unsupported successful-stop claim.
        assert env.disconnected and not env._active
        assert np.all(np.abs(env.backend.snapshot().qdot) <= RATE_LIMITS)
        assert env.ledger.elapsed_s == env.time_s
        before = env.tick, dataclasses.asdict(env.ledger), env.backend.snapshot()
        with pytest.raises(SafetyStopError, match="reset is required"):
            env.step(command(3, duration_s=0.1))
        assert (env.tick, dataclasses.asdict(env.ledger), env.backend.snapshot()) == before
        assert env.backend._renderer is None and env.time_s < 8.0
    finally:
        env.close()
