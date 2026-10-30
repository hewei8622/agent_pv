# Controlled source response core evidence and desktop check

Historical core record, 19 October 2026. **The later desktop execution and review
passed; see the [Step 1 acceptance](source-response-desktop-acceptance-20261019.md).**
The pending desktop instructions below describe the earlier handoff and do not
request another run. This is step 1 of the interactive PV prototype. It validates a
controlled source change within the existing synthetic model. It does not complete
the full historical M3 milestone or the human/internet interaction interface.

See the [authorized scope and numerical tolerances](../decisions/0012-source-response-scope.md),
[frozen protocol](../../configs/source_response_protocol.json),
[final core report](../../runs/source-response-core-20261019-02/report.json), and
scoped independent review.

## Implemented behavior

An optional private `source_schedule` changes direct irradiance at specified
simulation ticks. The source change reaches the shared optical state, electrical
model, reference measurement and actual MuJoCo light. Temperature and cumulative
energy stay continuous at the event boundary. Historical RGB resolves lighting
at its capture tick, and delayed sensor records retain their original values.
The public action contract is unchanged. With no schedule, accepted configuration
hashes remain unchanged; earlier evidence is retained as historical evidence.

The fixture holds the load at 1.8 V and the camera at its home position. At
2 s, direct irradiance falls from 800 to 400 W/m² while diffuse irradiance stays
at 100 W/m². Total cell/reference irradiance therefore falls from 900 to
500 W/m². The matched control retains 900 W/m² throughout. Both start at 25 °C
with noise disabled and run for 8 s. These are short evaluator fixtures, not
additional complete policy pilots.

## Actual numerical results

| Measurement | Unchanged source | Changed source |
|---|---:|---:|
| Power at exactly 2 s | 1.004410089 W | 0.547437663 W |
| Temperature at exactly 2 s | 28.110258192 °C | 28.110258192 °C |
| Power at 8 s | 0.990067769 W | 0.542871056 W |
| Temperature at 8 s | 36.730084298 °C | 32.744402518 °C |
| Maximum temperature error versus independent reference | 5.9171e-7 K | 2.8460e-7 K |
| Electrical energy error versus independent quadrature | 1.9219e-5 J | 9.4409e-6 J |
| Captured physical states | 4001 | 4001 |
| Delivered scalar samples | 320 | 320 |

Each source-boundary scalar capture occurs at 2.000 s and is delivered at
2.020 s. Every scalar capture is checked against the exact 10 Hz acquisition
grid and the first observation eligible to contain it. All delivered scalar
values match their recorded capture states exactly in this noise-free fixture.
The two worlds match before the event and have equal temperature at the event.
Both continue warming; the changed-source panel warms more slowly.

Expected current uses a separately derived uniform-series algebraic solution.
Expected temperature and energy use an independent RK4 integrator, without
production PV or thermal imports. Halving its step from 0.5 to 0.25 ms changes
temperature by at most 4.06e-13 K. All comparisons satisfy the tolerances frozen
in the protocol. Agreement is numerical consistency within the specified model;
it is not agreement with a measured physical panel.

## Actual checks and review

- Full non-graphics regression: **565 passed in 23.53 s**, zero failures,
  errors or skips. [JUnit](../../runs/source-response-build-20261019/non-graphics-regression.xml)
  and [recorded stdout](../../runs/source-response-build-20261019/evidence/non-graphics-regression-01.stdout.txt).
- Final recorded core command exited zero in 1.89 s. The
  [command log](../../runs/source-response-build-20261019/evidence/commands.jsonl)
  retains arguments, environment overrides, exit codes and timings.
- Ruff passed for `src`, `scripts` and `tests`; generated-schema checking passed.
  Only the private scenario schema gains the source schedule; public schemas
  are unchanged.
- The source/reference/controller/validation additions comprise 79 non-graphics
  tests. The prepared render collection contains **34 tests**, including one
  new source-response case. Collection did not execute those tests. A complete
  desktop run is expected to contain 599 tests with the current inventory.
- Independent review found an evidence-checker gap: rounded timestamps could
  admit a sub-tick shift or a sample in an earlier observation. The checker was
  strengthened and two mutation tests were added. The reviewer reproduced all
  eight validation tests and found no remaining scoped core blocker. Earlier
  core run `source-response-core-20261019-01` is preserved; `-02` uses the corrected
  checker. No physics or acceptance tolerance was relaxed.

Additional targeted and reviewer executions overlap the 565-test regression and
are not added to that count. Environment inspected here: macOS 15.7.4 arm64,
Python 3.11.17, MuJoCo 3.3.7, NumPy 2.4.6, Pydantic 2.14.1, Pillow 12.3.0,
pytest 9.1.1 and Ruff 0.17.1. No dependencies or renderer were changed.

## Run the remaining desktop check

From the project's `env` directory in the same desktop Terminal that rendered
M0–M2 successfully:

```sh
env -u MUJOCO_GL -u UV_PROJECT_ENVIRONMENT .venv/bin/python scripts/run_source_response_desktop.py
```

The controller checks schemas and runs the full regression, including actual
graphics tests. It creates a fresh timestamped batch, retains command logs,
stops at the first failure and performs no automatic retry. It has a shared
30-minute time limit. Its `--dry-run` displays the commands without execution.

The new render fixture will save three actual frames per world:

| Frame | Capture midpoint | Delivery | Intended check |
|---|---:|---:|---|
| 1 | 0.226 s | 0.332 s | Initial scene under the original source |
| 2 | 1.906 s | 2.012 s | Pre-change lighting retained after delivery across the event |
| 3 | 2.406 s | 2.512 s | New lighting in the changed world; unchanged control remains stable |

For batch ID `<batch>`, results are:

- `runs/<batch>/batch-report.json`, `tests.xml` and `evidence/`: desktop commands
  and regression results; existing M2 render cases also retain fresh images
  under `m2-regression-images/`.
- `runs/<batch>-source-response/report.json`: paired numerical/image checks.
- `runs/<batch>-source-response/case_0/public/frames/` and the corresponding
  `case_1` directory: the six new PNGs; control first, changed source second.
- `private_eval/<batch>-source-response/`: private configuration, truth,
  independent reference traces and hashes.

The image check requires equal pre-change pixels, an unchanged control, and a
decrease in mean brightness after the source drop. It uses newly rendered RGB,
with no saved-image substitution. The classic renderer is not a calibrated
radiometer; no exact irradiance-to-pixel ratio is claimed. Actual images still
need visual inspection, and the full desktop result needs independent review.
The agent's earlier CGL attempts remain exhausted, so none was repeated here.

The public reference sensor already reveals this uniform source change. This
fixture validates physical and data consistency; later interaction cases must
separately demonstrate when human or internet evidence adds useful information.
