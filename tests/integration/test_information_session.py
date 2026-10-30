"""Short real-dynamics interface tests; no renderer or live information provider."""

import json
import math
from dataclasses import asdict
from pathlib import Path

import pytest

from pv_sim.config import Config, load_config
from pv_sim.contracts import Finish, Wait
from pv_sim.env import PVEnv
from pv_sim.information_transport import RecordedExchange, ReplayTransport
from pv_sim.interaction import (
    InformationSession,
    PhysicalDecision,
    load_transcript,
    replay_interactions,
)
from pv_sim.interaction_contracts import InformationReply, InformationSource, InteractionRequest

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    value = 100.0
    timestamp = "2026-10-19T09:00:00+00:00"

    def monotonic(self):
        return self.value

    def utc(self):
        return self.timestamp


def request(identity="q1", *, channel="human", parent=None, episode="interface_test"):
    return InteractionRequest(
        episode_id=episode,
        request_id=identity,
        channel=channel,
        question="What context is available?",
        information_gap="Local context is unknown.",
        intended_decision="Decide whether another measurement would help.",
        parent_request_id=parent,
    )


def reply(text="The observation is uncertain."):
    return InformationReply(
        outcome="available",
        text=text,
        provenance="simulated",
        sources=(InformationSource(title="Authored interface test fixture"),),
    )


@pytest.fixture
def setup():
    env = PVEnv(load_config(ROOT / "configs/pilot.toml"), enable_rendering=False)
    _, initial = env.reset(episode_id="interface_test")
    clock = Clock()
    session = InformationSession(env, initial, clock=clock)
    try:
        yield env, session, clock
    finally:
        env.close()


def test_followup_and_completed_retry_charge_once(setup):
    env, session, clock = setup
    queries = (request(), request("q2", parent="q1", channel="internet"))
    transport = ReplayTransport(tuple(RecordedExchange(request=q, reply=reply()) for q in queries))
    first = session.request(queries[0], transport)
    frozen = (env.tick, asdict(env.ledger), len(session.transcript().events))
    clock.value += 10
    assert session.request(queries[0], transport) == first
    assert (env.tick, asdict(env.ledger), len(session.transcript().events)) == frozen
    assert transport.consumed == 1
    session.request(queries[1], transport)
    assert transport.consumed == 2
    assert env.time_s == pytest.approx(0.42)
    assert env.ledger.decisions == 2
    assert env.ledger.help_requests == 0
    assert session.receipts[-1].remaining_requests == 1


def test_pending_retry_and_conflict_leave_state_unchanged(setup):
    env, session, clock = setup
    first = session.begin(request())
    tick = env.tick
    assert session.begin(request()) == first
    assert env.tick == tick and env.ledger.decisions == 1
    with pytest.raises(ValueError, match="conflict"):
        session.begin(request().model_copy(update={"question": "Different question"}))
    with pytest.raises(RuntimeError, match="pending"):
        session.begin(request("q2"))
    with pytest.raises(ValueError, match="pending"):
        session.cancel("q2")
    assert session.pending == first
    clock.value += 2
    receipt = session.complete("q1", reply())
    assert receipt.elapsed_wall_s == 2
    assert session.complete("q1", reply()) == receipt
    with pytest.raises(ValueError, match="conflict"):
        session.complete("q1", reply("Contradictory new answer"))
    assert not env.information_wait_pending


@pytest.mark.parametrize("channel,deadline", [("human", 300), ("internet", 30)])
def test_deadline_uses_monotonic_time_and_waiting_adds_no_energy(setup, channel, deadline):
    env, session, clock = setup
    pending = session.begin(request(channel=channel))
    before = (
        env.tick,
        asdict(env.ledger),
        env.temperature_c,
        env.backend.snapshot(),
        env.clock._queue.copy(),
    )
    clock.timestamp = "2026-10-19T08:00:00+00:00"  # UTC adjustment does not extend deadline.
    clock.value += deadline - 0.001
    assert session.poll() is None
    with pytest.raises(RuntimeError, match="information"):
        session.step(physical_wait())
    clock.value += 0.001
    receipt = session.complete("q1", reply())
    assert receipt.reply.outcome == "timed_out"
    assert receipt.simulation_time_s == pending.observation.t_deliver_s
    assert (
        env.tick,
        asdict(env.ledger),
        env.temperature_c,
        env.backend.snapshot(),
        env.clock._queue,
    ) == before
    assert session.begin(request(channel=channel)) == receipt


def test_three_request_cap_counts_followup_cancel_and_unavailable(setup):
    env, session, _ = setup
    session.begin(request())
    session.cancel("q1")
    session.begin(request("q2", parent="q1", channel="internet"))
    session.complete("q2", InformationReply(outcome="unavailable", provenance="recorded"))
    session.begin(request("q3", parent="q2"))
    session.complete("q3", reply())
    before = (env.tick, env.ledger.decisions)
    with pytest.raises(ValueError, match="budget"):
        session.begin(request("q4"))
    assert (env.tick, env.ledger.decisions) == before
    assert before[1] == 3
    with pytest.raises(ValueError, match="initial reset"):
        InformationSession(env, session.history[-1])


@pytest.mark.parametrize(
    "parent,episode", [("missing", "interface_test"), (None, "another_episode")]
)
def test_invalid_relationship_does_not_charge(setup, parent, episode):
    env, session, _ = setup
    with pytest.raises(ValueError):
        session.begin(request(parent=parent, episode=episode))
    assert env.ledger.decisions == 0


@pytest.mark.parametrize("payload", ['{"outcome":"available"}', "not JSON", b"\xff", '{"x":NaN}'])
def test_malformed_response_is_explicit_and_releases_pause(setup, payload):
    env, session, _ = setup
    session.begin(request())
    receipt = session.complete("q1", payload)
    assert receipt.reply.outcome == "invalid_response"
    assert not env.information_wait_pending
    session.step(physical_wait())


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -1.0])
def test_bad_clock_cannot_mutate_or_release_pending_state(setup, bad):
    env, session, clock = setup
    session.begin(request())
    clock.value = bad
    with pytest.raises(ValueError, match="clock"):
        session.complete("q1", reply())
    assert env.information_wait_pending
    assert env.ledger.decisions == 1
    clock.value = 100
    assert session.cancel("q1").reply.outcome == "cancelled"


def physical_wait(action_id=1, refs=()):
    return PhysicalDecision(
        action=Wait(
            schema_version="1.0", action_id=action_id, timeout_s=0.2, kind="wait", duration_s=0.1
        ),
        information_refs=refs,
        interpretation="Collect the next sensor sample before deciding.",
    )


def test_linking_and_replay_preserve_whole_trace(setup, tmp_path):
    env, session, clock = setup
    session.begin(request())
    clock.value += 12.5
    session.complete("q1", reply())
    measured = session.step(physical_wait(refs=("q1",)))
    assert measured.sequence_id > session.receipts[0].observation_sequence_id
    session.begin(request("q2", parent="q1", channel="internet"))
    clock.value += 30
    session.poll()
    session.begin(request("q3", parent="q2"))
    clock.value += 1
    session.cancel("q3")
    final = session.step(
        PhysicalDecision(
            action=Finish(
                schema_version="1.0",
                kind="finish",
                action_id=2,
                timeout_s=2.0,
                resolution="unresolved",
            ),
            information_refs=("q2", "q3"),
            interpretation="Retain uncertainty; complete measured verification.",
        )
    )
    assert final.terminal
    path = tmp_path / "interaction.json"
    session.save(path)
    with pytest.raises(FileExistsError):
        session.save(path)
    trace = load_transcript(path)
    original = path.read_text()
    path.write_text(
        original.replace(
            '"mode": "recorded_interface"', '"mode": "other", "mode": "recorded_interface"'
        )
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_transcript(path)
    path.write_text(original)
    repeat = PVEnv(env.config, enable_rendering=False)
    try:
        _, initial = repeat.reset(episode_id="interface_test")
        result = replay_interactions(repeat, initial, trace)
        assert result["events"] == 8
        assert result["restored_original_wait_s"] == 43.5
        assert result["live_calls"] == 0
        assert asdict(repeat.ledger) == asdict(env.ledger)
        assert repeat.metrics() == env.metrics()
    finally:
        repeat.close()
    contents = json.loads(path.read_text())
    contents["transcript"]["events"][1]["receipt"]["reply"]["text"] = "tampered"
    path.write_text(json.dumps(contents))
    with pytest.raises(ValueError, match="checksum"):
        load_transcript(path)


def test_replay_rejects_missing_events_and_pending_tail(setup):
    env, session, _ = setup
    session.begin(request())
    incomplete = session.transcript()
    session.complete("q1", reply())
    missing = session.transcript().model_copy(update={"events": session.transcript().events[1:]})
    for trace in (incomplete, missing):
        repeat = PVEnv(env.config, enable_rendering=False)
        try:
            _, initial = repeat.reset(episode_id="interface_test")
            with pytest.raises(ValueError, match="incomplete|pending"):
                replay_interactions(repeat, initial, trace)
        finally:
            repeat.close()


def test_reject_legacy_recorder_and_out_of_band_activity(setup):
    env, session, _ = setup
    env.recorder = object()
    with pytest.raises(ValueError, match="Recorder"):
        InformationSession(env, session.initial)
    env.recorder = None
    env.step(physical_wait().action)
    with pytest.raises(RuntimeError, match="outside"):
        session.begin(request())


def test_transport_failure_is_unavailable_and_does_not_expose_exception(setup):
    env, session, _ = setup

    class Broken:
        def request(self, request):
            raise RuntimeError("private secret path")

    receipt = session.request(request(), Broken())
    assert receipt.reply.outcome == "unavailable"
    assert "private secret" not in receipt.model_dump_json()
    assert not env.information_wait_pending


def test_pending_request_retry_never_dispatches_again(setup):
    env, session, _ = setup
    pending = session.begin(request())

    class MustNotCall:
        def request(self, request):
            pytest.fail("pending request retry dispatched another transport call")

    assert session.request(request(), MustNotCall()) == pending
    assert env.ledger.decisions == 1
    session.cancel("q1")


def test_protection_during_overhead_auto_cancels_and_replays():
    raw = json.loads(load_config(ROOT / "configs/pilot.toml").canonical_json())
    raw["thermal"]["trip_temperature_c"] = 25.2
    config = Config.model_validate_json(json.dumps(raw))
    env = PVEnv(config, enable_rendering=False)
    repeat = PVEnv(config, enable_rendering=False)
    try:
        _, initial = env.reset(episode_id="interface_test")
        session = InformationSession(env, initial)
        result = session.begin(request())
        assert result.reply.outcome == "cancelled"
        assert env.terminal_reason and not env.information_wait_pending
        _, repeated_initial = repeat.reset(episode_id="interface_test")
        replayed = replay_interactions(repeat, repeated_initial, session.transcript())
        assert replayed["status"] == "passed" and replayed["events"] == 2
    finally:
        env.close()
        repeat.close()


@pytest.mark.parametrize(
    "increments",
    [
        (0.3774104787808403, 0.04545228559892646, 0.9184726232383812),
        (math.nextafter(30.0, 0.0), 0.04545228559892646, math.nextafter(30.0, 0.0)),
    ],
)
def test_fractional_waits_replay_exactly_without_deadline_rounding(setup, increments):
    env, session, clock = setup
    clock.value = 0.00014224131124069184
    for number, duration in enumerate(increments):
        session.begin(request(f"q{number}", channel="internet"))
        clock.value += duration
        session.complete(f"q{number}", reply())
    repeat = PVEnv(env.config, enable_rendering=False)
    try:
        _, initial = repeat.reset(episode_id="interface_test")
        assert replay_interactions(repeat, initial, session.transcript())["status"] == "passed"
    finally:
        repeat.close()


def test_deeply_nested_response_is_invalid_and_releases_pause(setup):
    env, session, _ = setup
    session.begin(request())
    wire = '{"unexpected":' + "[" * 1100 + "0" + "]" * 1100 + "}"
    result = session.complete("q1", wire)
    assert result.reply.outcome == "invalid_response"
    assert not env.information_wait_pending
    assert env.ledger.decisions == 1
    with pytest.raises(ValueError, match="nesting"):
        InteractionRequest.from_json(wire)
