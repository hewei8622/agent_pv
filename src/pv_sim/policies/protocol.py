"""Trusted local policy interface and helpers using public records only."""

from __future__ import annotations

from typing import Protocol

from pv_sim.contracts import (
    ACTION_ADAPTER,
    Action,
    ActionFeedback,
    Decision,
    Observation,
    PublicTask,
    ScalarSample,
    validate_decision_context,
)

TERMINAL_CODES = frozenset({"completed", "rejected", "timed_out", "failed", "cancelled"})
VOLTAGE_TOLERANCE_V = 0.03


class Policy(Protocol):
    def reset(self, task: PublicTask) -> None: ...

    def act(self, history: tuple[Observation, ...]) -> Decision: ...


def matched_pairs(
    samples: tuple[ScalarSample, ...],
) -> tuple[tuple[ScalarSample, ScalarSample], ...]:
    """Pair only valid V/I readings with exactly the same capture timestamp."""
    voltages = {
        s.t_capture_s: s for s in samples if s.channel == "voltage_v" and s.validity == "valid"
    }
    currents = {
        s.t_capture_s: s for s in samples if s.channel == "current_a" and s.validity == "valid"
    }
    return tuple((voltages[t], currents[t]) for t in sorted(voltages.keys() & currents.keys()))


class PublicBaseline:
    """Shared bookkeeping; no simulator reference, private configuration or callback."""

    def reset(self, task: PublicTask) -> None:
        self.task = task
        self.pending: Action | None = None
        self.next_action_id = 1
        self.stage = "start"

    def _emit(
        self,
        history: tuple[Observation, ...],
        kind: str,
        rationale: str,
        *,
        evidence_refs: tuple[int, ...] | None = None,
        timeout_s: float = 8.0,
        **fields: object,
    ) -> Decision:
        action = ACTION_ADAPTER.validate_python(
            dict(
                schema_version="1.0",
                action_id=self.next_action_id,
                kind=kind,
                timeout_s=timeout_s,
                **fields,
            )
        )
        decision = Decision(
            schema_version="1.0",
            action=action,
            predictions=(),
            hypothesis_probabilities=None,
            unresolved_hypotheses=self.task.hypothesis_classes,
            evidence_refs=(history[-1].sequence_id,)
            if evidence_refs is None and history
            else (evidence_refs or ()),
            rationale=rationale,
        )
        try:
            validate_decision_context(decision, self.task, history)
        except ValueError:
            if kind == "safe_stop":
                raise
            return self._stop(history, "Required action or target is unavailable.")
        self.next_action_id += 1
        self.pending = action
        return decision

    def _stop(self, history: tuple[Observation, ...], rationale: str) -> Decision:
        self.stage = "stopped"
        return self._emit(history, "safe_stop", rationale, timeout_s=2.0)

    def _completion(self, history: tuple[Observation, ...]) -> ActionFeedback | None:
        if self.pending is None:
            return None
        for observation in reversed(history):
            for feedback in reversed(observation.feedback):
                if feedback.action_id == self.pending.action_id and feedback.code in TERMINAL_CODES:
                    if feedback.commanded_target != self.pending:
                        return None
                    return feedback
        return None

    def _has_frame(self, history: tuple[Observation, ...], feedback: ActionFeedback) -> bool:
        if feedback.t_accepted_s is None:
            return False
        return any(
            frame.validity == "valid" and frame.t_start_s >= feedback.t_accepted_s
            for observation in history
            for frame in observation.rgb
        )

    @staticmethod
    def _voltage_confirmed(feedback: ActionFeedback, voltage: float) -> bool:
        return feedback.t_accepted_s is not None and any(
            isinstance(measurement.sample, ScalarSample)
            and measurement.sample.channel == "voltage_v"
            and measurement.sample.validity == "valid"
            and measurement.sample.t_capture_s >= feedback.t_accepted_s
            and measurement.sample.value is not None
            and abs(measurement.sample.value - voltage) <= VOLTAGE_TOLERANCE_V
            for measurement in feedback.measured_confirmation
        )
