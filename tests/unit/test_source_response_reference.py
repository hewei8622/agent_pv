"""Hand-derived checks for the evaluator-only uniform source-change reference."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "source_response_reference", ROOT / "scripts/source_response_reference.py"
)
assert SPEC is not None and SPEC.loader is not None
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)


@pytest.mark.parametrize(
    "voltage,expected_current,expected_power",
    [(1.8, 0.625, 1.125), (2.4, 0.5, 1.2), (1.2, 0.75, 0.9)],
)
def test_reference_conditions_have_hand_solved_series_current(
    voltage, expected_current, expected_power
):
    # E=1000 and T=25 give I_sc=1 A and eight*.6=4.8 V open circuit.
    assert reference.current(1000.0, 25.0, voltage) == pytest.approx(
        expected_current, abs=1e-14
    )
    assert reference.power(1000.0, 25.0, voltage) == pytest.approx(expected_power, abs=1e-14)


@pytest.fixture(scope="module")
def traces():
    return (
        reference.integrate(sample_dt_s=0.1),
        reference.integrate(event_s=None, sample_dt_s=0.1),
    )


def test_event_preserves_previous_interval_energy_and_continuous_temperature(traces):
    treatment, control = traces
    changed = next(sample for sample in treatment if sample["time_s"] == 2.0)
    unchanged = next(sample for sample in control if sample["time_s"] == 2.0)
    for channel in ("temperature_c", "absorbed_j", "electrical_j", "heat_loss_j"):
        assert changed[channel] == unchanged[channel]
    assert changed["absorbed_j"] == pytest.approx(97.2, abs=1e-12)
    assert changed["irradiance_w_m2"] == 500.0
    assert unchanged["irradiance_w_m2"] == 900.0
    assert changed["current_a"] < unchanged["current_a"]
    assert changed["power_w"] < unchanged["power_w"]
    assert all(
        a == b
        for a, b in zip(treatment, control, strict=True)
        if a["time_s"] < 2.0
    )


def test_lower_source_slows_heating_without_claiming_cooling(traces):
    treatment, control = traces
    assert all(
        later["temperature_c"] > earlier["temperature_c"]
        for earlier, later in zip(treatment, treatment[1:])
    )
    assert 25 < treatment[-1]["temperature_c"] < control[-1]["temperature_c"]
    assert treatment[-1]["electrical_j"] < control[-1]["electrical_j"]
    assert treatment[-1]["absorbed_j"] == pytest.approx(259.2, abs=1e-12)
    assert control[-1]["absorbed_j"] == pytest.approx(388.8, abs=1e-12)


def test_continuous_reference_conserves_energy(traces):
    for trace in traces:
        for sample in trace:
            residual = (
                sample["absorbed_j"]
                - sample["electrical_j"]
                - sample["heat_loss_j"]
                - 30.0 * (sample["temperature_c"] - 25.0)
            )
            assert abs(residual) < 2e-9


def test_reference_step_halving_meets_predeclared_tolerance():
    coarse = reference.integrate(duration_s=12.0, step_s=0.0005, sample_dt_s=0.1)
    fine = reference.integrate(duration_s=12.0, step_s=0.00025, sample_dt_s=0.1)
    assert [row["time_s"] for row in coarse] == [row["time_s"] for row in fine]
    error = max(
        abs(a["temperature_c"] - b["temperature_c"])
        for a, b in zip(coarse, fine, strict=True)
    )
    assert error <= reference.DEVELOPMENT_TOLERANCES["reference_refinement_temperature_c_abs"]
    assert abs(coarse[-1]["electrical_j"] - fine[-1]["electrical_j"]) < 1e-9


def test_off_grid_event_is_split_and_final_endpoint_is_retained():
    samples = reference.integrate(duration_s=0.103, event_s=0.037, sample_dt_s=0.02)
    assert [sample["time_s"] for sample in samples] == [
        0.0, 0.02, 0.037, 0.04, 0.06, 0.08, 0.1, 0.103
    ]
    event = samples[2]
    assert event["irradiance_w_m2"] == 500.0
    assert event["absorbed_j"] == pytest.approx(48.6 * 0.037, abs=1e-12)
    assert samples[-1]["absorbed_j"] == pytest.approx(
        48.6 * 0.037 + 27.0 * (0.103 - 0.037), abs=1e-12
    )


@pytest.mark.parametrize("event", [0.0, 0.1])
def test_boundary_event_is_right_continuous(event):
    samples = reference.integrate(duration_s=0.1, event_s=event, sample_dt_s=0.1)
    assert samples[-1]["irradiance_w_m2"] == 500.0
    assert samples[0]["irradiance_w_m2"] == (500.0 if event == 0 else 900.0)
    assert samples[-1]["absorbed_j"] == pytest.approx(27.0 * 0.1 if event == 0 else 48.6 * 0.1)


@pytest.mark.parametrize(
    "irradiance,temperature,voltage",
    [(0, 25, 1.8), (-1, 25, 1.8), (1000, 25, 4.8), (1000, 25, 0),
     (1000, 25, -1), (1000, float("nan"), 1.8), (True, 25, 1.8),
     (10000, 25, 1.8)],
)
def test_algebraic_reference_rejects_unsupported_branch(irradiance, temperature, voltage):
    with pytest.raises(ValueError):
        reference.current(irradiance, temperature, voltage)


@pytest.mark.parametrize(
    "kwargs",
    [{"duration_s": 0}, {"duration_s": 12.1}, {"event_s": -1}, {"event_s": 9},
     {"step_s": 0}, {"sample_dt_s": -1}, {"event_s": float("inf")},
     {"step_s": True}],
)
def test_reference_integrator_rejects_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        reference.integrate(**kwargs)
