# M0 graphics blocker and stop

Attempt 1 used Python 3.11.17, MuJoCo 3.3.7 `Renderer` and the default macOS CGL
context, with no MUJOCO_GL override. Imports/config succeeded. `CGLChoosePixelFormat`
raised `mujoco.cgl.cgl.CGLError: invalid CoreGraphics connection`. The verifier
returned 3 and preserved `runs/environment/failure.txt`. MuJoCo also emitted an
upstream destructor AttributeError after partial Renderer construction; that is
secondary to context creation failure.

Attempt 2 changed only the launcher to the installed MuJoCo `mjpython`, to test
whether macOS application/main-thread setup was responsible. Official 3.3.7 docs
describe this launcher for passive viewing; they do not guarantee it fixes batch
CGL failures. `uv run --locked mjpython ...` exited 134, without stdout/stderr or
the requested output directory: it aborted before our verifier started. Exact
command logs remain in `runs/m0-setup/evidence/011-render-mjpython.*`.

No render succeeded and no third environment attempt is allowed by this handoff.
No Linux graphics flags, engine changes, alternate tools, permission bypass,
mocked image or weakened acceptance criterion was attempted. The host reports an
Apple M4 GPU; that does not establish OpenGL access from this process. The precise
cause of the CoreGraphics failure remains unverified. A restricted/no-graphics
execution context is a hypothesis, not a proven permission rejection.

`scripts/reproduce_cgl_failure.py` is a minimal reviewer reproducer, prepared but
not executed after the stop. Next step: independent review of the recorded evidence
and an authorized graphics-capable execution context before another M0 attempt.
Do not proceed to M1. The session's permission policy does not allow escalation.
