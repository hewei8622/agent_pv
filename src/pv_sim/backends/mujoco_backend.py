"""MuJoCo 3.3.7 finite servo rig and lazy, actual-pose RGB renderer.

API references: https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html
and https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html.
Position actuators use kv damping and implicitfast, as recommended by that
version's position-actuator documentation. No policy command writes qpos/qvel.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import mujoco
import numpy as np

from pv_sim.config import Config
from pv_sim.engine import DynamicsSnapshot
from pv_sim.scene import Scene, Vector3


@dataclass
class _Ramp:
    """Exact piecewise constant acceleration; no per-tick position snapping."""

    rate_limit: float
    acceleration_limit: float
    position: float = 0.0
    velocity: float = 0.0
    target: float = 0.0
    segments: deque = field(default_factory=deque)

    def command(self, target: float | None) -> None:
        self.segments.clear()
        a = self.acceleration_limit
        stop = self.position + self.velocity * abs(self.velocity) / (2 * a)
        if self.velocity:
            self.segments.append((-math.copysign(a, self.velocity), abs(self.velocity) / a))
        self.target = stop if target is None else target
        distance = self.target - stop
        if distance:
            sign = math.copysign(1.0, distance)
            speed = min(self.rate_limit, math.sqrt(abs(distance) * a))
            ramp_time = speed / a
            cruise_time = max(0.0, (abs(distance) - speed * ramp_time) / speed)
            self.segments.append((sign * a, ramp_time))
            if cruise_time:
                self.segments.append((0.0, cruise_time))
            self.segments.append((-sign * a, ramp_time))

    def advance(self, dt: float) -> None:
        remaining = dt
        while self.segments and remaining > 0:
            acceleration, duration = self.segments.popleft()
            step = min(remaining, duration)
            self.position += self.velocity * step + 0.5 * acceleration * step**2
            self.velocity += acceleration * step
            remaining -= step
            duration -= step
            if duration > 1e-14:
                self.segments.appendleft((acceleration, duration))
        if not self.segments:
            # Remove roundoff at the analytically reached trajectory endpoint.
            self.position, self.velocity = self.target, 0.0


class MujocoBackend:
    def __init__(self, config: Config, scene: Scene | None = None):
        self.config = config
        self.scene = scene if scene is not None else Scene.from_config(config)
        self._renderer = None
        self._closed = False
        self._build()
        self.reset()

    def _build(self) -> None:
        self.xml = self.scene.to_mjcf(self.config)
        self.model = mujoco.MjModel.from_xml_string(self.xml)
        self.data = mujoco.MjData(self.model)
        self._render_data = mujoco.MjData(self.model)
        self.camera_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_CAMERA, "agent_rgb")
        self._source_light_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_LIGHT, "source")
        if self._source_light_id < 0:
            raise ValueError("scene requires its named source light")
        if (
            self.camera_id < 0
            or self.model.cam_bodyid[self.camera_id] == 0
            or self.model.cam_mode[self.camera_id] != mujoco.mjtCamLight.mjCAMLIGHT_FIXED
        ):
            raise ValueError("agent_rgb must be a named body-fixed camera")
        if self.model.nq != 3 or self.model.nv != 3 or self.model.nu != 3:
            raise ValueError("M1 requires exactly slide, yaw, and pitch position servos")
        c = self.config.camera
        self._limits = (c.slide_limits_m, c.yaw_limits_rad, c.pitch_limits_rad)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("backend is closed")

    def reset(self, scene: Scene | None = None) -> None:
        self._require_open()
        if scene is not None:
            if self._renderer is not None:
                self._renderer.close()
                self._renderer = None
            self.scene = scene
            self._build()
        mujoco.mj_resetData(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        c = self.config.camera
        self._ramps = [
            _Ramp(c.slide_rate_m_s, c.slide_acceleration_m_s2),
            _Ramp(c.angular_rate_rad_s, c.angular_acceleration_rad_s2),
            _Ramp(c.angular_rate_rad_s, c.angular_acceleration_rad_s2),
        ]
        self.tick = 0
        self.actuator_work_j = 0.0
        if self.config.source_schedule is not None:
            self.apply_source_state(0)

    @property
    def targets(self) -> Vector3:
        return tuple(r.target for r in self._ramps)

    def command_joint_targets(self, target: Vector3) -> None:
        self._require_open()
        if len(target) != 3 or any(isinstance(v, bool) or not math.isfinite(v) for v in target):
            raise ValueError("joint targets must contain three finite numbers")
        if any(not lo <= v <= hi for v, (lo, hi) in zip(target, self._limits, strict=True)):
            raise ValueError("joint target out of range")
        home = self.config.camera.home_position_m
        start = (home[0] + float(self.data.qpos[0]), home[1], home[2])
        end = (home[0] + target[0], home[1], home[2])
        if not self.scene.swept_clearance_ok(start, end):
            raise ValueError("joint command violates conservative clearance")
        for ramp, value in zip(self._ramps, target, strict=True):
            ramp.command(float(value))

    def halt(self) -> None:
        """Brake each setpoint at its acceleration bound, then hold the stop target."""
        self._require_open()
        for ramp in self._ramps:
            ramp.command(None)

    def advance(self, n_ticks: int = 1) -> None:
        self._require_open()
        if type(n_ticks) is not int or n_ticks < 0:
            raise ValueError("n_ticks must be a nonnegative integer")
        for _ in range(n_ticks):
            for i, ramp in enumerate(self._ramps):
                ramp.advance(self.config.simulation.dt_s)
                self.data.ctrl[i] = ramp.position
            q_before = self.data.qpos.copy()
            mujoco.mj_step(self.model, self.data)
            # mj_step leaves derived position fields at its evaluation pose.
            # Recompute them at the integrated q so snapshots never lag one tick.
            forces = self.data.actuator_force.copy()
            self.actuator_work_j += float(np.sum(np.abs(forces * (self.data.qpos - q_before))))
            mujoco.mj_forward(self.model, self.data)
            self.tick += 1
            if not (np.isfinite(self.data.qpos).all() and np.isfinite(self.data.qvel).all()):
                raise FloatingPointError("nonfinite MuJoCo dynamics")

    def snapshot(self) -> DynamicsSnapshot:
        self._require_open()
        return DynamicsSnapshot(
            tick=self.tick,
            time_s=self.tick * self.config.simulation.dt_s,
            q=tuple(float(x) for x in self.data.qpos),
            qdot=tuple(float(x) for x in self.data.qvel),
            camera_position_m=tuple(float(x) for x in self.data.cam_xpos[self.camera_id]),
            camera_rotation=tuple(float(x) for x in self.data.cam_xmat[self.camera_id]),
            actuator_work_j=self.actuator_work_j,
            setpoint=tuple(r.position for r in self._ramps),
            setpoint_rate=tuple(r.velocity for r in self._ramps),
            actuator_force=tuple(float(x) for x in self.data.actuator_force),
        )

    def limits_ok(self) -> bool:
        # Frozen v7 engineering slacks, duplicated explicitly to avoid silently
        # changing runtime protection by editing an evaluation-only test file.
        slacks = (1e-4, 1e-3, 1e-3)
        return all(
            math.isfinite(q) and lo - slack <= q <= hi + slack
            for q, (lo, hi), slack in zip(self.data.qpos, self._limits, slacks, strict=True)
        )

    def clearance_ok(self) -> bool:
        position = tuple(float(x) for x in self.data.cam_xpos[self.camera_id])
        return all(math.isfinite(x) for x in position) and self.scene.swept_clearance_ok(
            position, position
        )

    def apply_source_state(self, tick: int) -> None:
        """Apply the configured private source at a physical endpoint, without GL."""
        self._require_open()
        dni = self.config.source_dni_at_tick(tick)
        self.scene = self.scene.with_source_dni(dni)
        self.model.light_diffuse[self._source_light_id] = dni / 1000

    def render_rgb(self, snapshot: DynamicsSnapshot | None = None) -> np.ndarray:
        """Render the captured q on separate MjData; never change live dynamics.

        The renderer and graphics context are created only here. Production RGB
        failures propagate; no substitute image or automatic skip is provided.
        Source magnitude is resolved at the snapshot's tick, so historical
        captures retain their source state after a later scheduled change.
        """
        self._require_open()
        snapshot = self.snapshot() if snapshot is None else snapshot
        if len(snapshot.q) != 3 or not all(math.isfinite(v) for v in snapshot.q):
            raise ValueError("invalid historical camera state")
        mujoco.mj_resetData(self.model, self._render_data)
        self._render_data.qpos[:] = snapshot.q  # Private historical checkpoint restore only.
        self._render_data.qvel[:] = snapshot.qdot
        self._render_data.time = snapshot.time_s
        mujoco.mj_forward(self.model, self._render_data)
        if self._renderer is None:
            self._renderer = mujoco.Renderer(
                self.model, height=self.config.camera.height, width=self.config.camera.width
            )
        option = mujoco.MjvOption()
        option.geomgroup[3] = 0  # Co-centred inertial boxes are not optical blockers.
        current_diffuse = self.model.light_diffuse[self._source_light_id].copy()
        try:
            if self.config.source_schedule is not None:
                self.model.light_diffuse[self._source_light_id] = (
                    self.config.source_dni_at_tick(snapshot.tick) / 1000
                )
            self._renderer.update_scene(self._render_data, camera="agent_rgb", scene_option=option)
            rgb = self._renderer.render().copy()
        finally:
            # Rendering a previous state never changes the live source state,
            # even if the graphics operation fails.
            self.model.light_diffuse[self._source_light_id] = current_diffuse
        expected = (self.config.camera.height, self.config.camera.width, 3)
        if rgb.shape != expected or rgb.dtype != np.uint8:
            raise RuntimeError("renderer violated RGB shape or dtype")
        return rgb

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self._closed = True
