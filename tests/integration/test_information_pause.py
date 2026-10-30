"""Opt-in information waits on real dynamics; no renderer or external service.

These short fixtures test physical time/accounting and decision-boundary guards.
Recorded-response transport, wall deadlines and retry caching belong to the
separate interaction coordinator tests.
"""

import copy
from dataclasses import asdict
from pathlib import Path

import pytest

from pv_sim.config import Config, load_config
from pv_sim.env import PVEnv, SafetyStopError

ROOT = Path(__file__).resolve().parents[2]


def config(**sections):
    raw = load_config(ROOT / "configs/pilot.toml").model_dump()
    for name, changes in sections.items():
        if isinstance(changes, dict):
            raw[name].update(changes)
        else:
            raw[name] = changes
    return Config.model_validate(raw)


@pytest.fixture
def env():
    instance = PVEnv(config(), enable_rendering=False)
    instance.reset(episode_id="information_boundary")
    yield instance
    assert instance.backend._renderer is None
    instance.close()


def command(action_id=1, kind="wait", timeout_s=1.0, **fields):
    return dict(schema_version="1.0", action_id=action_id, kind=kind,
                timeout_s=timeout_s, **fields)


def state(env):
    """Owned exact values, including queued captures and delivered sample state."""
    return copy.deepcopy({
        "clock": asdict(env.clock),
        "ledger": asdict(env.ledger),
        "dynamics": env.backend.snapshot(),
        "point": env.point,
        "temperature": env.temperature_c,
        "source": env.scene.source,
        "latest_scalars": env._latest_scalars,
        "latest_encoder": env._latest_encoder,
        "buffer": env._buffer,
        "feedback": env._feedback,
        "sequence": env._sequence,
        "action_cache": env._cache,
        "requested_voltage": env.requested_voltage_v,
        "applied_voltage": env.applied_voltage_v,
        "pending_load": env._pending_load,
        "pending_rgb": env._pending_rgb,
    })


def test_wait_advances_only_overhead_then_freezes_captures_queue_and_energy():
    conf = config(
        source_schedule=(
            {"time_s": 0.1, "dni_w_m2": 400.0},
            {"time_s": 0.3, "dni_w_m2": 600.0},
        ),
        sensors={"numeric_latency_s": 0.05},
    )
    paused = PVEnv(conf, enable_rendering=False)
    reference = PVEnv(conf, enable_rendering=False)
    try:
        _, initial = paused.reset(71, episode_id="information_clock")
        reference.reset(71, episode_id="information_clock")
        initial_energy = paused.ledger.pv_energy_j
        observation = paused.begin_information_wait("request-1")
        reference._advance_to(125)
        assert observation.t_deliver_s == paused.time_s == 0.25
        assert observation.sequence_id == initial.sequence_id + 1
        assert observation.remaining_budgets.decisions == conf.budgets.decisions - 1
        assert paused.ledger.decisions == 1
        assert paused.ledger.help_requests == paused.ledger.help_delay_s == 0
        assert paused.ledger.pv_energy_j > initial_energy
        assert paused.temperature_c == reference.temperature_c
        assert paused.point == reference.point
        assert paused.backend.snapshot() == reference.backend.snapshot()
        assert paused.ledger.pv_energy_j == reference.ledger.pv_energy_j
        assert paused.ledger.absorbed_j == reference.ledger.absorbed_j
        # The event inside the overhead has happened; the later event has not.
        assert paused.scene.source.dni_w_m2 == 400
        assert paused.information_wait_pending
        assert paused.clock._queue
        queued = tuple(paused.clock._queue)
        frozen = state(paused)
        attempts = (
            lambda: paused.step(command(duration_s=0.1)),
            lambda: paused.reset(71, episode_id="replacement"),
            lambda: paused.begin_information_wait("request-2"),
            paused._tick,
            lambda: paused._advance_to(paused.tick),
            lambda: paused._advance_to(paused.tick + 100),
            paused._capture_periodic,
            paused._deliver_due,
            paused._observation,
        )
        for attempt in attempts:
            with pytest.raises(RuntimeError, match="information wait is pending"):
                attempt()
            assert state(paused) == frozen
        with pytest.raises(ValueError, match="does not match"):
            paused.end_information_wait("other-request")
        assert state(paused) == frozen and paused.information_wait_pending
        paused.end_information_wait("request-1")
        assert not paused.information_wait_pending and state(paused) == frozen
        resumed = paused.step(command(duration_s=0.1))
        assert resumed.t_deliver_s == pytest.approx(0.55)
        assert paused.scene.source.dni_w_m2 == 600
        for _, _, _, captured in queued:
            assert captured in (*resumed.scalars, *resumed.encoders)
            assert captured.t_capture_s <= 0.25 < captured.t_deliver_s
        assert paused.ledger.decisions == 2
        assert paused.backend._renderer is reference.backend._renderer is None
    finally:
        paused.close()
        reference.close()


@pytest.mark.parametrize("token", [None, 1, True, "", "a b", "a\n", "é", "a" * 129])
def test_invalid_token_rejects_without_charging(env, token):
    before = state(env)
    with pytest.raises(ValueError, match="visible ASCII"):
        env.begin_information_wait(token)
    assert not env.information_wait_pending and state(env) == before


def test_requires_reset_and_exact_resume_without_repeated_charge():
    instance = PVEnv(config(), enable_rendering=False)
    try:
        assert not instance.information_wait_pending
        with pytest.raises(RuntimeError, match="reset must precede"):
            instance.begin_information_wait("first")
        with pytest.raises(RuntimeError, match="no information wait"):
            instance.end_information_wait("first")
        instance.reset(episode_id="resume_contract")
        instance.begin_information_wait("first")
        frozen = state(instance)
        with pytest.raises(ValueError, match="visible ASCII"):
            instance.end_information_wait(1)
        assert state(instance) == frozen and instance.information_wait_pending
        instance.end_information_wait("first")
        with pytest.raises(RuntimeError, match="no information wait"):
            instance.end_information_wait("first")
        assert state(instance) == frozen
        instance.reset(episode_id="after_completed_request")
        assert instance.ledger.decisions == 0 and not instance.information_wait_pending
    finally:
        instance.close()


@pytest.mark.parametrize("condition", ["active", "load", "exposure", "trajectory", "motion"])
def test_rejects_in_flight_work_without_charge(env, condition):
    if condition == "active":
        env._active = True
    elif condition == "load":
        env._set_load(1.2)
    elif condition == "exposure":
        # Only a pending exposure marker; this fixture never calls rendering.
        env._pending_rgb = (env.tick, env.tick + 3, "not_captured")
    else:
        env.backend.command_joint_targets((0.1, 0.3, 0.2))
        if condition == "motion":
            env._advance_to(env.tick + 50)
            assert env.backend.snapshot().qdot[0] > 0.005
        else:
            assert env.backend.snapshot().setpoint_rate == (0.0, 0.0, 0.0)
    before = state(env)
    with pytest.raises(RuntimeError, match="concurrent actions|settled decision boundary"):
        env.begin_information_wait("unsafe-boundary")
    assert state(env) == before and not env.information_wait_pending


def test_completed_physical_move_and_load_allow_information_request(env):
    moved = env.step(command(
        kind="move_camera", timeout_s=4.0, slide_m=0.04, yaw_rad=0.0, pitch_rad=0.0,
        capture_after_settle=False,
    ))
    assert moved.feedback[-1].code == "completed"
    loaded = env.step(command(2, "set_voltage", timeout_s=2.0, voltage_v=1.2))
    assert loaded.feedback[-1].code == "completed"
    before = env.time_s
    observation = env.begin_information_wait("post-action")
    assert observation.t_deliver_s == pytest.approx(before + 0.2)
    assert env.ledger.decisions == 3 and env.information_wait_pending
    env.end_information_wait("post-action")


@pytest.mark.parametrize("remaining", [0, 1])
def test_reserves_a_later_finish_decision(env, remaining):
    env.ledger.decisions = env.config.budgets.decisions - remaining
    before = state(env)
    with pytest.raises(RuntimeError, match="decision budget"):
        env.begin_information_wait("no-decision-room")
    assert state(env) == before and not env.information_wait_pending


def test_exact_time_and_decision_reservation_allows_complete_verification_tail():
    conf = config(simulation={"horizon_s": 3.0}, budgets={"time_s": 3.0, "decisions": 2})
    instance = PVEnv(conf, enable_rendering=False)
    try:
        instance.reset(episode_id="exact-reservation")
        instance._advance_to(300)
        observation = instance.begin_information_wait("last-information")
        assert observation.t_deliver_s == 0.8
        assert observation.remaining_budgets.decisions == 1
        instance.end_information_wait("last-information")
        final = instance.step(command(kind="finish", timeout_s=2.0, resolution="unresolved"))
        assert final.terminal_reason == "finished"
        assert instance.time_s == 3.0 and instance.ledger.decisions == 2
        assert instance.metrics()["verification_tail_complete"]
    finally:
        instance.close()


def test_one_tick_short_of_overheads_and_tail_rejects_without_charge():
    conf = config(simulation={"horizon_s": 3.0}, budgets={"time_s": 3.0})
    instance = PVEnv(conf, enable_rendering=False)
    try:
        instance.reset(episode_id="insufficient-reservation")
        instance._advance_to(301)
        before = state(instance)
        with pytest.raises(RuntimeError, match="time budget"):
            instance.begin_information_wait("no-time-room")
        assert state(instance) == before and not instance.information_wait_pending
    finally:
        instance.close()


def test_safety_trip_during_overhead_is_terminal_without_stranded_pause():
    instance = PVEnv(config(thermal={"trip_temperature_c": 25.2}), enable_rendering=False)
    try:
        instance.reset(episode_id="overhead-protection")
        assert not instance.terminal_reason
        observation = instance.begin_information_wait("trip-during-overhead")
        assert observation.terminal_reason == "thermal_trip"
        assert instance.disconnected and instance.ledger.decisions == 1
        assert not instance._active and not instance.information_wait_pending
        assert instance.time_s < 0.22
        before = state(instance)
        with pytest.raises(RuntimeError, match="terminal episode"):
            instance.begin_information_wait("after-trip")
        assert state(instance) == before
    finally:
        instance.close()


def test_travel_guard_during_overhead_uses_existing_measured_stop(env):
    # Evaluator-side accounting fault activates the normally preventive guard.
    env.ledger.slide_path_m = env.config.budgets.slide_path_m + 0.001
    observation = env.begin_information_wait("overhead-budget-stop")
    assert observation.terminal_reason == "safe_stop"
    assert not env.information_wait_pending and not env._active
    assert env.disconnected and env.point.current_a == 0
    assert env.ledger.decisions == 1
    assert env._latest_encoder.t_capture_s > env._budget_stop_tick * env.clock.dt_s
    assert env._latest_scalars["current_a"].t_capture_s > env._budget_stop_tick * env.clock.dt_s


@pytest.mark.parametrize("failure", ["_stop_failed", "_budget_stop_failed"])
def test_unconfirmed_stop_cannot_be_paused(env, failure):
    setattr(env, failure, True)
    before = state(env)
    with pytest.raises(SafetyStopError, match="reset is required"):
        env.begin_information_wait("unconfirmed-stop")
    assert state(env) == before and not env.information_wait_pending


def test_legacy_physical_retry_remains_cached_and_legacy_help_remains_unavailable(env):
    original = env.step(command(duration_s=0.1))
    env.begin_information_wait("intervening-request")
    env.end_information_wait("intervening-request")
    before = state(env)
    assert env.step(command(duration_s=0.1)) == original
    assert state(env) == before
    result = env.step(command(2, "request_help", measurement="reference_irradiance"))
    assert result.feedback[-1].code == "rejected"
    assert result.feedback[-1].reason == "sensor_unavailable"
    assert env.task.available_help == ()
    assert env.ledger.help_requests == env.ledger.help_delay_s == 0
