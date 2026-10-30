"""Named, deterministic M2 development fixtures, not causal scene generators.

These trusted evaluator helpers are not policy tools. Scene.from_config remains
the sole geometry compiler. Aim targets use declared nominal geometry and must
be executed through ordinary finite camera actions or backend servos.
"""

from __future__ import annotations

import math
from typing import Literal

from pv_sim.config import Config
from pv_sim.scene import Vector3

ViewFixtureName = Literal["reframe", "narrow_screen", "rail_locked", "wide_screen"]
VIEW_FIXTURE_NAMES = ("reframe", "narrow_screen", "rail_locked", "wide_screen")


def view_fixture_config(base: Config, name: ViewFixtureName) -> Config:
    """Return an explicitly configured F1/F2 fixture with source direction +z."""
    if name not in VIEW_FIXTURE_NAMES:
        raise ValueError("unknown M2 view fixture")
    raw = base.model_dump(mode="python")
    raw["m2"] = {
        "view": {
            "screen_half_width_m": (
                None if name == "reframe" else 0.06 if name == "wide_screen" else 0.03
            ),
            "rail_locked": name == "rail_locked",
        }
    }
    raw["private_world"]["source_direction"] = (0.0, 0.0, 1.0)
    if name == "reframe":
        raw["private_world"]["reference_position_m"] = (0.40, 0.10, 0.01)
    return Config.model_validate(raw)


def nominal_aim_target(config: Config, slide_m: float, target_m: Vector3) -> Vector3:
    """Aim a joint target from public nominal geometry; never change camera pose."""
    hx, hy, hz = config.camera.home_position_m
    dx, dy, dz = target_m[0] - hx - slide_m, target_m[1] - hy, target_m[2] - hz
    if dy <= 0 or not all(math.isfinite(v) for v in (slide_m, dx, dy, dz)):
        raise ValueError("target must be finite and in front of the nominal rig")
    yaw = -math.atan2(dx, dy)
    pitch = math.atan2(math.hypot(dx, dy), -dz) - math.atan2(0.45, 0.35)
    command = (slide_m, yaw, pitch)
    limits = (
        config.camera.slide_limits_m,
        config.camera.yaw_limits_rad,
        config.camera.pitch_limits_rad,
    )
    if any(not lo <= value <= hi for value, (lo, hi) in zip(command, limits, strict=True)):
        raise ValueError("nominal view target exceeds rig limits")
    if config.m2 is not None and config.m2.view.rail_locked and slide_m != 0:
        raise ValueError("nominal view target requires unavailable rail translation")
    return command


def view_fixture_targets(config: Config, name: ViewFixtureName) -> tuple[tuple[str, Vector3], ...]:
    """Short diagnostic view sequence; these are unit fixtures, not full pilots."""
    if name not in VIEW_FIXTURE_NAMES:
        raise ValueError("unknown M2 view fixture")
    home = ("home", (0.0, 0.0, 0.0))
    if name == "reframe":
        return home, (
            "reframed",
            nominal_aim_target(config, 0.0, config.private_world.reference_position_m),
        )
    rotation = ("rotation_only", (0.0, 0.2, 0.1))
    if name == "rail_locked":
        return home, rotation
    return (
        home,
        rotation,
        ("right", nominal_aim_target(config, 0.15, (0.0, 0.0, 0.0))),
        ("left", nominal_aim_target(config, -0.15, (0.0, 0.0, 0.0))),
    )
