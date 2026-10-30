"""Accidental-leakage and serialization checks; these do not prove OS isolation."""

import ast
import inspect
from pathlib import Path

import pytest

from pv_sim.contracts import Decision, Observation, PublicTask, SafeStop
from pv_sim.policies import FixedPolicy, ScanPolicy
from pv_sim.policy_runner import MAX_DECISION_BYTES, PolicyRunner


def stop(action_id=1, **updates):
    fields = dict(
        schema_version="1.0",
        action=SafeStop(schema_version="1.0", action_id=action_id, timeout_s=2.0, kind="safe_stop"),
        predictions=(),
        hypothesis_probabilities=None,
        unresolved_hypotheses=(),
        evidence_refs=(),
        rationale="Stop.",
    )
    return Decision(**(fields | updates))


class SpyPolicy:
    def reset(self, task):
        self.task = task

    def act(self, history):
        self.history = history
        self.result = stop()
        return self.result


def test_only_public_records_reach_policy_after_json_roundtrip(task, observation):
    source = Observation.model_validate_json(__import__("json").dumps(observation))
    canary = "CANARY_PRIVATE_SEED_PATH_STATE"
    object.__setattr__(task, "private_seed", canary)
    object.__setattr__(source, "private_state", canary)
    policy = SpyPolicy()
    runner = PolicyRunner(policy, task)
    result = runner.decide((source,))
    assert type(policy.task) is PublicTask
    assert policy.task is not task and policy.task is not runner.task
    assert policy.history[0] is not source
    assert not hasattr(policy.task, "private_seed")
    assert not hasattr(policy.history[0], "private_state")
    assert canary not in policy.task.model_dump_json() + policy.history[0].model_dump_json()
    assert result is not policy.result and result == policy.result
    assert runner.last_latency_s >= 0.0
    assert runner.last_failure is None
    assert runner.mode == "trusted-policy/local"


@pytest.mark.parametrize("policy_type", [FixedPolicy, ScanPolicy])
def test_baseline_reset_has_no_private_arguments(policy_type):
    assert tuple(inspect.signature(policy_type.reset).parameters) == ("self", "task")
    assert tuple(inspect.signature(policy_type.act).parameters) == ("self", "history")


def test_policy_import_graph_has_only_public_contract_and_own_code():
    root = Path(__file__).resolve().parents[2] / "src/pv_sim"
    sources = [root / "policy_runner.py", *(root / "policies").glob("*.py")]
    allowed_roots = {"__future__", "typing", "math", "json", "time", "pydantic"}
    for source in sources:
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                assert node.level == 0
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                assert (
                    module.split(".")[0] in allowed_roots
                    or module == "pv_sim.contracts"
                    or module.startswith("pv_sim.policies.")
                ), (source, module)
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"open", "eval", "exec", "__import__"}
            for node in ast.walk(tree)
        )


@pytest.mark.parametrize("change", ["episode", "sequence", "time", "sensor"])
def test_invalid_history_never_reaches_policy(task, observation, change):
    import json

    source = Observation.model_validate_json(json.dumps(observation))
    history = (source,)
    if change == "episode":
        history = (source.model_copy(update={"episode_id": "wrong_episode"}),)
    elif change == "sequence":
        history += (source,)
    elif change == "time":
        later = source.model_copy(update={"sequence_id": 1, "t_deliver_s": 0.01, "scalars": ()})
        history += (later,)
    else:
        public = task.model_dump(mode="json")
        public["sensors"].remove("voltage_v")
        task = PublicTask.model_validate_json(json.dumps(public))
    policy = SpyPolicy()
    runner = PolicyRunner(policy, task)
    result = runner.decide(history)
    assert result.action.kind == "safe_stop"
    assert runner.last_failure == "invalid_input"
    assert not hasattr(policy, "history")


@pytest.mark.parametrize(
    "invalid", ["wrong_id", "future_ref", "raw_json", "oversized", "exception"]
)
def test_invalid_results_fall_back_without_error_or_path_leak(task, invalid):
    class InvalidPolicy(SpyPolicy):
        def act(self, history):
            if invalid == "wrong_id":
                return stop(99)
            if invalid == "future_ref":
                return stop(evidence_refs=(999,))
            if invalid == "raw_json":
                return stop().model_dump_json()
            if invalid == "oversized":
                return stop().model_copy(update={"rationale": "x" * (MAX_DECISION_BYTES + 1)})
            raise RuntimeError("CANARY_PRIVATE /hidden/path/seed")

    runner = PolicyRunner(InvalidPolicy(), task)
    result = runner.decide(())
    assert result.action.kind == "safe_stop"
    assert result.action.action_id == 1
    assert runner.last_failure == "invalid_output"
    assert "CANARY" not in result.model_dump_json()
    assert "/hidden" not in result.model_dump_json()
    assert len(result.model_dump_json().encode()) <= MAX_DECISION_BYTES


def test_unadvertised_help_is_rejected_at_boundary(task):
    from pv_sim.contracts import RequestHelp

    class HelpPolicy(SpyPolicy):
        def act(self, history):
            return stop(
                action=RequestHelp(
                    schema_version="1.0",
                    action_id=1,
                    timeout_s=8.0,
                    kind="request_help",
                    measurement="rear_inspection",
                )
            )

    runner = PolicyRunner(HelpPolicy(), task)
    assert runner.decide(()).action.kind == "safe_stop"
    assert runner.last_failure == "invalid_output"


def test_duplicate_decision_id_is_replaced_by_next_safe_stop(task):
    runner = PolicyRunner(SpyPolicy(), task)
    assert runner.decide(()).action.action_id == 1
    second = runner.decide(())
    assert second.action.action_id == 2
    assert second.action.kind == "safe_stop"
    assert runner.last_failure == "invalid_output"


def test_measured_latency_overrun_is_rejected_on_return(task, monkeypatch):
    readings = iter((0.0, 30.01))
    monkeypatch.setattr("pv_sim.policy_runner.time.perf_counter", lambda: next(readings))
    runner = PolicyRunner(SpyPolicy(), task)
    assert runner.decide(()).action.kind == "safe_stop"
    assert runner.last_failure == "latency_overrun"
    assert runner.last_latency_s == 30.01
