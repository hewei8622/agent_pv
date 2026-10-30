"""Minimal reviewer reproducer. NOT executed after the two-attempt M0 stop."""

import mujoco

context = mujoco.GLContext(640, 480)
try:
    context.make_current()
    print("CGL context created")
finally:
    context.free()
