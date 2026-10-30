# M0 after PNG correction — desktop render and 127 tests passed

Wei ran the corrected project in macOS Terminal on 17 October 2026. The real
camera render succeeded and the combined unit/render suite passed. This completes
the requested desktop evidence recheck; independent M0 acceptance, the exposure
timing decision and Wei's subsequent M1 approval remain pending.

## Actual execution and source

Run directory: `runs/m0-png-fix-20261017T064237Z-50847/`.
The two command labels append `-render` and `-tests` to that directory name.
Exact argv, timestamps, cwd, environment overrides, stdout and stderr paths are
in `runs/m0-setup/evidence/commands.jsonl` and the new handoff manifest.

| Check | Actual result |
|---|---|
| Import and real RGB probe | Exit 0; started 06:42:37.237956 UTC; 0.686 s wall time |
| Combined unit/render suite | Exit 0; started 06:42:37.950935 UTC; 1.612 s wall time |
| Pytest summary | 127 passed in 1.35 s |
| Parsed JUnit | 127 tests; 0 failures, errors or skips; 1.342 s |
| Live-render cases in JUnit | All 5 present and passed |
| Project Python / MuJoCo / uv | 3.11.17 / 3.3.7 / 0.13.1 |
| OpenGL | Apple / Apple M4 / 2.1 Metal - 89.4; default `mujoco.cgl` |
| Recorder Python | Conda Python 3.12.12; distinct from the project interpreter |

Before updating documentation, all 48 tracked source hashes matched the
`8392fdb1147a048db7d596ebee7b42b397b1b97c` handoff. The PNG correction is commit
`6b53683bafcae186d874e21dabd458dd84efb1d1`. This evidence update changes no runtime
source, tests, lock, configuration, schema or tolerance. No extra test run was
needed for documentation-only changes.

## Image inspection

The implementation agent opened the newly saved `agent_rgb.png` and inspected it
at its native 640×480 resolution. It shows eight blue panel tiles in two rows,
the complete silver frame, red/green/blue sphere markers from left to right,
a grey floor and a black background strip. The panel is centered and fully in
frame. The image is nonblank RGB uint8, with range 0–255, standard deviation
30.47398371687498 and 478 unique colours. The named fixed camera is `agent_rgb`,
attached to body 2 at (0, -0.45, 0.35) m, with headlight disabled.

The PNG hash equals the earlier static capture on the same host. This agreement
does not imply cross-GPU byte identity. It is a new recorded render, not the
historical image substituted for a failed probe. The test suite separately
created a live render for its camera and fiducial checks.

| Artifact | SHA-256 |
|---|---|
| `agent_rgb.png` | `feb98b0181b2a9826f9062675b0eced712055ed4e0b0466f2a8343a0ccb8fd90` |
| `tests.xml` | `80b6ceb89daa3bdf7277b47ec50f86c392993ceb6eeabd2b6805d4e5d3d38c20` |
| `environment.json` | `addc45eef79e6a201bd182b58c01508eb98ae04e12014e499cd0f70debeae4ce` |

## Preserved limitations and next review

The renewed agent probe at 05:47 UTC failed with `invalid CoreGraphics connection`
and remains at `runs/m0-gate-20261017T0547/`. The later successful execution was
in Wei's desktop Terminal. No further agent graphics probe was attempted.
No original failure, review verdict, source input or historical PDF was replaced.

The independent reviewer must assess the PNG correction and this evidence and
issue a new verdict. The 10 ms exposure midpoint / 2 ms tick conflict remains
unresolved; no preference answer or contract amendment has been inferred.
No reviewer was launched and M1 has not started. This is static M0 calibration,
not evidence for camera motion, PV/thermal dynamics, policies or physical fidelity.

Recorded desktop command wall time totals 2.298 s; evidence inspection and
documentation time are additional. No paid provider calls were made; coding
session monetary cost is not exposed.
