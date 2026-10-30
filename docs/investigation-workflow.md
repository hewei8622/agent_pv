# Shared investigation records and workflow replay

This first implementation checkpoint connects public observations, physical
choices, information requests, pre-action predictions and later verification.
It also provides an offline replay viewer of one retained procedural B1 episode.
An adaptive policy and its matched reference comparison are the next development
step; the viewer currently consumes the older retained episode format.

## Decision coordinator

`pv_sim.investigation.InvestigationSession(env, initial_observation)` wraps the
existing physical environment and information session. Its `context()` returns
a validated copy of the public task, observation history, completed information
receipts, budgets, next action ID and current world/self records.
No private scenario, true state, evaluation metrics or credentials are supplied
to the policy through that context.

The policy interface is `policy.act(context)`. `session.choose(policy)` calls
it and validates its returned `PhysicalChoice` or `InformationChoice`.
`session.submit(choice, transport=...)` records the complete choice, context hash
and predictions before dispatching the physical action or information request.
`complete`, `poll` and `cancel` handle a pending information request; it must be
settled before a new decision context can be requested. Exact
retries are idempotent; conflicting retries and effects after a dispatch failure
are rejected. `session.save(path)`, `load_investigation(path)` and
`replay_investigation(env, initial, transcript)` retain and replay the record.

The choice is committed in memory before dispatch. Persistence occurs on save;
this is not a crash-recovery journal. The interface is a trusted local data
boundary, not process isolation from hostile Python. Policy computation latency
and overruns must be recorded before an adaptive comparison; this checkpoint's
fixture submits authored choices directly.

`WorldBelief` records the policy's concise current explanation, information gap
and evidence references. `SelfModel` records its understanding of available or
unavailable tools and relevant evidence. These are attributed policy records,
not additional hidden truth, a learned physical simulator, new actuators or
cross-episode memory. Adaptation here means updating records within an episode.

## Retained verification fixture

The driver `scripts/validate_investigation.py` runs a short numeric MuJoCo/PV
episode: observe, obtain one authored information reply, commit a voltage
prediction, set voltage, collect fresh matched voltage/current, and finish with
the causal diagnosis unresolved. It verifies the transcript and exact replay.
It uses no rendering or live external service.

From the project directory, a fresh run can be retained with:

```sh
pv_fixture_id="investigation-check-$(date -u +%Y%m%dT%H%M%SZ)-$$"
python3 scripts/record_command.py \
  --label "$pv_fixture_id" --timeout 180 \
  --evidence-dir "runs/investigation-build-20261019/evidence" -- \
  .venv/bin/python scripts/validate_investigation.py \
  --output "runs/$pv_fixture_id"
```

Existing output directories are refused. The accepted fixture already exists at
`runs/investigation-fixture-20261019/`; rerunning it is not needed to view results.

## Offline visual replay

Open the evaluator HTML linked from the checkpoint evidence record in a browser.
Play/pause, scrub, or step by decision. Drag the 3D view to orbit, scroll to zoom,
and use Reset view to restore it. The perspective selector distinguishes public
evidence from evaluator information. The separate public HTML omits private data
from the artifact itself.

The original camera image remains separate from the 3D reconstruction. The
reconstruction uses recorded scene geometry and actual pose for explanation;
it is not an image seen by the policy. Public geometry remains unknown where no
public scene manifest exists. Public values appear only when returned to the
policy. Derived power requires valid capture-matched voltage/current readings.
Missing predictions remain missing; B1 does not interpret image pixels.

The builder creates exclusive new HTML and hash manifests. To rebuild the same
retained episode into a new location, use:

```sh
.venv/bin/python scripts/build_workflow_replay.py \
  --public-dir runs/m1-desktop-20261017T192106Z-8055-s11/public \
  --evaluator-dir private_eval/m1-desktop-20261017T192106Z-8055-s11 \
  --output output/workflow/new-review/b1-evaluator.html \
  --public-output output/workflow/new-review/b1-public.html
```

This processes retained evidence without rerunning physics or graphics. Static
browser screenshots document the viewer; synchronized agent/reference report
figures will follow actual matched comparison runs.

## Next implementation steps

1. Add measured policy latency/overrun handling and freeze executable cases,
   source corpus, validity rules, model configuration and both policy versions.
2. Implement the competent reference and adaptive policy with identical public
   capabilities, context authority and budgets. Retain null and failed outcomes.
3. Connect their new investigation transcripts to this viewer, including
   request/reply pauses, belief updates, predictions and verification residuals.
4. Run matched comparisons and export the supported workflow figures. Demonstrate
   actual human/web exchanges separately before making live-interaction claims.

See the [development plan](planning/interactive-pv-prototype-v2.md),
[visual specification](planning/workflow-visualization-v1.md) and
[scope decision](decisions/0014-investigation-development-scope.md).
