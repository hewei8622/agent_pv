"""Static unshaded M1/M2 optics over the immutable Scene that emits MJCF.

Visibility=1 is certified for complete surface rectangles against the complete
allowed rig sweep and the reference patch, rather than guessed from a camera
image. M2 adds finite-screen view rays and also certifies its source clearance;
partial source shading remains unsupported. The diffuse field is uniformly
unoccluded and reflected irradiance is zero, as declared by the M1 model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pv_sim.config import Config
from pv_sim.scene import Scene, Vector3


class UnsupportedOpticalScene(ValueError):
    """The geometry cannot be certified by the restricted unshaded model."""


def view_ray_clear(scene: Scene, origin: Vector3, target: Vector3) -> bool:
    """Whether a finite camera-to-target ray clears the declared static screen.

    This M2 fixture query deliberately takes no camera orientation: rotation
    changes framing, not the line from a fixed optical centre to a world point.
    Targets are the upward-facing panel/reference surfaces, with floor and
    backing below them. This is not a general arbitrary-scene visibility API.
    Touching a screen edge counts as occluded; image tests avoid those edges.
    """
    if (
        len(origin) != 3
        or len(target) != 3
        or not all(math.isfinite(v) for v in (*origin, *target))
        or origin == target
    ):
        raise ValueError("view ray requires distinct finite three-dimensional endpoints")
    if scene.screen is None:
        return True
    near, far = 0.0, 1.0
    low, high = scene.screen.bounds_m
    for start, end, lo, hi in zip(origin, target, low, high, strict=True):
        direction = end - start
        if direction == 0:
            if start < lo or start > hi:
                return True
            continue
        a, b = (lo - start) / direction, (hi - start) / direction
        near, far = max(near, min(a, b)), min(far, max(a, b))
        if near > far:
            return True
    return False


def _beam_intersects_box(
    center: Vector3,
    size: tuple[float, float],
    direction: Vector3,
    low: Vector3,
    high: Vector3,
) -> bool:
    """Slab intersection for all parallel rays from a full XY rectangle.

    For each axis, the possible origin interval plus t*direction must overlap
    the box interval. Intersect those t intervals with t>=0. A successful
    intersection is conservative for the rig's enclosing swept box.
    """
    half = (size[0] / 2, size[1] / 2, 0.0)
    near, far = 0.0, math.inf
    for origin, extent, d, lo, hi in zip(center, half, direction, low, high, strict=True):
        origin_low, origin_high = origin - extent, origin + extent
        if d == 0:
            if origin_high < lo or origin_low > hi:
                return False
            continue
        a, b = (lo - origin_high) / d, (hi - origin_low) / d
        near, far = max(near, min(a, b)), min(far, max(a, b))
        if near > far:
            return False
    return near <= far


def _unit(vector: Vector3) -> bool:
    return (
        len(vector) == 3
        and all(math.isfinite(x) for x in vector)
        and math.isclose(math.fsum(x * x for x in vector), 1.0, rel_tol=0, abs_tol=1e-12)
    )


@dataclass(frozen=True, init=False)
class Optics:
    scene: Scene
    grid_per_axis: int
    irradiance_w_m2: tuple[float, ...]
    reference_w_m2: float
    visibility: tuple[float, ...]
    reference_visibility: float
    quadrature_points_m: tuple[tuple[Vector3, ...], ...]

    def __init__(self, scene: Scene, config: Config):
        source = scene.source
        if (
            not _unit(source.direction)
            or source.direction[2] < 0
            or not math.isfinite(source.dni_w_m2)
            or not 0 <= source.dni_w_m2 <= 1200
            or not math.isfinite(source.dhi_w_m2)
            or not 0 <= source.dhi_w_m2 <= 200
        ):
            raise UnsupportedOpticalScene(
                "unsupported M1 source: require a finite upper-hemisphere source"
            )
        if source.reflected_w_m2 != 0:
            raise UnsupportedOpticalScene("unsupported M1 reflected irradiance: must be zero")
        if len(scene.cells) != 8 or tuple(cell.id for cell in scene.cells) != tuple(range(8)):
            raise UnsupportedOpticalScene("unsupported M1 cell topology")
        if scene.reference_normal != (0.0, 0.0, 1.0):
            raise UnsupportedOpticalScene("unsupported M1 reference orientation")
        for cell in scene.cells:
            if (
                cell.normal != (0.0, 0.0, 1.0)
                or not math.isfinite(cell.transmission)
                or not 0 <= cell.transmission <= 1
            ):
                raise UnsupportedOpticalScene("unsupported M1 cell orientation or transmission")

        radius = scene.rig_radius_m
        hx, hy, hz = config.camera.home_position_m
        rail_low, rail_high = config.camera.slide_limits_m
        rig_low = (hx + rail_low - radius, hy - radius, hz - radius)
        rig_high = (hx + rail_high + radius, hy + radius, hz + radius)
        rx, ry, rz = scene.reference_position_m
        if (
            not all(math.isfinite(v) for v in scene.reference_position_m)
            or rz < scene.panel_center_m[2]
        ):
            raise UnsupportedOpticalScene("unsupported M1 reference position")
        rw, rh, rd = scene.reference_patch_half_size_m
        patch_low = (rx - rw, ry - rh, rz - 2 * rd)
        patch_high = (rx + rw, ry + rh, rz)
        # Whole cell areas are certified, so changing quadrature density cannot
        # hide a missed blocker. Panel/backing and floor lie below these upward
        # facing surfaces and cannot block an upper-hemisphere incident beam.
        for cell in scene.cells:
            if _beam_intersects_box(
                cell.center_m, cell.size_m, source.direction, rig_low, rig_high
            ) or _beam_intersects_box(
                cell.center_m, cell.size_m, source.direction, patch_low, patch_high
            ):
                raise UnsupportedOpticalScene(
                    "unsupported M1 geometry: cell source beam may be blocked"
                )
            if scene.screen is not None and _beam_intersects_box(
                cell.center_m, cell.size_m, source.direction, *scene.screen.bounds_m
            ):
                raise UnsupportedOpticalScene(
                    "unsupported M2 geometry: screen may block a cell source beam"
                )
        if _beam_intersects_box(
            scene.reference_position_m, (2 * rw, 2 * rh), source.direction, rig_low, rig_high
        ):
            raise UnsupportedOpticalScene(
                "unsupported M1 geometry: reference source beam may be blocked"
            )
        if scene.screen is not None and _beam_intersects_box(
            scene.reference_position_m,
            (2 * rw, 2 * rh),
            source.direction,
            *scene.screen.bounds_m,
        ):
            raise UnsupportedOpticalScene(
                "unsupported M2 geometry: screen may block the reference source beam"
            )

        grid = config.private_world.optical_grid_per_axis
        points = tuple(cell.equal_area_points(grid) for cell in scene.cells)
        visibility = (1.0,) * 8
        irradiance = tuple(
            cell.transmission
            * (
                source.dni_w_m2
                * max(
                    0.0,
                    math.fsum(
                        n * light for n, light in zip(cell.normal, source.direction, strict=True)
                    ),
                )
                * visible
                + source.dhi_w_m2
            )
            for cell, visible in zip(scene.cells, visibility, strict=True)
        )
        reference = (
            source.dni_w_m2
            * max(
                0.0,
                math.fsum(
                    n * light
                    for n, light in zip(scene.reference_normal, source.direction, strict=True)
                ),
            )
            + source.dhi_w_m2
        )
        object.__setattr__(self, "scene", scene)
        object.__setattr__(self, "grid_per_axis", grid)
        object.__setattr__(self, "irradiance_w_m2", irradiance)
        object.__setattr__(self, "reference_w_m2", reference)
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(self, "reference_visibility", 1.0)
        object.__setattr__(self, "quadrature_points_m", points)

    def grid(self, cell_id: int) -> tuple[Vector3, ...]:
        """Equal-area midpoint samples in metres, ordered y-major then x."""
        if type(cell_id) is not int or not 0 <= cell_id < 8:
            raise ValueError("cell_id must be an integer in [0, 7]")
        return self.quadrature_points_m[cell_id]
