"""Isolated integer timing, immutable sample retention, and dimensional ledger tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pv_sim.actions import gate, required_tokens
from pv_sim.config import load_config
from pv_sim.contracts import Finish, ProbeVoltage, SafeStop, ScalarSample, Wait
from pv_sim.costs import Ledger
from pv_sim.scheduler import Scheduler, ticks
from pv_sim.sensors import build_public_task

ROOT = Path(__file__).resolve().parents[2]


def _sample(value, capture_tick, delivery_tick):
    return ScalarSample(
        channel="voltage_v",
        value=value,
        sigma=0.0,
        sensor_id="v",
        t_capture_s=capture_tick * 0.002,
        t_deliver_s=delivery_tick * 0.002,
        validity="valid",
    )


def test_integer_rounding_preserves_exposure_midpoint_and_deadline():
    assert ticks(0.012, 0.002) == 6
    assert ticks(0.006, 0.002) == 3
    assert ticks(0.003, 0.002, rounding="up") == 2
    assert ticks(0.003, 0.002, rounding="down") == 1
    assert ticks(0.3, 0.002) == 150
    with pytest.raises(ValueError):
        ticks(0.003, 0.002)
    for invalid in (-0.1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ticks(invalid, 0.002)


def test_delivery_tick_boundary_and_stable_same_kind_sequence():
    clock = Scheduler(0.002)
    late = _sample(3.0, 0, 5)
    first, second = _sample(1.0, 0, 2), _sample(2.0, 0, 2)
    clock.enqueue(5, late)
    clock.enqueue(2, first)
    clock.enqueue(2, second)
    clock.tick = 1
    assert clock.deliver() == ()
    clock.tick = 2
    assert clock.deliver() == (first, second)
    assert clock.deliver() == ()  # Delivery removes each event exactly once.
    clock.tick = 5
    assert clock.deliver() == (late,)
    assert clock.time_s == 0.010
    with pytest.raises(ValueError, match="past"):
        clock.enqueue(4, first)


def test_simultaneous_events_sort_by_kind_then_sequence():
    clock = Scheduler(0.002)
    rgb, encoder = _sample(3.0, 0, 5), _sample(2.0, 0, 5)
    first, second = _sample(1.0, 0, 5), _sample(1.5, 0, 5)
    clock.enqueue(5, rgb, event_kind="rgb")
    clock.enqueue(5, encoder, event_kind="encoder")
    clock.enqueue(5, first)
    clock.enqueue(5, second, event_kind="scalar")
    clock.tick = 5
    assert clock.deliver() == (first, second, encoder, rgb)
    clock.enqueue(5, first)  # Declared zero latency may deliver at current tick.
    assert clock.deliver() == (first,)


@pytest.mark.parametrize("dt", [0.0, -0.002, float("nan"), float("inf"), True, ".002"])
def test_invalid_clock_timestep_rejected(dt):
    with pytest.raises(ValueError):
        Scheduler(dt)
    with pytest.raises(ValueError):
        ticks(0.1, dt)


@pytest.mark.parametrize("tick", [-1, 0.5, 1.0, True, float("nan"), "5"])
def test_noninteger_or_negative_queue_ticks_rejected(tick):
    clock = Scheduler(0.002)
    with pytest.raises(ValueError):
        clock.enqueue(tick, _sample(1.0, 0, 5))
    assert clock.deliver() == ()
    with pytest.raises(ValueError):
        Scheduler(0.002, tick=tick)


def test_unknown_kind_and_rounding_do_not_silently_default():
    with pytest.raises(ValueError, match="kind"):
        Scheduler(0.002).enqueue(5, _sample(1.0, 0, 5), event_kind="other")
    with pytest.raises(ValueError, match="rounding"):
        ticks(0.1, 0.002, rounding="nearest")


def test_queued_capture_is_an_immutable_historical_value():
    clock = Scheduler(0.002)
    current = _sample(1.0, 0, 5)
    clock.enqueue(5, current)
    with pytest.raises(ValidationError):
        current.value = 9.0
    current = _sample(9.0, 4, 9)
    clock.enqueue(9, current)
    clock.tick = 5
    delivered = clock.deliver()
    assert delivered[0].value == 1.0
    assert delivered[0].t_capture_s == 0.0
    assert delivered[0].t_deliver_s == 0.010
    assert current.value == 9.0


def test_ledger_raw_units_and_energy_balance_remain_separate_from_utility():
    config = load_config(ROOT / "configs/pilot.toml")
    ledger = Ledger(
        elapsed_s=1.25,
        policy_wall_s=0.7,
        decisions=3,
        rgb_frames=2,
        voltage_points=3,
        slide_path_m=0.2,
        yaw_path_rad=0.3,
        pitch_path_rad=0.4,
        help_requests=1,
        pv_energy_j=120.0,
        potential_energy_j=150.0,
        actuator_work_j=9.0,
        absorbed_j=200.0,
        heat_loss_j=60.0,
        storage_j=20.0,
    )
    report = ledger.report(config)
    assert report["pv_energy_j"] == 120.0
    assert report["actuator_work_j"] == 9.0
    assert report["policy_wall_s"] == 0.7
    assert report["elapsed_s"] == 1.25
    assert report["synthetic_dimensionless_utility"] == pytest.approx(0.065)
    assert report["energy_balance_residual_j"] == 0.0
    remaining = ledger.remaining(config)
    assert remaining.time_s == 58.75
    assert remaining.decisions == 97 and remaining.rgb_frames == 18
    assert remaining.voltage_points == 9 and remaining.help_requests == 0
    assert remaining.slide_path_m == 1.3
    assert remaining.angular_path_rad == pytest.approx(5.3)
    # Ambient heating can make heat_loss_j negative; retain its physical sign.
    below_ambient = Ledger(absorbed_j=5.0, pv_energy_j=2.0, heat_loss_j=-1.0, storage_j=4.0)
    assert below_ambient.report(config)["energy_balance_residual_j"] == 0.0


def test_atomic_probe_token_gate_and_reserved_tail():
    config = load_config(ROOT / "configs/pilot.toml")
    task = build_public_task(config, "scheduler_fixture", enable_rendering=False)
    ledger = Ledger(voltage_points=10)
    probe = ProbeVoltage(
        schema_version="1.0",
        action_id=1,
        timeout_s=4.0,
        kind="probe_voltage",
        voltages_v=(1.0, 2.0, 3.0),
        dwell_s=0.2,
    )
    assert required_tokens(probe) == (0, 3)
    assert gate(probe, task, ledger.remaining(config), config, (0.0, 0.0, 0.0)) == "budget"
    assert ledger.voltage_points == 10  # Gate neither executes nor partially charges work.
    ledger.elapsed_s = 57.0
    wait = Wait(schema_version="1.0", action_id=2, timeout_s=2.0, kind="wait", duration_s=0.1)
    assert gate(wait, task, ledger.remaining(config), config, (0.0, 0.0, 0.0)) == "budget"
    finish = Finish(
        schema_version="1.0", action_id=3, timeout_s=2.0, kind="finish", resolution="unresolved"
    )
    assert gate(finish, task, ledger.remaining(config), config, (0.0, 0.0, 0.0)) is None
    ledger.elapsed_s = 60.0
    ledger.decisions = 100
    stop = SafeStop(schema_version="1.0", action_id=4, timeout_s=1.0, kind="safe_stop")
    assert gate(stop, task, ledger.remaining(config), config, (0.0, 0.0, 0.0)) is None
