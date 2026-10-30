"""Independent geometry and genuine MuJoCo motion; never initialize graphics."""

import dataclasses
import math
import tomllib
from pathlib import Path

import mujoco
import numpy as np
import pytest

from pv_sim.backends import MujocoBackend
from pv_sim.config import load_config
from pv_sim.scene import Scene

ROOT = Path(__file__).resolve().parents[2]
TOL = tomllib.loads((ROOT / "configs/tolerances.toml").read_text())["m1_planned_not_executed"]


@pytest.fixture
def backend():
    result = MujocoBackend(load_config(ROOT / "configs/pilot.toml"))
    yield result
    assert result._renderer is None  # All dynamics tests genuinely run without OpenGL.
    result.close()


def _analytic_frame(q):
    """Independent spherical-bearing derivation, without backend frame helpers."""
    slide, yaw, pitch = q
    bearing = math.atan2(9, 7) + pitch
    sy, cy, sa, ca = math.sin(yaw), math.cos(yaw), math.sin(bearing), math.cos(bearing)
    right = (cy, sy, 0.0)
    up = (-sy * ca, cy * ca, sa)
    backwards = (sy * sa, -cy * sa, ca)
    return np.column_stack((right, up, backwards)), (slide, -0.45, 0.35)


def test_manifest_matches_optical_and_compiled_cells(backend):
    scene = backend.scene
    assert len(scene.cells) == 8
    assert sum(cell.area_m2 for cell in scene.cells) == pytest.approx(0.06)
    for cell in scene.cells:
        geom = backend.model.geom(f"cell_{cell.id}")
        np.testing.assert_allclose(geom.pos[:2], cell.center_m[:2], atol=1e-12)
        assert geom.pos[2] + geom.size[2] == cell.center_m[2]
        assert len(cell.equal_area_points(8)) == 64
        assert cell.area_m2 == pytest.approx(math.prod(cell.size_m))
        assert cell.substring_id == cell.id // 4
    assert scene.source.dni_w_m2 == 800 and scene.source.dhi_w_m2 == 100
    np.testing.assert_allclose(backend.model.light_dir[0], (0, 0, -1))
    np.testing.assert_allclose(backend.model.light_diffuse[0], (0.8, 0.8, 0.8))
    assert backend.model.vis.headlight.active == 0
    assert np.all(backend.model.body_inertia[1:] > 0)
    masses = [backend.model.body(name).mass[0] for name in ("carriage", "yaw_link", "camera_link")]
    np.testing.assert_allclose(masses, (0.10, 0.03, 0.02))


@pytest.mark.parametrize(
    "target",
    [(0.0, 0.0, 0.0), (0.15, 0.0, 0.0), (0.0, 0.3, 0.0), (0.0, 0.0, 0.2), (-0.1, -0.2, -0.15)],
)
def test_home_side_yaw_pitch_frames_from_measured_pose(backend, target):
    backend.command_joint_targets(target)
    backend.advance(4000)
    state = backend.snapshot()
    expected, position = _analytic_frame(state.q)
    rotation = np.asarray(state.camera_rotation).reshape(3, 3)
    np.testing.assert_allclose(rotation, expected, atol=1e-10, rtol=0)
    np.testing.assert_allclose(state.camera_position_m, position, atol=1e-10, rtol=0)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-10, rtol=0)
    assert abs(np.linalg.det(rotation) - 1) < 1e-10
    np.testing.assert_allclose(state.q, target, atol=1e-6, rtol=0)
    assert backend.model.cam_mode[backend.camera_id] == mujoco.mjtCamLight.mjCAMLIGHT_FIXED
    assert backend.model.cam_bodyid[backend.camera_id] == backend.model.body("camera_link").id


def test_finite_move_bounded_ramps_forces_limits_and_settle(backend):
    targets = [(0.15, math.pi / 4, math.pi / 6), (-0.15, -math.pi / 4, -math.pi / 6)]
    c = backend.config.camera
    dt = backend.config.simulation.dt_s
    rates = np.array((c.slide_rate_m_s, c.angular_rate_rad_s, c.angular_rate_rad_s))
    accelerations = np.array(
        (c.slide_acceleration_m_s2, c.angular_acceleration_rad_s2, c.angular_acceleration_rad_s2)
    )
    errors = np.array(
        (TOL["slide_settle_error_m"], TOL["angle_settle_error_rad"], TOL["angle_settle_error_rad"])
    )
    last_work = 0.0
    for target in targets:
        before = backend.snapshot()
        backend.command_joint_targets(target)
        assert backend.snapshot() == before  # Neither commanded target nor ramp teleports q.
        consecutive = 0
        previous = before
        for tick in range(4000):
            backend.advance()
            state = backend.snapshot()
            if tick == 0:
                assert state.q != target
                assert state.q != state.setpoint  # A finite servo has dynamic lag.
                assert abs(state.q[0] - before.q[0]) < 0.001
            assert np.all(np.abs(state.setpoint_rate) <= rates + 1e-12)
            assert np.all(
                np.abs(np.array(state.setpoint_rate) - previous.setpoint_rate)
                <= accelerations * dt + 1e-12
            )
            assert np.all(
                np.abs(np.array(state.setpoint) - previous.setpoint) <= rates * dt + 1e-12
            )
            assert np.all(np.abs(state.actuator_force) <= np.array((5.0, 0.2, 0.2)) + 1e-12)
            assert backend.limits_ok() and backend.clearance_ok()
            assert state.actuator_work_j >= last_work
            last_work = state.actuator_work_j
            error_ok = np.all(np.abs(np.array(state.q) - target) <= errors)
            # Explicit frozen measured-rate criterion, same dimensional thresholds per second.
            slow = np.all(np.abs(state.qdot) <= errors)
            consecutive = consecutive + 1 if error_ok and slow else 0
            previous = state
        assert consecutive >= round(c.settle_s / dt)
    assert last_work > 0


def test_bounded_halt_and_reversal_without_state_write(backend):
    backend.command_joint_targets((0.15, 0.7, 0.5))
    backend.advance(400)
    before = backend.snapshot()
    assert before.q[0] > 0 and before.qdot[0] > 0
    backend.halt()
    assert backend.snapshot() == before
    stop_targets = backend.targets
    assert stop_targets[0] > before.setpoint[0]
    dt = backend.config.simulation.dt_s
    previous = before
    for _ in range(700):
        backend.advance()
        state = backend.snapshot()
        assert np.all(
            np.abs(np.array(state.setpoint_rate) - previous.setpoint_rate)
            <= np.array((0.2, 1.0, 1.0)) * dt + 1e-12
        )
        assert backend.limits_ok()
        previous = state
    np.testing.assert_allclose(state.q, stop_targets, atol=1e-6, rtol=0)
    np.testing.assert_allclose(state.qdot, 0, atol=1e-6, rtol=0)
    backend.command_joint_targets((-0.15, -0.7, -0.5))
    backend.advance(100)
    before = backend.snapshot()
    backend.command_joint_targets((0.1, 0.4, 0.3))
    previous = before
    for _ in range(3000):
        backend.advance()
        state = backend.snapshot()
        assert np.all(
            np.abs(np.array(state.setpoint_rate) - previous.setpoint_rate)
            <= np.array((0.2, 1.0, 1.0)) * dt + 1e-12
        )
        assert backend.limits_ok()
        previous = state
    np.testing.assert_allclose(state.q, (0.1, 0.4, 0.3), atol=1e-6, rtol=0)


@pytest.mark.parametrize(
    "target",
    [
        (0.151, 0.0, 0.0),
        (0.0, 0.8, 0.0),
        (0.0, 0.0, -0.53),
        (math.nan, 0.0, 0.0),
        (0.0, math.inf, 0.0),
    ],
)
def test_reject_illegal_targets_without_advancing(backend, target):
    before = backend.snapshot()
    with pytest.raises(ValueError):
        backend.command_joint_targets(target)
    assert backend.snapshot() == before


def test_actual_stall_is_observed_without_fabricated_tracking(backend):
    # Genuine disabled MuJoCo position feedback, retaining its velocity damping.
    backend.model.actuator_gainprm[:, 0] = 0
    backend.model.actuator_biasprm[:, 1] = 0
    backend.command_joint_targets((0.1, 0.2, 0.1))
    backend.advance(2000)
    state = backend.snapshot()
    np.testing.assert_array_equal(state.q, (0.0, 0.0, 0.0))
    np.testing.assert_allclose(state.setpoint, (0.1, 0.2, 0.1), atol=1e-12)
    assert state.q != state.setpoint
    assert state.actuator_work_j == 0


def test_snapshot_owned_immutable_reset_and_clearance(backend):
    initial = backend.snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        initial.tick = 9
    backend.command_joint_targets((0.1, 0.2, 0.1))
    backend.advance(100)
    assert initial.q == (0.0, 0.0, 0.0) and initial.tick == 0
    assert backend.snapshot().q != initial.q
    backend.reset()
    assert backend.snapshot() == initial
    scene = Scene.from_config(backend.config)
    assert scene.swept_clearance_ok((-0.15, -0.45, 0.35), (0.15, -0.45, 0.35))
    assert not scene.swept_clearance_ok((0.0, 0.0, 0.01), (0.0, 0.0, 0.01))
