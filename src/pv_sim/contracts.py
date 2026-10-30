"""Immutable public wire records. No simulator, evaluator or scenario imports.

Runtime acceptance, idempotence, measured verification and execution belong to M1.
These types validate payloads; an Action instance is never proof of execution.
"""

from __future__ import annotations

import base64
import binascii
import io
import math
import struct
import zlib
from typing import Annotated, Literal, Self

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Nonnegative = Annotated[Number, Field(ge=0)]
Positive = Annotated[Number, Field(gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=1000)]
Probability = Annotated[Number, Field(ge=0, le=1)]
Voltage = Annotated[Number, Field(ge=0.2, le=4.0)]
Vector3 = tuple[Number, Number, Number]
Matrix3 = tuple[Number, Number, Number, Number, Number, Number, Number, Number, Number]
Channel = Literal["voltage_v", "current_a", "temperature_c", "reference_w_m2"]
Validity = Literal["valid", "missing", "saturated", "stale"]
HelpType = Literal["reference_irradiance", "rear_inspection"]
ActionKind = Literal[
    "move_camera",
    "set_voltage",
    "probe_voltage",
    "capture_rgb",
    "wait",
    "request_help",
    "safe_stop",
    "finish",
]
Reason = Literal[
    "out_of_range",
    "budget",
    "busy",
    "sensor_unavailable",
    "tracking_timeout",
    "command_conflict",
    "invalid_payload",
]


class Record(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        revalidate_instances="always",
        validate_default=True,
    )


class ActionBase(Record):
    schema_version: Literal["1.0"]
    action_id: Annotated[int, Field(strict=True, ge=1)]
    timeout_s: Annotated[Positive, Field(le=15)]


class MoveCamera(ActionBase):
    kind: Literal["move_camera"]
    slide_m: Annotated[Number, Field(ge=-0.15, le=0.15)]
    yaw_rad: Annotated[Number, Field(ge=-math.pi / 4, le=math.pi / 4)]
    pitch_rad: Annotated[Number, Field(ge=-math.pi / 6, le=math.pi / 6)]
    capture_after_settle: bool


class SetVoltage(ActionBase):
    kind: Literal["set_voltage"]
    voltage_v: Voltage


class ProbeVoltage(ActionBase):
    kind: Literal["probe_voltage"]
    voltages_v: Annotated[tuple[Voltage, ...], Field(min_length=1, max_length=3)]
    dwell_s: Annotated[Number, Field(ge=0.2, le=2.0)]


class CaptureRGB(ActionBase):
    kind: Literal["capture_rgb"]


class Wait(ActionBase):
    kind: Literal["wait"]
    duration_s: Annotated[Number, Field(ge=0.1, le=5)]


class RequestHelp(ActionBase):
    kind: Literal["request_help"]
    measurement: HelpType


class SafeStop(ActionBase):
    kind: Literal["safe_stop"]


class Finish(ActionBase):
    kind: Literal["finish"]
    resolution: Literal["resolved", "unresolved", "help_needed"]


Action = Annotated[
    MoveCamera | SetVoltage | ProbeVoltage | CaptureRGB | Wait | RequestHelp | SafeStop | Finish,
    Field(discriminator="kind"),
]
ACTION_ADAPTER = TypeAdapter(Action)


class Limits(Record):
    slide_m: tuple[Number, Number]
    yaw_rad: tuple[Number, Number]
    pitch_rad: tuple[Number, Number]
    voltage_v: tuple[Number, Number]

    @model_validator(mode="after")
    def check_limits(self) -> Self:
        for name, lower, upper in (
            ("slide_m", -0.15, 0.15),
            ("yaw_rad", -math.pi / 4, math.pi / 4),
            ("pitch_rad", -math.pi / 6, math.pi / 6),
            ("voltage_v", 0.2, 4),
        ):
            low, high = getattr(self, name)
            if not lower <= low <= high <= upper:
                raise ValueError(f"invalid {name} bounds")
        return self


class Budgets(Record):
    time_s: Nonnegative
    rgb_frames: Count
    voltage_points: Count
    help_requests: Count
    decisions: Count
    slide_path_m: Nonnegative
    angular_path_rad: Nonnegative


class CostWeights(Record):
    pv_energy_scale_j: Positive
    rgb: Nonnegative
    voltage_point: Nonnegative
    help_request: Nonnegative
    slide_per_m: Nonnegative
    angle_per_rad: Nonnegative


class Calibration(Record):
    calibration_id: Identifier
    camera_id: Literal["agent_rgb"]
    width: Literal[640]
    height: Literal[480]
    fovy_deg: Number
    k: Matrix3
    home_position_m: Vector3
    pixel_convention: Literal["top_left_center_0_0_x_right_y_down"]
    camera_axes: Literal["x_right_y_up_minus_z_forward"]

    @model_validator(mode="after")
    def check_calibration(self) -> Self:
        f = 480 / (2 * math.tan(math.radians(45) / 2))
        expected = (f, 0, 319.5, 0, f, 239.5, 0, 0, 1)
        if self.fovy_deg != 45 or self.home_position_m != (0, -0.45, 0.35):
            raise ValueError("schema 1.0 requires the nominal v7 camera calibration")
        if any(abs(a - b) > 1e-10 for a, b in zip(self.k, expected, strict=True)):
            raise ValueError("K disagrees with nominal camera calibration")
        return self


class PublicTask(Record):
    schema_version: Literal["1.0"]
    episode_id: Identifier
    goal: Text
    sensors: tuple[
        Literal["voltage_v", "current_a", "temperature_c", "reference_w_m2", "encoders", "rgb"], ...
    ]
    limits: Limits
    available_actions: tuple[ActionKind, ...]
    available_help: tuple[HelpType, ...]
    horizon_s: Positive
    budgets: Budgets
    cost_weights: CostWeights
    nominal_calibration: Calibration
    knowledge_condition: Text
    allowed_adaptation: Text
    hypothesis_classes: tuple[Identifier, ...]

    @model_validator(mode="after")
    def check_capabilities(self) -> Self:
        for values in (
            self.sensors,
            self.available_actions,
            self.available_help,
            self.hypothesis_classes,
        ):
            if len(set(values)) != len(values):
                raise ValueError("duplicate capability or hypothesis")
        if "safe_stop" not in self.available_actions:
            raise ValueError("safe_stop must always be available")
        if self.available_help and "request_help" not in self.available_actions:
            raise ValueError("help types require the request_help capability")
        if self.budgets.time_s != self.horizon_s:
            raise ValueError("initial time budget must equal horizon")
        return self


class TimedSample(Record):
    t_capture_s: Nonnegative
    t_deliver_s: Nonnegative
    validity: Validity

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.t_deliver_s < self.t_capture_s:
            raise ValueError("delivery precedes capture")
        return self


class ScalarSample(TimedSample):
    channel: Channel
    value: Number | None
    sigma: Nonnegative | None
    sensor_id: Identifier

    @model_validator(mode="after")
    def missing_value(self) -> Self:
        if (self.value is None) != (self.validity == "missing"):
            raise ValueError("missing samples require null; other samples require a value")
        return self


class AxisSigma(Record):
    slide_m: Nonnegative | None
    yaw_rad: Nonnegative | None
    pitch_rad: Nonnegative | None


class EncoderSample(TimedSample):
    sensor_id: Identifier
    slide_m: Number | None
    yaw_rad: Number | None
    pitch_rad: Number | None
    slide_rate_m_s: Number | None = None
    yaw_rate_rad_s: Number | None = None
    pitch_rate_rad_s: Number | None = None
    sigma: AxisSigma

    @model_validator(mode="after")
    def missing_values(self) -> Self:
        positions = (self.slide_m, self.yaw_rad, self.pitch_rad)
        rates = (self.slide_rate_m_s, self.yaw_rate_rad_s, self.pitch_rate_rad_s)
        if self.validity == "missing":
            if any(x is not None for x in positions + rates):
                raise ValueError("missing encoder requires null values")
        elif any(x is None for x in positions):
            raise ValueError("present encoder requires all positions")
        return self


class Exposure(Record):
    duration_s: Positive
    approximation: Literal["midpoint_snapshot"]


def _validate_png_rgb8(raw: bytes) -> None:
    """Validate the restricted PNG wire format, then actually decode its pixels."""
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    pos, interlace = 8, None
    image_chunks: list[bytes] = []
    ended = False
    while pos < len(raw):
        if len(raw) - pos < 12:
            raise ValueError("truncated PNG chunk")
        size = struct.unpack_from(">I", raw, pos)[0]
        kind = raw[pos + 4 : pos + 8]
        end = pos + 12 + size
        if kind not in (b"IHDR", b"IDAT", b"IEND") or end > len(raw):
            raise ValueError("PNG metadata or malformed chunk")
        expected_crc = struct.unpack_from(">I", raw, end - 4)[0]
        if binascii.crc32(raw[pos + 4 : end - 4]) & 0xFFFFFFFF != expected_crc:
            raise ValueError("PNG chunk CRC mismatch")
        data = raw[pos + 8 : end - 4]
        if kind == b"IHDR":
            if pos != 8 or size != 13:
                raise ValueError("PNG requires one initial 13-byte IHDR")
            header = struct.unpack(">IIBBBBB", data)
            if header[:6] != (640, 480, 8, 2, 0, 0) or header[6] not in (0, 1):
                raise ValueError("PNG must be 640x480 truecolor RGB8 with valid methods")
            interlace = header[6]
        elif interlace is None:
            raise ValueError("PNG image data must follow IHDR")
        elif kind == b"IDAT":
            image_chunks.append(data)
        else:
            if size != 0 or not image_chunks or end != len(raw):
                raise ValueError("PNG requires an empty terminal IEND after IDAT")
            ended = True
        pos = end
    if not ended:
        raise ValueError("missing PNG ending")

    # A decoder can ignore excess IDAT bytes or a missing zlib trailer. Require
    # exactly one complete stream with precisely the RGB8 scanline byte count.
    # Bound decompression before allocating output; the public size limit remains.
    passes = (
        ((0, 0, 1, 1),)
        if interlace == 0
        else (
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        )
    )
    expected_size = sum(
        (3 * ((640 - x + dx - 1) // dx) + 1) * ((480 - y + dy - 1) // dy) for x, y, dx, dy in passes
    )
    decoder = zlib.decompressobj()
    pixels = decoder.decompress(b"".join(image_chunks), expected_size + 1)
    if (
        len(pixels) != expected_size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise ValueError("PNG IDAT must contain exactly the complete image stream")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.size != (640, 480):
            raise ValueError("PNG must decode as 640x480 RGB8")
        image.verify()
    # verify() checks integrity but does not decode. Reopening is required.
    with Image.open(io.BytesIO(raw)) as image:
        image.load()


class RGBSample(TimedSample):
    frame_id: Identifier
    camera_id: Literal["agent_rgb"]
    width: Literal[640]
    height: Literal[480]
    encoding: Literal["png_rgb8"]
    png_base64: Annotated[str, Field(max_length=2800000)] | None
    calibration_id: Identifier
    k: Matrix3
    exposure: Exposure
    t_start_s: Nonnegative
    t_end_s: Nonnegative

    @model_validator(mode="after")
    def check_image(self) -> Self:
        if not self.t_start_s <= self.t_capture_s <= self.t_end_s <= self.t_deliver_s:
            raise ValueError("invalid exposure/delivery ordering")
        if not math.isclose(
            self.t_capture_s, (self.t_start_s + self.t_end_s) / 2, rel_tol=0, abs_tol=1e-10
        ):
            raise ValueError("capture must be the exposure midpoint")
        if not math.isclose(
            self.t_end_s - self.t_start_s, self.exposure.duration_s, rel_tol=0, abs_tol=1e-10
        ):
            raise ValueError("exposure duration disagrees with interval")
        if self.k[0] <= 0 or self.k[4] <= 0 or self.k[6:] != (0, 0, 1):
            raise ValueError("invalid intrinsic matrix")
        if self.validity == "missing":
            if self.png_base64 is not None:
                raise ValueError("missing RGB requires null payload")
            return self
        if self.png_base64 is None:
            raise ValueError("present RGB requires PNG")
        try:
            raw = base64.b64decode(self.png_base64, validate=True)
            _validate_png_rgb8(raw)
        except (OSError, SyntaxError, binascii.Error, struct.error, zlib.error) as exc:
            raise ValueError("invalid PNG payload") from exc
        return self


class MeasuredConfirmation(Record):
    sample: ScalarSample | EncoderSample
    age_s: Nonnegative


class ActionFeedback(Record):
    action_id: Annotated[int, Field(strict=True, ge=1)]
    code: Literal[
        "accepted", "executing", "completed", "rejected", "timed_out", "failed", "cancelled"
    ]
    reason: Reason | None
    t_accepted_s: Nonnegative | None
    t_terminal_s: Nonnegative | None
    commanded_target: Action | None
    measured_confirmation: tuple[MeasuredConfirmation, ...]

    @model_validator(mode="after")
    def check_feedback(self) -> Self:
        if self.commanded_target and self.commanded_target.action_id != self.action_id:
            raise ValueError("feedback action ID mismatch")
        if self.code in ("accepted", "executing"):
            if self.t_accepted_s is None or self.t_terminal_s is not None:
                raise ValueError("nonterminal feedback has invalid times")
        elif self.t_terminal_s is None:
            raise ValueError("terminal code requires terminal time")
        if (
            self.t_terminal_s is not None
            and self.t_accepted_s is not None
            and self.t_terminal_s < self.t_accepted_s
        ):
            raise ValueError("termination precedes acceptance")
        return self


class Observation(Record):
    schema_version: Literal["1.0"]
    episode_id: Identifier
    sequence_id: Count
    t_deliver_s: Nonnegative
    scalars: tuple[ScalarSample, ...]
    encoders: tuple[EncoderSample, ...]
    rgb: tuple[RGBSample, ...]
    feedback: tuple[ActionFeedback, ...]
    remaining_budgets: Budgets
    terminal: bool
    terminal_reason: (
        Literal[
            "finished",
            "safe_stop",
            "horizon",
            "thermal_trip",
            "overcurrent",
            "numerical_error",
            "joint_limit",
            "clearance",
        ]
        | None
    )

    @model_validator(mode="after")
    def check_observation(self) -> Self:
        if self.terminal != (self.terminal_reason is not None):
            raise ValueError("terminal flag and reason disagree")
        for sample in self.scalars + self.encoders + self.rgb:
            if sample.t_deliver_s > self.t_deliver_s:
                raise ValueError("observation contains future delivery")
        for feedback in self.feedback:
            for time in (feedback.t_accepted_s, feedback.t_terminal_s):
                if time is not None and time > self.t_deliver_s:
                    raise ValueError("observation contains future feedback")
            for measurement in feedback.measured_confirmation:
                if measurement.sample.t_deliver_s > self.t_deliver_s:
                    raise ValueError("observation contains future measurement")
                age = self.t_deliver_s - measurement.sample.t_capture_s
                if not math.isclose(measurement.age_s, age, rel_tol=0, abs_tol=1e-10):
                    raise ValueError("measurement age disagrees with capture time")
        return self


class Prediction(Record):
    query_id: Identifier
    action_id: Annotated[int, Field(strict=True, ge=1)]
    channel: Channel
    horizon_s: Positive
    mean: Number | None
    sigma: Positive | None
    interval_90: tuple[Number, Number] | None = None
    status: Literal["predicted", "not_predictable"]
    missingness_probability: Probability | None = None

    @model_validator(mode="after")
    def check_prediction(self) -> Self:
        if self.status == "predicted" and self.mean is None:
            raise ValueError("predicted outcome requires a mean")
        if self.status == "not_predictable" and any(
            x is not None for x in (self.mean, self.sigma, self.interval_90)
        ):
            raise ValueError("declined prediction must not invent numeric predictions")
        if self.interval_90 and self.interval_90[0] > self.interval_90[1]:
            raise ValueError("reversed interval")
        return self


class HypothesisProbability(Record):
    hypothesis: Identifier
    probability: Probability


class Decision(Record):
    schema_version: Literal["1.0"]
    action: Action
    predictions: tuple[Prediction, ...]
    hypothesis_probabilities: tuple[HypothesisProbability, ...] | None
    unresolved_hypotheses: tuple[Identifier, ...]
    evidence_refs: tuple[Count, ...]
    rationale: Annotated[str, Field(strict=True, max_length=1000)]

    @model_validator(mode="after")
    def check_decision(self) -> Self:
        if any(p.action_id != self.action.action_id for p in self.predictions):
            raise ValueError("prediction belongs to a different action")
        if len({p.query_id for p in self.predictions}) != len(self.predictions):
            raise ValueError("duplicate prediction query")
        for values in (self.unresolved_hypotheses, self.evidence_refs):
            if len(set(values)) != len(values):
                raise ValueError("duplicate reference")
        if self.hypothesis_probabilities is not None:
            labels = [h.hypothesis for h in self.hypothesis_probabilities]
            if not labels or len(set(labels)) != len(labels):
                raise ValueError("empty or duplicate probability labels")
            if not math.isclose(
                sum(h.probability for h in self.hypothesis_probabilities),
                1,
                rel_tol=0,
                abs_tol=1e-10,
            ):
                raise ValueError("probabilities must sum to one")
        return self


def validate_decision_context(
    decision: Decision, task: PublicTask, history: tuple[Observation, ...]
) -> None:
    """Validate public context only. This does not accept or execute an action."""
    if any(o.episode_id != task.episode_id for o in history):
        raise ValueError("history episode mismatch")
    sequences = [o.sequence_id for o in history]
    if sequences != sorted(set(sequences)):
        raise ValueError("history sequence must increase")
    if not set(decision.evidence_refs) <= set(sequences):
        raise ValueError("evidence reference is not a past observation")
    if decision.action.kind not in task.available_actions:
        raise ValueError("action unavailable")
    if isinstance(decision.action, RequestHelp):
        if decision.action.measurement not in task.available_help:
            raise ValueError("help unavailable")
    if isinstance(decision.action, MoveCamera):
        for name in ("slide_m", "yaw_rad", "pitch_rad"):
            lower, upper = getattr(task.limits, name)
            if not lower <= getattr(decision.action, name) <= upper:
                raise ValueError("target outside advertised limits")
    voltages = ()
    if isinstance(decision.action, SetVoltage):
        voltages = (decision.action.voltage_v,)
    elif isinstance(decision.action, ProbeVoltage):
        voltages = decision.action.voltages_v
    if any(not task.limits.voltage_v[0] <= v <= task.limits.voltage_v[1] for v in voltages):
        raise ValueError("voltage outside advertised limits")
    if any(p.channel not in task.sensors for p in decision.predictions):
        raise ValueError("prediction for unavailable sensor")
    labels = set(task.hypothesis_classes)
    if not set(decision.unresolved_hypotheses) <= labels:
        raise ValueError("undeclared hypothesis")
    if decision.hypothesis_probabilities is not None:
        if {h.hypothesis for h in decision.hypothesis_probabilities} != labels:
            raise ValueError("probabilities must cover the declared hypothesis set")


def validate_observation_context(observation: Observation, task: PublicTask) -> None:
    if observation.episode_id != task.episode_id:
        raise ValueError("episode mismatch")
    if any(s.channel not in task.sensors for s in observation.scalars):
        raise ValueError("unadvertised scalar sensor")
    if observation.encoders and "encoders" not in task.sensors:
        raise ValueError("unadvertised encoders")
    if observation.rgb and "rgb" not in task.sensors:
        raise ValueError("unadvertised RGB")
    for feedback in observation.feedback:
        for measurement in feedback.measured_confirmation:
            sample = measurement.sample
            if isinstance(sample, ScalarSample) and sample.channel not in task.sensors:
                raise ValueError("unadvertised feedback sensor")
            if isinstance(sample, EncoderSample) and "encoders" not in task.sensors:
                raise ValueError("unadvertised feedback encoders")
    for frame in observation.rgb:
        if (
            frame.calibration_id != task.nominal_calibration.calibration_id
            or frame.k != task.nominal_calibration.k
        ):
            raise ValueError("frame calibration mismatch")
    for name in Budgets.model_fields:
        if getattr(observation.remaining_budgets, name) > getattr(task.budgets, name):
            raise ValueError("remaining budget exceeds initial budget")
