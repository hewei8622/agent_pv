"""Trusted projection of captured state into immutable public sensor records.

The pure factories retain the noise-free M1 projection. SensorModel adds M2
capture-indexed Gaussian noise and transport conditions. Reported sigmas are
nominal sensor uncertainties, not empirical estimates or hidden bias disclosure.
Capture/delivery times come from integer clock ticks; these functions neither
advance the world nor read it again at delivery.
"""

from __future__ import annotations

import base64
import io
import math
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from pv_sim.config import Config
from pv_sim.contracts import (
    AxisSigma,
    Calibration,
    EncoderSample,
    Exposure,
    Limits,
    PublicTask,
    RGBSample,
    ScalarSample,
)
from pv_sim.scenarios import rng_for_capture, seed_streams

if TYPE_CHECKING:
    from pv_sim.engine import DynamicsSnapshot
    from pv_sim.pv import OperatingPoint


def _tick(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("capture tick must be a nonnegative integer")
    return value


def _duration_ticks(config: Config, seconds: float) -> int:
    ticks = seconds / config.simulation.dt_s
    rounded = round(ticks)
    if not math.isclose(ticks, rounded, rel_tol=0, abs_tol=1e-9):
        raise ValueError("sensor duration must be an integer tick count")
    return rounded


def _calibration(config: Config) -> Calibration:
    camera = config.camera
    focal = camera.height / (2 * math.tan(math.radians(camera.fovy_deg) / 2))
    return Calibration(
        calibration_id="nominal_v1",
        camera_id="agent_rgb",
        width=camera.width,
        height=camera.height,
        fovy_deg=camera.fovy_deg,
        k=(focal, 0.0, (camera.width - 1) / 2, 0.0, focal, (camera.height - 1) / 2, 0.0, 0.0, 1.0),
        home_position_m=camera.home_position_m,
        pixel_convention="top_left_center_0_0_x_right_y_down",
        camera_axes="x_right_y_up_minus_z_forward",
    )


def build_public_task(config: Config, episode_id: str, enable_rendering: bool = True) -> PublicTask:
    """Project declared capabilities only; episode-specific world values stay private.

    Disabling rendering is explicitly a core-test capability condition. It cannot
    serve as the integrated M1 pilot or silently provide a replacement RGB frame.
    """
    if type(enable_rendering) is not bool:
        raise ValueError("enable_rendering must be a boolean")
    sensors = ("voltage_v", "current_a", "temperature_c", "reference_w_m2", "encoders")
    actions = ("move_camera", "set_voltage", "probe_voltage", "wait", "safe_stop", "finish")
    if enable_rendering:
        sensors += ("rgb",)
        actions += ("capture_rgb",)
    condition = "uninformed; public nominal calibration and action limits only"
    if not enable_rendering:
        condition += "; core-test/numeric-only, not an integrated RGB pilot"
    return PublicTask(
        schema_version="1.0",
        episode_id=episode_id,
        goal="Choose and verify an operating voltage using available observations.",
        sensors=sensors,
        limits=Limits(
            slide_m=(0.0, 0.0)
            if config.m2 is not None and config.m2.view.rail_locked
            else config.camera.slide_limits_m,
            yaw_rad=config.camera.yaw_limits_rad,
            pitch_rad=config.camera.pitch_limits_rad,
            voltage_v=config.pv.voltage_limits_v,
        ),
        available_actions=actions,
        available_help=(),
        horizon_s=config.simulation.horizon_s,
        budgets=config.budgets,
        cost_weights=config.cost_weights,
        nominal_calibration=_calibration(config),
        knowledge_condition=condition,
        allowed_adaptation="none",
        hypothesis_classes=(
            "source_change",
            "transmission_change",
            "electrical_change",
            "thermal_change",
            "actuation_or_sensing_change",
        ),
    )


def make_scalar_samples(
    config: Config,
    point: OperatingPoint,
    temperature_c: float,
    reference_w_m2: float,
    capture_tick: int,
) -> tuple[ScalarSample, ...]:
    """Capture exactly the supplied V/I/T/reference readings; never expose PV internals."""
    capture_tick = _tick(capture_tick)
    delivery_tick = capture_tick + _duration_ticks(config, config.sensors.numeric_latency_s)
    values = (
        ("voltage_v", point.voltage_v, config.sensors.voltage_sigma_v),
        ("current_a", point.current_a, config.sensors.current_sigma_a),
        ("temperature_c", temperature_c, config.sensors.temperature_sigma_c),
        ("reference_w_m2", reference_w_m2, config.sensors.reference_sigma_w_m2),
    )
    return tuple(
        ScalarSample(
            channel=channel,
            value=value,
            sigma=sigma,
            sensor_id=f"sensor_{channel}",
            t_capture_s=capture_tick * config.simulation.dt_s,
            t_deliver_s=delivery_tick * config.simulation.dt_s,
            validity="valid",
        )
        for channel, value, sigma in values
    )


def make_encoder_sample(config: Config, snapshot: DynamicsSnapshot) -> EncoderSample:
    """Project measured q/qdot only; do not serialize true pose, force or setpoints."""
    capture_tick = _tick(snapshot.tick)
    capture_s = capture_tick * config.simulation.dt_s
    if not math.isclose(snapshot.time_s, capture_s, rel_tol=0, abs_tol=1e-10):
        raise ValueError("snapshot time disagrees with its integer tick")
    delivery_tick = capture_tick + _duration_ticks(config, config.sensors.encoder_latency_s)
    return EncoderSample(
        sensor_id="sensor_encoders",
        slide_m=snapshot.q[0],
        yaw_rad=snapshot.q[1],
        pitch_rad=snapshot.q[2],
        slide_rate_m_s=snapshot.qdot[0],
        yaw_rate_rad_s=snapshot.qdot[1],
        pitch_rate_rad_s=snapshot.qdot[2],
        sigma=AxisSigma(
            slide_m=config.sensors.slide_sigma_m,
            yaw_rad=config.sensors.angular_sigma_rad,
            pitch_rad=config.sensors.angular_sigma_rad,
        ),
        t_capture_s=capture_s,
        t_deliver_s=delivery_tick * config.simulation.dt_s,
        validity="valid",
    )


def make_rgb_sample(config: Config, frame: np.ndarray, frame_id: str, start_tick: int) -> RGBSample:
    """Encode supplied midpoint pixels, without generating or substituting image content.

    The caller must obtain the array from the actual camera at the midpoint tick.
    No host path, actual camera transform, mask or metadata enters the wire record.
    """
    start_tick = _tick(start_tick)
    if (
        not isinstance(frame, np.ndarray)
        or frame.dtype != np.uint8
        or frame.shape != (config.camera.height, config.camera.width, 3)
    ):
        raise ValueError("RGB frame must be the configured height/width uint8 RGB array")
    exposure_ticks = _duration_ticks(config, config.sensors.rgb_exposure_s)
    if exposure_ticks < 2 or exposure_ticks % 2:
        raise ValueError("RGB exposure requires a positive integer midpoint tick")
    capture_tick = start_tick + exposure_ticks // 2
    end_tick = start_tick + exposure_ticks
    delivery_tick = end_tick + _duration_ticks(config, config.sensors.rgb_latency_s)
    output = io.BytesIO()
    Image.fromarray(frame).save(output, format="PNG")
    calibration = _calibration(config)
    dt = config.simulation.dt_s
    return RGBSample(
        frame_id=frame_id,
        camera_id="agent_rgb",
        width=config.camera.width,
        height=config.camera.height,
        encoding="png_rgb8",
        png_base64=base64.b64encode(output.getvalue()).decode("ascii"),
        calibration_id=calibration.calibration_id,
        k=calibration.k,
        exposure=Exposure(
            duration_s=exposure_ticks * dt,
            approximation=config.sensors.rgb_approximation,
        ),
        t_start_s=start_tick * dt,
        t_capture_s=capture_tick * dt,
        t_end_s=end_tick * dt,
        t_deliver_s=delivery_tick * dt,
        validity="valid",
    )


class SensorModel:
    """Capture immutable sensor values once, then schedule their public delivery.

    Numeric channels share one transport outcome because V/I/T/reference are one
    simultaneous acquisition. Their Gaussian errors are independent per channel.
    Encoder positions use their own stream; no rate-noise model is declared, so
    noisy encoders omit optional rates. RGB pixels remain noise-free at M2.

    Delivery jitter is uniform over the configured inclusive integer-tick range.
    Dropout produces an explicit missing record at the same scheduled delivery,
    retaining capture times and nominal uncertainty. Staleness means transport
    age strictly exceeds its configured threshold; later observation age is still
    recoverable from timestamps. No sample is replaced with a newer capture.
    """

    def __init__(self, config: Config, seed: int):
        seed_streams(seed)  # Validate even when the condition is deterministic.
        self.config = config
        self.seed = seed

    def _profile(self, kind: str):
        if kind not in ("numeric", "encoder", "rgb"):
            raise ValueError("unknown sensor transport kind")
        return None if self.config.m2 is None else getattr(self.config.m2.sensing, kind)

    def delivery_tick(self, kind: str, capture_tick: int, end_tick: int | None = None) -> int:
        """Return the keyed delivery tick without capturing, advancing or drawing state.

        RGB latency begins at exposure end, while its randomness and age are
        indexed by midpoint capture tick. Other sensor latencies begin at capture.
        """
        capture_tick = _tick(capture_tick)
        profile = self._profile(kind)
        origin = capture_tick
        if kind == "rgb":
            if end_tick is None:
                raise ValueError("RGB delivery requires its exposure end tick")
            origin = _tick(end_tick)
            if origin < capture_tick:
                raise ValueError("exposure end precedes capture")
        elif end_tick is not None:
            raise ValueError("only RGB delivery accepts an exposure end tick")
        latency = _duration_ticks(self.config, getattr(self.config.sensors, f"{kind}_latency_s"))
        if profile is not None:
            latency += _duration_ticks(self.config, profile.extra_delay_s)
            jitter = _duration_ticks(self.config, profile.jitter_s)
            if jitter:
                rng = rng_for_capture(self.seed, kind, kind, capture_tick, "delivery_jitter")
                latency += int(rng.integers(-jitter, jitter + 1))
        if latency < 0:
            raise ValueError("sensor transport latency must not be negative")
        return origin + latency

    def _transport(self, kind: str, capture_tick: int, end_tick: int | None = None) -> dict:
        delivery_tick = self.delivery_tick(kind, capture_tick, end_tick)
        profile = self._profile(kind)
        validity = "valid"
        if profile is not None:
            if profile.dropout_probability and (
                rng_for_capture(self.seed, kind, kind, capture_tick, "dropout").random()
                < profile.dropout_probability
            ):
                validity = "missing"
            elif profile.stale_after_s is not None and (
                delivery_tick - capture_tick > _duration_ticks(self.config, profile.stale_after_s)
            ):
                validity = "stale"
        return {
            "t_deliver_s": delivery_tick * self.config.simulation.dt_s,
            "validity": validity,
        }

    def _error(self, kind: str, channel: str, tick: int, sigma: float) -> float:
        rng = rng_for_capture(self.seed, kind, channel, tick, "gaussian_noise")
        return float(rng.normal(0, sigma))

    def capture_scalars(
        self,
        point: OperatingPoint,
        temperature_c: float,
        reference_w_m2: float,
        capture_tick: int,
    ) -> tuple[ScalarSample, ...]:
        samples = make_scalar_samples(
            self.config, point, temperature_c, reference_w_m2, capture_tick
        )
        transport = self._transport("numeric", capture_tick)
        result = []
        for sample in samples:
            value = sample.value
            if transport["validity"] == "missing":
                value = None
            elif self.config.pilot.numeric_noise:
                value += self._error("numeric", sample.channel, capture_tick, sample.sigma)
            # No sensor measurement range is declared. Actuation bounds are not
            # measurement bounds: retain out-of-range noise instead of clipping.
            result.append(
                ScalarSample.model_validate({**sample.model_dump(), **transport, "value": value})
            )
        return tuple(result)

    def capture_encoder(self, snapshot: DynamicsSnapshot) -> EncoderSample:
        sample = make_encoder_sample(self.config, snapshot)
        transport = self._transport("encoder", snapshot.tick)
        fields = sample.model_dump()
        positions = ("slide_m", "yaw_rad", "pitch_rad")
        rates = ("slide_rate_m_s", "yaw_rate_rad_s", "pitch_rate_rad_s")
        if transport["validity"] == "missing":
            fields.update({field: None for field in positions + rates})
        elif self.config.pilot.encoder_noise:
            for channel in positions:
                fields[channel] += self._error(
                    "encoder", channel, snapshot.tick, getattr(sample.sigma, channel)
                )
            fields.update({field: None for field in rates})
        return EncoderSample.model_validate({**fields, **transport})

    def capture_rgb(self, frame: np.ndarray, frame_id: str, start_tick: int) -> RGBSample:
        sample = make_rgb_sample(self.config, frame, frame_id, start_tick)
        duration = _duration_ticks(self.config, self.config.sensors.rgb_exposure_s)
        transport = self._transport("rgb", start_tick + duration // 2, start_tick + duration)
        fields = sample.model_dump()
        if transport["validity"] == "missing":
            fields["png_base64"] = None
        return RGBSample.model_validate({**fields, **transport})
