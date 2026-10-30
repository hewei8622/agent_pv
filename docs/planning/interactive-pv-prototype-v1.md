# Interactive PV decision making prototype plan

Version 1, 18 October 2026. Wei approved this planning revision after reviewing
the simpler prototype proposal. Status update, 19 October: step 1
[passed independent desktop review](../evidence/source-response-desktop-acceptance-20261019.md),
including 599 tests and the actual camera images. It extends the
[accepted M2 foundation](../evidence/M2-desktop-acceptance-20261018.md).
Step 2 also [passed independent review](../evidence/information-interface-acceptance-20261019.md)
on 19 October: 708 non-render tests and exact replay of the scripted information
fixture. Its replies are recorded/simulated, with no live exchange or adaptive
agent demonstrated. Steps 3–4 and the full historical M3 gate remain future work.

The first prototype will address one question:

> Can a PV asset choose between physical experiments and external information
> gathering, use what it learns to make a decision, and check the outcome?

Use one simulated PV asset with an unexpected output change. The agent may
inspect sensor readings or camera images, perform a bounded voltage experiment,
ask a human, or look up information. It can ask a follow-up question, take another
measurement, choose an operating point, or conclude that evidence is insufficient.
Questions and replies can be free text; physical actions retain their existing
bounds. Open-ended interaction here means that the next question or observation
can depend on the response. It does not require autonomous discovery of new
physics or learning new model weights.

## Existing foundation and changes in scope

M2 supplies real rendered images, camera motion, voltage probes, timed sensor
records, action verification, costs and replay. Its retained desktop suite
passed 519 tests. It establishes the simulator foundation, rather than the new
human or internet capability.

The v7 plan, checklist and historical
evidence remain unchanged. This addendum prioritizes a small interaction pilot
ahead of the full scenario bank, classical planner and comparative study in
v7. Physics, data boundaries and evidence standards still apply to every claim.
Completion of this pilot will not count as completion of the archived M3–M6
gates. Broader causal or performance claims retain their corresponding reviews.

Reconfiguration, cleaning, continual learning, multiple assets and hardware
transfer remain later research. A particular external AI provider is not a
requirement of the first prototype. Any model used to choose questions or actions
must be identified separately from the coding assistant; a scripted driver tests
the interface but does not demonstrate an adaptive AI agent.

## Interaction and information

The loop is: **observe → identify an information gap → choose an interaction →
interpret the response → decide → check the outcome**.

| Channel | First prototype role |
|---|---|
| Sensors and camera | Obtain local measurements or a different reachable view |
| Voltage experiment | Predict and measure the response to a bounded load change |
| Human dialogue | Ask about local observations, recent work or missing context; allow clarification |
| Internet lookup | Retrieve relevant technical information that can guide an experiment or decision |

Add a versioned interaction layer alongside the existing physical action
contract. The existing `request_help` accepts only `reference_irradiance` or
`rear_inspection`, and M2 advertises neither. Preserve that legacy meaning.
Free-text questions and external evidence need explicit records and compatibility
tests, rather than being placed into those measurement fields. Legacy diagnosis
labels must not limit the wording of questions, replies or interpretation.

Each interaction records a request ID, channel, question, information gap,
parent request for a follow-up, and the decision it could inform. The response
records its text, source or URL, source date when available, receipt time and
availability. Distinguish live, recorded and simulated replies. Link the evidence
to the subsequent decision and any sensor verification. An answer may justify
keeping the current plan; every answer need not cause a change.

A manual can explain a mechanism or suggest a test without establishing the
condition of this panel. A human can report what they observed without knowing
the cause. Preserve uncertainty and contradictions. The policy receives public
observations and retrieved evidence; evaluator labels, private state and future
events remain inaccessible. Human participants receive only their declared
observations/context, not the evaluator answer. Recorded evidence must not
encode hidden scenario IDs or outcomes.

Use a trusted retrieval component to return information to the agent. This is a
planned extension to v7's restriction on browser access, not unrestricted access
to files, code execution or the evaluator. External text supplies evidence; all
physical commands still pass through the existing action gate. Requests that
cannot be answered return an explicit unavailable, timed-out or cancelled result.

## Timing and budgets

The first prototype uses the existing offline timing convention: pause simulation
while the agent computes or waits for external information, only at a decision
boundary with no action in flight. Freeze the event queue as well as the physical
state; existing captures retain their timestamps. Resume the same clock afterward.
Movement, voltage probes and explicit waits advance the simulated world normally.

Preserve the 0.2 s simulated decision overhead for each new decision, including
an external request, and the physical action budgets and final verification tail.
An identical request-ID retry must return the recorded result without repeating
the interaction or charging again. External waiting time is logged separately in
wall-clock seconds; frozen wall time generates no additional simulated energy.
Results therefore describe an offline interaction experiment, not real-time
energy efficiency during human response delays.

Use an initial cap of three external requests per episode across both human and
internet channels; each follow-up consumes one request. Count them within the
total decision cap as well. Before the first trial, freeze channel response
deadlines and message-size limits in the experiment configuration. Record timeouts
and unavailable replies as outcomes. Apply the same limits to both comparison
policies. The legacy one-request, five-second simulated measurement-help rule
remains a separate capability.

## Development sequence and acceptance

Step 1 is accepted within the [19 October scope record](../decisions/0012-source-response-scope.md).
Step 2 is accepted within the [offline interface scope](../decisions/0013-information-interface-scope.md)
and its [independent evidence review](../evidence/information-interface-acceptance-20261019.md).
Steps 3–4 remain planned; each subsequent step follows review of the preceding
evidence. External data transfers, paid model calls and contacting human
participants belong to a later live-demonstration assignment.

| Step | Deliverable and acceptance criteria |
|---|---|
| 1. Validate one scenario | Select one output-change mechanism, starting with a source-level change within the existing simplified model. Freeze its public observations, goal and expected responses. Check direction, magnitude and timing against independent calculations; record unchanged conditions and noise. Include real camera images and state which changes are visually observable. |
| 2. Build and test the interface | Implement bounded questions, follow-ups, response provenance, pause/resume, budgets and replay. Recorded replies must reproduce the interaction trace. Reject malformed or conflicting requests; return the cached result for an identical request-ID retry. External text must not bypass the physical action gate. |
| 3. Demonstrate adaptive interaction | Connect the declared decision agent. Retain actual human dialogue and actual internet retrieval, with a response-dependent follow-up or physical test. Save questions, evidence, decisions, camera/sensor observations and verified outcomes. Label each channel demonstrated; fake/replay-only runs cannot pass the live-interaction criterion. |
| 4. Measure bounded usefulness | Compare the adaptive agent with a frozen investigation sequence over the same development cases, available channels, source collection and budgets. Retain successes, failures and unresolved outcomes. Report decision quality and raw costs separately. |

Step 1 must distinguish a real model response from a label or display change.
For the selected source change, check the electrical response at a fixed applied
voltage, the thermal response over its declared timescale, and the capture and
delivery of the resulting measurements. Use an unchanged-source control. Compare
errors against tolerances established before agent evaluation; do not calculate
the expected answer by calling the same implementation being tested.

M2's screens block camera views while leaving illumination unchanged. They must
not serve as evidence of shading-induced power loss. If source shadows or visible
contamination become necessary, validate their optical/electrical coupling first.
Do not require the camera to reveal a change that the rendered model does not
represent. These checks establish consistency within the specified digital model;
agreement with a real panel requires later measured calibration and validation.

## Small evaluation and completion record

Use one scenario with a few evidence conditions, rather than a large fault
taxonomy. Include a case where existing measurements or a probe suffice, a case
where external context usefully changes the next step, and a case with unavailable
or conflicting information. In the last case, further measurement or an unresolved
outcome can be appropriate. Do not hide already available measurements merely to
force a human or internet request. The agent need not use every channel in every
episode.

Before running the comparison, record which decisions are acceptable in each
case and what observation would verify them. Use the following common rubric:

| Question | Evidence to retain |
|---|---|
| Did the selected source address the gap? | The pre-request question and intended decision, the accessible evidence and whether a cheaper available observation already sufficed |
| Was evidence used appropriately? | Paired reply tests showing that relevant changes can alter the next decision, while irrelevant or unsupported claims do not force it |
| Was the outcome supported? | A pre-action prediction where possible, fresh measured confirmation and the case's predeclared success or unresolved criterion |
| What did the decision cost? | Probe points, frames, external requests, simulated elapsed time and actual computation/waiting time, reported separately |

The first comparison uses a small frozen evidence collection and recorded replies
for repeatability. Give both policies the same access and limits; answers may
differ because their questions differ. Freeze the fixed sequence before inspecting
comparison outcomes. Report episode-level results without treating successive
frames as independent experiments. Live web and human demonstrations are reported
separately because their responses may change between sessions. The comparison
can reveal useful behavior or no advantage; it does not by itself establish
general superiority over strong diagnostic controllers.

Completion requires a reviewed trace of the whole loop, original camera images
and sensor/action records, interface test results, a small comparison table and
documented failure cases. List which information channels were actually exercised
and which remain unavailable. Preserve the accepted M2 record, and record new
runtime and protocol versions with the new evidence. The resulting claim is
bounded interactive decision making in a validated simulated scenario.
