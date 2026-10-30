# Testing the PV interaction loop

Version 1, 19 October 2026. This guide reorganizes existing evidence around the
research process: **hidden environment change → public sensing → analysis →
information gathering or a physical experiment → decision → fresh verification**.
It does not implement a new agent. The [machine-readable map](interaction-test-map.json)
contains exact test selectors, source locations and hashes, limitations and planned
checks. Passing tests from separate fixtures is not the same as demonstrating one
autonomous end-to-end agent.

## What is hidden, and what the asset can observe

The evaluator chooses a private scenario and source schedule. In the accepted
source example, direct irradiance changes from 800 to 400 W/m² at 2 simulated
seconds while diffuse irradiance remains 100 W/m². The policy does not receive
that schedule, seed, hidden state or evaluator label. It does receive legitimately
available measurements: voltage, current, temperature, local reference irradiance,
encoders and actual RGB when rendering is enabled.

**Hidden cause does not mean unobservable effect.** The reference sensor directly
reports the incident-light reduction after capture and delivery. The first source
scenario can therefore be used to test whether a future agent uses available evidence;
it does not require asking a human or searching the internet. Sensor evidence may support a source-level
change without identifying whether a cloud, a lamp adjustment or another external
cause produced it. A human can supply context; a technical source can suggest a
test. Neither should be supplied the hidden evaluator answer as a convenience.

The control and treatment retain the same public task and pre-change conditions.
A good causal test changes the intended world mechanism, then checks the resulting
signals, timing and action consequences. Merely changing a label, answer string or
rendered colour is insufficient.

## What models currently exist

| Model | Implemented representation | What remains absent |
|---|---|---|
| Simulator world model | Private scene, source schedule, eight-cell electrical surrogate, lumped temperature, camera mechanics and sensor/event pipeline. | Empirical real-panel calibration and validation; geometric source shadows, cleaning and panel tilt. |
| Public capability and state information | Advertised sensors/actions, voltage/motion bounds, nominal camera calibration, budgets, observation validity/timestamps and measured action feedback. | A learned belief about actuator effectiveness or sensor reliability. |
| Existing policy state | B0 fixed operating point; B1 procedural stages, matched V/I selection, selected voltage and fresh-verification threshold. | A general causal world model, anomaly classifier, uncertainty-calibrated inference or revised model parameters. |
| Information record | Question, information gap, intended decision, parent question, reply provenance, sources, outcome, timing and links to a separate physical decision. | Evidence relevance assessment, response-dependent planning by a declared agent, or proof that a reply improved its decision. |

The public task declares an uninformed policy with nominal camera calibration and
action limits, and `allowed_adaptation="none"`. B1's tested decisions deliberately
have no numerical predictions or hypothesis probabilities and finish with an
unresolved causal diagnosis. Schema support for predictions is not evidence that
an agent produces correct predictions. The `PhysicalDecision` record explicitly
makes evidence references attribution, not proof of causation.

For the next small prototype, a world model can be a modest set of explicit
hypotheses and predicted responses. A self-model can be the available tools,
remaining resources, last attempted action and confidence in its measured result.
Neither requires continual learning, a new neural network or an elaborate fault
taxonomy. Their usefulness must be tested through pre-action predictions and
response-sensitive choices, not inferred from persuasive explanations.

## Available tools and procedures

| Asset capability | Current behavior and boundary |
|---|---|
| Local sensing | Read delivered scalar/encoder observations; obtain actual camera images through an advertised capture action. Original capture times and validity matter. |
| Active viewing | Move the rail/yaw/pitch within limits, then confirm actual pose and any requested capture. A publicly locked rail is known incapability, not a hidden fault discovery. |
| Electrical experiment | Set an operating voltage or probe at most three bounded points; wait for application/settling and fresh matched V/I. Probe restoration is separately confirmed. |
| Wait, Finish, safe stop | Advance physical time deliberately, retain the final two-second verification tail, or stop with measured confirmation and explicit failure if confirmation is absent. |
| Human/internet information interface | Bounded free-text requests and follow-ups, provenance, deadlines, caching and replay. Current transports use recorded/simulated replies; URLs are metadata, not automatic retrieval. |
| B0/B1 procedures | Fixed setting and scripted scan/choose/verify sequence. B1 checks image availability but does not interpret image pixels or diagnose faults. |

These are the simulated asset's capabilities. The coding assistant's browser,
PDF-generation tools and development skills are not automatically tools available
to the PV decision agent. Actual human/web interaction belongs to Step 3 and needs
a declared decision agent and reviewed live transport. Legacy `request_help`
retains measurement-only meanings and is not currently advertised as available.

## Existing tests by causal stage

The table gives representative tests; the JSON map contains the full focused
selection. Test names below are existing functions, not proposed implementations.

| Stage and question | Representative test | What a pass establishes |
|---|---|---|
| Hidden world change: did the mechanism actually change? | `test_source_boundary_integrates_old_interval_then_captures_new_state` in `tests/integration/test_source_schedule_runtime.py` | The old interval is integrated before the event; new electrical/light state is used at the event, without an instantaneous temperature jump. |
| Independent physical response: is this more than a changed label? | `test_control_and_changed_source_match_independent_reference` and `test_wrong_current_cannot_pass_a_correct_irradiance_label` in `tests/integration/test_source_response_validation.py` | Control/treatment match a separate reference; corrupt current fails even if irradiance labels look correct. This verifies the digital model, not real hardware. |
| Sensing: did the agent receive the correct evidence? | `test_queued_scalar_capture_before_change_keeps_original_value_and_timing` in `tests/integration/test_source_schedule_runtime.py`; `test_future_packet_in_earlier_observation_is_rejected` in `tests/integration/test_source_response_validation.py` | Measurements keep their original state/time and cannot appear before delivery. It does not show that an agent notices or interprets them. |
| Analysis: does the current policy use its limited evidence correctly? | `test_scan_complete_public_sequence_uses_probe_then_new_verification` and `test_scan_missing_stale_or_unmatched_dwell_point_stops` in `tests/unit/test_policies.py` | B1 chooses the largest measured V×I among its fixed points and rejects inadequate evidence. It does not select an experiment based on a causal explanation. |
| Information: is requesting and receiving evidence well-defined? | `test_followup_and_completed_retry_charge_once` in `tests/integration/test_information_session.py`; `test_wait_advances_only_overhead_then_freezes_captures_queue_and_energy` in `tests/integration/test_information_pause.py` | Follow-up linkage, retry accounting, pause and sensor/event timing work. This is interface correctness, not useful dialogue. |
| Action: did the request really apply? | `test_delayed_load_separates_acknowledgement_application_and_fresh_measurement` and `test_dropped_load_never_claims_applied_target_and_retry_is_idempotent` in `tests/integration/test_m2_actions.py` | Acknowledgement, application and measured response remain distinct; a dropped command does not become successful by assertion. |
| Verification: is the outcome fresh and supported? | `test_scan_old_measurements_cannot_verify_new_set` in `tests/unit/test_policies.py`; `test_missing_or_stale_numeric_data_cannot_verify_applied_load` in `tests/integration/test_m2_actions.py` | Old, missing or stale measurements do not verify a new state. Successful voltage execution still does not prove a diagnosis. |
| Whole recorded interface trace | `test_fixture_retains_exact_replay_provenance_links_and_artifact_hashes` in `tests/integration/test_information_fixture.py` | An authored three-exchange script links to a measured probe and unresolved Finish, with exact replay and honest simulated provenance. It is not an autonomous agent demonstration. |
| Boundary and replay | `test_transport_receives_only_an_owned_serialized_public_request` and `test_external_text_cannot_execute_or_read_files_or_change_voltage` in `tests/security/test_information_boundary.py` | The trusted transport receives public records; returned text cannot directly execute a physical action. This is not an OS sandbox or a test of a future LLM's semantic robustness. |

The map also identifies three accepted actual-render tests, including source-change
lighting, viewpoint/occlusion geometry and the real-RGB B1 sequence. They are
**historical retained rendering evidence only** in this documentation task. No GL
context or new camera render was started. The accepted 599-case Step 1 suite and
708-case Step 2 non-render suite overlap and must not be added together.

## Focused execution retained with this report

The report task reruns selected existing non-render tests once. The exact selection
is in [focused-test-selection.json](../../runs/interaction-report-v2-20261019/analysis/focused-test-selection.json),
the actual parameterized identities and results are in
[focused-tests.xml](../../runs/interaction-report-v2-20261019/analysis/focused-tests.xml),
and the machine-readable totals, input hashes, command log and limitations are in
[focused-test-results.json](../../runs/interaction-report-v2-20261019/analysis/focused-test-results.json).
The recorded command uses the locked environment and a 180-second limit. Some
existing tests create short numeric fixtures/replays in pytest temporary folders;
none is a new agent pilot, hardware experiment or external-service call.

**Actual result: 54 passed in 9.73 s, with zero failures, errors or skips.**
The 41 selected function selectors expanded to 54 unique parameterized cases: 26 integration, 5 security, 23 unit. The recorded command exited zero once in 10.135 s; all 61 frozen input hashes remained unchanged. No render tests were run.

Function selectors and parameterized test cases are different counts. The JSON
result reports both, checks unique JUnit identities, and verifies that hashed
runtime/config/test inputs did not change during execution. This focused subset
is additional regression evidence for the report's test map; it does not replace
the accepted full suites or advance a milestone.

## The next tests that would measure intelligence

1. **Notice and explain a change (P01).** Present a control and a source-step history
   through the public observation boundary. Freeze a detection window and false-alarm
   control. Require evidence available by the decision time. Do not hide the
   reference sensor to force an external question.
2. **Separate appearance from electrical cause (P02).** Contrast a source response
   with existing view-only occlusion. A blocked camera view should not be treated
   as shading-induced power loss when electrical/reference evidence says otherwise.
   This does not yet require adding geometric source shadows.
3. **Use a reply rather than merely log it (P03).** Hold the pre-request public
   history fixed and vary a relevant supported reply, an irrelevant reply and an
   unavailable reply. Freeze acceptable next decisions before the trial. Check
   that relevant information can change the justified next question or experiment,
   and that irrelevant text does not force arbitrary action.
4. **Choose a source for a real gap (P04).** A manual can guide timing or probe
   design; a human can add declared local context. Compare these with a case where
   sensor evidence already suffices. Reward justified no-query and unresolved
   outcomes, not use of every channel. Keep hidden labels out of replies.
5. **Track capabilities and failed actions (P05).** Test advertised rail limits,
   scarce budgets and existing hidden dropped-load conditions. Distinguish knowing
   a capability is unavailable from inferring that an attempted action failed.
   Require observation or safe stopping instead of false recovery claims.
6. **Predict, act and check (P06).** Record an expected direction or quantitative
   response and time window before an allowed probe. Score later fresh measurements
   and abstention coverage. Distinguish action success, information gained and
   causal conclusion; a plausible retrospective explanation is insufficient.
7. **Measure bounded value (P07).** Compare a declared adaptive agent with a frozen
   sequence under equal channels, source collection and budgets. Report decision
   quality, failures/unresolved episodes, probes, frames, requests, simulated time
   and wall time separately. Paused external waiting is not real-world energy yield.
8. **Validate transfer separately (P08).** Calibrate a specified physical counterpart
   on designated data, freeze the model and time alignment, then compare held-out
   light/load/motion changes. Report absolute and change residuals with measured
   uncertainty. Current digital tests cannot substitute for those measurements.

P01–P08 are proposed designs, not newly implemented tests or completed experiments.
They are deliberately small enough for the first prototype. There is no need to
claim open-world causal discovery, new model weights, cleaning or reconfiguration
to test response-dependent information gathering.

## Evidence boundary and interpretation

`PublicTask`, `Observation`, typed actions and information records define the
trusted local interface. Private source schedules, configuration, seeds, truth
trajectories and evaluator metrics remain evaluator inputs. Tests deliberately
inspect private values to verify implementation; an agent must not receive those
values or the test's expected answer. Test-only calibration markers also remain
outside production policy observations.

The simulator world model, a proposed agent belief model and the evaluator's
independent reference are three different objects. Sharing the same production
solver as the expected answer can hide a common error. A fresh reading can verify
an applied voltage without identifying why output changed. A checksum verifies
artifact integrity, not the truth of a human statement. A faithful replay verifies
reproducibility, not that the original decision was intelligent.

Current evidence supports bounded digital response, honest timed sensing, action
verification and a reproducible offline information interface. A declared adaptive
agent, live human/web exchange, response-dependent choices and comparative benefit
remain the next research claims to demonstrate.
