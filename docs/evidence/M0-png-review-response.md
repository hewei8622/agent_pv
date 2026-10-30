# M0 independent-review response: PNG correction accepted

The independent recheck on 17 October accepted the correction and desktop
evidence, and separately accepted the repaired 12 ms exposure / 2 ms tick
amendment. See `M0-acceptance-20261017.md`. The earlier response below retains
the sequence of findings and checks; no old verdict or failure was overwritten.

The review at `output/review/M0_INDEPENDENT_REVIEW_20261016.txt` returned
**FAIL / changes required**, with fresh graphics separately **BLOCKED**.
The implementer accepts the P2 PNG finding. The first bounded correction is
described in `docs/decisions/0005-png-wire-validation.md`.

## Actual results

| Command | Result |
|---|---|
| 051-png-regressions-before | Exit 1; 16 failed, 15 passed in 2.12 s; failing evidence preserved |
| 053-png-regressions-repair-1 | Exit 0; all 31 new regression cases passed in 0.16 s |
| 054-png-repair-unit-suite | Exit 0; 122 passed in 1.14 s; zero failures/errors/skips |
| 055-reviewer-png-cases-after | Exit 0; all four original reviewer assertions passed |
| 056-png-repair-lint | Exit 0; Ruff passed |
| 057-png-repair-schema-check | Exit 0; generated schemas match |

The reviewer reproducer was copied with only its output path changed, so the
original failure JSON cannot be overwritten. Its valid control is still accepted;
the corrupt IDAT, mislabeled RGB16 and nonempty IEND are rejected. The original
camera PNG is also accepted unchanged by a committed regression fixture.
No camera geometry, tolerance, runtime dependency or lock changed.

Evidence: `runs/m0-png-repair/` contains before/after JUnit files, all-unit JUnit,
reviewer-case results, preserved-review hashes and the repair handoff manifest.
Exact argv, UTC timestamps and exit codes are appended in
`runs/m0-setup/evidence/commands.jsonl` under the labels above.

## Historical report qualification

The original seven-page PDF remains byte-identical, SHA-256
`63933d615fb76026ace4c5e571ec48c0aad4ed1074cf4cd938befd6801d946f6`.
It accurately describes its historical image/tests, but its general
strict-validation claim predates the PNG finding and must not be treated as
post-review acceptance. The independent review and original failing artifacts
are also preserved unchanged. No reviewer verdict was rewritten.

## Desktop recheck completed on 17 October 2026

Wei ran the commands below in macOS Terminal at 06:42:37 UTC. Both commands
exited 0. The fresh camera PNG was saved and inspected; **127 tests passed in
1.35 s**, including all five live-render cases, with zero failures/errors/skips.
The actual JUnit, image hash, source checks and visual inspection are recorded in
[M0-post-fix-desktop.md](M0-post-fix-desktop.md). The original review verdict is
unchanged and independent acceptance remains pending.

The current project is `env`, having returned from `env 3`. Its main environment
was rebuilt from the same lock on 17 October 2026 because its interpreter still
pointed to the missing `env 3` location. Imports, 122 unit tests, lint and schema
checks passed again; see `M0-return-env.md`. The independent reviewer also
reproduced a clean install earlier, but its fresh CGL probe failed in that
execution context. After Wei requested steps 1–4, one renewed agent probe on
17 October exited 3 with the same CGL connection error; it is preserved under
`runs/m0-gate-20261017T0547/`. The agent stopped graphics attempts there. The later
successful commands ran in Wei's desktop Terminal, not the agent context.

For any reviewer-required reproduction, run the following from the `env` root
in the working macOS Terminal. A timestamp
and shell process ID supply fresh output paths. The tests run only if the render
succeeds. Keep this project at its current path while using its environment:

```sh
pv_check_id="m0-png-fix-$(date -u +%Y%m%dT%H%M%SZ)-$$"
env -u MUJOCO_GL -u UV_PROJECT_ENVIRONMENT python3 scripts/record_command.py \
  --label "$pv_check_id-render" --timeout 180 -- \
  uv run --locked python scripts/verify_environment.py \
  --render --output "runs/$pv_check_id" &&
env -u MUJOCO_GL -u UV_PROJECT_ENVIRONMENT python3 scripts/record_command.py \
  --label "$pv_check_id-tests" --timeout 180 -- \
  uv run --locked python -m pytest tests/unit tests/render -q \
  --junitxml="runs/$pv_check_id/tests.xml"
```

Inspect the new `agent_rgb.png` and retain the actual outputs. The current suite
contains 127 tests (122 unit plus five render cases), all passed in the recorded
desktop recheck. If a subsequent render fails, preserve the output and stop;
do not repeatedly retry graphics or count unit-only success as a render pass.

Then provide the correction and fresh evidence to the independent reviewer for
acceptance. The 10 ms exposure / 2 ms tick convention remains an explicit
pre-M1 decision. No M1 code or scheduler was implemented, and no acceptance or
M1 approval is inferred from the repair or the passing desktop suite.
