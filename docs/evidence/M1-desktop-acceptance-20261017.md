# M1 desktop acceptance - 17 October 2026

**PASS_M1.** The fresh independent desktop gate review found no blocking defect.
The desktop batch, machine audit, original-image inspection and independent
recomputations below satisfy the bounded M1 gate. M2 remains unauthorized.

The [eight-page rendered evidence PDF](../../output/pdf/PV_M1_Rendered_Evidence_20261017.pdf)
contains all six original camera images, actual 3D camera geometry, motion,
electrical/thermal traces, measured selection and replay results. The
independent review
defines the verdict's scope.

Wei ran `scripts/run_m1_desktop.py` in the working macOS desktop Terminal.
Batch: `m1-desktop-20261017T192106Z-8055`. Runtime revision:
`16e038a6e6630f52833bbdda589ffe37f2f50730`. Its recorded tracked diff was empty;
only local generated `output/` was untracked. Later report/documentation changes
do not change the runtime, scientific configuration, tests, schemas or lock.

## Actual desktop results

| Evidence | Observed result |
|---|---|
| Complete locked test suite | 408 passed in 15.85 s; zero failures, errors or skips |
| Required graphics cases | All 22 exact render testcase identities executed within that suite |
| B1 development pilots | Seeds 11, 23 and 47 all completed; 10.52 simulated seconds each |
| Actual camera images | Two original 640 x 480 RGB images per pilot, six in total |
| Recorded-action replay | All three passed on the same pinned host; no policy re-query |
| Private truth and metrics | 5,261 truth records per pair; recorded replay numeric differences zero |
| Independent decoded-image comparison by the implementer | Six replay frames compared with originals; maximum and mean pixel differences zero |
| Power identity | P = V x I at all 5,261 saved states per pilot; maximum residual zero |
| Completion | Measured choice, a fresh verification observation and the two-second retained-load tail all passed |
| Machine evidence audit | All checks passed, including complete testcase inventory, hashes, source/config, seeds, frames and replay provenance |

These are one actual 408-case execution and three completed pilots. The earlier
386-case core run and overlapping reviewer selections must not be added to the
desktop total. M1 is deterministic with noise/faults off, so the seeds demonstrate
repeatability rather than three different conditions or a statistical benchmark.

## Camera and operating-point evidence

All six original pilot images were viewed directly. The eight-cell panel is
visible in each; the side views show the expected perspective change. Original
home and side PNGs differ at 40,256 pixel locations. Images were not generated,
substituted, recoloured or repaired for this review.

| Capture | Capture time | Delivery time | Actual camera centre (m) |
|---|---:|---:|---|
| Home | 0.226 s | 0.332 s | (0.000000, -0.45, 0.35) |
| Settled side | 3.466 s | 3.572 s | (0.1199963907, -0.45, 0.35) |

Side yaw is 0.2606023917 rad. The final rail coordinate is 0.12 m; it is not
substituted for the slightly different capture-time position. Each 12 ms
exposure uses its actual midpoint, with delivery 100 ms after exposure end.
Camera headlight and automatic target tracking remain disabled.

B1 probes [0.8, 1.8, 3.0] V at the declared dwell, restores the previous point,
selects 1.8 V from delivered measured V/I pairs and verifies it. At the end of
the two-second tail, each pilot records 1.8 V, 0.546761454 A and 0.984170617 W.
Integrated PV output is 10.105492480 J. These final private state values are
distinct from the earlier public measurements used for the choice. Camera and
actuation costs are separate; this is not net harvested energy or a best-policy
comparison.

The planned slide rate cap applies to the servo setpoint ramp. Actual MuJoCo
velocity has small tracking overshoot (about 0.05124 m/s against a 0.05 m/s
setpoint cap), retained in the truth trace. Acceptance does not assert an exact
hardware velocity limit. Actual limits, finite forces, measured settlement and
the separate commanded trajectory remain the declared model checks.

## Independent gate review

The fresh reviewer independently checked all six retained recordings, current
source/configuration hashes, exact test inventory, capture-time measurements,
camera transforms, action budgets, probe/restoration/verification and replay.
Its separate verifier reads saved artifacts without importing the production
PV solver, constructing an environment or invoking a renderer. All six original
PNGs were inspected and all six replay images independently compared.

The independent uniform-cell closed form agreed to 9.99e-16; the frozen-input
thermal step agreed to 1.78e-14 C. Reintegrated energy balance residual was
-5.18e-11 J. A fresh 62-case non-GL selection passed in 2.72 s. These checks
support the reviewed desktop result and are not another full graphics execution.

Review SHA256:
`9ecf5f676029dc41fb6782950276537d24b020ad8e4008256fc866932fdf5453`.
Independent review manifest SHA256:
`995aa155bc07aa6bf86978da7def97731640284cf7d094ebf0e5be98178367ce`.
No new runtime defect, repair, tolerance change or full pilot was introduced
during this gate review. Earlier failures and bounded repairs remain in the
historical core/follow-through evidence.

The final eight-page PDF was rendered and every page inspected by both its
author and the lead implementer. QA verified 29 source/snapshot pairs, 34 bundle
files, six capture poses and exact preservation of all six embedded RGB images.
Its immutable provenance records build-time QA as pending; the separate
`visual-qa.json` records the subsequent successful inspection without rewriting
that provenance. PDF SHA256:
`d9b26bfe0f221839bbfee46531511db6bda0871534723fa5dbdbb640ef73e6dd`.

## Reproducible files

- `runs/m1-desktop-20261017T192106Z-8055/batch-report.json`, `tests.xml`,
  `machine-audit.json`, and `evidence/commands.jsonl`: original desktop results.
- `runs/m1-desktop-20261017T192106Z-8055-s11/public/frames/frame_000001.png`
  and `frame_000002.png`: original home/side images; analogous seed 23/47 paths.
- `private_eval/m1-desktop-20261017T192106Z-8055-s11/`: original private manifest,
  configuration, metrics and truth; analogous seed 23/47 and replay directories.
- `runs/m1-desktop-20261017T192106Z-8055-s11-replay/evidence/replay.json`:
  rendered replay comparison; analogous seed 23/47 paths.
- `runs/m1-desktop-validation-20261017/`: implementer read-only audit rerun,
  original-image visual record, decoded replay comparison and P=VI recomputation.
- `runs/m1-desktop-gate-review-20261017/`: separate independent review evidence.
- `runs/m1-desktop-report-20261017/`: preserved report inputs, scientific figures,
  all eight rendered PDF pages, generation commands and separate visual QA.
- `output/pdf/PV_M1_Rendered_Evidence_20261017.provenance.json`: PDF hash,
  source snapshots, report generator and dependency provenance.
- `runs/m1-accepted-handoff-20261017/acceptance-manifest.json` and adjacent
  `.sha256`: final hash inventory, runtime and documentation revisions.

Each of the seven test/pilot/replay commands exited zero. Their batch elapsed
26.54 s; the subsequent recorded audit took 2.16 s. All eight stderr files were
empty. The cap measurement was about 189.1 MB including historical run/private/
output artifacts. The independent count for this batch and its six recordings
was 37,883,698 bytes across 103 files. Both are below the 2 GB cap.
The three authorized complete development pilot seeds are now used; do not
automatically rerun them. The original results and earlier failed-context/core
evidence remain unchanged.

## Scope and next gate

This is the v7 simplified unshaded PV/thermal surrogate with trusted local B0/B1
policies. It establishes the bounded integrated simulation loop on this pinned
host, not physical validation, causal diagnosis, model superiority or hostile
policy isolation. Same-host replay agreement is not a cross-GPU pixel guarantee.
No paid provider or hardware operation was performed.

The agent execution context still cannot establish the CGL connection. The
accepted rendering source is Wei's actual desktop execution, with independent
checks performed from its saved artifacts; no additional graphics attempt or
pilot is manufactured for review. Full M1 review does not authorize M2: stop for
Wei's explicit next-milestone decision.
