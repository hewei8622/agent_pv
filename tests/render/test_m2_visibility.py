"""Required real M2 images. No graphics skip or synthetic-image substitute.

Production fixture images and calibration-only fiducials are saved separately.
These direct snapshot renders test geometry, not the sensor exposure timeline;
the observation-integrity tests separately exercise captured/delivered frames.
"""

import dataclasses
import hashlib
import json
import math
import os
import tomllib
from pathlib import Path

import numpy as np
import pytest
from fiducials import fiducial_centroid
from PIL import Image

from pv_sim.backends import MujocoBackend
from pv_sim.config import load_config
from pv_sim.m2_fixtures import VIEW_FIXTURE_NAMES, view_fixture_config, view_fixture_targets
from pv_sim.optics import view_ray_clear
from pv_sim.scene import Scene

pytestmark = pytest.mark.render
ROOT = Path(__file__).resolve().parents[2]
TOL = tomllib.loads((ROOT / "configs/tolerances.toml").read_text())["m0"]


class _CalibrationScene(Scene):
    """Test-only locator, absent from every production scene and policy frame."""

    @property
    def marker_position_m(self):
        if self.screen is None:
            x, y, z = self.reference_position_m
            return x, y, z + 0.012
        return 0.0, 0.0, 0.012

    def to_mjcf(self, config):
        xml = super().to_mjcf(config)
        pos = " ".join(str(x) for x in self.marker_position_m)
        marker = (
            '<geom name="m2_calibration_fiducial" type="sphere" size=".009" '
            f'pos="{pos}" rgba=".03 1 .03 1"/>'
        )
        return xml.replace('<body name="panel">', marker + '<body name="panel">')


def _green_pixels(rgb):
    values = rgb.astype(float)
    return int(
        np.count_nonzero(
            (values[:, :, 1] > 0)
            & (values[:, :, 1] > 5 * values[:, :, 0])
            & (values[:, :, 1] > 5 * values[:, :, 2])
        )
    )


def _project(state, point):
    """Independent spherical-bearing projection, not a backend camera helper."""
    slide, yaw, pitch = state.q
    bearing = math.atan2(9, 7) + pitch
    dx, dy, dz = point[0] - slide, point[1] + 0.45, point[2] - 0.35
    horizontal = math.cos(yaw) * dx + math.sin(yaw) * dy
    yz = -math.sin(yaw) * dx + math.cos(yaw) * dy
    vertical = math.cos(bearing) * yz + math.sin(bearing) * dz
    depth = math.sin(bearing) * yz - math.cos(bearing) * dz
    focal = 240 / math.tan(math.pi / 8)
    return 319.5 + focal * horizontal / depth, 239.5 - focal * vertical / depth


def _save_capture(directory, name, variant, label, config, backend, state, rgb):
    stem = f"m2_{name}_{variant}_{label}"
    png = directory / f"{stem}.png"
    with png.open("xb") as stream:
        Image.fromarray(rgb).save(stream, format="PNG")
    metadata = {
        "fixture": name,
        "variant": variant,
        "view": label,
        "image": png.name,
        "image_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        "config_sha256": config.sha256(),
        "mjcf_sha256": hashlib.sha256(backend.xml.encode()).hexdigest(),
        "actual_q": state.q,
        "camera_position_m": state.camera_position_m,
        "camera_rotation": state.camera_rotation,
        "tick": state.tick,
        "t_capture_s": state.time_s,
        "capture_mode": "direct_actual_pose_snapshot; not a sensor exposure",
        "screen": (
            None if backend.scene.screen is None else dataclasses.asdict(backend.scene.screen)
        ),
        "headlight_active": int(backend.model.vis.headlight.active),
        "calibration_only_fiducial": variant == "calibration",
        "seed": int(os.environ.get("PV_M2_VERIFY_SEED", "20261016")),
    }
    with (directory / f"{stem}.json").open("x") as stream:
        json.dump(metadata, stream, sort_keys=True, indent=2, allow_nan=False)
    return metadata


@pytest.fixture(scope="module", params=VIEW_FIXTURE_NAMES)
def captures(request, tmp_path_factory):
    name = request.param
    base_path = Path(os.environ.get("PV_M2_VERIFY_CONFIG", ROOT / "configs/dev.toml"))
    config = view_fixture_config(load_config(base_path), name)
    directory = Path(
        os.environ.get("PV_M2_RENDER_EVIDENCE_DIR", tmp_path_factory.mktemp("m2_actual_images"))
    )
    directory.mkdir(parents=True, exist_ok=True)
    frames = {}
    for variant, scene_type in (("production", Scene), ("calibration", _CalibrationScene)):
        backend = MujocoBackend(config, scene_type.from_config(config))
        frames[variant] = {}
        try:
            for label, target in view_fixture_targets(config, name):
                backend.command_joint_targets(target)
                backend.advance(4000)
                state = backend.snapshot()
                np.testing.assert_allclose(state.q, target, rtol=0, atol=1e-6)
                rgb = backend.render_rgb(state)
                metadata = _save_capture(
                    directory, name, variant, label, config, backend, state, rgb
                )
                frames[variant][label] = (state, rgb, metadata)
            assert backend.snapshot() == state  # Rendering cannot mutate the actual pose.
        finally:
            backend.close()
    return name, config, frames


def test_actual_production_and_calibration_frames_are_separate_and_nonblank(captures):
    name, config, frames = captures
    expected = len(view_fixture_targets(config, name))
    assert len(frames["production"]) == len(frames["calibration"]) == expected
    for variant, views in frames.items():
        for _, rgb, metadata in views.values():
            assert rgb.shape == (480, 640, 3) and rgb.dtype == np.uint8
            assert rgb.std() > TOL["minimum_pixel_standard_deviation"]
            assert len(np.unique(rgb.reshape(-1, 3), axis=0)) >= TOL["minimum_unique_colours"]
            assert metadata["headlight_active"] == 0
            assert metadata["calibration_only_fiducial"] is (variant == "calibration")
            if variant == "production":
                assert _green_pixels(rgb) == 0


def test_rendered_visibility_distinguishes_framing_translation_and_rail_limit(captures):
    name, config, frames = captures
    scene = _CalibrationScene.from_config(config)
    target = scene.marker_position_m
    for label, (state, rgb, _) in frames["calibration"].items():
        expected_visible = (name == "reframe" and label == "reframed") or (
            name == "narrow_screen" and label in ("right", "left")
        )
        if expected_visible:
            assert view_ray_clear(scene, state.camera_position_m, target)
            assert _green_pixels(rgb) > 20
            measured = fiducial_centroid(rgb, 1)
            expected = _project(state, target)
            np.testing.assert_allclose(measured, expected, atol=TOL["projection_pixels"], rtol=0)
        else:
            assert _green_pixels(rgb) == 0
            if name == "reframe":
                assert view_ray_clear(scene, state.camera_position_m, target)
                assert _project(state, target)[0] > 639.5 + 10
            else:
                assert not view_ray_clear(scene, state.camera_position_m, target)
