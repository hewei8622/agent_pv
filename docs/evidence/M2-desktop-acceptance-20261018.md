# M2 desktop acceptance - 18 October 2026

**PASS_M2.** The fresh independent desktop review found no blocking defect.
The full desktop suite, retained images/timelines, independent analytic audit
and visual inspection satisfy the bounded M2 gate. M3 remains unauthorized.

The independent verdict
defines the scope of this acceptance. The
[ten-page evidence PDF](../../output/pdf/PV_M2_Rendered_Evidence_20261018.pdf)
contains all 29 original images, a labelled scientific 3D schematic, delivery
and motion charts, test results and provenance.

Wei ran the prepared desktop controller in the working macOS Terminal:

```sh
env -u MUJOCO_GL -u UV_PROJECT_ENVIRONMENT .venv/bin/python scripts/run_m2_desktop.py
```

Batch: `m2-desktop-20261018T043656Z-85952`. Tested runtime revision:
`34eee53dc38a4575296d1bf6bfc24501f4e2c5da`. The recorded tracked diff was empty;
only generated `output/` was untracked. Subsequent report and documentation
work does not alter the tested runtime, configuration, tests, schemas or lock.

## Actual execution and checks

| Evidence | Result |
|---|---|
| Locked full regression suite | 519 passed in 25.15 s; zero failures, errors or skips |
| Exact test inventory | All 519 unique identities match the frozen M2 inventory |
| Required rendering | All 33 cases executed within the full suite |
| Generated schemas | Check passed, exit zero |
| Original render artifacts | 29 nonblank 640 x 480 RGB PNGs and 27 JSON records |
| Frozen effective inputs | All 84 hashes still match the desktop run |
| Image/metadata integrity | All 56 artifact hashes match |
| New complete policy pilots | Zero; the three authorized M1 pilots remain historical |

The full suite retains all 408 M1 cases and adds 111 M2 cases. Earlier core
executions and overlapping review checks are not added to the 519-case count.
Pytest stdout reports 25.15 s; JUnit reports 25.092 s. The complete schema and
verification batch took 26.339 s, below the 30-minute cap. Its schema,
verification and nested pytest commands all exited zero. Schema and pytest
stderr are empty; the outer verification stderr contains one newline and no
diagnostic text. The desktop batch, verification and private provenance total
4,070,319 bytes across 70 files, well below the 2 GB artifact cap.

Recorded host: macOS 15.7.4 arm64, Python 3.11.17, MuJoCo 3.3.7 classic renderer
with the default macOS context, NumPy 2.4.6, Pydantic 2.14.1 and Pillow 12.3.0.
These results come from Wei's desktop execution. The agent's exhausted CGL
attempts were not retried or bypassed during this review.

## Images and timing evidence

All 29 original images were visually inspected through labelled derived
contact sheets; selected originals were also viewed at full resolution. The
original files were not substituted or altered. The 24 visibility images are
direct actual-pose snapshots, not timed sensor exposures. Production views and
separate test-only calibration locators are explicitly distinguished.

| Fixture | Observed distinction |
|---|---|
| Reframe | The reference patch is outside the home field of view; bounded rotation brings it into view at the same optical centre |
| Narrow screen | Home and rotation-only views hide the target; left/right translation reveals it |
| Rail locked | The advertised slide range is zero; rotation-only views retain target occlusion |
| Wide screen | The target remains occluded at home, after rotation and at both lateral endpoints |

The reference patch is at (0.40, 0.10, 0.01) m for reframing. The screen is a
finite box centred at (0, -0.15, 0.125) m with half-depth 0.001 m, half-height
0.125 m and half-width 0.03 m or 0.06 m. One shared record defines its visual
geometry and analytic view intersection. These fixtures exclude screen/source
beam overlap; they do not implement new source-shading physics.

Five sensor images comprise three actual exposure-midpoint captures and two
evaluator-only delivery-pose comparisons. The visibility fixture seed is
20261016; the specific sensor fixtures use seed 61. The latter isolate RGB
transport with numeric/encoder noise disabled; they are not evidence that every
test uses the same configuration or seed.

| Sensor fixture | Capture midpoint | Transport delivery | Result |
|---|---:|---:|---|
| Late valid | 0.226 s | 1.132 s | Original capture hash retained; valid packet |
| Late stale | 0.226 s | 1.132 s | Original capture hash retained; stale packet |
| Dropped | 0.226 s | 0.332 s | Missing packet with null public PNG |

The exposure spans 0.220-0.232 s. Late capture actions time out at 0.420 s;
the later camera-move observation returns the historical frame at 2.310 s.
Transport delivery and public observation-return time are separate quantities.
At transport delivery the camera has moved 0.0169556493 m. Its evaluator-only
comparison image differs at 16,062 pixels from the retained midpoint image.
Each fixture charges
one frame, and subsequent waiting creates no additional RGB. The dropped
capture remains in private evaluator evidence, never as a public image payload.

The retained move trajectory has a maximum 0.0001024854 m step over one 2 ms
tick and an actual peak speed of 0.0512426894 m/s. As in accepted M1, 0.05 m/s
is the commanded ramp cap; finite-servo tracking overshoot is retained rather
than presented as an exact physical velocity bound. No servo gain, equation or
tolerance changed for this desktop gate.

## Action integrity and retained core work

The full suite includes move-command inhibition, load drops/delays, measured
verification, idempotent retry, conflicting IDs, bounded probe restoration,
rejection overhead, budgets and terminal safety. The public contracts remain
schema version 1.0; hidden configuration and fault records remain evaluator
data. The move-stall model inhibits the drive command while finite MuJoCo
dynamics continue; it is not a mechanical-obstruction or frozen-pose model.

The earlier short composed fault fixture and replay remain at
`private_eval/m2-core-fault-20261017/` and its `-replay` companion. Both load
commands, all 729 truth rows, observations, metrics and private actuation events
replay exactly over 1.456 simulated seconds. It is a numeric integrity fixture,
not a new complete policy pilot. The full repair history is retained in the
[historical core record](M2-core-and-desktop.md).

## Independent review and report QA

The independent reviewer checked the 84 effective inputs against both the
desktop fingerprints and git revision `34eee53`, the exact 519-case JUnit
inventory, all 56 render artifact hashes, all 29 images, camera transforms,
projection, source clearance and per-tick delivery traces. Its saved-artifact
audit performed 4,112 analytic assertions and exited zero; these assertions are
not additional pytest cases or another rendering execution. All 190 referenced
manifest entries were checked. No blocking finding remains.

Review SHA256:
`efba3ed520bfba8cd3bfdbc5555779999555105192bab86175bdb03ce44f544f`.
Independent review manifest SHA256:
`55abd170b3b2b5071a638e36355109f50b84a53c51aef212df5a72b0742c7e49`.
Two reviewer audit-driver errors were preserved and corrected: the inherited
M1 inventory key and the scope of the reported artifact byte total. Neither
changed the simulator or repaired a failing desktop test.

Evaluator timelines retain public PNG hashes instead of the full base64
payloads. Independent review matches those hashes to saved PNG bytes; the
frozen, executed render tests additionally decoded and compared the actual
public packet pixels. This is not a claim that full public wire payloads were
retained in the timeline JSON.

The ten-page PDF was rasterized and every final page inspected by its author
and the lead agent. All 29 original decoded 640 x 480 RGB image planes are
preserved in the PDF. The lead independently verified all 196 source/snapshot
pairs and both derived figure hashes; the immutable pre-build provenance was
not rewritten after PDF assembly. Separate build-time and final QA records
preserve that sequence. Repository Ruff checks and the new report builder's
format check passed; `git diff --check` passed.

PDF SHA256:
`d925c8f9a38ee2ad63f9743ee4deddfff2c70c4d5088770bf6a320cb007b32ea`.
Immutable report provenance SHA256:
`6e03a8cedbb7b17076612338596f28954db55bb9f74cd00e9bf9b283bd85deef`.

## Reproducible files

- `runs/m2-desktop-20261018T043656Z-85952/`: batch report, progress and exact
  schema/verification command records.
- `runs/m2-desktop-20261018T043656Z-85952-verification/`: original test stdout,
  stderr, command record, JUnit, verification report, 29 PNGs and 27 JSON records.
- `private_eval/m2-desktop-20261018T043656Z-85952-verification/`: private
  effective configuration and pre-execution provenance.
- `runs/m2-desktop-acceptance-20261018/`: lead read-only hash/inventory/timeline
  audit, contact sheets and separate visual inspection record.
- `runs/m2-independent-desktop-review-20261018/`: independent audit evidence.
- `runs/m2-desktop-report-20261018/`: report source snapshots, figures and QA.
- `runs/m2-desktop-report-20261018/provenance.json`, `qa-build.json` and
  `qa-final.json`: immutable pre-build provenance, pixel/text checks and later
  visual QA; the lead's separate result is
  `runs/m2-desktop-acceptance-20261018/final-pdf-qa.json`.
- `runs/m2-accepted-handoff-20261018/`: final acceptance manifest and SHA256,
  created only after independent review and PDF QA complete.

The original machine reports retain their execution-time status
`passed_pending_visual_and_independent_review`. Subsequent review does not
rewrite those original records; the independent verdict and final acceptance
manifest record completion of the remaining gate steps.

## Limitations and next gate

This is the bounded M2 synthetic simulation, not physical calibration, causal
diagnosis performance, hostile-code isolation or a cross-GPU image guarantee.
No complete policy pilot, paid provider call, installation, hardware operation
or external publication was performed for this gate. Private timing parameters
at extreme finite magnitudes can overflow runtime/integer ranges instead of
receiving a clean schema rejection. The bounded fixtures do not use such values;
the independent core review retains the reproducer as a nonblocking limitation.

M3 requires a separate authorization and physical-modelling review of scene,
energy and thermal consistency. No M3 implementation is included here.
