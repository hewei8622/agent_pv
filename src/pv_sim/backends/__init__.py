"""Trusted physics implementations; constructing one does not initialize OpenGL."""

from pv_sim.backends.mujoco_backend import MujocoBackend

__all__ = ["MujocoBackend"]
