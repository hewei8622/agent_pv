# M2 core evidence and required desktop checks

M2 is implemented but **not accepted**. The agent context's previously exhausted
CGL attempts remain blocked. No new graphics attempt, complete policy pilot,
installation, paid call or M3 work was performed. Wei's known working desktop
context is required for the prepared actual image tests.

## Current evidence

- Accepted M1 handoff: all 331 file hashes verified before edits in
  `runs/m2-build/preflight.json`; implementation baseline `2171e22`.
- Combined core: **486 passed in 19.23 s**, zero failures/errors/skips, in
  `runs/m2-build/combined-core.xml` and
  `runs/m2-build/evidence/m2-combined-core.*`.
- Full collection: **519 cases**, including **33 required graphics cases**.
  This retains all 408 M1 cases and adds 111 M2 cases. Collection is not execution.
  The frozen inventory is `configs/m2_test_inventory.json`, with actual command
evidence under `runs/m2-build/evidence/m2-full-inventory.*`.
- New graphics preparation comprises eight visibility cases and three sensor
  delivery cases. These 11 new cases and the previous 22 are not executed by
  the agent. They require genuine MuJoCo rendering and have no skip fallback.
- Retained short fault trace: `private_eval/m2-core-fault-20261017/manifest.json`,
  `runs/m2-core-fault-20261017/public/`, and corresponding `-replay` directories.
  It runs two load commands under noise/jitter and one silent drop, ending at
  1.456 s. All 729 truth records, public observations, metrics and private
  actuation events replay with zero numeric difference. This is a short numeric
  fixture, not a completed policy pilot or rendered M2 acceptance.
- The fresh independent review
  returned **BLOCKED_PENDING_DESKTOP**, with core ready for desktop validation
  and no remaining blocking core/harness defect. It independently ran 486 core
  tests in 19.08 s, verified exact inventory, inspected raw replay evidence and
  recomputed screen geometry, IV values and capture-indexed RNG. Its command
  records and hash manifest are in `runs/m2-independent-core-review/`.

Review SHA256: `0491e7a7777c921f268290e74a6313e177fb90a7fe43068ac2efc4d2cf60df45`.
Review manifest SHA256: `c3c4bda94832db17f20b17f3e4c79525275bccfff519ab68f82e0475b9943e25`.
Final source/evidence hashes and checkpoint revision are frozen in
`runs/m2-core-handoff-20261017/handoff-manifest.json`.

Module/reviewer selections overlap the combined suite and are not added to its
count. Commands, elapsed wall times, exit codes and first failures are retained
in `runs/m2-build/evidence/`. No runtime/physics tolerance was changed.

## Desktop command

In the macOS Terminal where M0/M1 rendering worked, from this `env` directory:

```sh
env -u MUJOCO_GL -u UV_PROJECT_ENVIRONMENT .venv/bin/python scripts/run_m2_desktop.py
```

The controller checks generated schemas, then runs the evaluator-only command
`pv-sim verify --suite development --config configs/dev.toml --seed 20261016`
with a new output directory. It records the complete 519-case suite once,
including all 33 required graphics cases, and stops on failure. It does not run
additional B0/B1 pilots. A shared 30-minute deadline covers both commands,
including reserved cleanup time. Use `--dry-run`
to inspect commands without executing them.

Expected new render evidence: **29 PNGs and 27 JSON records**. Twenty-four PNGs
are separate production/calibration views across reframe, narrow screen,
rail-lock and wide-screen fixtures. Five are actual midpoint/delivery-pose
images for late-valid, late-stale and dropped RGB fixtures. Calibration markers
and evaluator-only comparison images are labelled; they are not policy frames.

The machine audit requires the exact test inventory, zero skipped/failed cases,
all expected files, decoded nonblank RGB, image hashes and nonempty timelines.
It hashes runtime, tests, scripts, configs, schemas and fixtures before execution
and verifies they did not change. It reports only
`passed_pending_visual_and_independent_review`. Inspect the images/timelines and
obtain a fresh independent desktop gate verdict before calling M2 accepted.

New outputs appear under `runs/m2-desktop-<timestamp>-<pid>/` and its sibling
`...-verification/`; private configuration/provenance is under
`private_eval/...-verification/`. Prior evidence is never overwritten. A failure
retains partial images/logs and requires diagnosis rather than automatic retry.

## Repairs and limitations

The initial config compatibility test compared the canonical JSON digest with
the newline-bearing file digest; it was corrected against the retained M1
manifest, without changing the actual configuration. One schema-check failure
occurred because generation had not run after a lint failure; the private schema
was generated and checks passed. Sensor, action and visibility fixture tests each
had one expected-value/input-boundary correction; first results remain retained.
The independent reviewer caught a colliding unit/render test basename that
prevented whole-suite collection; the unit file was renamed, preserving tests.
The reviewer also requested complete effective-input hashing and exact sensor
image references; both are now enforced with a negative timeline check.
Its controller review found separate per-command limits could exceed the whole
batch cap. A shared deadline now limits both jobs; the recorded synthetic clock
check covers shrinking remaining time and refusal to launch after exhaustion.

The implemented mechanisms and their limits are recorded in
`docs/decisions/0011-m2-integrity-conventions.md`. This remains a deterministic
synthetic surrogate with trusted local policies. Screen source shading,
physical calibration, causal performance, hostile-code isolation and M3 are
outside the current evidence. Stop again after M2 for Wei's next decision.

The reviewer recorded a nonblocking private-config limit: extremely large finite
timing values (2e16 s jitter/delay or 1e308 s delay) can exceed integer/runtime
ranges rather than receiving a clean schema rejection. The bounded development
fixtures do not use those values. General adversarial private-config robustness
is not established; the exact reproducer remains in the independent evidence.
