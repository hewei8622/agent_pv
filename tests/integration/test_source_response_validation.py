"""Independent response checks and mutations that must fail the evidence gate."""

import copy
import sys
from pathlib import Path

import pytest

SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from source_response_fixture import run_fixture  # noqa: E402
from validate_source_response import check_numeric, check_pair  # noqa: E402


@pytest.fixture(scope="module")
def paired():
    return run_fixture(False), run_fixture(True)


def test_control_and_changed_source_match_independent_reference(paired):
    for changed, (trace, ledger) in zip((False, True), paired, strict=True):
        result, _ = check_numeric(trace, ledger, changed=changed)
        assert result["checks"] == "passed"
    assert all(check_pair(paired[0][0], paired[1][0]).values())


def test_wrong_current_cannot_pass_a_correct_irradiance_label(paired):
    trace, ledger = copy.deepcopy(paired[1])
    trace.rows[1000]["point"]["current_a"] += 0.01
    with pytest.raises(AssertionError, match="P=VI|current_a"):
        check_numeric(trace, ledger, changed=True)


def test_delivered_value_from_the_wrong_time_is_detected(paired):
    trace, ledger = copy.deepcopy(paired[1])
    sample = next(
        s
        for obs in trace.observations
        for s in obs["payload"]["scalars"]
        if s["channel"] == "reference_w_m2" and s["t_capture_s"] == 2.0
    )
    sample["value"] = 900.0
    with pytest.raises(AssertionError, match="delivered measurement"):
        check_numeric(trace, ledger, changed=True)


def test_one_tick_backdated_absorbed_energy_is_detected(paired):
    trace, ledger = copy.deepcopy(paired[1])
    ledger["absorbed_j"] -= (48.6 - 27.0) * 0.002
    with pytest.raises(AssertionError, match="absorbed_energy"):
        check_numeric(trace, ledger, changed=True)


def test_missing_capture_is_not_counted_as_a_complete_observation_record(paired):
    trace, ledger = copy.deepcopy(paired[1])
    trace.observations[0]["payload"]["scalars"].pop()
    with pytest.raises(AssertionError, match="coverage"):
        check_numeric(trace, ledger, changed=True)


def test_private_schedule_in_public_task_fails_pair_check(paired):
    control, changed = copy.deepcopy((paired[0][0], paired[1][0]))
    changed.task["source_schedule"] = [{"time_s": 2.0, "dni_w_m2": 400.0}]
    with pytest.raises(AssertionError, match="public task"):
        check_pair(control, changed)


def test_subtick_timestamp_shift_cannot_pass_tick_rounding(paired):
    trace, ledger = copy.deepcopy(paired[1])
    sample = next(
        s
        for obs in trace.observations
        for s in obs["payload"]["scalars"]
        if s["channel"] == "reference_w_m2" and abs(s["t_capture_s"] - 1.9) < 1e-12
    )
    sample["t_capture_s"] += 0.0001
    sample["t_deliver_s"] += 0.0001
    with pytest.raises(AssertionError, match="acquisition grid"):
        check_numeric(trace, ledger, changed=True)


def test_future_packet_in_earlier_observation_is_rejected(paired):
    trace, ledger = copy.deepcopy(paired[1])
    for obs in trace.observations:
        sample = next((s for s in obs["payload"]["scalars"] if s["t_capture_s"] == 2.0), None)
        if sample is not None:
            obs["payload"]["scalars"].remove(sample)
            trace.observations[0]["payload"]["scalars"].append(sample)
            break
    with pytest.raises(AssertionError, match="first eligible observation"):
        check_numeric(trace, ledger, changed=True)
