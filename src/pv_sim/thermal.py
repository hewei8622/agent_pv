"""Private lumped thermal surrogate and exact frozen-input energy accounting.

Electrical joules use the left-endpoint rectangular rule: the current tick's
electrical power is frozen for its entire duration. Heat loss is the analytic
integral over that same interval; it can be negative below ambient temperature.
The environment, not this integrator, terminates on the thermal trip threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pv_sim.config import Config


class EnergyBalanceError(ValueError):
    """The scenario or model requests more output than its absorbed input."""


@dataclass(frozen=True, slots=True)
class ThermalStep:
    temperature_c: float
    absorbed_j: float
    electrical_j: float
    heat_loss_j: float
    storage_j: float


def _finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _irradiance(values: tuple[float, ...]) -> None:
    if len(values) != 8:
        raise ValueError("the declared topology requires exactly eight irradiances")
    for value in values:
        _finite(value, "irradiance")
        if value < 0:
            raise ValueError("irradiance must be nonnegative")


class ThermalModel:
    """Exact linear cooling for one synthetic module, with frozen tick inputs."""

    def __init__(self, config: Config):
        self._ambient = config.private_world.ambient_temperature_c
        self._capacity = config.thermal.heat_capacity_j_k
        self._conductance = config.thermal.conductance_w_k
        self._absorption_area = config.thermal.absorptance * config.private_world.cell_area_m2

    def advance(
        self,
        temperature_c: float,
        irradiance_w_m2: tuple[float, ...],
        power_w: float,
        dt_s: float,
    ) -> ThermalStep:
        _finite(temperature_c, "temperature")
        _finite(power_w, "power")
        _finite(dt_s, "duration")
        _irradiance(irradiance_w_m2)
        if power_w < 0 or dt_s <= 0:
            raise ValueError("power must be nonnegative and duration must be positive")
        absorbed_w = self._absorption_area * math.fsum(irradiance_w_m2)
        if not math.isfinite(absorbed_w):
            raise ValueError("nonfinite absorbed power")
        if power_w > absorbed_w:
            raise EnergyBalanceError("electrical output exceeds absorbed incident power")
        heat_w = absorbed_w - power_w
        excess_c = temperature_c - self._ambient
        tau_s = self._capacity / self._conductance
        fraction = -math.expm1(-dt_s / tau_s)
        # expm1 keeps the update stable even for a small simulation timestep.
        delta_c = (heat_w / self._conductance - excess_c) * fraction
        new_c = temperature_c + delta_c
        decay_integral_s = tau_s * fraction
        heat_loss_j = (
            self._conductance * excess_c * decay_integral_s
            + heat_w * (dt_s - decay_integral_s)
        )
        step = ThermalStep(
            temperature_c=new_c,
            absorbed_j=absorbed_w * dt_s,
            electrical_j=power_w * dt_s,
            heat_loss_j=heat_loss_j,
            storage_j=self._capacity * (new_c - temperature_c),
        )
        if not all(
            math.isfinite(value)
            for value in (
                step.temperature_c,
                step.absorbed_j,
                step.electrical_j,
                step.heat_loss_j,
                step.storage_j,
            )
        ):
            raise ValueError("nonfinite thermal result")
        return step
