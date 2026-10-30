"""Versioned public decision bridge for trusted local investigation policies.

This is an accidental-leakage boundary, not a Python sandbox. The coordinator
owns the simulator; a policy receives only a serialized public AgentContext.
Existing physical and interaction schemas remain unchanged. Within-episode
records are explicit state, not trained adaptation or cross-episode memory.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from pv_sim.contracts import (
    ActionKind,
    Count,
    Decision,
    Identifier,
    Number,
    Observation,
    PublicTask,
    Record,
    Text,
    validate_decision_context,
    validate_observation_context,
)
from pv_sim.interaction import (
    InformationReceipt,
    InformationSession,
    InteractionTranscript,
    PendingInformation,
    PhysicalDecision,
    replay_interactions,
)
from pv_sim.interaction_contracts import InformationReply, InteractionLimits, InteractionRequest

VERSION = "investigation/1.0"
MAX_TRACE_BYTES = 16 * 1024 * 1024
MAX_CHOICE_BYTES = 64 * 1024
ADAPTATION = "within_episode_state_only_no_training_no_cross_episode_memory"


def _clone(record):
    return type(record).model_validate_json(record.model_dump_json())


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(record) -> str:
    return hashlib.sha256(_canonical(record.model_dump(mode="json")).encode()).hexdigest()


def _refs(observations, information, history, receipts):
    if len(set(observations)) != len(observations) or not set(observations) <= {
        observation.sequence_id for observation in history
    }:
        raise ValueError("observation references must identify distinct available observations")
    if len(set(information)) != len(information) or not set(information) <= {
        receipt.request.request_id for receipt in receipts
    }:
        raise ValueError("information references must identify distinct completed requests")


class WorldBelief(Record):
    """Recorded interpretation, never an evaluator's hidden physical state."""

    as_of_sequence_id: Count
    summary: Text
    alternatives: Annotated[tuple[Text, ...], Field(max_length=8)] = ()
    information_gap: Text | None = None
    observation_refs: tuple[Count, ...] = ()
    information_refs: Annotated[tuple[Identifier, ...], Field(max_length=3)] = ()


class SelfModel(Record):
    """Policy assessment; cannot expand advertised capabilities or budgets."""

    as_of_sequence_id: Count
    summary: Text
    unavailable_tools: tuple[ActionKind | Literal["human", "internet"], ...] = ()
    observation_refs: tuple[Count, ...] = ()
    information_refs: Annotated[tuple[Identifier, ...], Field(max_length=3)] = ()


def _state_refs(state, history, receipts):
    if state is None:
        return
    past = tuple(o for o in history if o.sequence_id <= state.as_of_sequence_id)
    if not past or past[-1].sequence_id != state.as_of_sequence_id:
        raise ValueError("state references an unavailable observation boundary")
    completed = tuple(r for r in receipts if r.observation_sequence_id <= state.as_of_sequence_id)
    _refs(state.observation_refs, state.information_refs, past, completed)


def _validate_available_records(task, history, receipts):
    if task.allowed_adaptation != "none":
        raise ValueError("investigation/1.0 supports no trained or cross-episode adaptation")
    sequences = [o.sequence_id for o in history]
    times = [o.t_deliver_s for o in history]
    if sequences != list(range(len(sequences))) or times != sorted(times):
        raise ValueError("history must contain ordered contiguous public observations")
    for observation in history:
        validate_observation_context(observation, task)
    identifiers = [r.request.request_id for r in receipts]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate completed information receipt")
    for index, receipt in enumerate(receipts):
        if receipt.request.episode_id != task.episode_id:
            raise ValueError("receipt episode mismatch")
        if receipt.observation_sequence_id not in sequences:
            raise ValueError("receipt refers to a future observation")
        boundary = history[receipt.observation_sequence_id]
        if receipt.simulation_time_s != boundary.t_deliver_s:
            raise ValueError("receipt simulation time differs from its observation")
        if receipt.remaining_requests != 2 - index:
            raise ValueError("receipt remaining request budget is inconsistent")
        parent = receipt.request.parent_request_id
        if parent is not None and parent not in identifiers[:index]:
            raise ValueError("receipt parent was not previously completed")


class AgentContext(Record):
    schema_version: Literal["investigation/1.0"] = VERSION
    task: PublicTask
    history: Annotated[tuple[Observation, ...], Field(min_length=1)]
    completed_information: Annotated[tuple[InformationReceipt, ...], Field(max_length=3)] = ()
    information_limits: InteractionLimits = InteractionLimits()
    information_channels: tuple[Literal["human", "internet"], ...] = ("human", "internet")
    remaining_information_requests: Annotated[int, Field(ge=0, le=3)] = 3
    next_action_id: Annotated[int, Field(ge=1)] = 1
    world_belief: WorldBelief | None = None
    self_model: SelfModel | None = None
    adaptation: Literal["within_episode_state_only_no_training_no_cross_episode_memory"] = (
        ADAPTATION
    )

    @model_validator(mode="after")
    def available_at_boundary(self):
        _validate_available_records(self.task, self.history, self.completed_information)
        if self.remaining_information_requests != 3 - len(self.completed_information):
            raise ValueError("remaining information budget is inconsistent")
        if self.information_channels != ("human", "internet"):
            raise ValueError("investigation/1.0 retains the two declared information channels")
        if self.next_action_id <= max(
            (f.action_id for o in self.history for f in o.feedback), default=0
        ):
            raise ValueError("next action ID must follow observed actions")
        _state_refs(self.world_belief, self.history, self.completed_information)
        _state_refs(self.self_model, self.history, self.completed_information)
        return self


class ChoiceBase(Record):
    schema_version: Literal["investigation/1.0"] = VERSION
    choice_id: Identifier
    context_sequence_id: Count
    information_refs: Annotated[tuple[Identifier, ...], Field(max_length=3)] = ()
    world_belief: WorldBelief | None = None
    self_model: SelfModel | None = None


class PhysicalChoice(ChoiceBase):
    kind: Literal["physical"] = "physical"
    decision: Decision


class InformationChoice(ChoiceBase):
    kind: Literal["information"] = "information"
    request: InteractionRequest
    observation_refs: tuple[Count, ...] = ()


InvestigationChoice = Annotated[PhysicalChoice | InformationChoice, Field(discriminator="kind")]
CHOICE_ADAPTER = TypeAdapter(InvestigationChoice)


def validate_choice(choice: InvestigationChoice, context: AgentContext) -> None:
    if choice.context_sequence_id != context.history[-1].sequence_id:
        raise ValueError("choice must use the current observation boundary")
    if context.history[-1].terminal:
        raise ValueError("terminal episode cannot accept a new choice")
    observation_refs = (
        choice.decision.evidence_refs
        if isinstance(choice, PhysicalChoice)
        else choice.observation_refs
    )
    _refs(observation_refs, choice.information_refs, context.history, context.completed_information)
    for state in (choice.world_belief, choice.self_model):
        _state_refs(state, context.history, context.completed_information)
        if state is not None and state.as_of_sequence_id != choice.context_sequence_id:
            raise ValueError("new state must declare the current observation boundary")
    if isinstance(choice, PhysicalChoice):
        validate_decision_context(choice.decision, context.task, context.history)
        if choice.decision.action.action_id != context.next_action_id:
            raise ValueError("physical choice must use the next action ID")
    else:
        if choice.request.episode_id != context.task.episode_id:
            raise ValueError("request episode mismatch")
        if context.remaining_information_requests == 0:
            raise ValueError("external request budget exhausted")
        completed = {r.request.request_id for r in context.completed_information}
        if choice.request.request_id in completed:
            raise ValueError("new choice cannot reuse a completed request ID")
        parent = choice.request.parent_request_id
        if parent is not None and parent not in completed:
            raise ValueError("follow-up parent must be completed")


class CommittedChoice(Record):
    """Appended before dispatch. Its full Decision includes every prediction."""

    kind: Literal["committed"] = "committed"
    choice: InvestigationChoice
    simulation_time_s: Annotated[Number, Field(ge=0)]
    interaction_event_start: Count
    context_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ChoiceOutcome(Record):
    kind: Literal["outcome"] = "outcome"
    choice_id: Identifier
    status: Literal[
        "physical_returned", "information_pending", "information_completed", "dispatch_failed"
    ]
    interaction_event_end: Count
    observation_sequence_id: Count | None = None
    # Failure is explicit and deliberately contains no private exception text.
    failure: Literal["dispatch_failed"] | None = None

    @model_validator(mode="after")
    def failure_status(self):
        if (self.status == "dispatch_failed") != (self.failure == "dispatch_failed"):
            raise ValueError("failure status and marker disagree")
        if self.status != "dispatch_failed" and self.observation_sequence_id is None:
            raise ValueError("a returned outcome must identify its observation")
        return self


InvestigationEvent = Annotated[CommittedChoice | ChoiceOutcome, Field(discriminator="kind")]


class InvestigationTranscript(Record):
    schema_version: Literal["investigation/1.0"] = VERSION
    adaptation: Literal["within_episode_state_only_no_training_no_cross_episode_memory"] = (
        ADAPTATION
    )
    mode: Literal["trusted_policy_local_recorded"] = "trusted_policy_local_recorded"
    interaction: InteractionTranscript
    events: tuple[InvestigationEvent, ...]

    @model_validator(mode="after")
    def linked_choices(self):
        # Reconstruct each public boundary from the unchanged interaction wire,
        # validating that recorded predictions were bound to pre-action evidence.
        history = [self.interaction.initial_observation]
        receipts = []
        _validate_available_records(self.interaction.task, history, receipts)
        index, next_action = 0, 1
        world, self_model = None, None
        commits = {}
        active = None
        waiting = False
        dispatch_failed = False
        finished = set()
        for event in self.events:
            if dispatch_failed:
                raise ValueError("events cannot continue after failed dispatch")
            if isinstance(event, CommittedChoice):
                if active is not None or event.choice.choice_id in commits:
                    raise ValueError("overlapping or duplicate committed choice")
                if event.interaction_event_start != index:
                    raise ValueError("commit interaction index differs from boundary")
                context = AgentContext(
                    task=self.interaction.task,
                    history=tuple(history),
                    completed_information=tuple(receipts),
                    remaining_information_requests=3 - len(receipts),
                    next_action_id=next_action,
                    world_belief=world,
                    self_model=self_model,
                )
                validate_choice(event.choice, context)
                if event.context_sha256 != _digest(context):
                    raise ValueError("commit context checksum mismatch")
                if event.simulation_time_s != history[-1].t_deliver_s:
                    raise ValueError("commit time differs from public boundary")
                commits[event.choice.choice_id] = event
                active = event.choice.choice_id
                waiting = False
                world = event.choice.world_belief or world
                self_model = event.choice.self_model or self_model
                if isinstance(event.choice, PhysicalChoice):
                    next_action += 1
            else:
                if event.choice_id != active or event.choice_id in finished:
                    raise ValueError("outcome has no active committed choice")
                if not index <= event.interaction_event_end <= len(self.interaction.events):
                    raise ValueError("outcome interaction index is invalid")
                added = self.interaction.events[index : event.interaction_event_end]
                choice = commits[active].choice
                if event.status == "physical_returned":
                    if not isinstance(choice, PhysicalChoice) or len(added) != 1:
                        raise ValueError("physical outcome is not linked to one physical event")
                    expected = PhysicalDecision(
                        action=choice.decision.action,
                        information_refs=choice.information_refs,
                        interpretation=choice.decision.rationale or "No rationale recorded.",
                    )
                    if added[0].kind != "physical_decision" or added[0].decision != expected:
                        raise ValueError("physical event differs from full committed decision")
                elif event.status in ("information_pending", "information_completed"):
                    if not isinstance(choice, InformationChoice) or not added:
                        raise ValueError("information outcome has no linked information events")
                    expected_kinds = (
                        ("information_started",)
                        if event.status == "information_pending" and not waiting
                        else ("information_completed",)
                        if event.status == "information_completed" and waiting
                        else ("information_started", "information_completed")
                        if event.status == "information_completed"
                        else ()
                    )
                    if tuple(item.kind for item in added) != expected_kinds:
                        raise ValueError("information outcome status differs from linked events")
                    for item in added:
                        request = (
                            item.pending.request
                            if item.kind == "information_started"
                            else item.receipt.request
                            if item.kind == "information_completed"
                            else None
                        )
                        if request != choice.request:
                            raise ValueError("information event differs from committed request")
                    if event.status == "information_completed":
                        started = self.interaction.events[
                            commits[active].interaction_event_start
                        ].pending
                        receipt = added[-1].receipt
                        if (
                            receipt.observation_sequence_id != started.observation.sequence_id
                            or receipt.simulation_time_s != started.observation.t_deliver_s
                            or receipt.started_monotonic_s != started.started_monotonic_s
                            or receipt.started_utc != started.started_utc
                        ):
                            raise ValueError("receipt differs from its original pending boundary")
                        if (
                            receipt.elapsed_wall_s >= started.deadline_s
                            and not started.observation.terminal
                            and receipt.reply.outcome != "timed_out"
                        ):
                            raise ValueError("expired receipt must report its timeout")
                for item in added:
                    if item.kind == "information_started":
                        history.append(item.pending.observation)
                    elif item.kind == "information_completed":
                        receipts.append(item.receipt)
                    else:
                        history.append(item.observation)
                index = event.interaction_event_end
                _validate_available_records(self.interaction.task, history, receipts)
                waiting = event.status == "information_pending"
                dispatch_failed = event.status == "dispatch_failed"
                if event.observation_sequence_id is not None:
                    if event.observation_sequence_id != history[-1].sequence_id:
                        raise ValueError("outcome observation differs from linked observation")
                if event.status != "information_pending":
                    finished.add(active)
                    active = None
        if index != len(self.interaction.events):
            raise ValueError("unlinked interaction event")
        return self


class InvestigationSession:
    """Trusted coordinator; never pass this object to a policy.

    choose() calls policy.act(public_context), then validates the returned wire.
    submit() precommits in memory and dispatches. save() persists that trace;
    this is not a crash-recovery journal. Identical choice retries have no additional
    effects. A dispatch exception is retained and latches this coordinator closed;
    it is never reported as a successful or verified physical outcome.
    """

    def __init__(self, env, initial: Observation, *, clock=None, investigation_recording=False):
        self._session = InformationSession(
            env, _clone(initial), clock=clock, investigation_recording=investigation_recording)
        self._session.task = _clone(self._session.task)
        self._events = []
        self._choices = {}
        self._results = {}
        self._request_choices = {}
        self._world = None
        self._self = None
        self._next_action = 1
        self._failed = False
        self.context()

    def context(self) -> AgentContext:
        self._session._check()
        if self._failed:
            raise RuntimeError("coordinator closed after dispatch failure")
        if self._session.pending is not None:
            raise RuntimeError("information request is pending; complete it before deciding")
        return AgentContext.model_validate_json(
            AgentContext(
                task=_clone(self._session.task),
                history=tuple(_clone(o) for o in self._session.history),
                completed_information=tuple(_clone(r) for r in self._session.receipts),
                remaining_information_requests=3 - len(self._session.receipts),
                next_action_id=self._next_action,
                world_belief=self._world,
                self_model=self._self,
            ).model_dump_json()
        )

    @staticmethod
    def _choice(choice):
        if not isinstance(choice, (PhysicalChoice, InformationChoice)):
            raise TypeError("policy must return a typed investigation choice")
        wire = choice.model_dump_json()
        if len(wire.encode()) > MAX_CHOICE_BYTES:
            raise ValueError("choice exceeds 64 KiB")
        return CHOICE_ADAPTER.validate_json(wire)

    def choose(self, policy) -> InvestigationChoice:
        context = self.context()
        choice = self._choice(policy.act(_clone(context)))
        validate_choice(choice, context)
        return choice

    def _outcome(self, choice_id, result):
        if isinstance(result, Observation):
            status, sequence = "physical_returned", result.sequence_id
        elif isinstance(result, PendingInformation):
            status, sequence = "information_pending", result.observation.sequence_id
        else:
            status, sequence = "information_completed", result.observation_sequence_id
        self._events.append(
            ChoiceOutcome(
                choice_id=choice_id,
                status=status,
                interaction_event_end=len(self._session.transcript().events),
                observation_sequence_id=sequence,
            )
        )
        self._results[choice_id] = _clone(result)
        return _clone(result)

    def submit(self, choice: InvestigationChoice, *, transport=None):
        self._session._check()
        choice = self._choice(choice)
        if self._failed:
            raise RuntimeError("coordinator closed after dispatch failure")
        if choice.choice_id in self._choices:
            if self._choices[choice.choice_id] != choice:
                raise ValueError("choice ID conflict")
            return _clone(self._results[choice.choice_id])
        context = self.context()
        validate_choice(choice, context)
        if isinstance(choice, InformationChoice):
            if choice.request.request_id in self._request_choices:
                raise ValueError("request ID is already bound to another choice")
        self._events.append(
            CommittedChoice(
                choice=choice,
                simulation_time_s=context.history[-1].t_deliver_s,
                interaction_event_start=len(self._session.transcript().events),
                context_sha256=_digest(context),
            )
        )
        self._choices[choice.choice_id] = choice
        self._world = choice.world_belief or self._world
        self._self = choice.self_model or self._self
        try:
            if isinstance(choice, PhysicalChoice):
                self._next_action += 1
                result = self._session.step(
                    PhysicalDecision(
                        action=choice.decision.action,
                        information_refs=choice.information_refs,
                        interpretation=choice.decision.rationale or "No rationale recorded.",
                    )
                )
            else:
                self._request_choices[choice.request.request_id] = choice.choice_id
                result = (
                    self._session.begin(choice.request)
                    if transport is None
                    else self._session.request(choice.request, transport)
                )
        except Exception:
            self._failed = True
            self._events.append(
                ChoiceOutcome(
                    choice_id=choice.choice_id,
                    status="dispatch_failed",
                    failure="dispatch_failed",
                    interaction_event_end=len(self._session.transcript().events),
                )
            )
            raise
        return self._outcome(choice.choice_id, result)

    def _require_open(self):
        self._session._check()
        if self._failed:
            raise RuntimeError("coordinator closed after dispatch failure")

    def complete(self, request_id: str, reply: InformationReply | str) -> InformationReceipt:
        self._require_open()
        result = self._session.complete(request_id, reply)
        choice_id = self._request_choices[request_id]
        if self._results.get(choice_id) != result:
            self._outcome(choice_id, result)
        return _clone(result)

    def poll(self) -> InformationReceipt | None:
        self._require_open()
        result = self._session.poll()
        if result is not None:
            self._outcome(self._request_choices[result.request.request_id], result)
        return _clone(result) if result is not None else None

    def cancel(self, request_id: str) -> InformationReceipt:
        self._require_open()
        result = self._session.cancel(request_id)
        return self._outcome(self._request_choices[request_id], result)

    def transcript(self) -> InvestigationTranscript:
        return InvestigationTranscript(
            interaction=self._session.transcript(), events=tuple(self._events)
        )

    def save(self, path: Path) -> str:
        trace = self.transcript()
        digest = _digest(trace)
        encoded = (
            json.dumps(
                {"sha256": digest, "transcript": trace.model_dump(mode="json")},
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        if len(encoded.encode()) > MAX_TRACE_BYTES:
            raise ValueError("investigation transcript exceeds 16 MiB")
        with Path(path).open("x") as stream:
            stream.write(encoded)
        return digest


def load_investigation(path: Path) -> InvestigationTranscript:
    if Path(path).stat().st_size > MAX_TRACE_BYTES:
        raise ValueError("investigation transcript exceeds 16 MiB")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate transcript JSON field")
            result[key] = value
        return result

    raw = json.loads(Path(path).read_text(), object_pairs_hook=unique)
    if not isinstance(raw, dict) or set(raw) != {"sha256", "transcript"}:
        raise ValueError("invalid investigation transcript envelope")
    canonical = _canonical(raw["transcript"])
    if hashlib.sha256(canonical.encode()).hexdigest() != raw["sha256"]:
        raise ValueError("investigation transcript checksum mismatch")
    return InvestigationTranscript.model_validate_json(canonical)


def replay_investigation(env, initial: Observation, transcript: InvestigationTranscript) -> dict:
    transcript = _clone(transcript)
    if any(
        isinstance(e, ChoiceOutcome) and e.status == "dispatch_failed" for e in transcript.events
    ):
        raise ValueError("cannot replay a transcript with failed dispatch")
    if transcript.events and (
        isinstance(transcript.events[-1], CommittedChoice)
        or transcript.events[-1].status == "information_pending"
    ):
        raise ValueError("cannot replay an incomplete investigation choice")
    result = replay_interactions(env, initial, transcript.interaction)
    return result | {
        "schema_version": VERSION,
        "committed_choices": sum(isinstance(e, CommittedChoice) for e in transcript.events),
        "full_predictions_retained": sum(
            len(e.choice.decision.predictions)
            for e in transcript.events
            if isinstance(e, CommittedChoice) and isinstance(e.choice, PhysicalChoice)
        ),
    }
