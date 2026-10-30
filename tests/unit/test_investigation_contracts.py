"""Public context availability and complete, versioned decision serialization."""

import json

import pytest
from pydantic import ValidationError

from pv_sim.contracts import Decision, Observation
from pv_sim.interaction import InformationReceipt
from pv_sim.interaction_contracts import InformationReply, InteractionRequest
from pv_sim.investigation import (
    AgentContext,
    InformationChoice,
    PhysicalChoice,
    SelfModel,
    WorldBelief,
    validate_choice,
)


def context(task, observation):
    return AgentContext(
        task=task, history=(Observation.model_validate_json(json.dumps(observation)),)
    )


def physical(decision, **updates):
    return PhysicalChoice(
        choice_id="step_1",
        context_sequence_id=0,
        decision=Decision.model_validate_json(json.dumps(decision)),
        **updates,
    )


def question(task):
    return InteractionRequest(
        episode_id=task.episode_id,
        request_id="q1",
        channel="human",
        question="What public context is available?",
        information_gap="Context is unknown.",
        intended_decision="Decide whether another observation is needed.",
    )


def receipt(task):
    return InformationReceipt(
        request=question(task),
        reply=InformationReply(outcome="unavailable", provenance="simulated"),
        started_utc="2026-10-19T09:00:00+00:00",
        received_utc="2026-10-19T09:00:01+00:00",
        started_monotonic_s=1.0,
        received_monotonic_s=2.0,
        elapsed_wall_s=1.0,
        simulation_time_s=0.02,
        observation_sequence_id=0,
        remaining_requests=2,
    )


def test_full_prediction_and_model_records_round_trip(task, observation, decision):
    decision["evidence_refs"] = [0]
    decision["predictions"] = [
        {
            "query_id": "v_expected",
            "action_id": 1,
            "channel": "voltage_v",
            "horizon_s": 1.0,
            "mean": 1.8,
            "sigma": 0.03,
            "interval_90": [1.75, 1.85],
            "status": "predicted",
            "missingness_probability": 0.01,
        }
    ]
    value = physical(
        decision,
        world_belief=WorldBelief(
            as_of_sequence_id=0,
            summary="Only the initial voltage is available.",
            alternatives=("The source may change later.",),
            observation_refs=(0,),
        ),
        self_model=SelfModel(
            as_of_sequence_id=0,
            summary="Advertised tools have not yet been tested.",
            unavailable_tools=("request_help",),
            observation_refs=(0,),
        ),
    )
    validate_choice(value, context(task, observation))
    restored = PhysicalChoice.model_validate_json(value.model_dump_json())
    assert restored == value
    assert restored.decision.predictions[0].interval_90 == (1.75, 1.85)
    assert restored.decision.evidence_refs == (0,)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "investigation/2.0"},
        {"private_scenario": {"seed": 123}},
        {"adaptation": "cross_episode_learning"},
        {"remaining_information_requests": 2},
        {"next_action_id": True},
    ],
)
def test_context_rejects_unknown_private_or_inconsistent_fields(task, observation, change):
    wire = context(task, observation).model_dump(mode="json") | change
    with pytest.raises(ValidationError):
        AgentContext.model_validate_json(json.dumps(wire))


@pytest.mark.parametrize(
    "change",
    [
        {"sequence_id": 2},
        {"episode_id": "another"},
        {"t_deliver_s": 0.01},
    ],
)
def test_context_rejects_foreign_missing_or_future_history(task, observation, change):
    observation.update(change)
    with pytest.raises(ValidationError):
        context(task, observation)


@pytest.mark.parametrize(
    "change",
    [
        {"observation_sequence_id": 1},
        {"simulation_time_s": 0.03},
        {"remaining_requests": 1},
    ],
)
def test_future_and_inconsistent_receipts_rejected(task, observation, change):
    wire = context(task, observation).model_dump(mode="json")
    wire["completed_information"] = [receipt(task).model_dump(mode="json") | change]
    wire["remaining_information_requests"] = 2
    with pytest.raises(ValidationError):
        AgentContext.model_validate_json(json.dumps(wire))


def test_completed_receipt_is_supplied_with_remaining_budget(task, observation):
    public = context(task, observation).model_dump(mode="json")
    public.update(
        completed_information=[receipt(task).model_dump(mode="json")],
        remaining_information_requests=2,
    )
    restored = AgentContext.model_validate_json(json.dumps(public))
    assert restored.completed_information[0].reply.outcome == "unavailable"
    assert restored.remaining_information_requests == 2


@pytest.mark.parametrize("kind", ["observation", "information", "state", "boundary", "action_id"])
def test_choice_rejects_future_refs_and_invalid_boundary(task, observation, decision, kind):
    updates = {}
    if kind == "observation":
        decision["evidence_refs"] = [1]
    elif kind == "information":
        updates["information_refs"] = ("future_q",)
    elif kind == "state":
        updates["world_belief"] = WorldBelief(as_of_sequence_id=1, summary="Future claim")
    elif kind == "action_id":
        decision["action"]["action_id"] = 2
    value = physical(decision, **updates)
    if kind == "boundary":
        value = value.model_copy(update={"context_sequence_id": 1})
    with pytest.raises(ValueError):
        validate_choice(value, context(task, observation))


def test_information_question_requires_completed_parent(task, observation):
    request = question(task).model_copy(update={"parent_request_id": "future_parent"})
    value = InformationChoice(choice_id="ask1", context_sequence_id=0, request=request)
    with pytest.raises(ValueError, match="parent"):
        validate_choice(value, context(task, observation))


def test_no_memory_extension_silently_reinterprets_legacy_adaptation(task, observation):
    task = task.model_copy(update={"allowed_adaptation": "learn from previous episodes"})
    with pytest.raises(ValidationError, match="cross-episode"):
        context(task, observation)
