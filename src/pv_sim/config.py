"""Private configuration, with explicit v7 constants and no policy projection."""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pv_sim.contracts import (
    Budgets,
    CostWeights,
    Nonnegative,
    Number,
    Positive,
    Record,
    Vector3,
)
from pv_sim.m2_config import M2Config


class SimulationConfig(Record):
    dt_s: Positive
    horizon_s: Positive
    decision_overhead_s: Positive
    minimum_decision_spacing_s: Positive
    verification_tail_s: Positive
    max_action_timeout_s: Annotated[Positive, Field(le=15)]


class BackendConfig(Record):
    name: Literal["mujoco"]
    camera: Literal["agent_rgb"]
    renderer: Literal["classic"]


class CameraConfig(Record):
    width: Annotated[int, Field(strict=True, ge=1)]
    height: Annotated[int, Field(strict=True, ge=1)]
    fovy_deg: Annotated[Positive, Field(lt=180)]
    home_position_m: Vector3
    slide_limits_m: tuple[Number, Number]
    yaw_limits_rad: tuple[Number, Number]
    pitch_limits_rad: tuple[Number, Number]
    slide_rate_m_s: Positive
    slide_acceleration_m_s2: Positive
    angular_rate_rad_s: Positive
    angular_acceleration_rad_s2: Positive
    settle_s: Positive
    headlight: bool


class ServoConfig(Record):
    carriage_mass_kg: Positive
    yaw_mass_kg: Positive
    camera_mass_kg: Positive
    slide_kp_n_m: Positive
    slide_damping_n_s_m: Nonnegative
    slide_force_cap_n: Positive
    hinge_kp_nm_rad: Positive
    hinge_damping_nm_s_rad: Nonnegative
    hinge_torque_cap_nm: Positive


class PVConfig(Record):
    backend: Literal["piecewise_cell_v1"]
    cells_per_substring: Annotated[int, Field(strict=True, gt=0)]
    substrings_in_series: Annotated[int, Field(strict=True, gt=0)]
    voltage_limits_v: tuple[Number, Number]
    current_limit_a: Positive
    initial_voltage_v: Number
    reference_irradiance_w_m2: Positive
    reference_temperature_c: Number
    isc_reference_a: Positive
    isc_temperature_coefficient_per_k: Number
    voc_reference_v: Positive
    voc_temperature_coefficient_v_k: Number
    voc_log_irradiance_coefficient_v: Number
    reverse_resistance_ohm: Positive
    bypass_voltage_v: Positive
    bisection_current_bounds_a: tuple[Number, Number]
    root_convention: Literal["lowest_nonnegative_root"]


class ThermalConfig(Record):
    absorptance: Annotated[Number, Field(ge=0, le=1)]
    heat_capacity_j_k: Positive
    conductance_w_k: Positive
    trip_temperature_c: Number
    update: Literal["exact_linear_cooling_frozen_input"]


class SensorConfig(Record):
    numeric_hz: Positive
    encoder_hz: Positive
    rgb_max_hz: Positive
    numeric_latency_s: Nonnegative
    encoder_latency_s: Nonnegative
    rgb_latency_s: Nonnegative
    rgb_exposure_s: Positive
    rgb_approximation: Literal["midpoint_snapshot"]
    voltage_sigma_v: Nonnegative
    current_sigma_a: Nonnegative
    temperature_sigma_c: Nonnegative
    reference_sigma_w_m2: Nonnegative
    slide_sigma_m: Nonnegative
    angular_sigma_rad: Nonnegative


class LoadConfig(Record):
    delay_s: Nonnegative
    slew_v_s: Positive
    settle_s: Positive
    probe_dwell_bounds_s: tuple[Positive, Positive]
    probe_max_points: Annotated[int, Field(strict=True, ge=1, le=3)]
    wait_bounds_s: tuple[Positive, Positive]
    help_delay_s: Positive


class PrivateWorld(Record):
    panel_size_m: tuple[Positive, Positive]
    panel_center_m: Vector3
    panel_normal: Vector3
    columns: Annotated[int, Field(strict=True, gt=0)]
    rows: Annotated[int, Field(strict=True, gt=0)]
    cell_area_m2: Positive
    source_direction: Vector3
    dni_w_m2: Annotated[Number, Field(ge=0, le=1200)]
    dhi_w_m2: Annotated[Number, Field(ge=0, le=200)]
    transmission: Annotated[
        tuple[Annotated[Number, Field(ge=0, le=1)], ...], Field(min_length=8, max_length=8)
    ]
    series_resistance_ohm: Annotated[Number, Field(ge=0, le=1)]
    ambient_temperature_c: Annotated[Number, Field(ge=0, le=40)]
    initial_temperature_c: Annotated[Number, Field(ge=0, le=60)]
    reference_position_m: Vector3
    optical_grid_per_axis: Annotated[int, Field(strict=True, ge=1)]
    diffuse_visibility: Literal["uniform_unoccluded"]
    reflected_w_m2: Nonnegative


class PilotConfig(Record):
    numeric_noise: bool
    encoder_noise: bool
    actuator_failures: bool
    rgb_required: bool


class SourceStep(Record):
    """Private exogenous DNI change; source direction and diffuse field stay fixed."""

    time_s: Positive
    dni_w_m2: Annotated[Number, Field(ge=0, le=1200)]


class Config(Record):
    schema_version: Literal["1.0"]
    mode: Literal["trusted-policy/local"]
    simulation: SimulationConfig
    backend: BackendConfig
    camera: CameraConfig
    servos: ServoConfig
    pv: PVConfig
    thermal: ThermalConfig
    sensors: SensorConfig
    load: LoadConfig
    budgets: Budgets
    cost_weights: CostWeights
    private_world: PrivateWorld
    pilot: PilotConfig
    m2: M2Config | None = None
    source_schedule: Annotated[tuple[SourceStep, ...], Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        camera, pv, world, sim = self.camera, self.pv, self.private_world, self.simulation
        for pair in (
            camera.slide_limits_m,
            camera.yaw_limits_rad,
            camera.pitch_limits_rad,
            pv.voltage_limits_v,
            pv.bisection_current_bounds_a,
            self.load.probe_dwell_bounds_s,
            self.load.wait_bounds_s,
        ):
            if pair[0] >= pair[1]:
                raise ValueError("reversed or empty interval")
        fixed = {
            "simulation.dt_s": (sim.dt_s, 0.002),
            "camera.width": (camera.width, 640),
            "camera.height": (camera.height, 480),
            "camera.fovy_deg": (camera.fovy_deg, 45),
            "camera.home_position_m": (camera.home_position_m, (0, -0.45, 0.35)),
            "camera.slide_limits_m": (camera.slide_limits_m, (-0.15, 0.15)),
            "camera.yaw_limits_rad": (camera.yaw_limits_rad, (-math.pi / 4, math.pi / 4)),
            "camera.pitch_limits_rad": (camera.pitch_limits_rad, (-math.pi / 6, math.pi / 6)),
            "pv.cells_per_substring": (pv.cells_per_substring, 4),
            "pv.substrings_in_series": (pv.substrings_in_series, 2),
            "pv.voltage_limits_v": (pv.voltage_limits_v, (0.2, 4)),
            "private_world.panel_size_m": (world.panel_size_m, (0.30, 0.20)),
            "private_world.panel_center_m": (world.panel_center_m, (0, 0, 0)),
            "private_world.panel_normal": (world.panel_normal, (0, 0, 1)),
            "private_world.columns": (world.columns, 4),
            "private_world.rows": (world.rows, 2),
        }
        for name, (actual, expected) in fixed.items():
            if actual != expected:
                raise ValueError(f"{name} conflicts with the v7 initial contract")
        if camera.headlight:
            raise ValueError("headlight must be disabled")
        if not pv.voltage_limits_v[0] <= pv.initial_voltage_v <= pv.voltage_limits_v[1]:
            raise ValueError("initial voltage outside bounds")
        if pv.current_limit_a != 2 or pv.bisection_current_bounds_a != (0, 2):
            raise ValueError("v7 requires 2 A solver/protection bound")
        if not math.isclose(sum(x * x for x in world.source_direction), 1, abs_tol=1e-12):
            raise ValueError("source direction must be a unit vector")
        if not math.isclose(
            world.cell_area_m2 * 8, math.prod(world.panel_size_m), rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError("cell areas do not sum to panel area")
        if sim.verification_tail_s >= sim.horizon_s or self.budgets.time_s != sim.horizon_s:
            raise ValueError("horizon, tail and time budget inconsistent")
        if self.thermal.trip_temperature_c <= world.initial_temperature_c:
            raise ValueError("initial state exceeds protection threshold")
        durations = (
            sim.horizon_s,
            sim.decision_overhead_s,
            sim.verification_tail_s,
            sim.minimum_decision_spacing_s,
            1 / self.sensors.numeric_hz,
            1 / self.sensors.encoder_hz,
            1 / self.sensors.rgb_max_hz,
            self.sensors.numeric_latency_s,
            self.sensors.encoder_latency_s,
            self.sensors.rgb_latency_s,
            self.sensors.rgb_exposure_s,
            self.load.delay_s,
        )
        for duration in durations:
            ticks = duration / sim.dt_s
            if not math.isclose(ticks, round(ticks), rel_tol=0, abs_tol=1e-9):
                raise ValueError("configured duration must be an integer tick count")
        midpoint_ticks = self.sensors.rgb_exposure_s / (2 * sim.dt_s)
        midpoint_tick_count = round(midpoint_ticks)
        if midpoint_tick_count < 1 or not math.isclose(
            midpoint_ticks, midpoint_tick_count, rel_tol=0, abs_tol=1e-9
        ):
            raise ValueError("RGB exposure midpoint must be a positive integer tick count")
        if self.m2 is None and (
            self.pilot.numeric_noise or self.pilot.encoder_noise or self.pilot.actuator_failures
        ):
            raise ValueError("M0/M1 pilot requires noise and failures off")
        if self.m2 is not None:
            profiles = self.m2.sensing
            for name, base_latency in (
                ("numeric", self.sensors.numeric_latency_s),
                ("encoder", self.sensors.encoder_latency_s),
                ("rgb", self.sensors.rgb_latency_s),
            ):
                profile = getattr(profiles, name)
                if profile.jitter_s > base_latency + profile.extra_delay_s:
                    raise ValueError("delivery jitter can precede capture or exposure end")
                for duration in (profile.extra_delay_s, profile.jitter_s, profile.stale_after_s):
                    if duration is not None and not math.isclose(
                        duration / sim.dt_s, round(duration / sim.dt_s), rel_tol=0, abs_tol=1e-9
                    ):
                        raise ValueError("M2 sensor duration must be an integer tick count")
            faults = self.m2.actuation
            if not self.pilot.actuator_failures and (
                faults.load_drop_commands or faults.load_extra_delay_s or faults.move_stall_commands
            ):
                raise ValueError("configured actuator fixtures require actuator_failures enabled")
            for _, duration in faults.load_extra_delay_s:
                if not math.isclose(
                    duration / sim.dt_s, round(duration / sim.dt_s), rel_tol=0, abs_tol=1e-9
                ):
                    raise ValueError("M2 load delay must be an integer tick count")
        if not self.pilot.rgb_required:
            raise ValueError("RGB is required")
        previous_tick = 0
        for step in self.source_schedule or ():
            # Bound before dividing: even finite out-of-domain times must fail
            # validation cleanly rather than overflowing a tick conversion.
            if not step.time_s < sim.horizon_s:
                raise ValueError("source step must precede the horizon")
            tick_count = step.time_s / sim.dt_s
            step_tick = round(tick_count)
            if step_tick <= previous_tick or not math.isclose(
                tick_count, step_tick, rel_tol=0, abs_tol=1e-9
            ):
                raise ValueError("source steps must be strictly increasing positive grid ticks")
            previous_tick = step_tick
        return self

    def source_dni_at_tick(self, tick: int) -> float:
        """Right-continuous private source state, including at a captured tick."""
        if type(tick) is not int or tick < 0:
            raise ValueError("source tick must be a nonnegative integer")
        dni = self.private_world.dni_w_m2
        for step in self.source_schedule or ():
            if tick < round(step.time_s / self.simulation.dt_s):
                break
            dni = step.dni_w_m2
        return dni

    def canonical_json(self) -> str:
        data = self.model_dump(mode="json")
        # Preserve the accepted M1 configuration digest and old recording input.
        if self.m2 is None:
            data.pop("m2")
        if self.source_schedule is None:
            data.pop("source_schedule")
        return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def load_config(path: Path) -> Config:
    raw = path.read_bytes()
    if path.suffix == ".toml":
        # JSON arrays become immutable tuples through the strict JSON boundary.
        raw = json.dumps(tomllib.loads(raw.decode()), allow_nan=False).encode()
    elif path.suffix != ".json":
        raise ValueError("configuration must be JSON or TOML")
    return Config.model_validate_json(raw)
