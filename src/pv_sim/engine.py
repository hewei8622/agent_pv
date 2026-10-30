"""Trusted dynamics boundary. These records must never be passed to a policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from pv_sim.scene import Scene, Vector3


@dataclass(frozen=True)
class DynamicsSnapshot:
    """Actual end-of-tick state, owned values with no mutable MuJoCo array views.

    q/qdot order is slide (m, m/s), yaw and pitch (rad, rad/s). The row-major
    camera_rotation maps camera coordinates to world coordinates: columns are
    right, up, backwards. The camera sees along local -Z. actuator_work_j is the
    accumulated absolute mechanical work of the separately powered rig.
    """

    tick: int
    time_s: float
    q: Vector3
    qdot: Vector3
    camera_position_m: Vector3
    camera_rotation: tuple[float, ...]
    actuator_work_j: float
    setpoint: Vector3
    setpoint_rate: Vector3
    actuator_force: Vector3


class DynamicsBackend(Protocol):
    def reset(self, scene: Scene | None = None) -> None: ...
    def command_joint_targets(self, target: Vector3) -> None: ...
    def advance(self, n_ticks: int = 1) -> None: ...
    def snapshot(self) -> DynamicsSnapshot: ...
    def render_rgb(self, snapshot: DynamicsSnapshot | None = None) -> np.ndarray: ...
    def halt(self) -> None: ...
    def clearance_ok(self) -> bool: ...
    def limits_ok(self) -> bool: ...
    def close(self) -> None: ...
