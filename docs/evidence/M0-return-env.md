# M0 location repair and readiness check — 17 October 2026

M0 is ready for a corrected desktop recheck and independent re-review. It is
not accepted for progression to M1. The existing independent verdict remains
FAIL, with fresh reviewer graphics separately BLOCKED.

## Location repair

The project is back at `env`; `env 3` is absent. The cause of the move is unknown.
The main `.venv/bin/python` still pointed into `env 3` and its target was missing.
Before changing anything, all 47 source hashes, all correction-evidence hashes,
and the preserved review/PDF hashes matched the PNG repair handoff manifest.
The runtime fix remains commit `6b53683bafcae186d874e21dabd458dd84efb1d1`.

The broken environment is preserved as `.venv-before-return-20261017`.
The new main `.venv` was created using `uv sync --locked --group dev` with the
project-local caches and Python installation. All 23 installed package versions
match the prior environment; the lock, dependencies, calibration, tolerances,
config, schemas and runtime source are unchanged. Historical auxiliary
environments are retained but are not claimed to work after relocation.

## Actual checks

| Recorded command label | Result |
|---|---|
| 062-preserve-relocated-environment | Exit 0; prior `.venv` preserved |
| 063-return-env-locked-sync | Exit 0; 23 packages installed from the unchanged lock |
| 064-return-env-imports | Exit 0; imports/config passed; real RGB explicitly not run |
| 065-return-env-unit-tests | Exit 0; 122 passed in 3.61 s; zero failures/errors/skips |
| 066-return-env-lint | Exit 0; all Ruff checks passed |
| 067-return-env-schema-check | Exit 0; public schemas match |

Evidence is in `runs/m0-return-env-20261017/`, including the before-state record,
import environment report, JUnit report and handoff manifest. Exact commands,
timestamps, exit codes and stdout/stderr paths are appended to
`runs/m0-setup/evidence/commands.jsonl`. No new graphics attempt or PNG repair
round occurred. No M1 code, paid provider calls or external messages were made.

## Remaining gate requirements

1. Run the commands in `M0-png-review-response.md` from `env` in the working
   macOS Terminal; retain a fresh image and full suite result. Inspect the image.
   The expected 127-case combined suite is not yet a passing result.
2. Have the independent reviewer recheck the PNG correction and fresh evidence,
   and issue a new verdict. Preserve the original failing verdict and report.
   `output/review/M0_RECHECK_REQUEST_20261017.txt` is a prepared handoff, not a
   launched review or an acceptance statement.
3. Resolve the exposure/tick convention explicitly before M1. A 10 ms exposure
   has its midpoint 5 ms after a tick-aligned start, which is between 2 ms ticks.
   Possible contract changes are a 12 ms exposure (6 ms midpoint, preserving
   2 ms steps), or a 1 ms clock/dynamics step (preserving 10 ms exposure).
   Both change the agreed plan and need a recorded, reviewed decision. Neither
   has been selected or implemented; no midpoint rounding is permitted.
4. Obtain Wei's explicit M1 approval after a passing M0 review.

The kickoff requires a hard stop after M0 for independent fresh-session review
and Wei's explicit approval. Passing the repaired unit tests does not replace it.
