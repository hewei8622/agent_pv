# Controlled source response acceptance

19 October 2026. **PASS_STEP1.** The independent desktop review found no remaining
blocker in the frozen controlled-source scenario. Step 1 of the interactive PV
prototype is complete: its electrical, thermal, sensor-timing and qualitative
rendering responses are consistent within the declared simplified model.

The independent verdict
defines this acceptance. The [earlier core record](source-response-core-and-desktop.md)
retains development checks, the timing-checker correction and the historical
desktop blocker. The original command and fixture reports retain their
pending-review status; this separate record closes the review gate.

## Actual execution

Wei ran `scripts/run_source_response_desktop.py` in the working desktop Terminal.
Batch: `source-desktop-20261019T055548Z-93694`.

| Check | Actual result |
|---|---|
| Full locked regression | 599 passed in 30.76 s; no failures, errors or skips |
| Exact test inventory | 479 unit, 70 integration, 34 real-render, 16 boundary/security cases |
| Schema and test commands | Both exit zero; both stderr files empty; no retries |
| New source images | Six original 640 × 480 RGB PNGs inspected |
| Existing rendering behavior | All 29 freshly rendered M2 images byte-match accepted originals |
| Source-run and full build inputs | All 43 and 97 hashes respectively match tested files |
| Recorded source artifacts | All 22 sizes and hashes match |
| Desktop batch duration | 31.97 s; below the 30-minute cap |

The 565 earlier core tests are included in the 599-test suite and are not added
to its count. JUnit records 30.752 s; pytest stdout rounds to 30.76 s. The desktop
batch and source public/private evidence comprise 88 files totaling 13,181,757
bytes, excluding the later review records.

The tested worktree is based on Git revision `f04fdc2271a470d7de478842bcac80776ce25634`
with the recorded Step 1 changes; that base revision alone does not identify the
new implementation. The frozen input hashes identify the tested files. No source,
test, configuration, tolerance or lock changes were needed after desktop execution.

## Measured response

At fixed 1.8 V, the treatment's total irradiance changes from 900 to 500 W/m²
at 2 s. The control stays at 900 W/m². Both temperatures are 28.110258192 °C
at that instant; control and treatment powers are 1.004410089 and 0.547437663 W.
At 8 s, their temperatures are 36.730084298 and 32.744402518 °C. The treatment
continues warming at a reduced rate.

A separate reviewer independently reimplemented the uniform-cell current law
and RK4 thermal/energy reference without importing the simulator or saved
reference module. Maximum temperature discrepancy is below 5.92e-7 K and
electrical energy discrepancy below 1.93e-5 J. All errors satisfy the numerical
tolerances frozen before evaluation.

Each world contains 4001 physical states and 320 delivered scalar samples.
The source-boundary samples capture at 2.000 s and deliver at 2.020 s. Exact
capture grids, original values and first eligible observation placement pass.

## Camera evidence

| Frame | Capture / delivery | Verified result |
|---|---|---|
| Initial | 0.226 / 0.332 s | Control and treatment images are identical |
| Before event, delivered after event | 1.906 / 2.012 s | Original lighting is preserved in the delivered frame |
| After event | 2.406 / 2.512 s | Treatment is darker; control remains identical to its earlier frames |

Open the original treatment [before image](../../runs/source-desktop-20261019T055548Z-93694-source-response/case_1/public/frames/frame_000001.png),
[delayed pre-change image](../../runs/source-desktop-20261019T055548Z-93694-source-response/case_1/public/frames/frame_000002.png),
and [after image](../../runs/source-desktop-20261019T055548Z-93694-source-response/case_1/public/frames/frame_000003.png).
The panel, cell grid, reference object and framing stay fixed. Mean RGB falls
from 44.7822 to 25.2537 code values, a decrease of 19.5285. This is qualitative
classic-renderer lighting evidence, not a calibrated irradiance-to-pixel ratio.

## Retained evidence and scope

- [Desktop batch record](../../runs/source-desktop-20261019T055548Z-93694/batch-report.json),
  [JUnit](../../runs/source-desktop-20261019T055548Z-93694/tests.xml) and
  [command log](../../runs/source-desktop-20261019T055548Z-93694/evidence/commands.jsonl).
- [Source response report](../../runs/source-desktop-20261019T055548Z-93694-source-response/report.json)
  and [private artifact manifest](../../private_eval/source-desktop-20261019T055548Z-93694-source-response/artifact-hashes.json).
- [Visual and integrity review](../../runs/source-response-accepted-20261019/visual-and-integrity-review.json)
  and [M2 image comparison](../../runs/source-response-accepted-20261019/regression-image-comparison.json).

Acceptance is limited to this controlled simulated scenario. Physical calibration,
calibrated radiometry, adaptive decision performance and the full historical M3
gate remain separate work. The public reference sensor already reveals this
source change; this fixture does not establish a need for outside information.
The next planned step is the versioned human/internet information interface,
including bounded follow-up questions, provenance, timing and repeatable tests.
