"""Thermal references use direct closed forms and independently integrated heat loss."""

import math
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from pv_sim.config import load_config
from pv_sim.pv import PVModel
from pv_sim.thermal import EnergyBalanceError, ThermalModel

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config():
    return load_config(ROOT / "configs/pilot.toml")


def test_cooling_closed_form_and_signed_ambient_heat(config):
    model = ThermalModel(config)
    for initial in (0.0, 25.0, 60.0):
        step = model.advance(initial, (0.0,) * 8, 0.0, 20.0)
        expected = 25 + (initial - 25) * math.exp(-20 / 50)
        assert step.temperature_c == pytest.approx(expected, abs=1e-12)
        assert step.storage_j == pytest.approx(30 * (expected - initial), abs=1e-12)
        assert step.heat_loss_j == pytest.approx(30 * (initial - 25) * (1 - math.exp(-0.4)))
        assert step.absorbed_j == step.electrical_j == 0


@pytest.mark.parametrize("duration", [0.002, 0.1, 2.0, 60.0])
def test_frozen_heat_closed_form_and_conservation(config, duration):
    model = ThermalModel(config)
    # Eight 0.0075 m2 cells, 900 W/m2, alpha=.9: absorbed 48.6 W.
    # P_out=1.0 W gives a 47.6 W thermal input and equilibrium 25+47.6/.6.
    step = model.advance(40.0, (900.0,) * 8, 1.0, duration)
    equilibrium = 25 + 47.6 / 0.6
    exponential = math.exp(-duration / 50)
    expected = equilibrium + (40 - equilibrium) * exponential
    expected_loss = 47.6 * duration + 0.6 * (40 - equilibrium) * 50 * (1 - exponential)
    assert step.temperature_c == pytest.approx(expected, abs=1e-12)
    assert step.absorbed_j == pytest.approx(48.6 * duration)
    assert step.electrical_j == duration
    assert step.heat_loss_j == pytest.approx(expected_loss, abs=1e-12)
    residual = step.absorbed_j - step.electrical_j - step.heat_loss_j - step.storage_j
    assert abs(residual) <= 1e-10


def test_semigroup_substeps_and_source_step(config):
    model = ThermalModel(config)
    full = model.advance(25.0, (900.0,) * 8, 1.0, 1.0)
    temperature = 25.0
    energy = [0.0, 0.0, 0.0, 0.0]
    for _ in range(500):
        step = model.advance(temperature, (900.0,) * 8, 1.0, 0.002)
        temperature = step.temperature_c
        for index, value in enumerate(
            (step.absorbed_j, step.electrical_j, step.heat_loss_j, step.storage_j)
        ):
            energy[index] += value
    assert temperature == pytest.approx(full.temperature_c, abs=1e-11)
    assert energy == pytest.approx(
        [full.absorbed_j, full.electrical_j, full.heat_loss_j, full.storage_j], abs=1e-9
    )
    dark = model.advance(temperature, (0.0,) * 8, 0.0, 1.0)
    assert dark.temperature_c == pytest.approx(25 + (temperature - 25) * math.exp(-0.02))
    assert 25 < dark.temperature_c < temperature


def test_explicit_temperature_power_coupling_refines_and_conserves(config):
    thermal = ThermalModel(config)
    electrical = PVModel(config)

    def integrate(dt):
        temperature, absorbed, output, loss = 25.0, 0.0, 0.0, 0.0
        for _ in range(round(1.0 / dt)):
            point = electrical.operate((900.0,) * 8, temperature, 1.8)
            step = thermal.advance(temperature, (900.0,) * 8, point.power_w, dt)
            temperature = step.temperature_c
            absorbed += step.absorbed_j
            output += step.electrical_j
            loss += step.heat_loss_j
        assert abs(absorbed - output - loss - 30 * (temperature - 25)) < 1e-8
        return temperature

    # Small bounded module test; formal M3 timestep/quadrature studies remain later work.
    coarse, medium, fine = (integrate(dt) for dt in (0.008, 0.004, 0.002))
    assert abs(medium - fine) < abs(coarse - medium)
    assert abs(medium - fine) < 1e-6


def test_energy_violation_rejected_and_outputs_immutable(config):
    model = ThermalModel(config)
    with pytest.raises(EnergyBalanceError):
        model.advance(25.0, (0.0,) * 8, 0.001, 0.002)
    with pytest.raises(EnergyBalanceError):
        model.advance(25.0, (900.0,) * 8, 49.0, 0.002)
    step = model.advance(25.0, (900.0,) * 8, 0.0, 0.002)
    with pytest.raises(FrozenInstanceError):
        step.temperature_c = 0.0


@pytest.mark.parametrize(
    "temperature,irradiance,power,duration",
    [
        (float("nan"), (900.0,) * 8, 0.0, 0.002),
        (25.0, (900.0,) * 7, 0.0, 0.002),
        (25.0, (-1.0,) * 8, 0.0, 0.002),
        (25.0, (float("inf"),) * 8, 0.0, 0.002),
        (25.0, (900.0,) * 8, -0.1, 0.002),
        (25.0, (900.0,) * 8, float("inf"), 0.002),
        (25.0, (900.0,) * 8, 0.0, 0.0),
        (25.0, (900.0,) * 8, 0.0, -0.1),
        (25.0, (900.0,) * 8, 0.0, float("inf")),
    ],
)
def test_invalid_input_rejected(config, temperature, irradiance, power, duration):
    with pytest.raises(ValueError):
        ThermalModel(config).advance(temperature, irradiance, power, duration)
