"""Private, explicitly synthetic eight-cell/two-substring electrical surrogate.

This is the v7 piecewise causal model, not a validated solar-cell model. Requested
voltage is a load setting; the returned voltage is the actual terminal reading.
The analytic maximum-power comparator is evaluator-only and never a sensor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pv_sim.config import Config
from pv_sim.thermal import EnergyBalanceError, _finite, _irradiance


class NumericalError(RuntimeError):
    """An electrical scenario has no bounded solution or a nonfinite result."""


@dataclass(frozen=True, slots=True)
class OperatingPoint:
    voltage_v: float
    current_a: float
    power_w: float
    open_circuit_voltage_v: float
    mode: Literal["generating", "open_circuit", "disconnected", "blackout"]


class PVModel:
    """Deterministic lower-root IV solver plus independent analytic comparator."""

    def __init__(self, config: Config):
        self._pv = config.pv
        self._rs = config.private_world.series_resistance_ohm
        self._absorption_area = config.thermal.absorptance * config.private_world.cell_area_m2

    def _cells(
        self, irradiance_w_m2: tuple[float, ...], temperature_c: float
    ) -> tuple[tuple[float, float], ...]:
        _irradiance(irradiance_w_m2)
        _finite(temperature_c, "temperature")
        pv = self._pv
        delta_c = temperature_c - pv.reference_temperature_c
        factor = 1 + pv.isc_temperature_coefficient_per_k * delta_c
        cells = []
        for irradiance in irradiance_w_m2:
            if irradiance == 0:
                cells.append((0.0, 0.0))
                continue
            ratio = irradiance / pv.reference_irradiance_w_m2
            isc = pv.isc_reference_a * ratio * factor
            # Log difference avoids underflow of E/E_ref for tiny positive E.
            voc_raw = (
                pv.voc_reference_v
                + pv.voc_temperature_coefficient_v_k * delta_c
                + pv.voc_log_irradiance_coefficient_v
                * (math.log(irradiance) - math.log(pv.reference_irradiance_w_m2))
            )
            if not math.isfinite(isc) or isc <= 0 or not math.isfinite(voc_raw):
                raise NumericalError("invalid cell parameters for this scenario")
            cells.append((isc, max(0.0, voc_raw)))
        return tuple(cells)

    def _voltage(self, current_a: float, cells: tuple[tuple[float, float], ...]) -> float:
        voltage = -current_a * self._rs
        for offset in (0, 4):
            substring = 0.0
            for isc, voc in cells[offset : offset + 4]:
                substring += (
                    voc * (1 - current_a / isc)
                    if isc > 0 and current_a <= isc
                    else -self._pv.reverse_resistance_ohm * (current_a - isc)
                )
            voltage += max(substring, -self._pv.bypass_voltage_v)
        if not math.isfinite(voltage):
            raise NumericalError("nonfinite module voltage")
        return voltage

    def module_voltage(
        self, current_a: float, irradiance_w_m2: tuple[float, ...], temperature_c: float
    ) -> float:
        """Return raw IV voltage (possibly negative) within the declared 0..2 A bound."""
        _finite(current_a, "current")
        if not 0 <= current_a <= self._pv.current_limit_a:
            raise ValueError("current outside declared solver/protection bounds")
        return self._voltage(current_a, self._cells(irradiance_w_m2, temperature_c))

    def _point(
        self,
        voltage: float,
        current: float,
        voc: float,
        irradiance: tuple[float, ...],
        mode: Literal["generating", "open_circuit", "disconnected", "blackout"],
    ) -> OperatingPoint:
        power = voltage * current
        if not all(math.isfinite(value) for value in (voltage, current, voc, power)):
            raise NumericalError("nonfinite operating point")
        if voltage < 0 or not 0 <= current <= self._pv.current_limit_a or power < 0:
            raise NumericalError("electrical operating point outside declared bounds")
        absorbed_w = self._absorption_area * math.fsum(irradiance)
        if not math.isfinite(absorbed_w):
            raise NumericalError("nonfinite absorbed incident power")
        if power > absorbed_w:
            raise EnergyBalanceError("electrical output exceeds absorbed incident power")
        return OperatingPoint(voltage, current, power, voc, mode)

    def operate(
        self,
        irradiance_w_m2: tuple[float, ...],
        temperature_c: float,
        requested_voltage_v: float,
        disconnected: bool = False,
    ) -> OperatingPoint:
        """Use exactly 64 lower-root bisections, never clipping an impossible result."""
        _finite(requested_voltage_v, "requested voltage")
        if not self._pv.voltage_limits_v[0] <= requested_voltage_v <= self._pv.voltage_limits_v[1]:
            raise ValueError("requested voltage outside declared load range")
        if not isinstance(disconnected, bool):
            raise ValueError("disconnected must be a boolean")
        cells = self._cells(irradiance_w_m2, temperature_c)
        voc = self._voltage(0.0, cells)
        if not any(irradiance_w_m2):
            return self._point(0.0, 0.0, 0.0, irradiance_w_m2, "blackout")
        if disconnected:
            return self._point(voc, 0.0, voc, irradiance_w_m2, "disconnected")
        if requested_voltage_v >= voc:
            return self._point(voc, 0.0, voc, irradiance_w_m2, "open_circuit")
        low, high = self._pv.bisection_current_bounds_a
        if self._voltage(high, cells) > requested_voltage_v:
            raise NumericalError("no current root in declared 0..2 A bracket")
        for _ in range(64):
            middle = (low + high) / 2
            if self._voltage(middle, cells) > requested_voltage_v:
                low = middle
            else:
                high = middle
        voltage = self._voltage(high, cells)
        if abs(voltage - requested_voltage_v) > 1e-6:
            raise NumericalError("current root failed voltage residual tolerance")
        return self._point(voltage, high, voc, irradiance_w_m2, "generating")

    def _linear_pieces(
        self, cells: tuple[tuple[float, float], ...]
    ) -> list[tuple[float, float, float, float]]:
        """Analytically assemble (I_low,I_high,intercept,slope), without root solving."""
        upper = self._pv.current_limit_a
        points = sorted({0.0, upper, *(isc for isc, _ in cells if 0 < isc < upper)})
        pieces = []
        for low, high in zip(points, points[1:]):
            middle = (low + high) / 2
            substrings = []
            cuts = {low, high}
            for offset in (0, 4):
                intercept, slope = 0.0, 0.0
                for isc, voc in cells[offset : offset + 4]:
                    if isc > middle:
                        intercept += voc
                        slope -= voc / isc
                    else:
                        intercept += self._pv.reverse_resistance_ohm * isc
                        slope -= self._pv.reverse_resistance_ohm
                substrings.append((intercept, slope))
                if slope < 0:
                    crossing = (-self._pv.bypass_voltage_v - intercept) / slope
                    if low < crossing < high:
                        cuts.add(crossing)
            ordered = sorted(cuts)
            for left, right in zip(ordered, ordered[1:]):
                probe = (left + right) / 2
                intercept, slope = 0.0, -self._rs
                for sub_intercept, sub_slope in substrings:
                    if sub_intercept + sub_slope * probe <= -self._pv.bypass_voltage_v:
                        intercept -= self._pv.bypass_voltage_v
                    else:
                        intercept += sub_intercept
                        slope += sub_slope
                pieces.append((left, right, intercept, slope))
        return pieces

    def maximum_power(
        self, irradiance_w_m2: tuple[float, ...], temperature_c: float
    ) -> OperatingPoint:
        """Private feasible-power comparator from linear breakpoints and stationary points.

        It never calls operate or its bisection solver. Ties select the smaller
        current. Bounds apply to the load command; an open circuit may measure
        below the minimum command voltage, exactly as operate does.
        """
        cells = self._cells(irradiance_w_m2, temperature_c)
        voc = self._voltage(0.0, cells)
        if not any(irradiance_w_m2):
            return self._point(0.0, 0.0, 0.0, irradiance_w_m2, "blackout")
        vmin, vmax = self._pv.voltage_limits_v
        best: tuple[float, float, float] | None = (0.0, 0.0, voc) if voc <= vmax else None
        for left, right, intercept, slope in self._linear_pieces(cells):
            if slope == 0:
                if not vmin <= intercept <= vmax:
                    continue
                # First matching current is the only feasible point on a plateau.
                right = left
            else:
                left = max(left, (vmax - intercept) / slope)
                right = min(right, (vmin - intercept) / slope)
            if left > right:
                continue
            candidates = [left, right]
            if slope < 0:
                stationary = -intercept / (2 * slope)
                if left <= stationary <= right:
                    candidates.append(stationary)
            for current in candidates:
                voltage = self._voltage(current, cells)
                power = voltage * current
                if best is None or power > best[0] or (power == best[0] and current < best[1]):
                    best = (power, current, voltage)
        if best is None:
            raise NumericalError("no feasible operating point within voltage/current bounds")
        _, current, voltage = best
        return self._point(
            voltage,
            current,
            voc,
            irradiance_w_m2,
            "generating" if current > 0 else "open_circuit",
        )
