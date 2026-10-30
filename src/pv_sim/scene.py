"""One immutable geometry/source manifest for the initial unshaded M1 world.

World axes are right handed, +z up. Camera yaw is about world +z and
pitch is about the yaw-rotated +x (camera-right) axis, both at the optical
centre. Positive angles obey the right-hand rule: R = Rz(yaw) Rx(pitch) Rhome.
Cell border gaps are visual only; quadrature covers each complete rectangle.
The initial rig is outside the source path; rig self-shadow is not modeled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from pv_sim.config import Config

Vector3 = tuple[float, float, float]


def _numbers(values) -> str:
    return " ".join(format(value, ".17g") for value in values)


@dataclass(frozen=True)
class Cell:
    id: int
    substring_id: int
    center_m: Vector3
    size_m: tuple[float, float]
    area_m2: float
    normal: Vector3
    transmission: float

    @property
    def vertices_m(self) -> tuple[Vector3, ...]:
        x, y, z = self.center_m
        w, h = self.size_m
        return tuple(
            (x + sx * w / 2, y + sy * h / 2, z) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        )

    def equal_area_points(self, grid_per_axis: int) -> tuple[Vector3, ...]:
        if type(grid_per_axis) is not int or grid_per_axis < 1:
            raise ValueError("quadrature size must be a positive integer")
        x, y, z = self.center_m
        w, h = self.size_m
        return tuple(
            (
                x + ((i + 0.5) / grid_per_axis - 0.5) * w,
                y + ((j + 0.5) / grid_per_axis - 0.5) * h,
                z,
            )
            for j in range(grid_per_axis)
            for i in range(grid_per_axis)
        )


@dataclass(frozen=True)
class Source:
    direction: Vector3  # Unit vector from a surface toward the source.
    dni_w_m2: float
    dhi_w_m2: float
    reflected_w_m2: float


@dataclass(frozen=True)
class Screen:
    """Static, opaque v5 screen; one record supplies visual and optical bounds.

    It is world-fixed, so MuJoCo never updates its transform independently.
    Finite thickness is 2 mm. Source-path intersections remain unsupported in
    M2: these fixtures distinguish view occlusion from source shading only.
    """

    half_width_m: float
    center_m: Vector3 = (0.0, -0.15, 0.125)
    half_height_m: float = 0.125
    half_depth_m: float = 0.001

    def __post_init__(self) -> None:
        if self.half_width_m not in (0.03, 0.06):
            raise ValueError("M2 screen half width must be 0.03 or 0.06 m")
        if (
            self.center_m != (0.0, -0.15, 0.125)
            or self.half_height_m != 0.125
            or self.half_depth_m != 0.001
        ):
            raise ValueError("M2 screen position, height and depth are frozen")

    @property
    def half_size_m(self) -> Vector3:
        return (self.half_width_m, self.half_depth_m, self.half_height_m)

    @property
    def bounds_m(self) -> tuple[Vector3, Vector3]:
        return tuple(
            tuple(c + sign * s for c, s in zip(self.center_m, self.half_size_m, strict=True))
            for sign in (-1, 1)
        )


@dataclass(frozen=True)
class Scene:
    cells: tuple[Cell, ...]
    source: Source
    panel_size_m: tuple[float, float]
    panel_center_m: Vector3
    reference_position_m: Vector3
    reference_normal: Vector3 = (0.0, 0.0, 1.0)
    screen: Screen | None = None

    # Declared half sizes generate the link inertias in MuJoCo, in metres.
    carriage_half_size_m = (0.025, 0.020, 0.010)
    yaw_half_size_m = (0.018, 0.018, 0.012)
    camera_half_size_m = (0.015, 0.010, 0.010)
    reference_patch_half_size_m = (0.010, 0.010, 0.001)

    @classmethod
    def from_config(cls, config: Config) -> Scene:
        w = config.private_world
        width, height = w.panel_size_m
        dx, dy = width / w.columns, height / w.rows
        cx, cy, cz = w.panel_center_m
        cells = tuple(
            Cell(
                id=row * w.columns + col,
                substring_id=row,
                center_m=(
                    cx - width / 2 + (col + 0.5) * dx,
                    cy - height / 2 + (row + 0.5) * dy,
                    cz,
                ),
                size_m=(dx, dy),
                area_m2=w.cell_area_m2,
                normal=w.panel_normal,
                transmission=w.transmission[row * w.columns + col],
            )
            for row in range(w.rows)
            for col in range(w.columns)
        )
        half_width = None if config.m2 is None else config.m2.view.screen_half_width_m
        return cls(
            cells,
            Source(w.source_direction, w.dni_w_m2, w.dhi_w_m2, w.reflected_w_m2),
            w.panel_size_m,
            w.panel_center_m,
            w.reference_position_m,
            screen=None if half_width is None else Screen(half_width),
        )

    @property
    def rig_radius_m(self) -> float:
        """Sphere containing every co-centred link at every allowed rotation."""
        return max(
            math.sqrt(sum(x * x for x in size))
            for size in (self.carriage_half_size_m, self.yaw_half_size_m, self.camera_half_size_m)
        )

    def with_source_dni(self, dni_w_m2: float) -> Scene:
        """New immutable magnitude state; geometry and all other optics are fixed."""
        if (
            isinstance(dni_w_m2, bool)
            or not isinstance(dni_w_m2, (int, float))
            or not math.isfinite(dni_w_m2)
            or not 0 <= dni_w_m2 <= 1200
        ):
            raise ValueError("DNI must be finite and in [0, 1200] W/m2")
        return replace(self, source=replace(self.source, dni_w_m2=float(dni_w_m2)))

    def swept_clearance_ok(self, start: Vector3, end: Vector3) -> bool:
        """Conservative swept bounding-box clearance for the static fixture.

        Static solids are the floor, panel/backing, and reference patch. Rotating
        links are enclosed by one sphere. This is a sufficient clearance test,
        not a contact solver or permission to add arbitrary blockers. M2's
        declared screen participates through the same bounds as view optics.
        """
        radius = self.rig_radius_m
        low = tuple(min(a, b) - radius for a, b in zip(start, end, strict=True))
        high = tuple(max(a, b) + radius for a, b in zip(start, end, strict=True))
        if low[2] <= -0.018:
            return False
        x, y, z = self.panel_center_m
        w, h = self.panel_size_m
        rx, ry, rz = self.reference_position_m
        rw, rh, rd = self.reference_patch_half_size_m
        obstacles = (
            (
                (x - w / 2 - 0.007, y - h / 2 - 0.007, z - 0.009),
                (x + w / 2 + 0.007, y + h / 2 + 0.007, z),
            ),
            ((rx - rw, ry - rh, rz - 2 * rd), (rx + rw, ry + rh, rz)),
        )
        if self.screen is not None:
            obstacles += (self.screen.bounds_m,)
        return all(any(high[i] < lo[i] or low[i] > hi[i] for i in range(3)) for lo, hi in obstacles)

    def to_mjcf(self, config: Config) -> str:
        """Compile the manifest into MJCF, using the frozen synthetic servo gains.

        RGB lighting uses fixed linear scales diffuse=DNI/1000 and ambient=DHI/1000,
        with classic-renderer clipping. RGB is not calibrated irradiance. There is
        no diagnosis-dependent material/light selection. Inertial boxes are hidden
        in rendering (group 3), because this ideal co-centred camera is inside them.
        """
        c, s = config.camera, config.servos
        length = math.hypot(0.45, 0.35)
        cells = []
        for cell in self.cells:
            x, y, z = cell.center_m
            w, h = cell.size_m
            # Fixed geometric checker pattern, independent of private causes.
            colour = ".03 .13 .35 1" if (cell.id + cell.substring_id) % 2 else ".05 .22 .50 1"
            cells.append(
                f'<geom name="cell_{cell.id}" type="box" '
                f'size="{w / 2 - 0.001} {h / 2 - 0.001} .001" '
                f'pos="{x} {y} {z - 0.001}" rgba="{colour}"/>'
            )
        limits = (c.slide_limits_m, c.yaw_limits_rad, c.pitch_limits_rad)
        actuators = []
        for i, name in enumerate(("slide", "yaw", "pitch")):
            kp = s.slide_kp_n_m if i == 0 else s.hinge_kp_nm_rad
            kv = s.slide_damping_n_s_m if i == 0 else s.hinge_damping_nm_s_rad
            cap = s.slide_force_cap_n if i == 0 else s.hinge_torque_cap_nm
            actuators.append(
                f'<position name="{name}_servo" joint="{name}" kp="{kp}" '
                f'kv="{kv}" ctrllimited="true" ctrlrange="{_numbers(limits[i])}" '
                f'forcelimited="true" forcerange="{-cap} {cap}"/>'
            )
        light_direction = _numbers(tuple(-x for x in self.source.direction))
        diffuse = _numbers((self.source.dni_w_m2 / 1000,) * 3)
        ambient = _numbers((self.source.dhi_w_m2 / 1000,) * 3)
        px, py, pz = self.panel_center_m
        pw, ph = self.panel_size_m
        rx, ry, rz = self.reference_position_m
        rw, rh, rd = self.reference_patch_half_size_m
        screen = ""
        if self.screen is not None:
            screen = (
                '<geom name="view_screen" type="box" '
                f'size="{_numbers(self.screen.half_size_m)}" '
                f'pos="{_numbers(self.screen.center_m)}" rgba=".42 .44 .46 1"/>'
            )
        return f'''<mujoco model="m1_unshaded_pv">
          <compiler angle="radian" inertiafromgeom="true"/>
          <option timestep="{config.simulation.dt_s}" integrator="implicitfast">
            <flag autoreset="disable"/>
          </option>
          <visual><global offwidth="{c.width}" offheight="{c.height}"/>
            <headlight active="0"/><rgba haze=".08 .10 .14 1"/></visual>
          <default><geom contype="0" conaffinity="0"/></default>
          <worldbody>
            <light name="source" directional="true" pos="0 0 1" dir="{light_direction}"
                   ambient="{ambient}" diffuse="{diffuse}" specular="0 0 0"/>
            <geom name="floor" type="plane" size=".6 .6 .01" pos="0 0 -.018"
                  rgba=".18 .20 .24 1"/>
            <body name="panel">
              <geom name="panel_backing" type="box" size="{pw / 2 + 0.007} {ph / 2 + 0.007} .004"
                    pos="{px} {py} {pz - 0.005}" rgba=".7 .72 .75 1"/>
              {"".join(cells)}
            </body>
            <geom name="reference_patch" type="box" size="{rw} {rh} {rd}"
                  pos="{rx} {ry} {rz - rd}" rgba=".7 .7 .7 1"/>
            {screen}
            <body name="carriage" pos="{_numbers(c.home_position_m)}">
              <joint name="slide" type="slide" axis="1 0 0" limited="true"
                     range="{_numbers(limits[0])}"/>
              <geom name="carriage_inertia" type="box" group="3"
                    size="{_numbers(self.carriage_half_size_m)}" mass="{s.carriage_mass_kg}"/>
              <body name="yaw_link">
                <joint name="yaw" type="hinge" axis="0 0 1" limited="true"
                       range="{_numbers(limits[1])}"/>
                <geom name="yaw_inertia" type="box" group="3"
                      size="{_numbers(self.yaw_half_size_m)}" mass="{s.yaw_mass_kg}"/>
                <body name="camera_link">
                  <joint name="pitch" type="hinge" axis="1 0 0" limited="true"
                         range="{_numbers(limits[2])}"/>
                  <geom name="camera_inertia" type="box" group="3"
                        size="{_numbers(self.camera_half_size_m)}" mass="{s.camera_mass_kg}"/>
                  <camera name="agent_rgb" mode="fixed" fovy="{c.fovy_deg}"
                          xyaxes="1 0 0 0 {0.35 / length:.17g} {0.45 / length:.17g}"/>
                </body>
              </body>
            </body>
          </worldbody><actuator>{"".join(actuators)}</actuator>
        </mujoco>'''
