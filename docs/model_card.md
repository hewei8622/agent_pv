# Scope at the M0 review handoff

Accepted M0 scope: the independent recheck on 17 October returned PASS at
`20655ca`, including the 12 ms exposure / 2 ms tick amendment after its
lower-bound correction. See `docs/evidence/M0-acceptance-20261017.md`. This
acceptance does not authorize M1 or verify its unimplemented behavior.
The pre-acceptance history below is preserved for context.

Current review status: the independent M0 review found a PNG wire-validation
defect. One correction passes the reviewer's reproducer. The fresh desktop render
and all 127 unit/render tests passed on 17 October; the saved PNG was inspected.
Independent acceptance remains pending. The original PDF and historical 96-test
result predate this finding. See `docs/evidence/M0-post-fix-desktop.md`.

Only public data contracts, configuration validation, package/CLI setup, and a
static rendering fixture exist. The fixture is a locally authored calibration
board with eight blue rectangles and three coloured spheres. The camera is fixed
on a body at the v7 nominal home position, with headlight disabled.

No camera motion, electrical model, thermal evolution, optical coupling, action
execution, policy, replay or scientific experiment has been implemented. None of
the plan's M1–M7 claims have been tested. Real RGB failed in the restricted agent
context but succeeded in Wei’s desktop Terminal; that PNG was inspected. The
latest combined suite passed all 127 tests, including five fresh live-render
checks. No generated or mocked image substitutes for that result.

Serialization is an accidental-leak prevention measure, not an OS sandbox. No
hostile policy isolation or physical fidelity is claimed. The original M0 code was
independently reviewed; the PNG correction has not yet received reviewer acceptance.
