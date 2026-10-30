"""Short real-dynamics shared-loop tests; no GL, model or live channel calls."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from pv_sim.config import load_config
from pv_sim.contracts import Decision, Prediction, SetVoltage, Wait
from pv_sim.env import PVEnv
from pv_sim.interaction import InformationReceipt, PendingInformation
from pv_sim.interaction_contracts import InformationReply, InformationSource, InteractionRequest
from pv_sim.investigation import (
    ChoiceOutcome,
    CommittedChoice,
    InformationChoice,
    InvestigationSession,
    PhysicalChoice,
    WorldBelief,
    load_investigation,
    replay_investigation,
)

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    value = 100.0

    def monotonic(self):
        return self.value

    def utc(self):
        return "2026-10-19T09:00:00+00:00"


@pytest.fixture
def setup():
    env = PVEnv(load_config(ROOT / "configs/pilot.toml"), enable_rendering=False)
    _, initial = env.reset(episode_id="investigation_test")
    clock = Clock()
    session = InvestigationSession(env, initial, clock=clock)
    yield env, session, clock
    assert env.backend._renderer is None
    env.close()


def wait_choice(session, identity="wait1"):
    return wait_from_context(session.context(), identity)


def wait_from_context(context, identity="wait1"):
    return PhysicalChoice(
        choice_id=identity,
        context_sequence_id=context.history[-1].sequence_id,
        decision=Decision(
            schema_version="1.0",
            action=Wait(
                schema_version="1.0",
                action_id=context.next_action_id,
                kind="wait",
                timeout_s=2.0,
                duration_s=0.1,
            ),
            predictions=(),
            hypothesis_probabilities=None,
            unresolved_hypotheses=(),
            evidence_refs=(context.history[-1].sequence_id,),
            rationale="Obtain another public measurement before choosing a load.",
        ),
    )


def ask_choice(session, identity="ask1", request_id="q1"):
    context = session.context()
    return InformationChoice(
        choice_id=identity,
        context_sequence_id=context.history[-1].sequence_id,
        observation_refs=(context.history[-1].sequence_id,),
        request=InteractionRequest(
            episode_id=context.task.episode_id,
            request_id=request_id,
            channel="human",
            question="What maintenance context is available?",
            information_gap="The local maintenance context is unknown.",
            intended_decision="Decide whether that context justifies another investigation.",
        ),
    )


def answer():
    return InformationReply(
        outcome="available",
        text="No reliable observation of maintenance is available.",
        provenance="simulated",
        sources=(InformationSource(title="Authored fixture"),),
    )


def test_full_prediction_is_precommitted_before_voltage_changes(setup, monkeypatch):
    env, session, _ = setup
    context = session.context()
    action = SetVoltage(
        schema_version="1.0", action_id=1, kind="set_voltage", timeout_s=2.0, voltage_v=2.0
    )
    prediction = Prediction(
        query_id="v1",
        action_id=1,
        channel="voltage_v",
        horizon_s=1.0,
        mean=2.0,
        sigma=0.02,
        interval_90=(1.95, 2.05),
        status="predicted",
    )
    choice = PhysicalChoice(
        choice_id="set1",
        context_sequence_id=0,
        decision=Decision(
            schema_version="1.0",
            action=action,
            predictions=(prediction,),
            hypothesis_probabilities=None,
            unresolved_hypotheses=(),
            evidence_refs=(0,),
            rationale="Check measured response to the requested load.",
        ),
    )
    original_step = env.step
    before_voltage = env.applied_voltage_v

    def inspected_step(command):
        trace = session.transcript()
        assert isinstance(trace.events[-1], CommittedChoice)
        assert trace.events[-1].choice.decision.predictions == (prediction,)
        assert trace.events[-1].simulation_time_s == context.history[-1].t_deliver_s
        assert env.applied_voltage_v == before_voltage
        return original_step(command)

    monkeypatch.setattr(env, "step", inspected_step)
    observation = session.submit(choice)
    assert observation.feedback[-1].code == "completed"
    measurements = observation.feedback[-1].measured_confirmation
    voltage = [m.sample for m in measurements if getattr(m.sample, "channel", None) == "voltage_v"]
    assert voltage and voltage[-1].t_capture_s > context.history[-1].t_deliver_s
    assert 1.95 <= voltage[-1].value <= 2.05
    assert session.transcript().events[0].choice.decision == choice.decision


def test_wait_question_reply_next_decision_linked_save_and_replay(setup, tmp_path):
    env, session, clock = setup
    session.submit(wait_choice(session))
    pending = session.submit(ask_choice(session))
    assert isinstance(pending, PendingInformation)
    frozen = (env.tick, asdict(env.ledger), env.backend.snapshot(), env.clock._queue.copy())
    clock.value += 12.0
    receipt = session.complete("q1", answer())
    assert (env.tick, asdict(env.ledger), env.backend.snapshot(), env.clock._queue) == frozen
    assert receipt.elapsed_wall_s == 12.0

    class PublicPolicy:
        def act(self, context):
            assert context.completed_information == (receipt,)
            assert context.remaining_information_requests == 2
            assert context.history[-1].sequence_id == receipt.observation_sequence_id
            base = wait_from_context(context, "wait2")
            return base.model_copy(
                update={
                    "information_refs": ("q1",),
                    "world_belief": WorldBelief(
                        as_of_sequence_id=context.history[-1].sequence_id,
                        summary="The reply provides no reliable maintenance observation.",
                        information_refs=("q1",),
                    ),
                }
            )

    selected = session.choose(PublicPolicy())
    session.submit(selected)
    assert session.context().world_belief == selected.world_belief
    destination = tmp_path / "investigation.json"
    session.save(destination)
    trace = load_investigation(destination)
    assert trace == session.transcript()
    with pytest.raises(FileExistsError):
        session.save(destination)
    replay_env = PVEnv(load_config(ROOT / "configs/pilot.toml"), enable_rendering=False)
    try:
        _, initial = replay_env.reset(episode_id="investigation_test")
        result = replay_investigation(replay_env, initial, trace)
        assert result["status"] == "passed" and result["committed_choices"] == 3
        assert result["live_calls"] == 0 and result["restored_original_wait_s"] == 12.0
        assert replay_env.time_s == env.time_s
    finally:
        replay_env.close()


def test_identical_physical_and_information_retries_never_duplicate_effects(setup):
    env, session, _ = setup
    physical = wait_choice(session)
    observation = session.submit(physical)
    frozen = (env.tick, asdict(env.ledger), session.transcript())
    assert session.submit(physical) == observation
    assert (env.tick, asdict(env.ledger), session.transcript()) == frozen
    question = ask_choice(session)

    class Transport:
        calls = 0

        def request(self, request):
            self.calls += 1
            return answer()

    transport = Transport()
    receipt = session.submit(question, transport=transport)
    frozen = (env.tick, asdict(env.ledger), session.transcript())
    assert session.submit(question, transport=transport) == receipt
    assert (env.tick, asdict(env.ledger), session.transcript()) == frozen
    assert transport.calls == 1
    with pytest.raises(ValueError, match="conflict"):
        session.submit(question.model_copy(update={"observation_refs": ()}))


def test_pending_retry_timeout_and_no_decision_during_wait(setup):
    env, session, clock = setup
    question = ask_choice(session)
    pending = session.submit(question)
    before = (env.tick, asdict(env.ledger), session.transcript())
    assert session.submit(question) == pending
    assert (env.tick, asdict(env.ledger), session.transcript()) == before
    with pytest.raises(RuntimeError, match="pending"):
        session.context()
    clock.value += 300.0
    receipt = session.poll()
    assert isinstance(receipt, InformationReceipt) and receipt.reply.outcome == "timed_out"
    assert session.context().remaining_information_requests == 2
    assert session.submit(question) == receipt
    assert session.transcript().events[-1].status == "information_completed"


def test_dispatch_failure_is_retained_and_coordinator_latches_closed(setup, monkeypatch):
    env, session, _ = setup
    choice = wait_choice(session)

    def broken_step(action):
        raise RuntimeError("PRIVATE_CANARY_DETAIL")

    monkeypatch.setattr(env, "step", broken_step)
    with pytest.raises(RuntimeError, match="PRIVATE_CANARY_DETAIL"):
        session.submit(choice)
    trace = session.transcript()
    assert isinstance(trace.events[-1], ChoiceOutcome)
    assert trace.events[-1].status == "dispatch_failed"
    assert "PRIVATE_CANARY_DETAIL" not in trace.model_dump_json()
    with pytest.raises(RuntimeError, match="closed"):
        session.submit(choice)
    with pytest.raises(ValueError, match="failed dispatch"):
        replay_investigation(env, session._session.initial, trace)


def test_tampered_pre_action_context_and_checksum_rejected(setup, tmp_path):
    _, session, _ = setup
    session.submit(wait_choice(session))
    path = tmp_path / "trace.json"
    session.save(path)
    raw = json.loads(path.read_text())
    raw["transcript"]["events"][0]["choice"]["decision"]["rationale"] = "Altered later"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="checksum"):
        load_investigation(path)
    wire = session.transcript().model_dump(mode="json")
    wire["events"][0]["choice"]["context_sequence_id"] = 1
    with pytest.raises(ValueError, match="current observation"):
        type(session.transcript()).model_validate_json(json.dumps(wire))


def test_failed_information_dispatch_blocks_every_continuation_and_remains_saveable(
    setup, tmp_path
):
    env, session, clock = setup

    class ReversingClockTransport:
        def request(self, request):
            clock.value -= 1.0
            return InformationReply(outcome="unavailable", provenance="simulated")

    choice = ask_choice(session)
    with pytest.raises(ValueError, match="nondecreasing"):
        session.submit(choice, transport=ReversingClockTransport())
    assert session._session.pending is not None
    trace = session.transcript()
    assert trace.events[-1].status == "dispatch_failed"
    before = (env.tick, asdict(env.ledger), env.clock._queue.copy(), trace)
    # Restoring a valid wall clock must not reopen the failed coordinator or
    # turn the retained failed dispatch into a later successful outcome.
    clock.value += 302.0
    for continuation in (
        lambda: session.complete("q1", answer()),
        session.poll,
        lambda: session.cancel("q1"),
    ):
        with pytest.raises(RuntimeError, match="closed"):
            continuation()
        assert (env.tick, asdict(env.ledger), env.clock._queue, session.transcript()) == before
        assert session._session.pending is not None
    destination = tmp_path / "failed-investigation.json"
    session.save(destination)
    assert load_investigation(destination) == trace


@pytest.mark.parametrize("change", [{"episode_id": "foreign"}, {"sequence_id": 99}])
def test_final_physical_outcome_is_validated_without_a_later_commit(setup, change):
    _, session, _ = setup
    session.submit(wait_choice(session))
    trace = session.transcript()
    wire = trace.model_dump(mode="json")
    wire["interaction"]["events"][-1]["observation"].update(change)
    with pytest.raises(ValueError):
        type(trace).model_validate_json(json.dumps(wire))


@pytest.mark.parametrize("change", [{"simulation_time_s": 90.0}, {"remaining_requests": 1}])
def test_final_receipt_is_validated_without_a_later_commit(setup, change):
    _, session, _ = setup
    session.submit(ask_choice(session))
    session.complete("q1", answer())
    trace = session.transcript()
    wire = trace.model_dump(mode="json")
    wire["interaction"]["events"][-1]["receipt"].update(change)
    with pytest.raises(ValueError):
        type(trace).model_validate_json(json.dumps(wire))


@pytest.mark.parametrize("pending_outcome", [True, False])
def test_incomplete_replay_is_rejected_before_any_simulator_effect(setup, pending_outcome):
    _, session, _ = setup
    session.submit(ask_choice(session))
    trace = session.transcript()
    if not pending_outcome:
        wire = trace.model_dump(mode="json")
        wire["events"] = wire["events"][:1]
        wire["interaction"]["events"] = []
        trace = type(trace).model_validate_json(json.dumps(wire))
    replay_env = PVEnv(load_config(ROOT / "configs/pilot.toml"), enable_rendering=False)
    try:
        _, initial = replay_env.reset(episode_id="investigation_test")
        before = (
            replay_env.tick,
            asdict(replay_env.ledger),
            replay_env.clock._queue.copy(),
            replay_env.backend.snapshot(),
        )
        with pytest.raises(ValueError, match="incomplete investigation choice"):
            replay_investigation(replay_env, initial, trace)
        assert (
            replay_env.tick,
            asdict(replay_env.ledger),
            replay_env.clock._queue,
            replay_env.backend.snapshot(),
        ) == before
        assert not replay_env.information_wait_pending
    finally:
        replay_env.close()


def test_receipt_cannot_claim_an_earlier_valid_observation_boundary(setup):
    _, session, _ = setup
    initial = session.context().history[0]
    session.submit(ask_choice(session))
    session.complete("q1", answer())
    trace = session.transcript()
    wire = trace.model_dump(mode="json")
    receipt = wire["interaction"]["events"][-1]["receipt"]
    # Both fields are internally consistent with a real earlier observation,
    # but neither identifies the boundary at which this request was paused.
    receipt["observation_sequence_id"] = initial.sequence_id
    receipt["simulation_time_s"] = initial.t_deliver_s
    with pytest.raises(ValueError, match="original pending boundary"):
        type(trace).model_validate_json(json.dumps(wire))
