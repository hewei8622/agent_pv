"""Independent analytic F1/F2 checks with actual servo poses and no graphics."""

import dataclasses
import json
import math
from pathlib import Path

import numpy as np
import pytest

from pv_sim.backends import MujocoBackend
from pv_sim.config import load_config
from pv_sim.contracts import Decision, validate_decision_context
from pv_sim.m2_fixtures import (
    VIEW_FIXTURE_NAMES,
    nominal_aim_target,
    view_fixture_config,
    view_fixture_targets,
)
from pv_sim.optics import Optics, UnsupportedOpticalScene, view_ray_clear
from pv_sim.pv import PVModel
from pv_sim.scene import Scene, Screen, Source
from pv_sim.sensors import build_public_task

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def base():
    return load_config(ROOT / "configs/pilot.toml")


def _project(state, point):
    """Independent spherical-bearing projection from measured joint encoders."""
    slide, yaw, pitch = state.q
    bearing = math.atan2(9, 7) + pitch
    dx, dy, dz = point[0] - slide, point[1] + 0.45, point[2] - 0.35
    horizontal = math.cos(yaw) * dx + math.sin(yaw) * dy
    yz = -math.sin(yaw) * dx + math.cos(yaw) * dy
    vertical = math.cos(bearing) * yz + math.sin(bearing) * dz
    depth = math.sin(bearing) * yz - math.cos(bearing) * dz
    assert depth > 0
    focal = 240 / math.tan(math.pi / 8)
    return 319.5 + focal * horizontal / depth, 239.5 - focal * vertical / depth


@pytest.mark.parametrize("name", VIEW_FIXTURE_NAMES)
def test_shared_finite_geometry_light_and_unshaded_source_certificate(base, name):
    config = view_fixture_config(base, name)
    scene = Scene.from_config(config)
    optics = Optics(scene, config)
    baseline = Optics(Scene.from_config(base), base)
    backend = MujocoBackend(config, scene)
    try:
        assert optics.scene is backend.scene is scene
        assert backend.model.vis.headlight.active == 0
        np.testing.assert_array_equal(backend.model.light_dir[0], (0, 0, -1))
        np.testing.assert_allclose(backend.model.light_diffuse[0], (0.8,) * 3)
        assert optics.irradiance_w_m2 == baseline.irradiance_w_m2 == (900.0,) * 8
        assert optics.reference_w_m2 == baseline.reference_w_m2 == 900.0
        assert PVModel(config).operate(optics.irradiance_w_m2, 25.0, 1.8) == PVModel(base).operate(
            baseline.irradiance_w_m2, 25.0, 1.8
        )
        if name == "reframe":
            assert scene.screen is None
            assert tuple(backend.model.geom("reference_patch").pos[:2]) == (0.4, 0.1)
        else:
            screen = backend.model.geom("view_screen")
            assert screen.bodyid[0] == 0  # Static world pose; no separate runtime transform.
            np.testing.assert_array_equal(screen.pos, scene.screen.center_m)
            np.testing.assert_array_equal(screen.size, scene.screen.half_size_m)
            low, high = scene.screen.bounds_m
            np.testing.assert_allclose(low, (-scene.screen.half_width_m, -0.151, 0))
            np.testing.assert_allclose(high, (scene.screen.half_width_m, -0.149, 0.25))
        assert backend.clearance_ok() and backend._renderer is None
    finally:
        backend.close()


@pytest.mark.parametrize("slide", [-0.15, -0.09, 0.0, 0.09, 0.15])
def test_independent_screen_plane_and_finite_thickness_rays(base, slide):
    # Along the camera-to-origin ray, y=-.15 means t=2/3, hence x=s/3,
    # z=.35/3. At the front/back faces x=s*(.151/.45) and s*(.149/.45).
    center_hit = (slide / 3, -0.15, 0.35 / 3)
    assert 0 < center_hit[2] < 0.25
    xs = (slide * 0.151 / 0.45, slide * 0.149 / 0.45)
    for name, half_width in (("narrow_screen", 0.03), ("wide_screen", 0.06)):
        scene = Scene.from_config(view_fixture_config(base, name))
        independent_blocked = min(xs) <= half_width and max(xs) >= -half_width
        assert view_ray_clear(scene, (slide, -0.45, 0.35), (0.0, 0.0, 0.0)) == (
            not independent_blocked
        )


def test_edges_thickness_parallel_rays_and_segment_endpoints(base):
    scene = Scene.from_config(view_fixture_config(base, "narrow_screen"))
    # Parallel rays touch the closed x edge, clear just outside it, and are
    # outside the finite z extent above/below. No pixel thresholds involved.
    for x, expected in ((0.03, False), (0.030001, True), (0.029999, False)):
        assert view_ray_clear(scene, (x, -0.3, 0.1), (x, 0.0, 0.1)) is expected
    assert view_ray_clear(scene, (0.0, -0.3, 0.250001), (0.0, 0.0, 0.250001))
    assert view_ray_clear(scene, (0.0, -0.3, -0.000001), (0.0, 0.0, -0.000001))
    assert view_ray_clear(scene, (0.0, -0.3, 0.1), (0.0, -0.152, 0.1))
    assert not view_ray_clear(scene, (0.0, -0.3, 0.1), (0.0, -0.15, 0.1))
    assert not view_ray_clear(scene, (0.0, -0.15, 0.1), (0.0, 0.0, 0.1))


@pytest.mark.parametrize("name", VIEW_FIXTURE_NAMES)
def test_actual_joint_motion_distinguishes_reframe_reveal_and_reachable_limit(base, name):
    config = view_fixture_config(base, name)
    scene = Scene.from_config(config)
    backend = MujocoBackend(config, scene)
    target = scene.reference_position_m if name == "reframe" else (0.0, 0.0, 0.0)
    home = backend.snapshot()
    outcomes = {}
    try:
        for label, command in view_fixture_targets(config, name):
            backend.command_joint_targets(command)
            backend.advance(4000)
            state = backend.snapshot()
            np.testing.assert_allclose(state.q, command, rtol=0, atol=1e-6)
            outcomes[label] = (view_ray_clear(scene, state.camera_position_m, target), state)
            if label in ("rotation_only", "reframed"):
                np.testing.assert_allclose(
                    state.camera_position_m, home.camera_position_m, atol=1e-10
                )
                assert state.camera_rotation != home.camera_rotation
        if name == "reframe":
            assert _project(home, target)[0] > 639.5 + 10  # Whole reference patch starts offscreen.
            assert outcomes["home"][0] and outcomes["reframed"][0]
            np.testing.assert_allclose(_project(outcomes["reframed"][1], target), (319.5, 239.5))
        else:
            assert not outcomes["home"][0] and not outcomes["rotation_only"][0]
            if name != "rail_locked":
                assert outcomes["right"][0] is (name == "narrow_screen")
                assert outcomes["left"][0] is (name == "narrow_screen")
        assert backend._renderer is None
    finally:
        backend.close()


def test_wide_screen_blocks_complete_rail_and_rotation_cannot_change_ray(base):
    scene = Scene.from_config(view_fixture_config(base, "wide_screen"))
    # Analytic bound for all s in [-.15,.15], not merely a sampled endpoint:
    # the largest |x| on either finite screen face is .15*.151/.45 < .06.
    assert 0.15 * 0.151 / 0.45 < 0.06
    assert 0 < 0.35 * 0.149 / 0.45 < 0.35 * 0.151 / 0.45 < 0.25
    assert not view_ray_clear(scene, (0.0, -0.45, 0.35), (0.0, 0.0, 0.0))


def test_rail_locked_is_advertised_and_context_rejects_translation(base, decision):
    config = view_fixture_config(base, "rail_locked")
    task = build_public_task(config, "m2_rail_locked")
    assert task.limits.slide_m == (0.0, 0.0)
    assert task.limits.yaw_rad == config.camera.yaw_limits_rad
    assert task.limits.pitch_rad == config.camera.pitch_limits_rad
    assert config.camera.slide_limits_m == (-0.15, 0.15)
    with pytest.raises(ValueError, match="outside advertised limits"):
        validate_decision_context(Decision.model_validate_json(json.dumps(decision)), task, ())
    decision["action"].update(slide_m=0.0, yaw_rad=0.2, pitch_rad=0.1)
    validate_decision_context(Decision.model_validate_json(json.dumps(decision)), task, ())
    with pytest.raises(ValueError, match="unavailable rail"):
        nominal_aim_target(config, 0.15, (0.0, 0.0, 0.0))


def test_screen_source_shading_fails_explicitly_until_m3(base):
    config = view_fixture_config(base, "narrow_screen")
    scene = dataclasses.replace(
        Scene.from_config(config), source=Source((0.0, -0.6, 0.8), 800.0, 100.0, 0.0)
    )
    with pytest.raises(UnsupportedOpticalScene, match="screen may block a cell source beam"):
        Optics(scene, config)


def test_fixture_boundaries_and_no_m1_marker_or_screen(base):
    baseline = Scene.from_config(base)
    assert baseline.screen is None
    xml = baseline.to_mjcf(base)
    assert "view_screen" not in xml and "fiducial" not in xml
    for values in ((0.02,), (0.03, (0.0, -0.16, 0.125))):
        with pytest.raises(ValueError):
            Screen(*values)
    for origin, target in (
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        ((math.nan, 0.0, 0.0), (0.0, 0.0, 0.0)),
        ((0.0, 0.0), (0.0, 0.0, 0.0)),
    ):
        with pytest.raises(ValueError, match="view ray requires"):
            view_ray_clear(baseline, origin, target)
