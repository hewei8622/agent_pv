"""Adversarial evaluator checks against genuine numeric investigation traces."""

import copy
import json

import pytest

from pv_sim.comparison import (
    choose_timed,
    default_cases,
    evaluate_episode,
    observations,
    prediction_checks,
    public_pairs,
    run_episode,
    survey_evidence,
)
from pv_sim.comparison_sources import PublicBrief
from pv_sim.config import Config
from pv_sim.env import PVEnv
from pv_sim.investigation import InvestigationSession, load_investigation
from pv_sim.recorder import Recorder
from pv_sim.replay import ReplayError, replay, verify_recording


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    folder = tmp_path_factory.mktemp("comparison-evaluator")
    cases = default_cases()
    found = {}
    for case in (cases[0], cases[3]):
        result, recorder = run_episode(case, "A", folder / case["case_id"], folder / "private")
        assert result["status"] == "complete", result
        pub = recorder.public_dir
        found[case["case_id"]] = {
            "case": case, "result": result, "recorder": recorder,
            "trace": load_investigation(pub / "investigation.json"),
            "assessment": json.loads((pub / "assessment.json").read_text()),
            "metrics": json.loads((recorder.private_dir / "metrics.json").read_text()),
            "timing": json.loads((pub / "decision_timing.json").read_text()),
            "audit": json.loads((pub / "policy_audit.json").read_text()),
        }
    return found


def score(run, *, trace=None, audit=None, metrics=None):
    return evaluate_episode(
        trace or run["trace"], run["assessment"], metrics or run["metrics"],
        run["case"]["expected"], run["timing"], audit or run["audit"],
        PublicBrief.model_validate_json(json.dumps(run["case"]["public_brief"])),
    )


def replace_observation(trace, old, new):
    events = []
    for event in trace.interaction.events:
        if event.kind == "physical_decision" and event.observation == old:
            event = event.model_copy(update={"observation": new})
        elif event.kind == "information_started" and event.pending.observation == old:
            event = event.model_copy(update={
                "pending": event.pending.model_copy(update={"observation": new})})
        events.append(event)
    interaction = trace.interaction.model_copy(update={"events": tuple(events)})
    return trace.model_copy(update={"interaction": interaction})


@pytest.mark.parametrize("case_id", ["C01", "C04"])
def test_actual_recording_scores_and_exact_replays(recorded, case_id):
    run = recorded[case_id]
    assert score(run)["success"]
    assert run["result"]["replay_metrics_equal"]
    assert run["metrics"]["elapsed_s"] == 16.0
    manifest, _ = verify_recording(run["recorder"].manifest_path)
    names = {p["path"] for p in manifest["artifacts"]}
    assert {"public/investigation.json", "public/decision_timing.json",
            "public/policy_audit.json", "public/verification.json", "result.json"} <= names


def test_physical_only_replay_rejects_investigation_before_output(recorded, tmp_path):
    output = tmp_path / "wrong-replay"
    with pytest.raises(ReplayError, match="replay_investigation"):
        replay(recorded["C04"]["recorder"].manifest_path, output)
    assert not output.exists()


def test_finish_tail_cannot_retroactively_support_early_claim(recorded):
    run = recorded["C01"]
    audit = copy.deepcopy(run["audit"])
    audit[-1]["simulation_time_s"] = 2.62
    result = score(run, audit=audit)
    assert not result["fresh_verified_outcome"]
    assert result["errors"]["false_completion"]


def test_new_contradictory_voltage_cannot_reuse_older_success(recorded):
    run = recorded["C01"]
    claim = run["audit"][-1]
    sequence = claim["assessment"]["verification_evidence"]["observation_sequence_id"]
    obs = next(o for o in observations(run["trace"]) if o.sequence_id == sequence)
    latest = max(s.t_capture_s for s in obs.scalars if s.channel == "voltage_v")
    altered = obs.model_copy(update={"scalars": tuple(
        s.model_copy(update={"value": 3.5})
        if s.channel == "voltage_v" and s.t_capture_s == latest else s for s in obs.scalars)})
    result = score(run, trace=replace_observation(run["trace"], obs, altered))
    assert not result["success"]
    assert result["errors"]["false_completion"]


def test_survey_requires_actual_attributed_permission_not_expected_label(recorded):
    run = recorded["C04"]
    events = tuple(e.model_copy(update={"choice": e.choice.model_copy(
        update={"information_refs": ()})}) if e.kind == "committed"
        and e.choice.kind == "physical" and e.choice.decision.action.kind == "probe_voltage"
        else e for e in run["trace"].events)
    result = score(run, trace=run["trace"].model_copy(update={"events": events}))
    assert result["errors"]["unauthorized_probe"]
    assert not result["success"]


@pytest.mark.parametrize("mutation", ["foreign_action", "duplicated_confirmation"])
def test_survey_does_not_credit_foreign_or_duplicate_probe_feedback(recorded, mutation):
    trace = recorded["C04"]["trace"]
    history = observations(trace)
    obs = next(o for o in history if any(f.code == "executing" for f in o.feedback))
    rows = list(obs.feedback)
    index = next(i for i, f in enumerate(rows) if f.code == "executing")
    if mutation == "foreign_action":
        rows[index] = rows[index].model_copy(update={"action_id": 999})
    else:
        rows.insert(index, rows[index])
    altered = tuple(obs.model_copy(update={"feedback": tuple(rows)}) if o == obs else o
                    for o in history)
    probes = [e.choice for e in trace.events if e.kind == "committed"
              and e.choice.kind == "physical"
              and e.choice.decision.action.kind == "probe_voltage"]
    _, valid = survey_evidence(altered, probes)
    assert not valid


def test_capture_pairing_is_exact_not_rounded(recorded):
    obs = observations(recorded["C01"]["trace"])[0]
    changed = obs.model_copy(update={"scalars": tuple(
        s.model_copy(update={"t_capture_s": s.t_capture_s + 1e-12})
        if s.channel == "current_a" else s for s in obs.scalars)})
    assert public_pairs((obs,))
    assert not public_pairs((changed,))


def test_prediction_cannot_use_foreign_action_terminal(recorded):
    trace = recorded["C01"]["trace"]
    events = []
    for event in trace.events:
        if (event.kind == "committed" and event.choice.kind == "physical"
                and event.choice.decision.predictions):
            decision = event.choice.decision
            predictions = tuple(p.model_copy(update={"action_id": 999})
                                for p in decision.predictions)
            event = event.model_copy(update={"choice": event.choice.model_copy(update={
                "decision": decision.model_copy(update={"predictions": predictions})})})
        events.append(event)
    checks = prediction_checks(trace.model_copy(update={"events": tuple(events)}))
    assert checks and not any(c["passed"] for c in checks)


def test_safe_stop_is_not_normal_success(recorded):
    run = recorded["C01"]
    metrics = {**run["metrics"], "terminal_reason": "safe_stop",
               "verification_tail_complete": False}
    assert not score(run, metrics=metrics)["success"]


def test_computation_overrun_rejected_before_dispatch():
    class Session:
        def choose(self, policy):
            return "unexecuted choice"
    clock = iter((0.0, 31.0))
    with pytest.raises(TimeoutError) as error:
        choose_timed(Session(), object(), clock=lambda: next(clock))
    assert error.value.latency_s == 31.0


def test_recorder_opt_in_requires_explicit_protocol_marker(tmp_path):
    config = Config.model_validate_json(json.dumps(default_cases()[0]["config"]))
    recorder = Recorder(tmp_path / "unmarked", private_root=tmp_path / "private")
    env = PVEnv(config, enable_rendering=False, recorder=recorder)
    try:
        _, initial = env.reset(1, episode_id="pv_asset")
        with pytest.raises(ValueError, match="legacy Recorder"):
            InvestigationSession(env, initial)
        with pytest.raises(ValueError, match="marked Recorder"):
            InvestigationSession(env, initial, investigation_recording=True)
        assert env.ledger.decisions == 0 and env.time_s == 0.02
    finally:
        env.close()
        recorder.close()
