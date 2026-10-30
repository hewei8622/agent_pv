"""Up-front public resource gate. Acceptance is not measured completion."""

from pv_sim.config import Config
from pv_sim.contracts import (
    Action,
    Budgets,
    CaptureRGB,
    Finish,
    MoveCamera,
    ProbeVoltage,
    PublicTask,
    RequestHelp,
    SafeStop,
    SetVoltage,
)


def required_tokens(action: Action) -> tuple[int, int]:
    frames = int(
        isinstance(action, CaptureRGB)
        or (isinstance(action, MoveCamera) and action.capture_after_settle)
    )
    points = (
        len(action.voltages_v)
        if isinstance(action, ProbeVoltage)
        else int(isinstance(action, SetVoltage))
    )
    return frames, points


def gate(
    action: Action,
    task: PublicTask,
    remaining: Budgets,
    config: Config,
    q: tuple[float, float, float],
) -> str | None:
    if isinstance(action, SafeStop):
        return None
    if action.timeout_s > config.simulation.max_action_timeout_s:
        return "out_of_range"
    if action.kind not in task.available_actions or isinstance(action, RequestHelp):
        return "sensor_unavailable"
    frames, points = required_tokens(action)
    if frames and "rgb" not in task.sensors:
        return "sensor_unavailable"
    if frames > remaining.rgb_frames or points > remaining.voltage_points:
        return "budget"
    if isinstance(action, MoveCamera):
        requested = (action.slide_m, action.yaw_rad, action.pitch_rad)
        advertised = (task.limits.slide_m, task.limits.yaw_rad, task.limits.pitch_rad)
        if any(
            not low <= value <= high
            for value, (low, high) in zip(requested, advertised, strict=True)
        ):
            return "out_of_range"
    if isinstance(action, (SetVoltage, ProbeVoltage)):
        values = (action.voltage_v,) if isinstance(action, SetVoltage) else action.voltages_v
        low, high = task.limits.voltage_v
        if any(not low <= value <= high for value in values):
            return "out_of_range"
    if isinstance(action, MoveCamera):
        # Conservative reservation includes a full-speed braking distance and
        # the declared measured tracking tolerances. Actual travel is charged.
        camera = config.camera
        slide = (
            abs(action.slide_m - q[0])
            + camera.slide_rate_m_s**2 / (2 * camera.slide_acceleration_m_s2)
            + 0.001
        )
        angle = (
            abs(action.yaw_rad - q[1])
            + abs(action.pitch_rad - q[2])
            + (camera.angular_rate_rad_s**2 / camera.angular_acceleration_rad_s2)
            + 0.02
        )
        if slide > remaining.slide_path_m or angle > remaining.angular_path_rad:
            return "budget"
    tail = config.simulation.verification_tail_s
    if isinstance(action, Finish) and action.timeout_s < tail:
        return "out_of_range"
    required = action.timeout_s if isinstance(action, Finish) else action.timeout_s + tail
    if required > remaining.time_s + 1e-10:
        return "budget"
    return None
