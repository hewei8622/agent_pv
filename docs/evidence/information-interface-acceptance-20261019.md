# Step 2 information interface evidence

19 October 2026. **PASS_STEP2_INTERFACE.** Independent review found no remaining
blocker within the offline interface scope. Step 2 is complete.
The new interface supports bounded questions and follow-ups, attributed replies,
pause/resume, budgets, retries and replay. The demonstration uses a fixed script
and simulated answers, with no live human, internet or model-provider exchange.

The [scope decision](../decisions/0013-information-interface-scope.md) and
[usage guide](../interaction-interface.md) describe the implementation. The
independent review
records findings and their dispositions.
All four findings are closed. The reviewer independently passed 133 focused
tests and reproduced the retained eight-event trace with matching metrics;
those focused cases are included in the main suite and are not added to its count.
The review input record
identifies 68 checked files. The
[acceptance manifest](../../runs/information-interface-accepted-20261019/acceptance-manifest.json)
freezes the final inputs, command results, fixture artifacts and review records.

## Actual checks and artifacts

| Check | Retained result |
|---|---|
| Non-render regression | **708 passed in 25.94 s**; zero failures, errors or skips |
| Exact inventory | 558 unit, 125 integration and 25 security/boundary cases |
| Added Step 2 coverage | 143 cases, included in the 708 total |
| Ruff | All checks passed across source, tests and scripts |
| Interface fixture | Three requests, one follow-up, two physical actions, five decisions |
| Physical duration | 4.52 simulated seconds, including the two-second Finish verification tail |
| Replay | Eight events exactly reproduced; final evaluator metrics exactly equal |
| Actual information elapsed time | 0.128527 s of local computation and authored fixture delays |
| Actual replay duration | 0.276080 s; restored original waiting metadata reported separately |
| External activity | Zero live human, internet or AI-provider calls |

Commands and stdout/stderr are retained in
[`runs/interaction-step2-final-20261019T061833Z/evidence`](../../runs/interaction-step2-final-20261019T061833Z/evidence).
The [JUnit inventory](../../runs/interaction-step2-final-20261019T061833Z/core-tests.xml)
supports the test counts. The original 565 non-render Step 1 cases are included
in this suite, not added to it.

The retained [fixture summary](../../runs/interaction-step2-final-20261019T061833Z-fixture/summary.json),
[public interaction transcript](../../runs/interaction-step2-final-20261019T061833Z-fixture/public/interaction.json)
and [replay result](../../runs/interaction-step2-final-20261019T061833Z-fixture/replay.json)
provide the concrete demonstration. Private configuration, seed, runtime,
input hashes and evaluator metrics are in the matching
[`private_eval` directory](../../private_eval/interaction-step2-final-20261019T061833Z-fixture).
All 45 fixture input hashes match the tested files.

The tested worktree includes uncommitted Step 1 and Step 2 changes. The Git base
revision alone does not identify this implementation; input hashes identify the
actual code used. Previous acceptance artifacts remain historical evidence.

## What the demonstration does

The script asks a human-channel question about missing context, an internet-channel
question about checking a voltage probe, then a human-channel clarification.
All three answers are explicitly authored simulated fixtures. They preserve
uncertainty and do not supply a hidden scenario label. This fixture uses constant
nominal conditions; it does not introduce a new panel fault or source event.

After the exchanges, the script submits a separate bounded electrical experiment.
The simulator measures the following settled points:

| Commanded voltage | Measured voltage | Measured current | Capture / delivery time |
|---|---|---|---|
| 1.2 V | 1.2 V | 0.672938 A | 1.30 / 1.32 simulated s |
| 1.8 V | 1.8 V | 0.558137 A | 1.90 / 1.92 simulated s |

The probe restores 1.8 V with fresh confirmation at capture 2.30 s, delivered
at 2.32 s. Finish consumes its 0.2 s decision overhead and completes the final
two-second verification period. Its resolution is explicitly **unresolved**:
successful execution and measurement do not establish the cause of an anomaly.
The evidence references link the replies to these decisions and observations.

During a measured 0.030222 s local wait, the simulator stays at 0.22 simulated s.
Its temperature, motion, energy ledger, sensor queue and delivered state remain
exactly unchanged. An identical request retry adds zero transport calls,
decisions, simulated ticks or energy. Unit and integration tests additionally
exercise the full deadlines with controlled clocks; the retained script does
not pretend to have waited for an actual person.

## What the tests establish

Contract tests check bounded UTF-8 text and JSON, strict types, source attribution,
dates, URLs, duplicate fields, unsupported live provenance and schema exports.
Budget tests count follow-ups and unsuccessful outcomes, reject a fourth request,
reserve physical completion resources and prevent restarting the allowance
mid-episode. Timing tests exercise deadline equality, clock faults, delayed
sensor packets, source changes during overhead and frozen future events.

Boundary tests check that the transport receives only public request data,
external text cannot execute code or change voltage, guessed evidence references
reject, and separate physical commands still obey the existing gate. These
are tests of a trusted local architecture, not an operating-system sandbox.

Replay tests cover physical outcomes, unavailable/cancelled/invalid responses,
timeouts, reordered or incomplete events, checksum and duplicate-key rejection,
fractional wall-clock intervals and automatic cancellation during protection.
The independent review found and prompted fixes for an allowance reset loophole,
ambiguous duplicate JSON and floating-point reconstruction of elapsed time.
An additional collaborator found the protection-cancellation replay edge case.
Final review also found deeply nested malformed JSON escaping the normal rejection
path; the parser now rejects it and returns invalid_response without stranding
the pause.
The final full regression run includes the resulting tests.

## Limits and next step

This step validates the information interface and its accounting. It does not
show that an agent chooses useful questions, that a response improves a decision,
or that the simulator agrees with real PV hardware. Original monotonic timestamps
are retained to reproduce waiting intervals exactly; they are process-local
clock readings, not cross-machine calendar times.

No graphics renderer was run for Step 2. The accepted Step 1 desktop suite and
camera images remain the visual evidence; its 34 rendering tests are not counted
as rerun here. The new work changes orchestration guards and adds interface code,
without changing the renderer, optical model, electrical model or thermal model.
No replacement or illustrative images were created.

Step 3 is the next assignment: identify the decision agent, demonstrate actual
human dialogue and internet retrieval, and retain a response-dependent follow-up
or physical test. Step 4 then compares usefulness against a frozen investigation
sequence with the same channels and budgets. Those results must not be inferred
from this scripted interface fixture.
