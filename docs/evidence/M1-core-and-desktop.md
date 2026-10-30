# M1 implementation checkpoint — 17 October 2026

Status: implementation and core verification performed; graphics and complete
pilot gates pending. Wei's “can we start M1” authorized this milestone only.
The M0 acceptance remains intact. No M2 faults, causal corpus, paid model calls,
hardware operation, new renderer or external publication has been introduced.

## Actual checks

| Check | Actual result | Recorded evidence |
|---|---|---|
| Current combined unit, policy boundary and core integration suite after autonomous follow-through | 386 passed in 14.43 s, no skips | `runs/m1-followthrough/evidence/m1-followthrough-final-core.stdout.txt`, `runs/m1-followthrough/core-tests-final.xml` |
| Current Ruff across source, tests and scripts | Passed | `runs/m1-followthrough/evidence/m1-followthrough-final-lint.stdout.txt` |
| Previous combined core checkpoint | 335 passed in 6.53 s, no skips | `runs/m1-build/evidence/m1-combined-core-after-review.stdout.txt`, `runs/m1-build/core-tests-after-review.xml` |
| Short actual MuJoCo core recording/replay | Exact public observations, ticks, private truth and JSON metrics; core-only | `runs/m1-build/recorder/evidence/m1-replay-core-repair1.stdout.txt` |
| Real graphics test collection | 22 tests collected; NOT executed | `runs/m1-build/evidence/m1-render-collection.stdout.txt` |
| Desktop batch dry run | Printed seven planned commands plus the post-run audit; no pilot executed | `runs/m1-followthrough/evidence/m1-followthrough-desktop-plan.stdout.txt` |
| Current environment imports | Passed; Python 3.11.17, MuJoCo 3.3.7, NumPy 2.4.6, Pillow 12.3.0, Pydantic 2.14.1 | `runs/m1-core-environment/environment.json` |
| Independent preliminary reproduction | 192 targeted tests and analytic IV/cooling checks; original replay-cost failure reproduced and repair confirmed; 19 replay/recorder regressions passed | `runs/m1-independent-core-review/evidence/` |
| Independent follow-through reproduction | 29 travel/core tests; final 41 audit/runner tests; 60 analytic IV cases, thermal/protection and fresh replay checks; no remaining reproduced core blocker | `runs/m1-followthrough/independent-review/evidence/`, `output/review/M1_FOLLOWTHROUGH_REVIEW_20261017.txt` |

Component tests include independent electrical/thermal calculations, actual
finite servo motion and transforms, shared optical geometry, named seed streams,
capture/delivery timing, resource gates, policy serialization, recorder integrity,
canonical retries and action cleanup. These counts are included in the combined
total; they must not be added to produce an inflated test count.

Initial evidence is preserved. Physics test setup errors, policy line formatting,
an exact binary float assertion, and a replay tuple/list comparison were fixed
without changing scientific assumptions or frozen tolerances. Internal review
also reproduced four runtime defects: move timeout returned before braking,
very short safe stop could terminate while moving, set confirmation timeout
left the load connected, and a later load action did not reconnect it. A first
runtime repair passed all four new regressions. Canonical malformed-ID retry
and conflict regressions also passed. Original failures and repairs remain in
`runs/m1-build/{backend,physics,policies,recorder}/evidence/`.

No new M1 RGB image has yet been produced or inspected. The retained M0 image
used in PNG serialization unit tests is explicitly a real historical fixture,
not a replacement M1 render. Neither core test result is a complete RGB gate.

The initial combined 333-test result remains preserved. Fresh independent
review then found that replay copied policy decisions but lost recorded wall
latency and did not itself compare private traces/metrics. The reviewer showed
1.25 s becoming zero while replay reported success. One repair restores the
recorded latency without policy re-querying and makes every private truth
record and runtime metric part of replay success. Two new mutation checks prove
that even consistently rehashed incorrect truth/metrics fail comparison.
The reviewer reran the original reproducer at tick 2460 and confirmed exact
1.25 s accounting and successful private comparisons. That value is a deliberate
replay test input, not a measured benchmark-policy latency. Its verdict and remaining
desktop gates are in
`output/review/M1_PRELIMINARY_CORE_REVIEW_20261017.txt`.

## Autonomous follow-through

Wei authorized further M1 work while away from the screen. Ten new boundary
cases cover travel-budget braking, pending-action cancellation, the exact
trigger tick, decision overhead, horizon precedence and missing confirmation.
The initial eight failing cases are preserved; one runtime repair closes them.
The rig now physically brakes within the fixed cleanup allowance and requires
fresh V/I and encoder measurements before terminal safe stop. Default gains,
reservations and numerical tolerances are unchanged.

The command recorder terminates its owned child process group on timeout or
interruption. The desktop watchdog allows that cleanup before a forced exit.
A reviewer reproduced a separate case where a successful command leader left
a running child. One repair now terminates that group and reports exit 125,
retaining the leader's original exit code. Real process/heartbeat regressions
cover these paths; no pilot or renderer runs in those tests.

The new read-only batch auditor checks seven recorded commands, the complete
frozen testcase inventory including all 22 required render cases, three
current-source/config pilot recordings, two
nonblank 640 x 480 RGB frames per recording, capture-time actual poses,
timestamped P=VI, verification tails, and matching rendered replay provenance,
truth and metrics. Independent review reproduced acceptance of a partial JUnit
file; the first repair required every frozen render identity and rejected
duplicates. A second coverage reproducer showed that selecting only the render
cases could still hide the omitted core suite. The final bounded repair uses
`configs/m1_test_inventory.json` for exact complete-suite membership, reconciles
the recorded pytest summary, and rejects deselection. The desktop controller
also removes inherited `PYTEST_ADDOPTS`. The inventory is collected without
executing fixtures or graphics, and must be deliberately updated when tests
change. Two coverage repairs are the limit for this invariant.
Its synthetic positive inputs exercise audit logic only and are never presented
as real pilots. An actual core-only recording is correctly rejected for the
full rendered gate. Initial failures and repairs are retained under
`runs/m1-followthrough/{budget-stop,audit,independent-review}/evidence/`.

The combined result above includes these new cases; component and reviewer
test totals must not be added to it. The earlier 377-case follow-through run is
retained in `runs/m1-followthrough/core-tests.xml`. The final collection contains
408 cases: 386 executed core cases and 22 unexecuted real-render cases.
No further graphics context attempt or
complete M1 pilot was made in this follow-through.

The fresh independent recording is a 4.92 s hand-authored partial action trace
with 2,461 saved actual MuJoCo states, not a B1 pilot. Its replay matches ticks,
public observations, private truth and metrics. It includes a known injected
1.25 s accounting value to test latency preservation; no model inference or
policy benchmark latency was measured. The original scripts and complete
source/replay records are under `runs/m1-followthrough/independent-review/`.

The final follow-through reviewer returned `BLOCKED_PENDING_DESKTOP`: no
remaining reproduced core/runtime or evidence-control blocker, with full M1
acceptance still pending. Its source/script/inventory hashes are in
`runs/m1-followthrough/independent-review/evidence/final-provenance.json`.
The review does not recertify every original source path or replace the final
moving-camera gate.

## Illustrated evidence report

`output/pdf/PV_M1_Core_Evidence_20261017.pdf` presents the final test result,
the fresh partial simulation trace, electrical/thermal and actual-joint plots,
3D recorded camera/panel geometry, replay evidence and remaining gates. The
3D figure is a scientific plot, not a MuJoCo camera image. There are zero M1
RGB frames and zero completed development pilots in these report inputs.

The adjacent `.provenance.json` records source snapshots, complete artifact
hashes, measurements and generation command. Rendered page checks and the
separate QA record are under
`runs/m1-followthrough/report/PV_M1_Core_Evidence_20261017/`. The report generator
uses the existing `.tools/pdf-report` environment and makes no runtime dependency
changes. The original M0 PDF and earlier report draft remain unchanged.

The final file/hash inventory is
`runs/m1-followthrough-handoff-20261017/handoff-manifest.json`, with an adjacent
SHA-256 file. It records the committed revision, reviewed runtime fingerprint,
final JUnit result and retained evidence. The earlier
`runs/m1-core-handoff-20261017/` checkpoint remains unchanged.

## Desktop command

Run from the project directory in the same macOS Terminal used for the accepted
M0 renders:

```sh
cd agent_pv
env -u MUJOCO_GL -u UV_PROJECT_ENVIRONMENT .venv/bin/python scripts/run_m1_desktop.py
```

This runs the full suite, including the 22 required live-render cases, then
three B1 pilot runs using seeds 11/23/47, with a recorded-action replay after
each. The batch stops on its first nonzero result. It does not retry, change
configuration, substitute frames, or query a policy during replay. Each command
has a 180 s timeout; the batch has a 30 minute limit and a 2 GB artifact check.
Project-local tools and caches are supplied by `record_command.py`.

After those seven commands succeed, the script runs the read-only machine audit.
`progress.json` records current activity and the audit exit status; immutable
`batch-report.json` records the seven-command result. A passing audit still
requires visual inspection and independent review. Timeout cleanup is bounded,
remaining descendants cannot silently outlive a successful recorded command,
and the controller reserves enough of the 30 minute allowance for each job.

The printed batch ID determines these new locations:

- `runs/<batch-id>/batch-report.json`, `tests.xml`, and `evidence/commands.jsonl`.
- `runs/<batch-id>/progress.json` and, after successful commands, `machine-audit.json`.
- `runs/<batch-id>-s11/public/frames/frame_000001.png` — home camera.
- `runs/<batch-id>-s11/public/frames/frame_000002.png` — actual settled side camera.
- `runs/<batch-id>-s11/public/` — public task, observations, decisions, actions,
  and feedback JSON/JSONL evidence, with analogous seed 23/47 directories.
- `private_eval/<batch-id>-s11/` — manifest, metrics, config, and truth trace.
- `runs/<batch-id>-s11-replay/evidence/replay.json`, with analogous replay runs.

Retain the first failure's printed error and batch directory; do not repeatedly
rerun it. If a completed seed already exists, the CLI refuses another complete
pilot for that seed pending review.

## Remaining M1 acceptance

Inspect the actual home/side PNGs and measured poses, confirm P=VI against the
timestamped trace, review three complete pilot reports and same-host replay,
and obtain the separate reviewer verdict. Core-only reproduction cannot
establish graphics or end-to-end success. The independent preliminary review
is separate from the implementation helpers' internal checks. After complete
M1 evidence passes review, stop for Wei's explicit decision before M2.

This is a deliberately simplified deterministic surrogate under
`trusted-policy/local`. The three seeds have no M1 stochastic perturbations and
are reproducibility checks. No physical validation, diagnosis superiority,
benchmark model result or hostile-code security guarantee is claimed.
