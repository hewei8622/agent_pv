# Investigation foundation and workflow replay — 19 October 2026

This checkpoint implements the shared decision coordinator and the first retained
procedural workflow replay. It prepares the v3 research comparison; it does not
yet establish adaptive performance or complete the live-interaction milestone.

## Delivered artifacts

- [Interactive replay, public view](../../output/workflow/build-03/b1-public.html):
  synchronized original RGB, orbitable 3D reconstruction, engineering plots,
  recorded decisions, event inspection and resource usage.
- [Public-only replay](../../output/workflow/build-03/b1-public.html): private
  truth, configuration and pose payloads are physically omitted.
- [Experiment design](../../configs/investigation_experiment_v1.json): competent
  procedural reference, allowed context-dependent choices, common capabilities,
  case definitions, budgets and verification rules. Executable case/policy/model
  freezing remains necessary before comparison runs.
- [API and run guide](../investigation-workflow.md) and
  [implementation scope](../decisions/0014-investigation-development-scope.md).
- [Recorded numeric fixture](../../runs/investigation-fixture-20261019/summary.json),
  [full public transcript](../../runs/investigation-fixture-20261019/public/investigation.json)
  and [verification](../../runs/investigation-fixture-20261019/public/verification.json).
- Independent review.

Earlier viewer builds are preserved as development evidence. Use the build-03
links above, not the earlier previews. Technical report v3 and accepted camera
artifacts remain unchanged.

## What the new fixture actually demonstrates

The script executes real numeric MuJoCo/PV dynamics with rendering disabled.
It collects an observation, receives one explicitly simulated information reply,
commits a voltage prediction before dispatch, applies the command, and verifies
it using fresh capture-matched voltage/current. It finishes with its causal
diagnosis unresolved. This is an authored integration script, not an autonomous
policy or a real internet exchange.

| Recorded quantity | Result |
|---|---:|
| Total simulated duration | 4.82 s |
| Committed choices | 5: four physical choices and one information request |
| Prediction committed | 0.82 s |
| Predicted voltage and capture | 1.2 V at 1.90 s |
| Set-voltage terminal time | 1.42 s |
| Verification capture / delivery / observation return | 1.90 / 1.92 / 2.62 s |
| Measured voltage | 1.2 V |
| Capture-matched current | 0.6725351105161711 A |
| Voltage residual / predeclared tolerance | 0 / 0.02 V |
| Exact transcript replay and final metric equality | Passed |
| Live calls, training and cross-episode memory | None |

The new transcript retains full predictions, information receipts, evidence
references and world/self records. It validates the final outcome as well as
intermediate contexts. A failed dispatch prevents further effects while leaving
the failure record saveable; incomplete replay is rejected before simulator
effects. Pre-dispatch commitment is in memory, with persistence on save.

## What the viewer actually demonstrates

The viewer uses the accepted B1 seed-11 desktop episode from 17 October:
`runs/m1-desktop-20261017T192106Z-8055-s11/public`, paired with its verified private
manifest. It consumes six recorded decisions, two original PNGs, 424 scalar
samples and 106 valid matched public power pairs. It does not rerun that pilot.

The 3D view reconstructs recorded panel geometry and camera pose for the human
evaluator. It is not a sensor image or policy input. Original PNG bytes are
embedded intact and hash-checked. The public view leaves unknown scene geometry
unknown and uses only delivered encoder evidence.

Public plots use observation-return time. For example, the three probe
confirmations captured at 4.6, 5.5 and 6.4 s become available together at 7.02 s.
Their event labels retain capture times; the inspector discloses that original
progress-emission time was not recorded. Private continuous dynamics are a
separate labelled overlay. Missing measurements remain gaps, commands are not
shown as successful application, and absent predictions remain absent.

B1's skills are explanatory annotations to its frozen procedure. B1 checks image
presence; it does not interpret pixels, update a causal model or choose external
questions. The new investigation fixture and the older B1 visual replay are
separate artifacts. Their integration into an adaptive workflow is pending.

## Verification and provenance

The actual environment check recorded Python 3.11.17, macOS 15.7.4 arm64,
MuJoCo 3.3.7, NumPy 2.4.6, Pydantic 2.14.1 and pytest 9.1.1. The command recorder
ran under Python 3.14.8; its version is not the simulator runtime version.

Command arguments, working directory, exit status, durations and separate
stdout/stderr are retained in
[commands.jsonl](../../runs/investigation-build-20261019/evidence/commands.jsonl).
The final suite passed **802 tests in 27.72 s**, with zero failures, errors or
skips: [JUnit XML](../../runs/investigation-build-20261019/final-nonrender.xml) and
[stdout](../../runs/investigation-build-20261019/evidence/final-nonrender-regression.stdout.txt).
This includes the 42 D2 and 52 viewer focused cases; independent repeats are
overlapping checks and are not added to the total. Ruff passes across source,
scripts and tests; the three exported investigation schemas match their models.

The [browser QA record](../../runs/investigation-build-20261019/browser-qa.json)
identifies tested builds, interactions and final artifact/screenshot hashes.
Final screenshots show the
[3D scene and original camera](../../output/workflow/build-03/workflow-scene-camera.jpg),
[engineering plots](../../output/workflow/build-03/workflow-plots.jpg) and
[public-only view](../../output/workflow/build-03/workflow-public.jpg).
Chrome testing used a loopback-only server. Direct `file:` navigation was blocked
by the browser tool's URL policy and was not bypassed or claimed as tested.

No new GL test or desktop pilot was required to produce these retained-data
views. Historical rendering counts are not added to this checkpoint's tests.

Independent review identified and checked fixes for failure continuation,
final-outcome validation, effect-free replay preflight, missing samples/encoders,
mismatched episode pairing, and impossible feedback timing. Browser inspection
also corrected misleading probe timestamps, a clipped plot tick and public-mode
legend labels. Regression cases cover the substantive data-integrity failures.

The [legacy integrity check](../../runs/investigation-build-20261019/legacy-integrity.json)
confirms all 109 pre-existing source/config/schema/test hashes captured at the
start of this checkpoint remain unchanged. This statement is relative to the
checkpoint's input snapshot, not a claim that the entire git worktree is clean.
The experiment's original and reviewed design-freeze records are retained under
`runs/investigation-build-20261019/`; no comparison outcome was collected before
or during the design review.

## Remaining work before an agentic-performance claim

1. Record policy computation latency and overruns, then freeze executable cases,
   source/context rules, validity schedules, seeds, evaluator, both policies and
   the adaptive model/provider configuration.
2. Implement and run the competent reference and adaptive policy on matched
   cases. Current service context must be authoritative before it can permit a
   voltage survey; ambiguous, irrelevant or unverified replies do not grant it.
3. Connect the shared investigation transcript to the viewer: actual question/
   reply events, pause time, world/self updates, pre-action predictions, fresh
   verification, failures and paired R/A comparisons.
4. Export supported paired plots/3D snapshots into a later evidence report.
   Demonstrate live human/web exchanges separately, then evaluate memory only
   after the no-memory comparison is understood.

No energy advantage, open-world competence or hardware agreement follows from
this foundation checkpoint. Those require the planned comparisons and physical
validation, including null or negative outcomes.
