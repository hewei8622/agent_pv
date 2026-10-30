"""Paired real-dynamics tests of decision evidence, authority and bounded recovery."""

import json
from pathlib import Path

import pytest

from pv_sim.comparison_policies import (
    AdaptiveInvestigationPolicy,
    FrozenReferencePolicy,
    fresh_verification,
)
from pv_sim.comparison_sources import ControlledServiceSource, PublicBrief, ServiceCorpus
from pv_sim.config import Config, load_config
from pv_sim.contracts import Observation, ScalarSample
from pv_sim.env import PVEnv
from pv_sim.investigation import AgentContext, InformationChoice, InvestigationSession

ROOT = Path(__file__).resolve().parents[2]
POLICIES = (FrozenReferencePolicy, AdaptiveInvestigationPolicy)


def config(*, step=False, dropped=False):
    raw = load_config(ROOT / "configs/pilot.toml").model_dump(mode="json")
    raw["simulation"]["horizon_s"] = 16.0
    raw["budgets"]["time_s"] = 16.0
    if step:
        raw["source_schedule"] = [{"time_s": 2.0, "dni_w_m2": 400.0}]
    if dropped:
        raw["pilot"]["actuator_failures"] = True
        raw["m2"] = {"actuation": {"load_drop_commands": [1]}}
    return Config.model_validate_json(json.dumps(raw))


def run(
    policy_cls,
    *,
    known=None,
    instruction="hold",
    behavior="authoritative",
    step=False,
    dropped=False,
    candidates=(0.8, 1.8, 3.0),
):
    env = PVEnv(config(step=step, dropped=dropped), enable_rendering=False)
    try:
        _, initial = env.reset(20261019, episode_id="public_asset")
        session = InvestigationSession(env, initial)
        policy = policy_cls(PublicBrief(known_instruction=known, survey_candidates_v=candidates))
        source = ControlledServiceSource(ServiceCorpus(instruction=instruction, behavior=behavior))
        for _ in range(20):
            context = session.context()
            if context.history[-1].terminal:
                break
            choice = policy.act(context)
            # Audit claims are computed at this pre-dispatch boundary.
            assert policy.audit_log[-1]["simulation_time_s"] == env.time_s
            assessment = policy.audit_log[-1]["assessment"]
            if assessment["operational_verified"]:
                assert assessment["verification_evidence"]["available_at_s"] <= env.time_s
            session.submit(
                choice, transport=source if isinstance(choice, InformationChoice) else None
            )
        assert env.backend._renderer is None
        return policy, session.context(), session.transcript(), env.metrics()
    finally:
        env.close()


@pytest.mark.parametrize("policy_cls", POLICIES)
@pytest.mark.parametrize(
    "known,instruction,ready,queries,probes",
    [
        ("hold", "hold", 3.32, 0, 0),
        (None, "hold", 3.52, 1, 0),
        (None, "survey", 6.92, 1, 1),
    ],
)
def test_primary_cases_reach_same_horizon_without_unnecessary_interventions(
    policy_cls,
    known,
    instruction,
    ready,
    queries,
    probes,
):
    policy, context, _, metrics = run(policy_cls, known=known, instruction=instruction)
    result = policy.assessment(context)
    assert context.history[-1].t_deliver_s == 16.0
    assert metrics["verification_tail_complete"]
    assert result["ready_at_s"] == pytest.approx(ready)
    assert result["operational_verified"] and result["causal_resolution"] == "unresolved"
    assert not result["source_drop_detected"]
    assert result["service_instruction"] == instruction
    assert len(context.completed_information) == queries
    assert sum(a.kind == "probe_voltage" for a in policy.actions) == probes
    assert not any(a.kind in ("capture_rgb", "move_camera", "set_voltage") for a in policy.actions)
    assert (
        result["ready_verification"]["voltage"]["t_capture_s"]
        > (result["ready_verification"]["after_s"])
    )


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_reference_drop_is_detected_when_returned_without_hidden_cause_claim(policy_cls):
    policy, context, _, _ = run(policy_cls, known="hold", step=True)
    claim = policy.audit_log[1]["source_assessment"]
    assert claim["incident_light_reduction"]
    assert claim["reference_drop_w_m2"] == 400.0
    assert claim["first_detected_capture_s"] == 2.0
    assert claim["first_detected_available_s"] == 2.62
    assert claim["unique_cause"] == "unresolved"
    assert policy.assessment(context)["source_drop_detected"]
    assert not context.completed_information


@pytest.mark.parametrize("policy_cls", POLICIES)
@pytest.mark.parametrize(
    "behavior,requests", [("irrelevant", 2), ("conflicting", 2), ("unavailable", 1)]
)
def test_unresolved_context_never_grants_survey_permission(policy_cls, behavior, requests):
    policy, context, _, _ = run(policy_cls, behavior=behavior, instruction="survey")
    result = policy.assessment(context)
    assert result["service_instruction"] == "unknown"
    assert result["operational_verified"]
    assert len(context.completed_information) == requests
    assert all(a.kind not in ("probe_voltage", "set_voltage") for a in policy.actions)


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_dropped_probe_is_not_a_verified_success(policy_cls):
    policy, context, _, _ = run(policy_cls, instruction="survey", dropped=True)
    assert context.history[-1].terminal_reason == "safe_stop"
    assert policy.assessment(context)["declared_failure"]
    assert not policy.assessment(context)["operational_verified"]
    assert policy.ready_at_s is None
    assert "probe_voltage" in context.self_model.unavailable_tools


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_changed_candidate_point_is_applied_predicted_and_freshly_verified(policy_cls):
    policy, context, transcript, _ = run(
        policy_cls,
        instruction="survey",
        candidates=(0.8, 1.0, 1.2),
    )
    sets = [
        e
        for e in transcript.events
        if e.kind == "committed"
        and e.choice.kind == "physical"
        and e.choice.decision.action.kind == "set_voltage"
    ]
    assert len(sets) == 1
    event = sets[0]
    assert event.choice.decision.predictions[0].mean == 1.2
    assert event.simulation_time_s < policy.ready_at_s
    assert policy.assessment(context)["target_voltage_v"] == 1.2
    assert policy.assessment(context)["operational_verified"]
    pair = policy.ready_verification
    assert pair["voltage"]["t_capture_s"] > pair["after_s"]
    assert pair["voltage"]["t_capture_s"] == pair["current"]["t_capture_s"]
    assert abs(pair["voltage"]["value"] - 1.2) <= 0.02


def test_goal_planner_records_candidates_and_revises_context_belief():
    policy, context, _, _ = run(AdaptiveInvestigationPolicy, instruction="survey")
    before = next(r for r in policy.audit_log if r["selected_operator"] == "ask_context")
    after = next(r for r in policy.audit_log if r["selected_operator"] == "survey")
    assert before["service_assessment"]["instruction"] == "unknown"
    assert after["service_assessment"]["instruction"] == "survey"
    assert not before["goals_satisfied"]["resolve_service_context"]
    assert after["goals_satisfied"]["resolve_service_context"]
    assert any(not option["eligible"] for option in after["alternatives"])
    assert before["world_model"]["information_gap"] is not None
    assert after["world_model"]["information_gap"] is None
    question = context.completed_information[0].request.question
    assert before["source_assessment"]["status"] in question
    assert "does not establish a physical cause" in question


def test_newest_contradictory_pair_invalidates_old_matching_verification():
    env = PVEnv(config(), enable_rendering=False)
    try:
        task, initial = env.reset(1, episode_id="boundary")
        samples = tuple(
            ScalarSample(
                channel=channel,
                value=value,
                sigma=None,
                sensor_id="fixture",
                t_capture_s=capture,
                t_deliver_s=capture,
                validity="valid",
            )
            for capture, channel, value in (
                (0.1, "voltage_v", 1.8),
                (0.1, "current_a", 0.5),
                (0.2, "voltage_v", 0.8),
                (0.2, "current_a", 0.7),
            )
        )
        later = Observation(
            schema_version="1.0",
            episode_id=task.episode_id,
            sequence_id=1,
            t_deliver_s=0.2,
            scalars=samples,
            encoders=(),
            rgb=(),
            feedback=(),
            remaining_budgets=initial.remaining_budgets,
            terminal=False,
            terminal_reason=None,
        )
        context = AgentContext(task=task, history=(initial, later))
        assert fresh_verification(context, 1.8, 0.0) is None
        assert fresh_verification(context, 0.8, 0.0)["voltage"]["t_capture_s"] == 0.2
        assert fresh_verification(context, 0.8, 0.2) is None
    finally:
        env.close()
