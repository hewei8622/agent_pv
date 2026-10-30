# PV investigation simulator — paired investigation and workflow replay

## Current development step

Start with the [capability and case-design report](output/pdf/PV_INVESTIGATION_CAPABILITIES_AND_CASES_v2.pdf)
for an explanation of sensing, analysis, tool choice, action and verification;
why C01-C04 exist; and what the current goal-driven agent does differently from
the procedural reference. The earlier evidence report remains the detailed audit
of the same batch. This revision adds explanation, not new experiment results.

The [interactive PV prototype plan v2](docs/planning/interactive-pv-prototype-v2.md)
records the current direction agreed on 19 October 2026: compare an adaptive
investigation policy with a competent frozen procedure using the same sensing,
physical experiments, information sources and budgets. It builds on the
[18 October plan](docs/planning/interactive-pv-prototype-v1.md).

[Workflow plots and synchronized 3D replay](docs/planning/workflow-visualization-v1.md)
are core deliverables: show the world change, evidence available to the agent,
recorded decisions, physical responses and verification, alongside the reference
procedure. Technical report v3 explains the research scope.

**The first paired controlled comparison passed independent review: eight successful episodes.**
R is a competent frozen procedure; A is a deterministic goal-driven symbolic
planner. Both use the same tools, public priors, controlled information source,
budgets and four physical/context cases. All episodes replayed exactly and all
16 numerical predictions passed. The non-render regression suite passed
**875 tests in 63.98 s**, with no failures, errors or skips.

The systems tied on supported outcomes, physical resources and energy in every
pair. Identical pre-query sensor histories led to different hold/survey branches
when the external service instruction changed. This establishes an auditable
investigation loop; it does not establish an adaptive performance advantage.

Open the [paired R/A replay](output/workflow/paired-03/paired-public.html) (public view; the
evaluator view with hidden truth can be rebuilt locally) and the
[explanatory evidence PDF](output/pdf/PAIRED_INVESTIGATION_REPORT_20261019.pdf).
The [evidence record](docs/evidence/paired-investigation-20261019.md),
[run and interpretation guide](docs/paired-investigation.md) and
independent review
explain the source records, tests, results and remaining work.

The new 3D views reconstruct recorded private geometry and actual pose. These
eight numeric episodes acquired no RGB and used no LLM, live human/web call,
training or cross-episode memory. Those capabilities and hardware validation
remain separate work. Original camera evidence is preserved in the earlier B1
viewer below; the new comparison does not rerun accepted desktop graphics.

**The shared-decision foundation passed independent review on 19 October.**
The shared decision coordinator retains public context, information replies,
world/self records and complete predictions before dispatch. Its short numeric
fixture verified a precommitted 1.2 V prediction from fresh measurements and
replayed exactly. The final non-render suite passed **802 tests in 27.72 s**, with
zero failures, errors or skips. No new desktop rendering run was needed.

Open the [interactive workflow replay](output/workflow/build-03/b1-public.html)
for orbitable 3D, original camera images, synchronized plots, recorded decisions,
event inspection and resource use. It shows retained **procedural B1** evidence
in its public view, which omits private payloads. Read the [checkpoint evidence](docs/evidence/investigation-foundation-20261019.md),
[API/run guide](docs/investigation-workflow.md) and
independent review.

The later paired comparison extends that foundation with two declared policies,
an executable 42-input freeze, independent scoring and a linked R/A viewer.
The historical 802-test checkpoint and its original evidence remain unchanged.

**Step 1 passed independent desktop review on 19 October.** The
[source-response acceptance](docs/evidence/source-response-desktop-acceptance-20261019.md)
records 599 passing tests, including all 34 rendering cases, six inspected source
images and unchanged M2 regression images. Electrical, thermal and sensor-timing
responses match the independent reference within the frozen tolerances.
This accepts the bounded source scenario within the simplified model.

**Step 2 passed independent review on 19 October.** The
[information-interface acceptance](docs/evidence/information-interface-acceptance-20261019.md)
records **708 passing non-render tests**, bounded free-text questions and
follow-ups, attributed replies, pause/resume, shared budgets, cached retries and
exact replay. The retained scripted fixture links three simulated exchanges to a
measured voltage probe and final verification. See the
[interface guide](docs/interaction-interface.md) for the API and rerun command.

Step 3 will demonstrate actual human/web exchanges with a declared decision agent.
Step 2 makes no live-call or adaptive-agent claim, and its test count excludes
the historical rendering suite. Full M3 and physical validation remain separate
work. The archived v7 plan and earlier acceptance records remain unchanged.
The accepted desktop batch does not need another run for this interface step.

## Accepted M2 checkpoint

Wei authorized M2 after independent M1 acceptance. The M2 implementation adds
capture-indexed noise, delayed/stale/dropped sensor delivery, private actuation
fault fixtures, bounded recovery and F1/F2 visibility fixtures. **M2 passed
independent review on 18 October 2026:** Wei's desktop suite passed **519 tests
in 25.15 s**, including all **33 real rendering cases**, with zero failures,
errors or skips. All 29 original camera images and their 27 metadata/timeline
records were inspected. That acceptance did not authorize M3; the later bounded
source-response assignment is documented above and does not complete full M3.

The fresh desktop review
returned `PASS_M2`, independently checking the exact test inventory, 84 frozen
inputs, all 56 artifact hashes, actual camera geometry, source clearance and
late/stale/dropped-frame timelines. Tested runtime revision: `34eee53`.
No simulator, test, tolerance or configuration change was needed at this gate.

Read the [M2 acceptance record](docs/evidence/M2-desktop-acceptance-20261018.md),
[rendered evidence PDF](output/pdf/PV_M2_Rendered_Evidence_20261018.pdf) and
[integrity conventions](docs/decisions/0011-m2-integrity-conventions.md).
The report distinguishes production and calibration images, direct actual-pose
snapshots and exposure-midpoint captures, and evaluator-only comparison images.
The [earlier core record](docs/evidence/M2-core-and-desktop.md) preserves its
historical desktop blocker and the exact command later executed successfully.
Use `scripts/run_m2_desktop.py --dry-run` to inspect the prepared commands;
the accepted result does not require another run or additional complete pilots.

The known nonblocking limit for extremely large private timing values remains
documented. These bounded synthetic checks establish neither physical
calibration nor causal-performance or hostile-code-isolation claims.

## Accepted M1 checkpoint

Wei approved starting M1 after independent M0 acceptance. The repository now
implements a shared unshaded scene, real finite MuJoCo slide/yaw/pitch servos,
eight-cell/two-substring PV and thermal models, timed immutable sensors,
blocking actions and budgets, public-only B0/B1 policies, recording and replay.
The project was private at that time; it has since been released under the MIT licence.

**M1 passed independent review on 17 October 2026.** Wei's actual desktop
suite passed **408 tests in 15.85 s**, including all **22 real graphics cases**,
with zero failures, errors or skips. All three complete B1 pilots (seeds 11, 23,
47) and their recorded-action replays passed. Six original home/side camera
images were inspected; every replay image matched its original pixel for pixel.
Runtime revision: `16e038a6e6630f52833bbdda589ffe37f2f50730`.

The fresh independent desktop review
returned `PASS_M1`, with no blocking defect. It independently recomputed the
retained evidence and passed 62 additional overlapping non-GL checks; those
counts are not added to the 408-case suite. The eight-page
[rendered evidence PDF](output/pdf/PV_M1_Rendered_Evidence_20261017.pdf) contains
all six original images, recorded 3D camera geometry, motion, electrical/thermal
traces, measured load selection and replay results.

Read the [M1 acceptance record](docs/evidence/M1-desktop-acceptance-20261017.md)
for exact paths, hashes, commands and limitations. That checkpoint predates the
authorized M2 changes. No causal-performance or hardware-validity claim is made.

Historical checkpoints remain in the [M1 core record](docs/evidence/M1-core-and-desktop.md)
and [core evidence PDF](output/pdf/PV_M1_Core_Evidence_20261017.pdf). See also the
[scope authorization](docs/decisions/0007-m1-scope.md), and
[runtime conventions](docs/decisions/0008-m1-runtime-conventions.md).
All initial failures and bounded repairs are retained under `runs/m1-build/`
and `runs/m1-followthrough/`.

## Retained desktop evidence

Accepted batch: `runs/m1-desktop-20261017T192106Z-8055/`. Its command log records
the exact seven test/pilot/replay commands and the subsequent machine audit,
all with exit zero and empty stderr. The three authorized complete development
pilot seeds have now been used; do not automatically rerun the batch.
`scripts/run_m1_desktop.py --dry-run` can display its commands without execution.

The agent context has repeatedly failed to establish a CGL connection; the
working graphics context was Wei's desktop Terminal. Acceptance uses that
execution and independent checks of its saved artifacts. Original PNGs are under
`runs/m1-desktop-20261017T192106Z-8055-s11/public/frames/`
(and the corresponding other seeds).
Private configuration, truth, seeds and metrics stay in `private_eval/<run-id>/`.
These directory/data boundaries do not isolate hostile policy code.

## Accepted M0 checkpoint

The [independent M0 acceptance](docs/evidence/M0-acceptance-20261017.md) covers
runtime commit `20655ca`, including strict PNG validation and the approved
12 ms exposure on 2 ms ticks. The reviewer reproduced 132 unit tests and
audited Wei's separate 127-test desktop suite and genuine camera image.
These are separate results, not an invented 137-test live run.

Historical setup, failed contexts, repairs, images and the original M0 PDF
remain unchanged. See [M0 history](docs/evidence/M0.md),
[desktop evidence](docs/evidence/M0-post-fix-desktop.md), and
[environment provenance](docs/environment.md). Those static M0 images are not
evidence of M1 motion, electrical dynamics or policy execution.
