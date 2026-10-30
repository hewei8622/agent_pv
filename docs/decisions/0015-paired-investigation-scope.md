# 0015 — First paired investigation comparison

Date: 19 October 2026. Wei authorized all five implementation, experiment,
recording, visualization and evaluation steps with “yes, complete 1-5”. This
continues the accepted [v2 plan](../planning/interactive-pv-prototype-v2.md)
after the reviewed shared-decision foundation.

## Executable scope

Implement a competent frozen procedural reference R and a deterministic
goal-driven symbolic planner A. Both receive the same public technical brief,
capabilities, sensor streams, controlled service-information endpoint and
budgets. A updates evidence-backed within-episode world/self records and selects
an unmet goal; R follows a frozen measured branch procedure. Neither is an LLM,
an open-ended learner or a cross-episode memory system. Existing public adaptation
constraints are retained: no parameter training or cross-episode policy update.

The first controlled batch has four paired cases, one deterministic episode per
arm: unchanged known hold; incident-light reduction with known hold; unknown
service context receiving hold; and unknown service context receiving survey.
All eight episodes use a 16 s horizon and the same seed. The latter pair has
identical physical configuration and initial public brief: only the external
service instruction differs. Compare their pre-query local-history hashes.
This tests whether the received instruction changes a justified operating
decision. It does not identify a previously unknown physical fault.

The service endpoint accepts new questions but returns a typed current service
record. It is a controlled simulated source, not semantic internet search or a
live human. Invalid, unavailable, irrelevant, conflicting and ineffective-action
responses are robustness tests, not extra primary performance episodes. Broader
cases, live channels, memory and hardware validation remain separate work.

Freeze exact runtime, policy/evaluator code, source records, configurations,
budgets, numerical thresholds and seed before the formal batch. Engineering
smoke checks and fixture tests necessarily precede that executable freeze; these
are development cases, not a preregistered held-out performance study. Retain all
scheduled outcomes and any failed attempts. A tie is an informative result and
must not trigger weakening of the reference or post-result rubric changes.

## Recorded evidence and compatibility

Retain full public observation history, question/reply provenance, pre-dispatch
audit records and predictions, executed actions, measured survey points and
fresh verification. Evaluate claims against information available when claimed;
finish-tail measurements cannot retrospectively justify an earlier decision.
Exact investigation replay must reproduce observations and final metrics.

Three existing runtime modules intentionally change: `interaction.py` and
`investigation.py` add explicit opt-in for a Recorder marked
`execution_protocol="investigation/1.0"`; `replay.py` rejects those recordings
in the legacy physical-only replay entry point before creating output. The
default Recorder rejection and old physical replay behavior remain intact.
The investigation replay includes charged information-decision overhead and
observations. This versioned bridge avoids silently replaying incomplete actions.

## Visual and analytical acceptance

Build synchronized R/A plots and orbitable 3D from the same verified recordings,
including information gaps, replies, goals, predictions and verification costs.
New episodes are numeric-only and produce zero RGB frames. Label the 3D scene as
an evaluator reconstruction; do not present it as camera evidence or imply image
interpretation. Keep public exports physically free of private scene/truth and
evaluator results. Existing accepted camera evidence remains separately linked.

Report supported decisions, fresh outcomes, all error categories, raw resource
costs and PV energy over the common horizon. Synchronous policy timing includes
public-context and output validation; over-budget returns are rejected before
dispatch, but hostile/non-returning Python is not preemptively isolated. External
waiting pauses simulation and the in-memory source's wall time is not human or
internet latency. No live transfer, paid model call or new dependency is needed.

Complete independent code/evidence review, meaningful non-render regression
tests, actual browser interaction checks and visual inspection of every PDF
page. Do not rerun accepted desktop rendering solely for this numeric extension.
The final evidence record must report actual results and outstanding scope.
