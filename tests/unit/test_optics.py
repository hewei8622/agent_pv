"""Analytic M1 irradiance and conservative whole-surface visibility checks."""

import dataclasses
import math
import tomllib
from pathlib import Path

import mujoco
import numpy as np
import pytest

from pv_sim.backends import MujocoBackend
from pv_sim.config import load_config
from pv_sim.optics import Optics, UnsupportedOpticalScene
from pv_sim.scene import Scene, Source

ROOT = Path(__file__).resolve().parents[2]
FRAME_TOL = tomllib.loads((ROOT / "configs/tolerances.toml").read_text())["m0"]["frame_residual"]


@pytest.fixture
def config():
    return load_config(ROOT / "configs/pilot.toml")


def test_uniform_beam_independent_area_power_reference_and_geometry(config):
    scene = Scene.from_config(config)
    optics = Optics(scene, config)
    assert optics.scene is scene
    assert optics.visibility == (1.0,) * 8
    assert optics.reference_visibility == 1.0
    assert optics.irradiance_w_m2 == (900.0,) * 8
    assert optics.reference_w_m2 == 900.0
    # 0.3 by 0.2 m panel receives 54 W before module absorption.
    assert sum(cell.area_m2 * e for cell, e in zip(scene.cells, optics.irradiance_w_m2)) == 54.0
    model = mujoco.MjModel.from_xml_string(scene.to_mjcf(config))
    reference = model.geom("reference_patch")
    np.testing.assert_allclose(reference.size, scene.reference_patch_half_size_m)
    assert abs(reference.pos[2] + reference.size[2] - scene.reference_position_m[2]) <= FRAME_TOL
    for cell in scene.cells:
        geom = model.geom(f"cell_{cell.id}")
        assert geom.pos[2] + geom.size[2] == cell.center_m[2]
        assert cell.normal == (0.0, 0.0, 1.0)


def test_reference_is_local_incident_not_transmitted_cell_average(config):
    original = Scene.from_config(config)
    cells = tuple(
        dataclasses.replace(cell, transmission=0.0 if cell.id == 0 else 0.5)
        for cell in original.cells
    )
    scene = dataclasses.replace(original, cells=cells)
    optics = Optics(scene, config)
    assert optics.irradiance_w_m2 == (0.0,) + (450.0,) * 7
    assert optics.reference_w_m2 == 900.0
    assert optics.reference_w_m2 != sum(optics.irradiance_w_m2) / 8
    with pytest.raises(dataclasses.FrozenInstanceError):
        optics.reference_w_m2 = 0.0


def test_shared_source_cosine_and_diffuse_counted_once(config):
    scene = dataclasses.replace(
        Scene.from_config(config), source=Source((0.6, 0.0, 0.8), 600.0, 30.0, 0.0)
    )
    optics = Optics(scene, config)
    # 3-4-5 source elevation gives 4/5 of direct normal plus one diffuse term.
    assert optics.irradiance_w_m2 == (510.0,) * 8
    assert optics.reference_w_m2 == 510.0
    model = mujoco.MjModel.from_xml_string(scene.to_mjcf(config))
    np.testing.assert_allclose(model.light_dir[0], (-0.6, 0.0, -0.8))
    np.testing.assert_allclose(model.light_diffuse[0], (0.6,) * 3)
    np.testing.assert_allclose(model.light_ambient[0], (0.03,) * 3)


@pytest.mark.parametrize(
    "dni,dhi,expected", [(0.0, 0.0, 0.0), (0.0, 100.0, 100.0), (1200.0, 200.0, 1400.0)]
)
def test_zero_diffuse_only_and_upper_domain(config, dni, dhi, expected):
    scene = dataclasses.replace(
        Scene.from_config(config), source=Source((0.0, 0.0, 1.0), dni, dhi, 0.0)
    )
    result = Optics(scene, config)
    assert result.irradiance_w_m2 == (expected,) * 8
    assert result.reference_w_m2 == expected


def test_midpoint_grid_covers_full_cell_area_and_linear_moments(config):
    optics = Optics(Scene.from_config(config), config)
    assert optics.grid_per_axis == 8
    assert len(optics.quadrature_points_m) == 8
    assert all(len(points) == 64 for points in optics.quadrature_points_m)
    np.testing.assert_allclose(optics.grid(0)[0], (-0.1453125, -0.09375, 0.0), atol=1e-15)
    np.testing.assert_allclose(optics.grid(7)[-1], (0.1453125, 0.09375, 0.0), atol=1e-15)
    points = np.asarray(optics.quadrature_points_m)
    np.testing.assert_allclose(points[0].mean(axis=0), (-0.1125, -0.05, 0.0), atol=1e-15)
    assert len(np.unique(points.reshape(-1, 3), axis=0)) == 512
    assert abs(np.sum(points[:, :, 0] + 2 * points[:, :, 1])) < 1e-12
    with pytest.raises(ValueError):
        optics.grid(-1)


@pytest.mark.parametrize("grid", [16, 32])
def test_unshaded_quadrature_converges_exactly(config, grid):
    world = config.private_world.model_copy(update={"optical_grid_per_axis": grid})
    other = config.model_copy(update={"private_world": world})
    scene = Scene.from_config(config)
    assert Optics(scene, other).irradiance_w_m2 == Optics(scene, config).irradiance_w_m2
    assert len(Optics(scene, other).grid(0)) == grid**2


def test_complete_rig_sweep_does_not_change_incident_power(config):
    scene = Scene.from_config(config)
    optics = Optics(scene, config)
    backend = MujocoBackend(config, scene)
    before = backend.snapshot()
    try:
        backend.command_joint_targets((0.15, math.pi / 4, math.pi / 6))
        backend.advance(3500)
        assert backend.snapshot().q != before.q
        assert backend._renderer is None
        assert optics.irradiance_w_m2 == (900.0,) * 8
        assert optics.reference_w_m2 == 900.0
        # Independent disjoint-footprint proof for all yaw/pitch and rail poses:
        # the entire rig sphere stays below y=-.416, panel starts at y=-.1.
        assert config.camera.home_position_m[1] + scene.rig_radius_m < -0.1
    finally:
        backend.close()


def test_rig_intersection_is_explicit_unsupported_not_false_visibility(config):
    length = math.hypot(0.45, 0.35)
    scene = dataclasses.replace(
        Scene.from_config(config),
        source=Source((0.0, -0.45 / length, 0.35 / length), 800.0, 100.0, 0.0),
    )
    with pytest.raises(UnsupportedOpticalScene, match="source beam may be blocked"):
        Optics(scene, config)


def test_reference_patch_cannot_silently_occlude_cells(config):
    scene = dataclasses.replace(Scene.from_config(config), reference_position_m=(0.0, 0.0, 0.01))
    with pytest.raises(UnsupportedOpticalScene, match="cell source beam may be blocked"):
        Optics(scene, config)


@pytest.mark.parametrize(
    "source",
    [
        Source((0.0, 0.0, -1.0), 800.0, 100.0, 0.0),
        Source((0.0, 0.0, 2.0), 800.0, 100.0, 0.0),
        Source((0.0, 0.0, 1.0), math.nan, 100.0, 0.0),
        Source((0.0, 0.0, 1.0), 800.0, 100.0, 1.0),
    ],
)
def test_unsupported_optical_domain_rejects(config, source):
    scene = dataclasses.replace(Scene.from_config(config), source=source)
    with pytest.raises(UnsupportedOpticalScene):
        Optics(scene, config)
