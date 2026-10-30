"""Independent reference for the nominal uniform-source development fixture.

This stdlib-only module intentionally duplicates documented nominal constants;
it must not obtain expected values from the production simulator. The caller
must separately check that its production configuration matches this fixture.

Eight identical series cells stay on their forward generating branch, with no
series resistance and a fixed 1.8 V load. Total irradiance changes from 900 to
500 W/m2 (DNI 800 to 400, DHI 100). The independently integrated continuous
thermal equation is a reference for the production frozen-power time step,
not a claim of agreement with a measured physical panel.
"""

from __future__ import annotations

import math

INITIAL_IRRADIANCE_W_M2 = 900.0
FINAL_IRRADIANCE_W_M2 = 500.0
AMBIENT_TEMPERATURE_C = 25.0
INITIAL_TEMPERATURE_C = 25.0
ABSORPTANCE_TIMES_AREA_M2 = 0.054
HEAT_CAPACITY_J_K = 30.0
CONDUCTANCE_W_K = 0.6
FIXED_VOLTAGE_V = 1.8
MAX_REFERENCE_DURATION_S = 12.0

# Predeclared before comparison with the new production source-change scenario.
# These apply to this <=12 s, noise-free fixture, not arbitrary model settings.
DEVELOPMENT_TOLERANCES = {
    "current_a_abs": 1e-12,
    "power_w_abs": 1e-11,
    "reference_refinement_temperature_c_abs": 1e-9,
    "production_temperature_c_abs": 5e-6,
    "electrical_j_abs": 1e-4,
    "absorbed_j_abs": 1e-8,
}


def _number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def current(E: float, T: float, voltage: float = FIXED_VOLTAGE_V) -> float:
    """Closed-form current for eight identical cells on the generating branch.

    V = 8*v_oc*(1-I/I_sc), hence I = I_sc*(1-V/(8*v_oc)). This
    eliminates root solving and never calls the production electrical model.
    Unsupported dark, reverse, open-circuit and current-limit cases are rejected.
    """
    E = _number(E, "irradiance")
    T = _number(T, "temperature")
    voltage = _number(voltage, "voltage")
    if E <= 0:
        raise ValueError("reference requires positive uniform irradiance")
    theta = T - 25.0
    isc = (E / 1000.0) * (1.0 + 0.0005 * theta)
    voc_cell = 0.60 - 0.002 * theta + 0.03 * (math.log(E) - math.log(1000.0))
    if not math.isfinite(isc) or not math.isfinite(voc_cell):
        raise ValueError("nonfinite reference cell parameters")
    if isc <= 0 or voc_cell <= 0 or not 0 < voltage < 8.0 * voc_cell:
        raise ValueError("reference supports only the uniform forward generating branch")
    result = isc * (1.0 - voltage / (8.0 * voc_cell))
    if not 0 < result < isc or result > 2.0:
        raise ValueError("reference current outside the supported generating branch")
    return result


def power(E: float, T: float, voltage: float = FIXED_VOLTAGE_V) -> float:
    """Algebraic V*I using the independent uniform-series expression."""
    return voltage * current(E, T, voltage)


def _rhs(E: float, state: tuple[float, float, float]) -> tuple[float, float, float]:
    temperature = state[0]
    electrical = power(E, temperature)
    heat_loss = CONDUCTANCE_W_K * (temperature - AMBIENT_TEMPERATURE_C)
    return (
        (ABSORPTANCE_TIMES_AREA_M2 * E - electrical - heat_loss) / HEAT_CAPACITY_J_K,
        electrical,
        heat_loss,
    )


def _add(
    state: tuple[float, float, float], derivative: tuple[float, float, float], scale: float
) -> tuple[float, float, float]:
    return tuple(value + scale * rate for value, rate in zip(state, derivative, strict=True))


def _rk4(
    E: float, state: tuple[float, float, float], h: float
) -> tuple[float, float, float]:
    k1 = _rhs(E, state)
    k2 = _rhs(E, _add(state, k1, h / 2))
    k3 = _rhs(E, _add(state, k2, h / 2))
    k4 = _rhs(E, _add(state, k3, h))
    return tuple(
        value + h * (a + 2 * b + 2 * c + d) / 6
        for value, a, b, c, d in zip(state, k1, k2, k3, k4, strict=True)
    )


def integrate(
    duration_s: float = 8.0,
    event_s: float | None = 2.0,
    step_s: float = 0.0005,
    sample_dt_s: float = 0.002,
) -> list[dict[str, float]]:
    """Integrate continuous T/output/loss, returning initial and endpoint samples.

    ``event_s=None`` is the unchanged-source control. The event is right
    continuous: the interval ending at the event uses the old source, while
    the instantaneous electrical reading at the event uses the new source.
    T and cumulative energy are continuous. Integration explicitly splits at
    every requested sample and at the event, so no RK4 stage crosses the jump.

    Samples include the regular sample grid, the exact event (if off-grid),
    and the exact final endpoint. Each RK4 substep is at most ``step_s``.
    The supported duration is at most 12 s, matching the declared tolerances.
    """
    duration_s = _number(duration_s, "duration")
    step_s = _number(step_s, "reference step")
    sample_dt_s = _number(sample_dt_s, "sample interval")
    if not 0 < duration_s <= MAX_REFERENCE_DURATION_S:
        raise ValueError("reference duration must be positive and at most 12 seconds")
    if step_s <= 0 or sample_dt_s <= 0:
        raise ValueError("reference step and sample interval must be positive")
    if event_s is not None:
        event_s = _number(event_s, "event time")
        if not 0 <= event_s <= duration_s:
            raise ValueError("event must fall within the reference duration")

    times = {0.0, duration_s}
    times.update(
        index * sample_dt_s
        for index in range(1, math.ceil(duration_s / sample_dt_s))
        if index * sample_dt_s < duration_s
    )
    if event_s is not None:
        times.add(event_s)

    state = (INITIAL_TEMPERATURE_C, 0.0, 0.0)
    previous_time = 0.0
    samples = []
    for time_s in sorted(times):
        interval = time_s - previous_time
        if interval > 0:
            # Every interval is split at the event; its left endpoint selects E.
            interval_E = (
                FINAL_IRRADIANCE_W_M2
                if event_s is not None and previous_time >= event_s
                else INITIAL_IRRADIANCE_W_M2
            )
            count = max(1, math.ceil(interval / step_s))
            h = interval / count
            for _ in range(count):
                state = _rk4(interval_E, state, h)
        E = (
            FINAL_IRRADIANCE_W_M2
            if event_s is not None and time_s >= event_s
            else INITIAL_IRRADIANCE_W_M2
        )
        old_duration = time_s if event_s is None else min(time_s, event_s)
        absorbed = ABSORPTANCE_TIMES_AREA_M2 * (
            INITIAL_IRRADIANCE_W_M2 * old_duration
            + FINAL_IRRADIANCE_W_M2 * (time_s - old_duration)
        )
        samples.append(
            {
                "time_s": time_s,
                "temperature_c": state[0],
                "current_a": current(E, state[0]),
                "power_w": power(E, state[0]),
                "irradiance_w_m2": E,
                "absorbed_j": absorbed,
                "electrical_j": state[1],
                "heat_loss_j": state[2],
            }
        )
        previous_time = time_s
    return samples
