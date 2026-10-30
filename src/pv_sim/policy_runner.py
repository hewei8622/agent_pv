"""Serialization boundary for trusted-policy/local baselines.

This is accidental-leakage prevention, not an OS sandbox or provider adapter.
Only public task/history JSON enters policy methods. Wall time is measured; an
overrun is rejected on return, not forcibly interrupted in this synchronous mode.
"""

from __future__ import annotations

import json
import time

from pydantic import TypeAdapter

from pv_sim.contracts import (
    Decision,
    Observation,
    PublicTask,
    SafeStop,
    validate_decision_context,
    validate_observation_context,
)
from pv_sim.policies.protocol import Policy

_HISTORY_ADAPTER = TypeAdapter(tuple[Observation, ...])
MAX_DECISION_BYTES = 64 * 1024


class PolicyRunner:
    mode = "trusted-policy/local"

    def __init__(self, policy: Policy, task: PublicTask) -> None:
        self.task = PublicTask.model_validate_json(task.model_dump_json())
        self.policy = policy
        self.last_latency_s = 0.0
        self.last_failure: str | None = None
        self._last_action_id = 0
        self._reset_failed = False
        try:
            policy.reset(PublicTask.model_validate_json(self.task.model_dump_json()))
        except Exception:
            self._reset_failed = True

    def decide(self, history: tuple[Observation, ...]) -> Decision:
        started = time.perf_counter()
        self.last_failure = None
        public_history: tuple[Observation, ...] = ()
        next_id = self._last_action_id + 1
        try:
            if not isinstance(history, tuple) or any(
                not isinstance(o, Observation) for o in history
            ):
                raise ValueError("invalid input type")
            public_history = _HISTORY_ADAPTER.validate_json(
                json.dumps([o.model_dump(mode="json") for o in history], allow_nan=False)
            )
            for observation in public_history:
                validate_observation_context(observation, self.task)
            sequences = [o.sequence_id for o in public_history]
            times = [o.t_deliver_s for o in public_history]
            if sequences != sorted(set(sequences)) or times != sorted(times):
                raise ValueError("history ordering")
            next_id = (
                max(
                    (
                        self._last_action_id,
                        *(f.action_id for o in public_history for f in o.feedback),
                    )
                )
                + 1
            )
        except Exception:
            self.last_failure = "invalid_input"
        if self.last_failure is None:
            try:
                if self._reset_failed:
                    raise RuntimeError("reset failed")
                result = self.policy.act(public_history)
                if not isinstance(result, Decision):
                    raise ValueError("result is not a Decision")
                wire = result.model_dump_json()
                if len(wire.encode("utf-8")) > MAX_DECISION_BYTES:
                    raise ValueError("response too large")
                result = Decision.model_validate_json(wire)
                validate_decision_context(result, self.task, public_history)
                if result.action.action_id != next_id:
                    raise ValueError("action ID is not the next new ID")
            except Exception:
                self.last_failure = "invalid_output"
        self.last_latency_s = time.perf_counter() - started
        if self.last_latency_s > 30.0:
            self.last_failure = "latency_overrun"
        if self.last_failure is not None:
            result = Decision(
                schema_version="1.0",
                action=SafeStop(
                    schema_version="1.0", action_id=next_id, kind="safe_stop", timeout_s=2.0
                ),
                predictions=(),
                hypothesis_probabilities=None,
                unresolved_hypotheses=self.task.hypothesis_classes,
                evidence_refs=(),
                rationale="Trusted local policy boundary failed; stop safely.",
            )
        self._last_action_id = result.action.action_id
        return result
