# Paired PV investigation: running and reading the comparison

The first controlled comparison is complete. Read the
[evidence record](evidence/paired-investigation-20261019.md),
[capability and case-design report v2](../output/pdf/PV_INVESTIGATION_CAPABILITIES_AND_CASES_v2.pdf) and
[paired replay](../output/workflow/paired-03/paired-public.html).
The [scope decision](decisions/0015-paired-investigation-scope.md) declares the
mechanism and boundaries. Original technical report v3 remains unchanged.
The [earlier evidence report](../output/pdf/PAIRED_INVESTIGATION_REPORT_20261019.pdf)
is retained as the audit of the same experiment. The revised explanation does not
add capabilities or claim a new run.

## What runs

`comparison.py` owns private cases and evaluation. `comparison_policies.py`
implements the procedural reference R and goal-driven symbolic planner A. Both
operate through `InvestigationSession` with cloned public `AgentContext` inputs
and identical `PublicBrief` priors. Policies receive no private case label,
configuration, source schedule or evaluator answer. This is a trusted local
data boundary, not an operating-system sandbox for hostile Python.

The world contains simplified PV/electrical and thermal dynamics, a light source,
camera mechanics, measurement timing and bounded actuation. The agent's world
belief is a compact evidence-backed summary, not a copy of the world's hidden
state. Its self model records tools, failures and remaining budgets. A selects
among declared operators using unmet goals; R follows a prescribed measured
branch procedure. Neither trains, calls an LLM, interprets pixels or retains
experience across episodes.

The controlled external endpoint accepts a valid newly worded question and
returns a typed current service instruction. It does not conduct semantic web
search. The authority marker is a fixture identity, not cryptographic
authentication; arbitrary prose is not semantically interpreted. `RecordedTransport`
continues to serve exact recorded replay. Live human/web transport remains later work.

## Reproduce without overwriting evidence

From the `env` directory, use new paths for every new experiment and freeze.
The existing freeze checks all 42 runtime inputs and the actual Python/library
versions; it refuses changed source. Freeze the current reviewed source before a
new development batch. Do not call a newly frozen batch a held-out replication.

```bash
pv_pair_id="paired-investigation-$(date -u +%Y%m%dT%H%M%SZ)-$$"

.venv/bin/python scripts/record_command.py \
  --label "$pv_pair_id-freeze" --evidence-dir "runs/$pv_pair_id-build/evidence" \
  --timeout 180 -- .venv/bin/python scripts/run_paired_investigation.py \
  --prepare --freeze "private_eval/$pv_pair_id-freeze.json"

.venv/bin/python scripts/record_command.py \
  --label "$pv_pair_id-run" --evidence-dir "runs/$pv_pair_id-build/evidence" \
  --timeout 180 -- .venv/bin/python scripts/run_paired_investigation.py \
  --freeze "private_eval/$pv_pair_id-freeze.json" --output "runs/$pv_pair_id"

.venv/bin/python scripts/build_comparison_viewer.py \
  --manifest "runs/$pv_pair_id/paired_manifest.json" \
  --output "output/workflow/$pv_pair_id/paired-evaluator.html" \
  --public-output "output/workflow/$pv_pair_id/paired-public.html"
```

Rendering is disabled for these numeric episodes; no desktop OpenGL command is
needed. HTML files are self-contained and open locally. The evaluator export
contains private truth and scene geometry; use the separate public export when
those data must be absent, rather than merely hidden by a display switch.

## Read one investigation

Select C04 (unknown service context, survey reply). Advance the common cursor:

1. At 0.02 s, local observation is returned and the initial wait is committed.
2. At 2.62 s, the systems can assess local light measurements and ask about the
   unresolved service instruction. The question contains no hidden scenario label.
3. At 2.82 s, after the charged 0.2 s decision overhead, the attributed simulated
   reply becomes available. External wall waiting occurred at that frozen
   simulation time. The current instruction permits the survey.
4. The probe measures three candidates, 0.8, 1.8 and 3.0 V. These are measured
   points, not an oracle optimum. The probe restores the previous 1.8 V point,
   which is also the highest measured-power candidate here.
5. At 6.92 s, fresh matched V/I confirms that operating point after the actual
   probe terminal. The system holds the verified point to the common 16 s horizon.

Read the world/self summaries and exact event details beside the plots. A
command acknowledgement alone is not verification. Numeric predictions are
committed before execution and checked at their declared capture times. The
probe current is explicitly marked unpredictable by these policies. Holding
until 16 s allows equal-horizon energy accounting; it is not extra diagnosis.

Switch C04 to C03: the physical configuration, seed and pre-query local sensor
history are identical. The different reply requires holding without a probe.
Switch to C02: the reference sensor exposes the incident-light drop, so no
outside question is needed. Neither arm claims a unique physical fault.

The 3D panel/camera view reconstructs recorded private geometry and actual pose.
Orbiting it changes the observer's viewpoint, not the agent's camera or world.
No RGB was acquired in these new episodes. Retained original camera evidence
remains in the [earlier B1 viewer](../output/workflow/build-03/b1-public.html).

## Evidence and compatibility

Each public episode retains `investigation.json`, decisions, observations,
`policy_audit.json`, `decision_timing.json`, `assessment.json`, `public_brief.json`
and `verification.json`. Its private companion contains configuration, truth,
metrics, independent result and completed recorder manifest. The batch manifest
links both arms; `artifact-index.json` hashes all batch files.

`InvestigationSession(..., investigation_recording=True)` requires a real Recorder
whose metadata declares `execution_protocol="investigation/1.0"`. The default
Recorder rejection remains intact. Use `replay_investigation` for this protocol;
legacy physical-only replay rejects these recordings before creating output.
It continues to support old physical recordings.

Tests cover typed source authority/validity, response-dependent choices, negative
responses, failure handling, capture/availability timing, stale or mismatched
verification, exact replay, manifest bindings and public export. The executable
batch is a four-case development comparison. It establishes an auditable
investigation loop, not general fault diagnosis, real-plant fidelity or an
adaptive performance advantage.
