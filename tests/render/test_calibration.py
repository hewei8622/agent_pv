import math
import tomllib
from pathlib import Path

import numpy as np
import pytest
from fiducials import fiducial_centroid

from pv_sim.calibration import render_calibration

pytestmark = pytest.mark.render
TOL = tomllib.loads((Path(__file__).resolve().parents[2] / "configs/tolerances.toml").read_text())[
    "m0"
]


@pytest.fixture(scope="module")
def rendered():
    return render_calibration()


def test_required_real_named_rgb(rendered):
    rgb, details, _ = rendered
    assert rgb.shape == (480, 640, 3) and rgb.dtype == np.uint8
    assert details["camera"] == "agent_rgb" and details["camera_body_id"] > 0
    assert details["camera_mode"] == 0  # mjCAMLIGHT_FIXED
    assert details["headlight_active"] == 0
    assert details["unique_colours"] >= TOL["minimum_unique_colours"]
    assert rgb.std() > TOL["minimum_pixel_standard_deviation"]


def test_actual_camera_basis_independent_expectation(rendered):
    _, details, _ = rendered
    rotation = np.array(details["camera_rotation"])
    tolerance = TOL["frame_residual"]
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=tolerance, rtol=0)
    assert abs(np.linalg.det(rotation) - 1) <= tolerance
    np.testing.assert_allclose(
        details["camera_position_m"], [0, -0.45, 0.35], atol=tolerance, rtol=0
    )
    forward = -rotation[:, 2]
    # Independent direction ratio to the target, not copied renderer matrix code.
    assert abs(forward[1] / (-forward[2]) - 9 / 7) <= tolerance
    assert abs(forward[0]) <= tolerance


@pytest.mark.parametrize("colour,x", [(0, -0.10), (1, 0.0), (2, 0.10)])
def test_fiducial_projection_from_analytic_geometry(rendered, colour, x):
    rgb, _, _ = rendered
    measured_x, measured_y = fiducial_centroid(rgb, colour)
    # Analytic pinhole projection of each sphere centre from the home geometry.
    length = math.sqrt(0.45**2 + 0.35**2)
    depth = (0.45**2 + 0.35 * (0.35 - 0.012)) / length
    vertical = 0.45 * 0.012 / length
    focal = 240 / math.tan(math.pi / 8)
    expected_x = 319.5 + focal * x / depth
    expected_y = 239.5 - focal * vertical / depth
    assert abs(measured_x - expected_x) <= TOL["projection_pixels"]
    assert abs(measured_y - expected_y) <= TOL["projection_pixels"]
