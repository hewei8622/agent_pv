"""Competent fixed procedure and bounded evidence-driven symbolic goal planner.

Both receive only AgentContext and identical PublicBrief records. Shared helpers
implement measurement, authority and verification, so neither arm gains hidden
physics or deliberately weaker evidence checks. A recomputes goal deficits and
eligible operators; it is not an LLM, learned policy, or open-ended intelligence.
"""

from __future__ import annotations

import math

from pv_sim.comparison_sources import PublicBrief, read_service_reply
from pv_sim.contracts import ACTION_ADAPTER, Decision, Prediction, ScalarSample
from pv_sim.interaction_contracts import InteractionRequest
from pv_sim.investigation import (
    AgentContext,
    InformationChoice,
    PhysicalChoice,
    SelfModel,
    WorldBelief,
    validate_choice,
)
from pv_sim.policies.protocol import TERMINAL_CODES, matched_pairs

POLICY_VERSION = "paired-policies/1.0"


def source_assessment(context: AgentContext, brief: PublicBrief) -> dict:
    readings = [
        (o.sequence_id, o.t_deliver_s, s)
        for o in context.history
        for s in o.scalars
        if s.channel == "reference_w_m2" and s.validity == "valid"
    ]
    if len(readings) < 2:
        return {
            "status": "insufficient_evidence",
            "incident_light_reduction": False,
            "unique_cause": "unresolved",
            "observation_refs": [],
        }
    first, last = readings[0], readings[-1]
    drop = first[2].value - last[2].value
    detected = drop > brief.source_drop_threshold_w_m2
    first_detected = next(
        (r for r in readings if first[2].value - r[2].value > brief.source_drop_threshold_w_m2),
        None,
    )
    return {
        "status": "measured_reference_reduction" if detected else "no_threshold_reduction",
        "incident_light_reduction": detected,
        "unique_cause": "unresolved",
        "initial_reference_w_m2": first[2].value,
        "latest_reference_w_m2": last[2].value,
        "reference_drop_w_m2": drop,
        "threshold_w_m2": brief.source_drop_threshold_w_m2,
        "observation_refs": sorted({first[0], last[0]}),
        "first_detected_available_s": None if first_detected is None else first_detected[1],
        "first_detected_capture_s": None
        if first_detected is None
        else first_detected[2].t_capture_s,
    }


def service_assessment(context: AgentContext, brief: PublicBrief) -> dict:
    now = context.history[-1].t_deliver_s
    if brief.known_instruction is not None and now <= brief.instruction_valid_until_s:
        prior = brief.known_instruction
    else:
        prior = None
    receipts = context.completed_information
    results = [(r.request.request_id, *read_service_reply(r.reply, now)) for r in receipts]
    valid_values = {value for _, value, _ in results if value != "unknown"}
    if prior is not None:
        valid_values.add(prior)
    conflicting = any(reason == "conflicting_service_records" for _, _, reason in results)
    if len(valid_values) > 1 or conflicting:
        return {
            "instruction": "unknown",
            "status": "conflicting_service_records",
            "information_refs": [r.request.request_id for r in receipts],
        }
    # An unknown later answer does not erase an earlier still-current valid directive;
    # an explicit conflict does. Every original reply remains in the transcript.
    if len(valid_values) == 1:
        return {
            "instruction": next(iter(valid_values)),
            "status": "known_public_instruction" if prior else "current_authorized_service_record",
            "information_refs": [r.request.request_id for r in receipts],
        }
    return {
        "instruction": "unknown",
        "status": results[-1][2] if results else "missing_context",
        "information_refs": [r.request.request_id for r in receipts],
    }


def fresh_verification(
    context: AgentContext, target_v: float, after_s: float, tolerance_v: float = 0.02
) -> dict | None:
    for observation in reversed(context.history):
        for voltage, current in reversed(matched_pairs(observation.scalars)):
            if voltage.t_capture_s <= after_s:
                continue
            # A newer valid contradictory pair supersedes an older matching pair.
            if abs(voltage.value - target_v) > tolerance_v or current.value < 0:
                return None
            return {
                "target_voltage_v": target_v,
                "after_s": after_s,
                "tolerance_v": tolerance_v,
                "observation_sequence_id": observation.sequence_id,
                "available_at_s": observation.t_deliver_s,
                "voltage": voltage.model_dump(mode="json"),
                "current": current.model_dump(mode="json"),
                "power_w": voltage.value * current.value,
            }
    return None


def probe_measurements(context: AgentContext, action, completed, tolerance_v: float) -> dict:
    """Only settled executing-confirmation pairs can become survey candidates."""
    points = {}
    if completed is None or completed.code != "completed":
        return points
    for observation in context.history:
        for feedback in observation.feedback:
            if (
                feedback.action_id != action.action_id
                or feedback.code != "executing"
                or feedback.commanded_target != action
                or feedback.t_accepted_s is None
            ):
                continue
            samples = tuple(
                m.sample
                for m in feedback.measured_confirmation
                if isinstance(m.sample, ScalarSample) and m.sample in observation.scalars
            )
            for voltage, current in matched_pairs(samples):
                if not feedback.t_accepted_s <= voltage.t_capture_s < completed.t_terminal_s:
                    continue
                for target in action.voltages_v:
                    if abs(voltage.value - target) <= tolerance_v and current.value >= 0:
                        candidate = {
                            "target_voltage_v": target,
                            "capture_s": voltage.t_capture_s,
                            "available_at_s": observation.t_deliver_s,
                            "power_w": voltage.value * current.value,
                            "observation_sequence_id": observation.sequence_id,
                            "voltage": voltage.model_dump(mode="json"),
                            "current": current.model_dump(mode="json"),
                        }
                        if (
                            target not in points
                            or candidate["capture_s"] > points[target]["capture_s"]
                        ):
                            points[target] = candidate
    return points


class _SharedPolicy:
    name = "shared"

    def __init__(self, brief: PublicBrief):
        self.brief = PublicBrief.model_validate_json(brief.model_dump_json())
        self.audit_log: list[dict] = []
        self.actions = []
        self.ready_at_s: float | None = None
        self.ready_verification: dict | None = None
        self.stage = "observe"
        self._bound_episode = None

    def _facts(self, context):
        if self._bound_episode is None:
            self._bound_episode = context.task.episode_id
        elif self._bound_episode != context.task.episode_id:
            raise ValueError("construct a fresh policy for each episode")
        if context.history[-1].terminal:
            raise ValueError("terminal context has no next decision")
        now = context.history[-1].t_deliver_s
        completions = {
            f.action_id: f for o in context.history for f in o.feedback if f.code in TERMINAL_CODES
        }
        failures = [
            a
            for a in self.actions
            if a.action_id in completions and completions[a.action_id].code != "completed"
        ]
        missing = [a for a in self.actions if a.action_id not in completions]
        service = service_assessment(context, self.brief)
        source = source_assessment(context, self.brief)
        probes = [a for a in self.actions if a.kind == "probe_voltage"]
        probe = probes[-1] if probes else None
        points = (
            {}
            if probe is None
            else probe_measurements(
                context,
                probe,
                completions.get(probe.action_id),
                self.brief.voltage_tolerance_v,
            )
        )
        complete_survey = set(points) == set(self.brief.survey_candidates_v)
        target = self.brief.nominal_voltage_v
        if service["instruction"] == "survey" and complete_survey:
            target = max(self.brief.survey_candidates_v, key=lambda v: points[v]["power_w"])
        cutoff = max((r.simulation_time_s for r in context.completed_information), default=0.0)
        first_observation = next((a for a in self.actions if a.kind == "wait"), None)
        if first_observation is not None and first_observation.action_id in completions:
            cutoff = max(cutoff, completions[first_observation.action_id].t_terminal_s)
        for action in self.actions:
            if action.kind in ("set_voltage", "probe_voltage") and action.action_id in completions:
                cutoff = max(cutoff, completions[action.action_id].t_terminal_s)
        verification = fresh_verification(context, target, cutoff, self.brief.voltage_tolerance_v)
        observed = any(a.kind == "wait" for a in self.actions) and now >= (
            context.history[0].t_deliver_s + self.brief.initial_observation_s
        )
        query_count = len(context.completed_information)
        can_query = (
            service["instruction"] == "unknown"
            and context.remaining_information_requests > 0
            and query_count < 1 + self.brief.clarification_limit
            and service["status"] not in {"unavailable", "timed_out", "cancelled"}
        )
        latest_pairs = [
            (o.sequence_id, v, i) for o in context.history for v, i in matched_pairs(o.scalars)
        ]
        at_target = bool(
            latest_pairs
            and abs(latest_pairs[-1][1].value - target) <= self.brief.voltage_tolerance_v
        )
        return {
            "now_s": now,
            "service": service,
            "source": source,
            "observed": observed,
            "probe": probe,
            "probe_points": points,
            "survey_complete": complete_survey,
            "target_v": target,
            "verification_after_s": cutoff,
            "verification": verification,
            "can_query": can_query,
            "failures": failures,
            "missing_feedback": missing,
            "at_target": at_target,
        }

    def _models(self, context, facts):
        refs = tuple(
            sorted(
                set(
                    facts["source"]["observation_refs"]
                    + [
                        context.history[-1].sequence_id,
                    ]
                )
            )
        )
        info = tuple(r.request.request_id for r in context.completed_information)
        service = facts["service"]
        source = facts["source"]
        world = WorldBelief(
            as_of_sequence_id=context.history[-1].sequence_id,
            summary=f"Reference evidence: {source['status']}; unique physical cause unresolved. "
            f"Current service instruction: {service['instruction']} ({service['status']}). "
            f"Operating target from public evidence: {facts['target_v']:.3f} V.",
            alternatives=(
                "Incident illumination can vary independently of panel condition.",
                "Reference measurements do not identify a unique external or panel fault.",
            ),
            information_gap="Current service permission is unresolved."
            if (service["instruction"] == "unknown")
            else None,
            observation_refs=refs,
            information_refs=info,
        )
        unavailable = tuple(sorted({a.kind for a in facts["failures"]}))
        if "rgb" not in context.task.sensors:
            unavailable = tuple(sorted(set(unavailable) | {"capture_rgb"}))
        if service["status"] in {"unavailable", "timed_out"}:
            unavailable = tuple(sorted(set(unavailable) | {"internet"}))
        self_model = SelfModel(
            as_of_sequence_id=context.history[-1].sequence_id,
            summary=f"Advertised tools remain bounded by public limits. "
            f"{context.remaining_information_requests} external requests remain; "
            f"{context.history[-1].remaining_budgets.voltage_points} voltage points remain. "
            f"Failed physical actions observed: {len(facts['failures'])}. "
            "Completion needs fresh matched V/I, not acknowledgement alone.",
            unavailable_tools=unavailable,
            observation_refs=(context.history[-1].sequence_id,),
            information_refs=info,
        )
        return world, self_model

    def _emit(self, context, facts, operator, rationale, alternatives):
        sequence = context.history[-1].sequence_id
        choice_id = f"decision_{len(self.audit_log) + 1:03d}"
        world, self_model = self._models(context, facts)
        info = tuple(r.request.request_id for r in context.completed_information)
        refs = tuple(
            sorted(
                {
                    sequence,
                    *facts["source"]["observation_refs"],
                    *[p["observation_sequence_id"] for p in facts["probe_points"].values()],
                }
            )
        )
        common = dict(
            choice_id=choice_id,
            context_sequence_id=sequence,
            information_refs=info,
            world_belief=world,
            self_model=self_model,
        )
        fields = {}
        predictions = ()
        expected = "No physical change is inferred merely from an acknowledgement."
        if operator == "ask_context":
            question = self._question(facts, len(info) > 0)
            request = InteractionRequest(
                episode_id=context.task.episode_id,
                request_id=f"service_{len(info) + 1}",
                channel="internet",
                question=question,
                information_gap="Current authoritative service permission for a voltage survey.",
                intended_decision="Choose a permitted survey or retain nominal voltage.",
                parent_request_id=info[-1] if info else None,
            )
            choice = InformationChoice(**common, request=request, observation_refs=refs)
            expected = (
                "A current authoritative hold/survey directive can resolve the permission gap."
            )
        else:
            kind = {
                "observe": "wait",
                "verify": "wait",
                "pad_horizon": "wait",
                "survey": "probe_voltage",
                "apply_target": "set_voltage",
                "finish": "finish",
                "safe_stop": "safe_stop",
            }[operator]
            timeout = 8.0
            if operator == "observe":
                fields["duration_s"] = self.brief.initial_observation_s
            elif operator == "verify":
                fields["duration_s"] = 0.5
            elif operator == "pad_horizon":
                finish_at = (
                    self.brief.horizon_s
                    - self.brief.finish_tail_s
                    - (self.brief.decision_overhead_s)
                )
                duration = finish_at - facts["now_s"] - self.brief.decision_overhead_s
                selected_duration = min(5.0, duration)
                leftover = duration - selected_duration
                if 1e-8 < leftover < 0.3 - 1e-8:
                    selected_duration -= 0.3 - leftover
                fields["duration_s"] = round(selected_duration, 9)
                if fields["duration_s"] < 0.1:
                    raise ValueError("public padding schedule has less than a valid wait")
            elif operator == "survey":
                fields.update(
                    voltages_v=self.brief.survey_candidates_v, dwell_s=self.brief.survey_dwell_s
                )
                expected = (
                    "Settled matched V/I for every permitted candidate can rank measured power."
                )
            elif operator == "apply_target":
                fields["voltage_v"] = facts["target_v"]
                expected = "A fresh measured voltage will match the requested target within 0.02 V."
            elif operator == "finish":
                fields["resolution"] = "unresolved"
                timeout = 2.0
                expected = "Operating point is measured; unique physical cause remains unresolved."
            elif operator == "safe_stop":
                timeout = 2.0
                expected = "Safe-stop feedback is not a successful operating-point verification."
            if kind == "wait":
                timeout = fields["duration_s"]
            elif kind == "set_voltage":
                timeout = 1.5
            elif kind == "probe_voltage":
                timeout = 5.0
            action = ACTION_ADAPTER.validate_python(
                dict(
                    schema_version="1.0",
                    action_id=context.next_action_id,
                    kind=kind,
                    timeout_s=timeout,
                    **fields,
                )
            )
            if kind in ("set_voltage", "wait") and operator != "pad_horizon":
                # Freeze a prediction at an advertised capture-grid time before dispatch.
                # The public brief declares this grid; no private sensor config is read.
                lookahead = 1.0 if kind == "set_voltage" else fields["duration_s"] + 0.3
                period = self.brief.numeric_capture_period_s
                capture = math.ceil((facts["now_s"] + lookahead - 1e-10) / period) * period
                predictions = (
                    Prediction(
                        query_id=choice_id + "_voltage",
                        action_id=action.action_id,
                        channel="voltage_v",
                        horizon_s=round(capture - facts["now_s"], 10),
                        mean=facts["target_v"],
                        sigma=None,
                        interval_90=None,
                        status="predicted",
                    ),
                )
            elif kind == "probe_voltage":
                predictions = (
                    Prediction(
                        query_id=choice_id + "_current_unknown",
                        action_id=action.action_id,
                        channel="current_a",
                        horizon_s=0.5,
                        mean=None,
                        sigma=None,
                        status="not_predictable",
                    ),
                )
            choice = PhysicalChoice(
                **common,
                decision=Decision(
                    schema_version="1.0",
                    action=action,
                    predictions=predictions,
                    hypothesis_probabilities=None,
                    unresolved_hypotheses=context.task.hypothesis_classes,
                    evidence_refs=refs,
                    rationale=rationale,
                ),
            )
            self.actions.append(action)
        validate_choice(choice, context)
        goals = {
            "collect_local_evidence": facts["observed"],
            "resolve_service_context": facts["service"]["instruction"] != "unknown",
            "survey_if_authorized": facts["service"]["instruction"] != "survey"
            or facts["survey_complete"],
            "freshly_verify_target": facts["verification"] is not None,
        }
        self.audit_log.append(
            {
                "policy": self.name,
                "policy_version": POLICY_VERSION,
                "choice_id": choice_id,
                "context_sequence_id": sequence,
                "boundary_time_s": facts["now_s"],
                "simulation_time_s": facts["now_s"],
                "verification_after_s": facts["verification_after_s"],
                "goals_satisfied": goals,
                "alternatives": alternatives,
                "selected_operator": operator,
                "basis": rationale,
                "expected_effect": expected,
                "source_assessment": facts["source"],
                "service_assessment": facts["service"],
                "target_voltage_v": facts["target_v"],
                "verification": facts["verification"],
                "ready_at_s": self.ready_at_s,
                "world_model": world.model_dump(mode="json"),
                "self_model": self_model.model_dump(mode="json"),
            }
        )
        self.audit_log[-1]["assessment"] = self.assessment(context)
        return choice

    def _question(self, facts, followup):
        if followup:
            return "Clarify the conflicting or missing current service instruction: hold or survey?"
        return "What is the current authorized service instruction: hold nominal voltage or survey?"

    def _ready_operator(self, facts):
        if self.ready_at_s is None:
            self.ready_at_s = facts["now_s"]
            self.ready_verification = facts["verification"]
        finish_at = self.brief.horizon_s - self.brief.finish_tail_s - self.brief.decision_overhead_s
        return "pad_horizon" if facts["now_s"] < finish_at - 1e-8 else "finish"

    def assessment(self, context: AgentContext) -> dict:
        """Public-evidence result, not the evaluator's judgement of correctness."""
        terminal = context.history[-1].terminal
        # Do not call _facts on terminal records; retain the latest assessed intent,
        # then refresh only measurement/source/service evidence available now.
        last = self.audit_log[-1] if self.audit_log else {}
        target = last.get("target_voltage_v", self.brief.nominal_voltage_v)
        cutoff = last.get("verification_after_s", 0.0)
        source = source_assessment(context, self.brief)
        service = service_assessment(context, self.brief)
        verification = fresh_verification(context, target, cutoff, self.brief.voltage_tolerance_v)
        terminal_feedback = [
            f
            for o in context.history
            for f in o.feedback
            if f.t_terminal_s is not None and f.t_terminal_s <= cutoff
        ]
        relevant = terminal_feedback[-1] if terminal_feedback else None
        evidence = (
            None
            if verification is None
            else {
                "action_id": None if relevant is None else relevant.action_id,
                "terminal_s": None if relevant is None else relevant.t_terminal_s,
                "freshness_after_s": cutoff,
                "observation_sequence_id": verification["observation_sequence_id"],
                "capture_s": verification["voltage"]["t_capture_s"],
                "available_at_s": verification["available_at_s"],
            }
        )
        return {
            "policy": self.name,
            "policy_version": POLICY_VERSION,
            "source_drop_detected": source["incident_light_reduction"],
            "source_drop_evidence": source["observation_refs"],
            "service_instruction": service["instruction"],
            "context_status": service["status"],
            "operational_verified": verification is not None
            and self.ready_at_s is not None
            and last.get("selected_operator") != "safe_stop",
            "verification_evidence": evidence,
            "causal_resolution": "unresolved",
            "source": source,
            "service": service_assessment(context, self.brief),
            "target_voltage_v": target,
            "verification": fresh_verification(
                context, target, cutoff, self.brief.voltage_tolerance_v
            ),
            "ready_at_s": self.ready_at_s,
            "ready_verification": self.ready_verification,
            "terminal": terminal,
            "terminal_reason": context.history[-1].terminal_reason,
            "declared_failure": last.get("selected_operator") == "safe_stop",
            "unique_physical_cause": "unresolved",
            "no_cross_episode_memory": True,
        }


class FrozenReferencePolicy(_SharedPolicy):
    """Fixed observe/context/survey-or-hold/verify sequence with prudent branches."""

    name = "R_frozen_procedure"

    def act(self, context: AgentContext):
        facts = self._facts(context)
        if facts["failures"] or facts["missing_feedback"]:
            operator, rationale = "safe_stop", "Prior action lacks successful terminal feedback."
        elif self.stage == "observe":
            self.stage = "context"
            operator, rationale = (
                "observe",
                "Fixed procedure: collect the common local evidence window.",
            )
        elif self.stage == "context" and facts["can_query"]:
            operator, rationale = (
                "ask_context",
                "Fixed procedure: request missing service permission.",
            )
        else:
            if self.stage == "context":
                self.stage = "operation"
            if self.stage == "operation" and facts["service"]["instruction"] == "survey":
                self.stage = "survey_returned"
                operator, rationale = (
                    "survey",
                    "Current service permission allows the fixed survey.",
                )
            else:
                if self.stage == "survey_returned":
                    if not facts["survey_complete"]:
                        return self._emit(
                            context,
                            facts,
                            "safe_stop",
                            "Every survey candidate needs settled matched V/I.",
                            [],
                        )
                    self.stage = "verification"
                    if not facts["at_target"]:
                        return self._emit(
                            context,
                            facts,
                            "apply_target",
                            "Apply the candidate with greatest measured V times I.",
                            [],
                        )
                if facts["verification"] is None:
                    if self.stage == "verification_waited":
                        operator, rationale = (
                            "safe_stop",
                            "Fresh matched V/I did not verify the target.",
                        )
                    else:
                        self.stage = "verification_waited"
                        operator, rationale = (
                            "verify",
                            "Collect matched V/I after the last change or reply.",
                        )
                else:
                    operator = self._ready_operator(facts)
                    rationale = "Operating point is verified; " + (
                        "hold it for the shared comparison horizon."
                        if operator == "pad_horizon"
                        else "finish with the physical cause unresolved."
                    )
        return self._emit(
            context,
            facts,
            operator,
            rationale,
            [
                {
                    "operator": operator,
                    "eligible": True,
                    "reason": "Frozen procedural branch.",
                }
            ],
        )


class AdaptiveInvestigationPolicy(_SharedPolicy):
    """Recompute public goal deficits and eligible operators at each boundary.

    Priorities are declared deterministic design choices, not learned value-of-
    information estimates. Equal outcomes to the strong reference are valid.
    """

    name = "A_bounded_goal_planner"

    def _question(self, facts, followup):
        prefix = "Clarify the previous unresolved response. " if followup else ""
        return prefix + (
            f"Local reference evidence is {facts['source']['status']}; this does not establish "
            "a physical cause. What current service instruction governs whether I should "
            "hold 1.8 V or perform the declared bounded voltage survey?"
        )

    def act(self, context: AgentContext):
        facts = self._facts(context)
        failed = bool(facts["failures"] or facts["missing_feedback"])
        survey_needed = facts["service"]["instruction"] == "survey" and not facts["survey_complete"]
        incomplete_probe = facts["probe"] is not None and not facts["survey_complete"]
        exhausted_verification = (
            sum(a.kind == "wait" and getattr(a, "duration_s", 0) == 0.5 for a in self.actions) >= 2
        )
        ready = (
            facts["observed"]
            and not facts["can_query"]
            and not survey_needed
            and facts["verification"] is not None
            and not failed
        )
        candidates = [
            (
                "safe_stop",
                1000,
                failed or incomplete_probe,
                "Failed or unverified execution cannot support a successful conclusion.",
            ),
            (
                "observe",
                100,
                not facts["observed"],
                "The local evidence window is incomplete; another source cannot replace it.",
            ),
            (
                "ask_context",
                90,
                facts["observed"] and facts["can_query"],
                "Local sensors cannot fill the decision-relevant service-permission gap.",
            ),
            (
                "survey",
                80,
                facts["observed"] and survey_needed and facts["probe"] is None,
                "Permission allows experiments; measured candidate power ranking is missing.",
            ),
            (
                "apply_target",
                70,
                facts["survey_complete"] and not facts["at_target"],
                "The greatest measured-power candidate is not the latest measured operating point.",
            ),
            (
                "verify",
                60,
                facts["observed"] and facts["verification"] is None and not exhausted_verification,
                "Fresh matched V/I after the last change must test the expected effect.",
            ),
            (
                "safe_stop",
                50,
                facts["observed"] and facts["verification"] is None and exhausted_verification,
                "Bounded additional observation did not establish successful application.",
            ),
        ]
        if ready:
            operator = self._ready_operator(facts)
            candidates.append(
                (
                    operator,
                    20,
                    True,
                    "No decision-relevant goal deficit remains; preserve the verified point "
                    "on the shared horizon and leave the unique physical cause unresolved.",
                )
            )
        eligible = [item for item in candidates if item[2]]
        if not eligible:
            raise RuntimeError("goal planner found no bounded action")
        operator, _, _, rationale = max(eligible, key=lambda item: item[1])
        alternatives = [
            {"operator": op, "priority": priority, "eligible": allowed, "reason": reason}
            for op, priority, allowed, reason in candidates
        ]
        return self._emit(context, facts, operator, rationale, alternatives)
