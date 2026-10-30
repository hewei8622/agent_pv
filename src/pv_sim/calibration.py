"""Static M0 calibration fixture only; no actuators or PV physics."""

from __future__ import annotations

import ctypes
import math
import platform

import mujoco
import numpy as np


def calibration_xml() -> str:
    """Locally authored geometry; camera optical centre and basis follow v7."""
    length = math.hypot(0.45, 0.35)
    up_y, up_z = 0.35 / length, 0.45 / length
    tiles = []
    for row in range(2):
        for col in range(4):
            colour = "0.03 0.13 0.35 1" if (row + col) % 2 else "0.05 0.22 0.50 1"
            tiles.append(
                f'<geom type="box" size="0.0365 0.049 0.001" '
                f'pos="{-0.1125 + col * 0.075} {-0.05 + row * 0.10} 0" '
                f'rgba="{colour}"/>'
            )
    return f"""<mujoco model="m0_static_calibration">
      <option timestep="0.002"/>
      <visual>
        <global offwidth="640" offheight="480"/>
        <headlight active="0"/>
        <rgba haze="0.08 0.10 0.14 1"/>
      </visual>
      <worldbody>
        <light name="world_light" directional="true" pos="0 0 1" dir="0 0 -1"
               ambient="0.25 0.25 0.25" diffuse="0.8 0.8 0.8" specular="0 0 0"/>
        <geom name="floor" type="plane" size="0.6 0.6 0.01" pos="0 0 -0.018"
              rgba="0.18 0.20 0.24 1"/>
        <body name="calibration_board">
          <geom type="box" size="0.157 0.107 0.004" pos="0 0 -0.005"
                rgba="0.7 0.72 0.75 1"/>
          {"".join(tiles)}
          <geom name="red_fiducial" type="sphere" size="0.009" pos="-0.10 0 0.012"
                rgba="1 0.03 0.03 1"/>
          <geom name="green_fiducial" type="sphere" size="0.009" pos="0 0 0.012"
                rgba="0.03 1 0.03 1"/>
          <geom name="blue_fiducial" type="sphere" size="0.009" pos="0.10 0 0.012"
                rgba="0.03 0.03 1 1"/>
        </body>
        <body name="camera_mount" pos="0 -0.45 0.35">
          <camera name="agent_rgb" mode="fixed" fovy="45"
                  xyaxes="1 0 0 0 {up_y:.17g} {up_z:.17g}"/>
        </body>
      </worldbody>
    </mujoco>"""


def render_calibration() -> tuple[np.ndarray, dict, str]:
    xml = calibration_xml()
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    camera_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "agent_rgb")
    if camera_id < 0 or model.cam_bodyid[camera_id] == 0:
        raise AssertionError("named body-fixed camera missing")
    with mujoco.Renderer(model, height=480, width=640) as renderer:
        renderer.update_scene(data, camera="agent_rgb")
        rgb = renderer.render().copy()
        gl_info = {}
        if platform.system() == "Darwin":
            gl = ctypes.CDLL("/System/Library/Frameworks/OpenGL.framework/OpenGL")
            gl.glGetString.argtypes = [ctypes.c_uint]
            gl.glGetString.restype = ctypes.c_char_p
            for name, code in (("vendor", 0x1F00), ("renderer", 0x1F01), ("version", 0x1F02)):
                value = gl.glGetString(code)
                gl_info[name] = value.decode() if value else None
        details = {
            "camera": "agent_rgb",
            "camera_id": int(camera_id),
            "camera_body_id": int(model.cam_bodyid[camera_id]),
            "camera_mode": int(model.cam_mode[camera_id]),
            "camera_position_m": data.cam_xpos[camera_id].tolist(),
            "camera_rotation": data.cam_xmat[camera_id].reshape(3, 3).tolist(),
            "headlight_active": int(model.vis.headlight.active),
            "context": type(renderer._gl_context).__module__,
            "opengl": gl_info,
            "shape": list(rgb.shape),
            "dtype": str(rgb.dtype),
            "minimum": int(rgb.min()),
            "maximum": int(rgb.max()),
            "standard_deviation": float(rgb.std()),
            "unique_colours": int(len(np.unique(rgb.reshape(-1, 3), axis=0))),
            "scope": "static M0 calibration; no camera motion or PV simulation",
        }
    if rgb.shape != (480, 640, 3) or rgb.dtype != np.uint8:
        raise AssertionError("expected 640x480 uint8 RGB")
    if details["unique_colours"] < 16 or details["standard_deviation"] <= 1:
        raise AssertionError("blank or insufficiently varied calibration render")
    return rgb, details, xml
