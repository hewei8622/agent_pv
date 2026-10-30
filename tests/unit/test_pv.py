"""Independent closed-form expectations for the declared synthetic IV model."""

import math
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from pv_sim.config import Config, load_config
from pv_sim.pv import NumericalError, PVModel
from pv_sim.thermal import EnergyBalanceError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config():
    return load_config(ROOT / "configs/pilot.toml")


def changed(config, section, **updates):
    data = config.model_dump()
    data[section].update(updates)
    return Config.model_validate(data)


@pytest.mark.parametrize("requested", [0.2, 0.8, 1.8, 2.4, 3.0, 4.0])
def test_uniform_analytic_series_and_power_identity(config, requested):
    point = PVModel(config).operate((1000.0,) * 8, 25.0, requested)
    assert point.current_a == pytest.approx(1 - requested / 4.8, abs=1e-14)
    assert point.voltage_v == pytest.approx(requested, abs=1e-14)
    assert point.open_circuit_voltage_v == pytest.approx(4.8)
    assert point.power_w == pytest.approx(requested * (1 - requested / 4.8), abs=1e-14)
    assert point.power_w == point.voltage_v * point.current_a
    assert point.mode == "generating"


@pytest.mark.parametrize("temperature", [0.0, 25.0, 60.0, 89.0])
def test_temperature_and_connection_resistance_closed_form(config, temperature):
    model = PVModel(changed(config, "private_world", series_resistance_ohm=0.7))
    isc = 0.9 * (1 + 0.0005 * (temperature - 25))
    voc = 8 * (0.6 - 0.002 * (temperature - 25) + 0.03 * math.log(0.9))
    point = model.operate((900.0,) * 8, temperature, 1.8)
    assert point.current_a == pytest.approx((voc - 1.8) / (voc / isc + 0.7), abs=1e-14)
    assert point.power_w == point.voltage_v * point.current_a


def test_dark_substring_independent_breakpoints(config):
    model = PVModel(config)
    irradiance = (0.0,) * 4 + (1000.0,) * 4
    # Dark row reaches bypass at I=.3/4=.075 A. Bright row reaches bypass
    # at I=1+.3/4=1.075 A. These reference pieces are hand-derived.
    pieces = [
        (0.0, 0.075, 2.4, -6.4),
        (0.075, 1.0, 2.1, -2.4),
        (1.0, 1.075, 3.7, -4.0),
        (1.075, 2.0, -0.6, 0.0),
    ]
    for low, high, intercept, slope in pieces:
        for current in (low, (low + high) / 2, high):
            assert model.module_voltage(current, irradiance, 25.0) == pytest.approx(
                intercept + slope * current, abs=1e-14
            )
    for request, expected_i in [(2.2, 0.2 / 6.4), (1.8, 0.3 / 2.4), (0.2, 1.9 / 2.4)]:
        point = model.operate(irradiance, 25.0, request)
        assert point.current_a == pytest.approx(expected_i, abs=1e-14)


def test_partial_shade_topology_and_bypass(config):
    model = PVModel(config)
    irradiance = (0.0,) + (1000.0,) * 7
    # First row: 3*.6*(1-I)-I = 1.8-2.8I, bypass at .75 A.
    for request, expected_i in [(1.8, 2.4 / 5.2), (0.2, 1.9 / 2.4)]:
        point = model.operate(irradiance, 25.0, request)
        assert point.current_a == pytest.approx(expected_i, abs=1e-14)
    grouped = (0.0,) * 4 + (1000.0,) * 4
    scattered = (0.0, 1000.0) * 4
    assert model.module_voltage(0.5, grouped, 25.0) == pytest.approx(0.9)
    assert model.module_voltage(0.5, scattered, 25.0) == pytest.approx(-0.6)


@pytest.mark.parametrize("requested", [0.2, 0.5, 1.0, 1.8, 2.4, 3.0, 4.0])
def test_asymmetric_substrings_analytic_root(config, requested):
    model = PVModel(config)
    irradiance = (200.0,) * 4 + (1000.0,) * 4
    weak_voc = 0.6 + 0.03 * math.log(0.2)
    # Three physically distinct positive-voltage linear pieces, derived by hand.
    if requested >= 1.92:
        expected = (4 * weak_voc + 2.4 - requested) / (20 * weak_voc + 2.4)
    elif requested >= 1.44:
        expected = (3.2 - requested) / 6.4
    else:
        expected = (2.1 - requested) / 2.4
    point = model.operate(irradiance, 25.0, requested)
    assert point.current_a == pytest.approx(expected, abs=1e-13)
    assert abs(point.voltage_v - requested) <= 1e-6


def test_disconnection_open_circuit_and_blackout(config):
    model = PVModel(config)
    disconnected = model.operate((1000.0,) * 8, 25.0, 0.2, disconnected=True)
    assert disconnected.voltage_v == pytest.approx(4.8)
    assert disconnected.current_a == disconnected.power_w == 0
    assert disconnected.mode == "disconnected"
    # At 89 C and low E, measured open circuit is below the valid 4 V command.
    dim = model.operate((10.0,) * 8, 89.0, 4.0)
    assert dim.voltage_v == pytest.approx(8 * (0.6 - 0.002 * 64 + 0.03 * math.log(0.01)))
    assert dim.current_a == dim.power_w == 0 and dim.mode == "open_circuit"
    black = model.operate((0.0,) * 8, 25.0, 1.8)
    assert black.voltage_v == black.current_a == black.power_w == 0
    assert black.mode == "blackout"
    # Positive input can give zero Voc without being a blackout.
    zero_voc = model.operate((1e-12,) * 8, 25.0, 0.2)
    assert zero_voc.voltage_v == zero_voc.current_a == 0
    assert zero_voc.mode == "open_circuit"
    with pytest.raises(FrozenInstanceError):
        black.power_w = 1.0


def test_lowest_root_convention_on_flat_fixture(config):
    class FlatVoltageFixture(PVModel):
        def _voltage(self, current_a, cells):
            if current_a < 0.4:
                return 2 - 2.5 * current_a
            if current_a <= 0.8:
                return 1.0
            return 1.0 - (current_a - 0.8)

    point = FlatVoltageFixture(config).operate((1000.0,) * 8, 25.0, 1.0)
    assert point.current_a == pytest.approx(0.4, abs=1e-15)
    assert point.voltage_v == 1.0


def test_numerical_and_energy_failures_are_not_clipped(config):
    too_much_current = PVModel(changed(config, "pv", isc_reference_a=10.0))
    with pytest.raises(NumericalError, match="no current root"):
        too_much_current.operate((1000.0,) * 8, 25.0, 0.2)
    invalid_coefficients = PVModel(
        changed(config, "pv", voc_temperature_coefficient_v_k=1e308)
    )
    with pytest.raises(NumericalError, match="invalid cell parameters"):
        invalid_coefficients.operate((1000.0,) * 8, 60.0, 1.8)
    impossible_efficiency = PVModel(changed(config, "thermal", absorptance=0.001))
    with pytest.raises(EnergyBalanceError):
        impossible_efficiency.operate((1000.0,) * 8, 25.0, 2.4)
    with pytest.raises(EnergyBalanceError):
        impossible_efficiency.maximum_power((1000.0,) * 8, 25.0)


@pytest.mark.parametrize("requested", [0.19, 4.01, float("nan"), float("inf"), True])
def test_invalid_voltage_rejected(config, requested):
    with pytest.raises(ValueError):
        PVModel(config).operate((900.0,) * 8, 25.0, requested)


@pytest.mark.parametrize("values", [(900.0,) * 7, (-1.0,) * 8, (float("nan"),) * 8])
def test_invalid_irradiance_rejected(config, values):
    with pytest.raises(ValueError):
        PVModel(config).operate(values, 25.0, 1.8)


@pytest.mark.parametrize("current", [-0.01, 2.01, float("inf")])
def test_current_bound_rejected(config, current):
    with pytest.raises(ValueError):
        PVModel(config).module_voltage(current, (900.0,) * 8, 25.0)


def test_analytic_maximum_and_no_solver_dependency(config, monkeypatch):
    model = PVModel(config)

    def forbidden(*args, **kwargs):
        raise AssertionError("maximum_power must not call the operating-point solver")

    monkeypatch.setattr(model, "operate", forbidden)
    uniform = model.maximum_power((1000.0,) * 8, 25.0)
    assert (uniform.voltage_v, uniform.current_a, uniform.power_w) == pytest.approx((2.4, 0.5, 1.2))
    asymmetric = model.maximum_power((200.0,) * 4 + (1000.0,) * 4, 25.0)
    assert asymmetric.voltage_v == pytest.approx(1.05)
    assert asymmetric.current_a == pytest.approx(0.4375)
    assert asymmetric.power_w == pytest.approx(1.05 * 0.4375)


def test_maximum_respects_voltage_limit_and_open_circuit(config):
    # Voc_module=9.6 V makes unconstrained Vmpp=4.8 V unavailable.
    model = PVModel(changed(config, "pv", voc_reference_v=1.2))
    point = model.maximum_power((1000.0,) * 8, 25.0)
    assert point.voltage_v == pytest.approx(4.0)
    assert point.current_a == pytest.approx(1 - 4 / 9.6)
    assert point.power_w == pytest.approx(4 * (1 - 4 / 9.6))
    black = model.maximum_power((0.0,) * 8, 25.0)
    assert black.mode == "blackout" and black.power_w == 0
    dim = model.maximum_power((1e-30,) * 8, 25.0)
    assert dim.mode == "open_circuit" and dim.power_w == 0


def test_independent_dense_grid_and_monotonicity(config):
    model = PVModel(config)
    irradiance = (200.0,) * 4 + (1000.0,) * 4
    weak_voc = 0.6 + 0.03 * math.log(0.2)
    dense_best = 0.0
    last_voltage = math.inf
    for tick in range(10001):
        current = tick / 5000
        if current <= 0.2:
            voltage = 4 * weak_voc * (1 - current / 0.2) + 2.4 * (1 - current)
        elif current <= 0.275:
            voltage = 3.2 - 6.4 * current
        elif current <= 1.0:
            voltage = 2.1 - 2.4 * current
        elif current <= 1.075:
            voltage = 3.7 - 4 * current
        else:
            voltage = -0.6
        actual = model.module_voltage(current, irradiance, 25.0)
        assert actual == pytest.approx(voltage, abs=1e-14)
        assert actual <= last_voltage + 1e-14
        last_voltage = actual
        if 0.2 <= voltage <= 4.0:
            dense_best = max(dense_best, voltage * current)
    analytic = model.maximum_power(irradiance, 25.0).power_w
    assert 0 <= analytic - dense_best <= 2.5e-8
