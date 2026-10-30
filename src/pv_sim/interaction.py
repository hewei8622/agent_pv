"""Offline information sessions, separate from the legacy physical action wire.

This is trusted local orchestration, not a sandbox for untrusted Python. External
text is never interpreted as an action. A caller must submit a separate typed
physical decision, which still passes through PVEnv.step and its existing gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from pv_sim.contracts import Action, Identifier, Number, Observation, PublicTask, Record, Text
from pv_sim.interaction_contracts import InformationReply, InteractionLimits, InteractionRequest


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("receipt time must be UTC")
    return value


class PendingInformation(Record):
    schema_version: Literal["interaction/1.0"] = "interaction/1.0"
    request: InteractionRequest
    observation: Observation
    started_utc: str
    started_monotonic_s: Annotated[Number, Field(ge=0)]
    deadline_s: Annotated[Number, Field(gt=0)]

    _validate_utc = field_validator("started_utc")(_utc)


class InformationReceipt(Record):
    schema_version: Literal["interaction/1.0"] = "interaction/1.0"
    request: InteractionRequest
    reply: InformationReply
    started_utc: str
    received_utc: str
    started_monotonic_s: Annotated[Number, Field(ge=0)]
    received_monotonic_s: Annotated[Number, Field(ge=0)]
    elapsed_wall_s: Annotated[Number, Field(ge=0)]
    simulation_time_s: Annotated[Number, Field(ge=0)]
    observation_sequence_id: Annotated[int, Field(ge=0)]
    remaining_requests: Annotated[int, Field(ge=0, le=3)]

    _validate_utc = field_validator("started_utc", "received_utc")(_utc)

    @model_validator(mode="after")
    def elapsed_matches_stamps(self):
        if self.received_monotonic_s - self.started_monotonic_s != self.elapsed_wall_s:
            raise ValueError("elapsed wall time differs from original monotonic stamps")
        return self


class PhysicalDecision(Record):
    """Evidence references are attribution, not a claim of verified causation."""

    schema_version: Literal["interaction/1.0"] = "interaction/1.0"
    action: Action
    information_refs: Annotated[tuple[Identifier, ...], Field(max_length=3)] = ()
    interpretation: Text


class StartedEvent(Record):
    kind: Literal["information_started"] = "information_started"
    pending: PendingInformation


class CompletedEvent(Record):
    kind: Literal["information_completed"] = "information_completed"
    receipt: InformationReceipt


class PhysicalEvent(Record):
    kind: Literal["physical_decision"] = "physical_decision"
    decision: PhysicalDecision
    observation: Observation


InteractionEvent = Annotated[
    StartedEvent | CompletedEvent | PhysicalEvent, Field(discriminator="kind")
]


class InteractionTranscript(Record):
    schema_version: Literal["interaction/1.0"] = "interaction/1.0"
    mode: Literal["recorded_interface", "recorded_replay"]
    limits: InteractionLimits
    task: PublicTask
    initial_observation: Observation
    events: tuple[InteractionEvent, ...]


class WallClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class InformationSession:
    """One episode, one owner, at most one pending external request.

    The nonblocking begin/complete/poll/cancel API freezes simulator time, not the
    Python process. Deadlines are checked on API calls; no background timer or live
    transport is supplied in Step 2. Call poll while awaiting an asynchronous reply.
    """

    def __init__(self, env, initial: Observation, *, clock=None, mode="recorded_interface",
                 investigation_recording=False):
        if type(investigation_recording) is not bool:
            raise ValueError("investigation recording must be explicitly boolean")
        if investigation_recording:
            from pv_sim.recorder import Recorder

            if (not isinstance(env.recorder, Recorder)
                    or env.recorder._manifest.get("metadata", {}).get("execution_protocol")
                    != "investigation/1.0"):
                raise ValueError("investigation recording requires a marked Recorder")
        if not env._has_reset or (env.recorder is not None and not investigation_recording):
            raise ValueError("use a reset environment without a legacy Recorder")
        if (
            initial.episode_id != env.task.episode_id
            or initial.sequence_id != 0
            or env._sequence != 1
            or env.ledger.decisions != 0
            or initial.t_deliver_s != env.time_s
            or env.information_wait_pending
        ):
            raise ValueError("interaction session must start at the initial reset observation")
        self.env = env
        self._clock_identity = env.clock
        self._wall = clock or WallClock()
        self.limits = InteractionLimits()
        self.task = env.task
        self.initial = initial
        self.history = [initial]
        self.mode = mode
        self._events = []
        self._requests = {}
        self._receipts = {}
        self._physical = {}
        self._pending = None
        self._started = None
        self._last_wall = None
        # Validate mode before any effects.
        self.transcript()

    @property
    def pending(self) -> PendingInformation | None:
        return self._pending

    @property
    def receipts(self) -> tuple[InformationReceipt, ...]:
        return tuple(self._receipts.values())

    def _check(self):
        if self.env.clock is not self._clock_identity:
            raise RuntimeError("session belongs to an earlier environment reset")
        last = self.history[-1]
        if self.env._sequence != last.sequence_id + 1 or self.env.time_s != last.t_deliver_s:
            raise RuntimeError("environment advanced outside its interaction session")

    def _now(self):
        value = self._wall.monotonic()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid monotonic clock")
        if (
            not math.isfinite(value)
            or value < 0
            or (self._last_wall is not None and value < self._last_wall)
        ):
            raise ValueError("monotonic clock must be finite and nondecreasing")
        utc = _utc(self._wall.utc())
        self._last_wall = value
        return value, utc

    def begin(self, request: InteractionRequest) -> PendingInformation | InformationReceipt:
        self._check()
        if not isinstance(request, InteractionRequest):
            raise TypeError("begin requires a validated public InteractionRequest")
        request = InteractionRequest.from_json(request.to_json())
        if request.episode_id != self.task.episode_id:
            raise ValueError("request episode mismatch")
        previous = self._requests.get(request.request_id)
        if previous is not None:
            if previous != request:
                raise ValueError("request ID conflict")
            if request.request_id in self._receipts:
                return self._receipts[request.request_id]
            self.poll()
            return self._receipts.get(request.request_id) or self._pending
        self.poll()
        if self._pending is not None:
            raise RuntimeError("another information request is pending")
        if len(self._requests) >= self.limits.max_requests:
            raise ValueError("external request budget exhausted")
        if (
            request.parent_request_id is not None
            and request.parent_request_id not in self._receipts
        ):
            raise ValueError("follow-up parent must be a completed request in this episode")
        # Validate clocks before touching the environment; time waiting starts
        # at this decision boundary and includes local overhead computation.
        now, utc = self._now()
        observation = self.env.begin_information_wait(request.request_id)
        self.history.append(observation)
        self._requests[request.request_id] = request
        self._started = now
        self._pending = PendingInformation(
            request=request,
            observation=observation,
            started_utc=utc,
            started_monotonic_s=float(now),
            deadline_s=self.limits.deadline_s(request.channel),
        )
        self._events.append(StartedEvent(pending=self._pending))
        if not self.env.information_wait_pending:
            return self._finish(self._outcome("cancelled", "Simulator stopped during overhead."))
        return self._pending

    @staticmethod
    def _outcome(outcome, text):
        return InformationReply(outcome=outcome, text=text, provenance="simulated")

    def _finish(self, reply, *, stamp=None):
        now, utc = stamp or self._now()
        pending = self._pending
        receipt = InformationReceipt(
            request=pending.request,
            reply=reply,
            started_utc=pending.started_utc,
            received_utc=utc,
            started_monotonic_s=float(self._started),
            received_monotonic_s=float(now),
            elapsed_wall_s=now - self._started,
            simulation_time_s=self.env.time_s,
            observation_sequence_id=pending.observation.sequence_id,
            remaining_requests=self.limits.max_requests - len(self._requests),
        )
        if self.env.information_wait_pending:
            self.env.end_information_wait(pending.request.request_id)
        self._receipts[pending.request.request_id] = receipt
        self._events.append(CompletedEvent(receipt=receipt))
        self._pending = None
        self._started = None
        return receipt

    def poll(self) -> InformationReceipt | None:
        self._check()
        if self._pending is None:
            return None
        stamp = self._now()
        if stamp[0] - self._started >= self._pending.deadline_s:
            return self._finish(
                self._outcome("timed_out", "Response deadline elapsed."), stamp=stamp
            )
        return None

    def complete(self, request_id: str, reply: InformationReply | str) -> InformationReceipt:
        self._check()
        if request_id not in self._requests:
            raise ValueError("unknown request ID")
        try:
            wire = reply.to_json() if isinstance(reply, InformationReply) else reply
            validated = InformationReply.from_json(wire)
        except (ValueError, TypeError, AttributeError):
            validated = self._outcome(
                "invalid_response", "Response failed the public wire contract."
            )
        if request_id in self._receipts:
            cached = self._receipts[request_id]
            if cached.reply != validated:
                raise ValueError("completion conflict")
            return cached
        if self._pending is None or request_id != self._pending.request.request_id:
            raise ValueError("request is not pending")
        stamp = self._now()
        if stamp[0] - self._started >= self._pending.deadline_s:
            validated = self._outcome("timed_out", "Response deadline elapsed.")
        return self._finish(validated, stamp=stamp)

    def cancel(self, request_id: str) -> InformationReceipt:
        self._check()
        if self._pending is None or self._pending.request.request_id != request_id:
            raise ValueError("request is not pending")
        stamp = self._now()
        reply = self._outcome("cancelled", "Request cancelled by caller.")
        if stamp[0] - self._started >= self._pending.deadline_s:
            reply = self._outcome("timed_out", "Response deadline elapsed.")
        return self._finish(reply, stamp=stamp)

    def request(self, request: InteractionRequest, transport):
        if not isinstance(request, InteractionRequest):
            raise TypeError("request requires a validated public InteractionRequest")
        already_started = request.request_id in self._requests
        result = self.begin(request)
        if isinstance(result, InformationReceipt) or already_started:
            return result
        # This convenience call is for immediate recorded fixtures only.
        # Future live providers use begin/complete and a polling event loop.
        try:
            reply = transport.request(InteractionRequest.from_json(request.to_json()))
        except Exception:
            reply = self._outcome("unavailable", "Recorded information source unavailable.")
        return self.complete(request.request_id, reply)

    def step(self, decision: PhysicalDecision) -> Observation:
        self._check()
        if not isinstance(decision, PhysicalDecision):
            raise TypeError("step requires a validated PhysicalDecision")
        decision = PhysicalDecision.model_validate_json(decision.model_dump_json())
        self.poll()
        if self._pending is not None:
            raise RuntimeError("complete or cancel information request before a physical action")
        refs = decision.information_refs
        if len(set(refs)) != len(refs) or any(ref not in self._receipts for ref in refs):
            raise ValueError("information references must identify distinct completed requests")
        old = self._physical.get(decision.action.action_id)
        if old is not None:
            if old.decision != decision:
                raise ValueError("physical decision ID conflict")
            return old.observation
        observation = self.env.step(decision.action)
        self.history.append(observation)
        event = PhysicalEvent(decision=decision, observation=observation)
        self._physical[decision.action.action_id] = event
        self._events.append(event)
        return observation

    def transcript(self) -> InteractionTranscript:
        return InteractionTranscript(
            mode=self.mode,
            limits=self.limits,
            task=self.task,
            initial_observation=self.initial,
            events=tuple(self._events),
        )

    def save(self, path: Path) -> str:
        """Exclusive write; a pending transcript remains explicitly incomplete."""
        raw = self.transcript().model_dump(mode="json")
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        envelope = {"sha256": digest, "transcript": raw}
        encoded = json.dumps(envelope, indent=2, allow_nan=False) + "\n"
        if len(encoded.encode()) > 16 * 1024 * 1024:
            raise ValueError("interaction transcript exceeds 16 MiB")
        with Path(path).open("x") as stream:
            stream.write(encoded)
        return digest


def load_transcript(path: Path) -> InteractionTranscript:
    if Path(path).stat().st_size > 16 * 1024 * 1024:
        raise ValueError("interaction transcript exceeds 16 MiB")

    def unique_fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("duplicate transcript JSON field")
            result[name] = value
        return result

    raw = json.loads(Path(path).read_text(), object_pairs_hook=unique_fields)
    if not isinstance(raw, dict) or set(raw) != {"sha256", "transcript"}:
        raise ValueError("invalid transcript envelope")
    canonical = json.dumps(
        raw["transcript"], sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    if hashlib.sha256(canonical.encode()).hexdigest() != raw["sha256"]:
        raise ValueError("transcript checksum mismatch")
    return InteractionTranscript.model_validate_json(canonical)


class _ReplayClock:
    elapsed = 0.0
    timestamp = "2000-01-01T00:00:00+00:00"

    def __init__(self):
        self.stamps = []

    def monotonic(self):
        if self.stamps:
            self.elapsed, self.timestamp = self.stamps.pop(0)
        return self.elapsed

    def utc(self):
        return self.timestamp


def replay_interactions(env, initial: Observation, transcript: InteractionTranscript) -> dict:
    """Replay public events on a separately reset env; no information transport.

    Original receipt wall times are restored metadata. Actual replay wall time is
    reported separately and never presented as a real human/internet exchange.
    """
    started = time.monotonic()
    transcript = InteractionTranscript.model_validate_json(transcript.model_dump_json())
    clock = _ReplayClock()
    session = InformationSession(env, initial, clock=clock, mode="recorded_replay")
    if (session.task, initial, session.limits) != (
        transcript.task,
        transcript.initial_observation,
        transcript.limits,
    ):
        raise ValueError("replay initial state differs")
    index = 0
    while index < len(transcript.events):
        event = transcript.events[index]
        before = len(session._events)
        if isinstance(event, StartedEvent):
            if session.pending is not None:
                raise ValueError("replay start overlaps pending request")
            clock.stamps = [(event.pending.started_monotonic_s, event.pending.started_utc)]
            # A protection trip during overhead completes the request inside
            # begin(). Supply its original next wall stamp if that path runs.
            if index + 1 < len(transcript.events):
                following = transcript.events[index + 1]
                if isinstance(following, CompletedEvent):
                    clock.stamps.append(
                        (
                            following.receipt.received_monotonic_s,
                            following.receipt.received_utc,
                        )
                    )
            session.begin(event.pending.request)
        elif isinstance(event, CompletedEvent):
            if session.pending is None:
                raise ValueError("replay completion has no pending request")
            clock.stamps = [
                (
                    event.receipt.received_monotonic_s,
                    event.receipt.received_utc,
                )
            ]
            session.complete(event.receipt.request.request_id, event.receipt.reply)
        else:
            session.step(event.decision)
        generated = session._events[before:]
        if not generated or generated != list(transcript.events[index : index + len(generated)]):
            raise ValueError("replay event differs from recorded event")
        index += len(generated)
    if session.pending is not None:
        raise ValueError("replay transcript ends with an incomplete information request")
    return {
        "status": "passed",
        "mode": "recorded_replay",
        "events": len(transcript.events),
        "restored_original_wait_s": sum(r.elapsed_wall_s for r in session.receipts),
        "actual_replay_wall_s": time.monotonic() - started,
        "simulation_time_s": env.time_s,
        "decisions": env.ledger.decisions,
        "external_requests": len(session.receipts),
        "live_calls": 0,
    }
