# Interactive PV prototype: adaptive decisions, comparison and workflow visualization

Version 2, 19 October 2026. Wei accepted the development direction following
technical report v3 and added workflow plots and 3D visualization as a key part
of the prototype. This revision specifies that work; it does not record its
implementation or acceptance. It supersedes v1 for the next development steps.
The [v1 plan](interactive-pv-prototype-v1.md), accepted Steps 1–2, reports and
archived v7 milestones remain historical evidence.

## Research question and intended demonstration

> Can a PV asset choose between physical experiments and external information,
> use the evidence to make a supported decision, and verify its outcome more
> usefully than a frozen procedural reference under matched conditions?

The demonstration must explain **how** each system works, as well as report its
outcome: hidden world change → available evidence → interpretation/information
gap → choice of interaction → prediction/action → fresh verification → revision.
Plots and a synchronized 3D replay are core deliverables, with acceptance
criteria in the [workflow visualization specification](workflow-visualization-v1.md).

The potential change in PV operation is evidence-dependent investigation: the
asset can choose when a measurement, physical experiment, outside question or
no intervention is useful. Whether this improves decisions, costs or energy is
an experimental result, including the possibility of no advantage. Attractive
animation, more questions or a convincing explanation are not measures of benefit.

## Existing foundation and boundaries

- **WORLD:** accepted simplified electrical/thermal simulator, source schedule,
  scene/camera mechanics, sensor delays and bounded action execution.
- **INTERFACE:** public observations, physical action gate, information requests,
  provenance, pause/resume, budgets, recording and replay.
- **Current policies:** B0 fixed voltage and B1 fixed scan/measure/select/verify.
  B1 uses measured values but does not interpret images or revise causal beliefs.
- **EVALUATOR:** private scenario/truth and independent reference calculations.
  These are not inputs to the decision policy or its memory.

The next development work integrates these pieces. It does not require cleaning,
reconfiguration, new PV physics, a fault taxonomy, new model training or hardware.
Agreement with real hardware remains the separate P08 calibration/validation task.
The coding assistant's tools are not automatically tools of the PV agent.

## Experimental arms

| Arm | Decision behavior | Role |
|---|---|---|
| R: procedural reference | Frozen investigation order, question templates and response branches; measured selection and fresh verification. | Primary non-agentic comparator, based on B1. |
| A: adaptive investigation | Selects the next sensing/probe/question step from public evidence; can revise explanations and compose follow-ups. | First agent under test, without cross-episode memory. |
| B0: fixed operation | Existing fixed-voltage policy. | Optional descriptive reference; not sufficient alone to establish the value of investigation. |
| A+M: agent with experience | Same A configuration with a frozen permitted experience collection and applicability checks. | Later memory-on/off comparison; not a prerequisite for R versus A. |

R is a competent programmed procedure, not an intentionally weak agent. It may
branch on failures, select the largest measured probe power and apply predefined
evidence rules. Freeze its useful investigation and external-query rules using
development cases before examining held-out results. Do not force it to perform
needless expensive actions or omit measurements available to A.

Both R and A use the same lower-level action/measurement/verification helpers,
physical limits, prior technical information, source collection, response
conditions and resource caps. Equal access does not require equal tool usage or
identical answers to different questions. Record all differences in configuration.
Explicitly declare any permitted prior scene geometry: the current public task's
nominal camera calibration is not a complete public scene manifest.
The contrast being tested is adaptive investigation versus a prescribed procedure;
it is not a claim that fixed feedback control lacks all intelligence.

## Development work packages

| Package | Required change | Completion evidence |
|---|---|---|
| D1 — Freeze task and reference | Define the goal, acceptable decisions/unresolved outcomes, context conditions, R procedure, budgets, common evaluation horizon and metrics. | Reviewed experiment manifest and development/held-out split before comparison. |
| D2 — Integrate decision flow | Add a versioned public context and typed physical/information choice; retain full predictions, references and verification through the coordinator. | One linked trace; schema, boundary, timing, retry and replay tests. |
| D3 — Implement minimal A | Declare the decision mechanism/configuration; maintain compact world-belief and self-capability records; select existing tools from evidence. | Response-dependent decisions, justified invariance, pre-action prediction and measured verification. |
| D4 — Supply usable information | Add controlled queryable sources for newly composed questions, then separate live human/web transports. | Frozen-source comparison plus separately labelled actual live exchanges. |
| D5 — Compare and explain | Run paired R/A episodes and produce synchronized workflow plots, 3D replay and a result table from the same records. | Complete successes/failures/unresolved cases; independent data and visual review. |
| D6 — Test memory separately | Add permitted experience storage/retrieval, context matching and current verification. | Same-agent memory-on/off study including stale/misleading memories. |

Visualization development begins with D2's event contract, not after collecting
results. A retained B1 trace can establish playback/data correctness, clearly
labelled as procedural. It cannot stand in for the later adaptive demonstration.
D2/D3 and the recorded-source portion of D4 can be developed together. A small
repeatable comparison is a development check before the separate live showcase;
recorded-only evidence cannot complete v1's Step 3 live requirement.

### Decision interface and records

`PolicyRunner` currently accepts observation history and emits a physical
`Decision`. `InformationSession` separately records replies and a smaller
`PhysicalDecision` without the original predictions. Bridge these paths rather
than attaching a model to a flow that never supplies it with replies.

The public context should contain task/capabilities, observations available by the
decision boundary, completed replies, remaining budgets and, only for A+M,
permitted memories. The trusted coordinator owns the environment and dispatches
validated choices; the policy receives neither it nor private files/state.

Retain a concise decision summary with public evidence references, information
gap, alternatives when recorded, selected interaction, expected measurement/time
window, and subsequent verification. Store world belief and self capability
updates with their evidence and time. Do not require invented numerical confidence
or an exhaustive private reasoning transcript. Missing reasoning/prediction stays
explicitly absent. A post-hoc explanation is labelled commentary, not a prediction.

A world belief represents the panel/environment as understood by the agent. A
self record represents available/effective tools, limits and resources. These
need not be learned neural networks. The chosen model or rules, version, prompt,
configuration, declared image access and permitted prior knowledge must be recorded.
An agent that only receives scalar data cannot be shown interpreting camera pixels.

Preserve legacy action and transcript compatibility through explicit versioning.
Declare allowed adaptation for the new task; do not silently reinterpret the
current `allowed_adaptation="none"` when introducing memory. Keep accepted B0/B1
replays and the historical pilot CLI behavior intact. A dedicated comparison
entry point should own new manifests, public records and private evaluation.

### Information sources and live demonstration

`RecordedTransport` matches every request field exactly. Preserve it for replay;
provide a separate frozen document/context source that accepts new questions.
Its retrieval/answering rules, provenance and human-context visibility are part
of the experiment, independent of the policy and private evaluator answer.
Human reports describe declared observations/context, not hidden labels supplied
to make diagnosis easy. A document can suggest a test without proving panel state.

Live human/web adapters require versioned live provenance and a polling/cancellation
flow. Preserve the accepted three-request cap, follow-up accounting, 300 s human
and 30 s internet wall deadlines, message limits and cached identical retries
unless a measured, documented protocol revision is made before evaluation.
Actual external transfers, paid model calls and participant contact remain a
separately specified live assignment; no such calls are made by this plan update.

Simulation and the event queue remain paused during external waiting at a settled
decision boundary, after the charged decision overhead. Physical actions and
explicit waits advance simulation normally. Display simulated and wall time
separately. Neither graphs nor animations may imply that paused time produced
energy or that the prototype measures real-world human-response-delay losses.

## First case family and acceptance tests

Use the existing v3/test-guide P01–P07 identifiers; do not expand the first
prototype into a large fault taxonomy. Freeze numerical thresholds and acceptable
sets of next decisions in D1. They are not selected after observing agent outputs.

| Case | Behavioral acceptance | Existing/proposed test link |
|---|---|---|
| Unchanged control and accepted source step | Distinguish change from noise using available timestamps/evidence; avoid false alarms and needless queries. | P01, P04 |
| Source change versus view-only obstruction | Do not infer electrically effective shading from a blocked camera view. | P02 |
| Matched sensor history with relevant/irrelevant/unavailable/conflicting replies | Change decisions when supported, remain invariant when appropriate, or investigate/declare unresolved. | P03, P04 |
| Advertised incapability or measured action failure | Replan; distinguish unavailable action, failed application and panel response. | P05 |
| Bounded probe with prior prediction | Check direction/magnitude/timing where predictable, using fresh matched measurements; report inability to predict honestly. | P06 |
| Matched R/A episodes | Supported decisions, appropriate abstention and costs under the same task/access/limits. | P07 |

The accepted source step is a local-evidence case: reference irradiance already
reveals the incident-light change. Do not remove that sensor to force a question.
Before implementing a context-use case, specify a concrete allowed decision whose
acceptable choice genuinely depends on additional context. If this cannot be
demonstrated in the selected scenario, report no demonstrated external-information
benefit; do not manufacture a diagnosis label or information gap.

Extend integration tests to the combined context, receipts and memory: no future
packets, hidden truth or evaluator outputs; no direct execution of external text;
explicit invalid response and budget handling; predictions saved before outcomes;
no stale measurement used as fresh verification. Future model interpretation of
misleading source text also needs behavioral tests, not only transport validation.

## Evaluation and visual explanation

Primary outcomes are supported task decisions and fresh verified outcomes,
including justified unresolved results. Score inappropriate abstention separately
so always stopping cannot win. Freeze that rubric and success criteria before trials.
Report false alarms, unsupported attribution, false completion and failures.

Report raw probes, frames, motion, requests, simulated elapsed time, computation
and external waiting wall time separately. Compare PV energy only over a common
simulated horizon with declared terminal behavior. Do not call dimensionless
utility net energy or infer real hardware benefit from surrogate-model results.

Pair initial conditions, exogenous event schedules and named random streams.
Different actions can produce different subsequent measurements and world states.
Use episodes as experimental units, retain every scheduled outcome and report
per-case differences before aggregate summaries. Repeated model runs, if used,
are declared in advance and are not substituted for missing condition diversity.

The visual deliverable must let a viewer answer: what changed; what each policy
could know at that moment; why its recorded decision was made; what tool it used;
what physically happened; what measurement verified it; and whether the difference
was useful. A null result or failed attempt must be equally visible. Claims about
the value of adaptivity require matched runs, not an invented alternative path.

## Completion and handoff

Deliver the experiment manifest, R/A implementations and tests, original images,
public decision/interaction traces, private evaluation, paired results, the
workflow viewer, and exportable annotated plots/3D snapshots. Record which live
channels were actually exercised. The visualization specification defines its
own traceability, timing, boundary and readability acceptance checks.

Review the smallest complete recorded-source slice before expanding the case
set or adding memory. Live Step 3 acceptance and bounded Step 4 usefulness remain
separate reported conclusions. Full archived M3–M6 and hardware validity are not
completed by this prototype or by its visualization.

This revision changes planning and navigation only. It runs no new experiment,
adds no runtime capability, and does not change the accepted test results.
