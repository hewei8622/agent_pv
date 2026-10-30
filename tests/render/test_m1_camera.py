"""Required desktop OpenGL tests; no skip or synthetic-render fallback."""

import math
import tomllib
from pathlib import Path

import numpy as np
import pytest
from fiducials import fiducial_centroid

from pv_sim.backends import MujocoBackend
from pv_sim.config import load_config
from pv_sim.scene import Scene

pytestmark = pytest.mark.render
ROOT = Path(__file__).resolve().parents[2]
TOL = tomllib.loads((ROOT / "configs/tolerances.toml").read_text())["m0"]


class _FiducialScene(Scene):
    """Independent calibration markers in a test fixture, absent from production."""

    def to_mjcf(self, config):
        xml = super().to_mjcf(config)
        markers = "".join(
            f'<geom type="sphere" size=".009" pos="{x} 0 .012" rgba="{colour}"/>'
            for x, colour in ((-0.10, "1 .03 .03 1"), (0.0, ".03 1 .03 1"), (0.10, ".03 .03 1 1"))
        )
        return xml.replace('<body name="panel">', '<body name="panel">' + markers)


@pytest.fixture(scope="module")
def captures():
    config = load_config(ROOT / "configs/pilot.toml")
    backend = MujocoBackend(config, _FiducialScene.from_config(config))
    frames = []
    try:
        home = backend.snapshot()
        home_rgb = backend.render_rgb(home)
        frames.append((home, home_rgb))
        for target in ((0.1, 0.0, 0.0), (0.1, 0.15, 0.0), (0.1, 0.15, 0.10)):
            backend.command_joint_targets(target)
            backend.advance(4000)
            snapshot = backend.snapshot()
            frames.append((snapshot, backend.render_rgb(snapshot)))
        backend.command_joint_targets((-0.1, -0.1, -0.1))
        backend.advance(130)
        moving = backend.snapshot()
        assert abs(moving.qdot[0]) > 1e-3
        frames.append((moving, backend.render_rgb(moving)))
        backend.advance(2000)
        live = backend.snapshot()
        # Historical exposure rendering cannot mutate the current dynamics, and
        # must reproduce the old pose rather than silently rendering the live q.
        np.testing.assert_array_equal(backend.render_rgb(home), home_rgb)
        np.testing.assert_array_equal(backend.render_rgb(moving), frames[-1][1])
        assert backend.snapshot() == live
        yield backend, frames
    finally:
        backend.close()


def test_required_rgb_actual_body_fixed_camera_and_motion(captures):
    backend, frames = captures
    assert backend.model.vis.headlight.active == 0
    assert backend.model.cam_mode[backend.camera_id] == 0
    assert backend.model.cam_bodyid[backend.camera_id] == backend.model.body("camera_link").id
    for _, rgb in frames:
        assert rgb.shape == (480, 640, 3) and rgb.dtype == np.uint8
        assert rgb.std() > TOL["minimum_pixel_standard_deviation"]
        assert len(np.unique(rgb.reshape(-1, 3), axis=0)) >= TOL["minimum_unique_colours"]
    assert not np.array_equal(frames[0][1], frames[1][1])
    assert not np.array_equal(frames[1][1], frames[2][1])
    assert not np.array_equal(frames[2][1], frames[3][1])


@pytest.mark.parametrize("view_index", range(5))
@pytest.mark.parametrize("colour,x", [(0, -0.10), (1, 0.0), (2, 0.10)])
def test_fiducials_follow_measured_pose_analytic_projection(captures, view_index, colour, x):
    _, frames = captures
    state, rgb = frames[view_index]
    measured_x, measured_y = fiducial_centroid(rgb, colour)
    slide, yaw, pitch = state.q
    # Independent ray projection derived from spherical yaw/elevation geometry.
    bearing = math.atan2(9, 7) + pitch
    dx, dy, dz = x - slide, 0.45, 0.012 - 0.35
    horizontal = math.cos(yaw) * dx + math.sin(yaw) * dy
    yz = -math.sin(yaw) * dx + math.cos(yaw) * dy
    vertical = math.cos(bearing) * yz + math.sin(bearing) * dz
    depth = math.sin(bearing) * yz - math.cos(bearing) * dz
    focal = 240 / math.tan(math.pi / 8)
    expected_x = 319.5 + focal * horizontal / depth
    expected_y = 239.5 - focal * vertical / depth
    assert abs(measured_x - expected_x) <= TOL["projection_pixels"]
    assert abs(measured_y - expected_y) <= TOL["projection_pixels"]
