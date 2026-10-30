# Independent M0 review procedure

The 17 October recheck has now returned PASS for M0 and the timing amendment at
`20655ca`. See `M0-acceptance-20261017.md` and the new independent verdict under
`output/review/`. The remaining progression gate is Wei's explicit M1 approval.
The original procedure and pre-acceptance status below are retained as history.

Current status: the first independent review returned FAIL for PNG wire validation,
with fresh graphics separately blocked. The first correction is documented in
`M0-png-review-response.md`, including exact desktop commands and actual results.
Review the correction and reproduce fresh graphics before changing the verdict.
The corrected desktop render and all 127 tests passed on 17 October; the PNG was
inspected. See `M0-post-fix-desktop.md` for the new submitted evidence. That does
not replace the reviewer's verdict. The older checkpoint below is retained as
history.

Wei’s desktop render succeeded and its PNG was inspected. The subsequent combined
unit/render suite passed all 96 tests in 1.19 s with zero failures, errors or skips.
See `M0-desktop-render.md` and `runs/m0-review-ready/handoff-manifest.json`.
Implementation verification is complete; the next step is independent review.
The commands below are for the reviewer's independent reproduction.

The implementation agent exhausted its initial two graphics setup attempts. On
17 October, after Wei requested steps 1–4, one renewed agent probe again failed
with an invalid CoreGraphics connection and the agent stopped graphics attempts.
Wei's subsequent desktop probe and live suite succeeded. This procedure is for an independent reviewer using an
authorized graphics-capable macOS session. Do not
route commands through another application to bypass a denied tool permission.

The reviewer should inspect the kickoff/plan/checklist, current source, commits,
`docs/evidence/M0.md`, the original failure and the continuation evidence. The
implementer has not started or impersonated an independent reviewer.

From the `env` repository root, the approved reviewer can make one initial probe:

```sh
python3 scripts/record_command.py --label reviewer-m0-render-01 --timeout 180 -- uv run --locked python scripts/verify_environment.py --render --output runs/reviewer-m0-render-01
```

Use a new label and output path if they already exist. The wrapper supplies the
project-local uv path and cache/Python settings. It does not modify permissions,
launch another application or retry automatically. It preserves stdout, stderr,
times and exit status in `runs/m0-setup/evidence/commands.jsonl`.

If the probe exits 0, inspect `runs/reviewer-m0-render-01/agent_rgb.png` at full size.
It must be an actual 640×480 RGB render showing the blue calibration board and
red/green/blue fiducials. Record the visual inspection, then run:

```sh
python3 scripts/record_command.py --label reviewer-m0-tests-01 --timeout 180 -- uv run --locked python -m pytest tests/unit tests/render -q --junitxml=runs/reviewer-m0-render-01/tests.xml
python3 scripts/record_command.py --label reviewer-m0-lint-01 -- uv run --locked ruff check src tests scripts
python3 scripts/record_command.py --label reviewer-m0-schemas-01 -- uv run --locked python scripts/export_schemas.py --check
```

If the initial graphics probe fails, preserve its evidence and report the failure;
do not run repeated graphics tests as a substitute for diagnosing the context.
Never count the deliberately disabled-renderer unit test as a successful image.

The second clean environment's actual install, imports and 85-test run are already
recorded, but the reviewer must reproduce decisive evidence independently. Check
the licence inventory and the initial schema choices. Resolve the 10 ms exposure
midpoint versus 2 ms tick convention before implementing M1's scheduler.

A successful render does not itself authorize M1. Record an independent M0
verdict, then obtain Wei's explicit approval for M1. No physical fidelity,
hardware safety or hostile-policy isolation follows from these software checks.
