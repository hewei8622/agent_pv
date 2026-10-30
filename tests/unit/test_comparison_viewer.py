"""Recorded-evidence invariants for the paired viewer; no rendering or network."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pv_sim.comparison_viewer import (
    build_comparison_index,
    comparison_state,
    public_export,
    write_comparison,
)
from pv_sim.config import load_config
from pv_sim.contracts import Decision, Finish, Prediction, Wait
from pv_sim.env import PVEnv
from pv_sim.interaction_contracts import InformationReply, InformationSource, InteractionRequest
from pv_sim.investigation import InformationChoice, InvestigationSession, PhysicalChoice
from pv_sim.recorder import Recorder
from pv_sim.workflow_replay import sha256

ROOT = Path(__file__).resolve().parents[2]


def dump(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def recorded(tmp_path):
    recorder = Recorder(tmp_path / "runs/episode", tmp_path / "private",
                        metadata={"execution_protocol": "investigation/1.0"})
    env = PVEnv(load_config(ROOT / "configs/pilot.toml"),
                enable_rendering=False, recorder=recorder)
    try:
        _, initial = env.reset(17, episode_id="paired_view_test")
        session = InvestigationSession(env, initial, investigation_recording=True)
        timing = []
        audit = []

        def submit(choice):
            boundary = session.context().history[-1].t_deliver_s
            timing.append({"choice_id": choice.choice_id, "simulation_time_s": boundary,
                           "wall_clock_latency_s": 0.002, "status": "accepted"})
            audit.append({"choice_id": choice.choice_id, "simulation_time_s": boundary,
                          "context_sequence_id": choice.context_sequence_id,
                          "world_model": None, "self_model": None,
                          "goals_satisfied": {"collect": True}, "alternatives": [],
                          "selected_operator": "observe", "basis": "fixture",
                          "expected_effect": "fresh samples"})
            return session.submit(choice)

        def physical(identity, action, predictions=()):
            return PhysicalChoice(
                choice_id=identity,
                context_sequence_id=session.context().history[-1].sequence_id,
                decision=Decision(schema_version="1.0", action=action, predictions=predictions,
                                  hypothesis_probabilities=None, unresolved_hypotheses=(),
                                  evidence_refs=(0,), rationale="Recorded numeric test"),
            )

        prediction = Prediction(query_id="voltage_check", action_id=1, channel="voltage_v",
                                horizon_s=0.68, mean=1.8, sigma=None, interval_90=None,
                                status="predicted")
        first = submit(physical("observe", Wait(schema_version="1.0", action_id=1,
                                                kind="wait", timeout_s=1.0, duration_s=0.3),
                                (prediction,)))
        request = InteractionRequest(episode_id="paired_view_test", request_id="q1",
                                     channel="internet", question="What is the instruction?",
                                     information_gap="Permission", intended_decision="Hold or test")
        submit(InformationChoice(choice_id="ask", request=request,
                                 context_sequence_id=first.sequence_id))
        session.complete("q1", InformationReply(outcome="available", text="Hold instruction.",
                                                provenance="simulated",
                                                sources=(InformationSource(title="Fixture"),)))
        obs = submit(physical("check", Wait(schema_version="1.0", action_id=2,
                                            kind="wait", timeout_s=1.5, duration_s=0.8)))
        submit(physical("finish", Finish(schema_version="1.0", action_id=3, kind="finish",
                                          timeout_s=2.0, resolution="unresolved")))
        terminal = next(f.t_terminal_s for f in first.feedback
                        if f.action_id == 1 and f.code == "completed")
        obs = next(o for o in session.context().history if any(
            s.channel == "voltage_v" and abs(s.t_capture_s - 0.7) < 1e-9 for s in o.scalars))
        sample = next(s for s in obs.scalars if s.channel == "voltage_v"
                      and abs(s.t_capture_s - 0.7) < 1e-9)
        session.save(recorder.public_dir / "investigation.json")
        dump(recorder.public_dir / "decision_timing.json", timing)
        dump(recorder.public_dir / "policy_audit.json", audit)
        dump(recorder.public_dir / "public_brief.json", {"known_instruction": None})
        dump(recorder.public_dir / "verification.json", [{
            "choice_id": "observe", "prediction": prediction.model_dump(mode="json"),
            "predicted_capture_s": initial.t_deliver_s + prediction.horizon_s,
            "available_s": obs.t_deliver_s, "capture_s": sample.t_capture_s,
            "delivery_s": sample.t_deliver_s, "observed": sample.value,
            "residual": sample.value - 1.8, "tolerance": 0.02,
            "passed": abs(sample.value - 1.8) <= 0.02, "fresh_after_s": terminal,
            "freshness_action_id": 1, "observation_sequence_id": obs.sequence_id,
        }])
        dump(recorder.public_dir / "assessment.json", {"operational_verified": True})
        dump(recorder.private_dir / "result.json", {"case_id": "C01", "arm": "R",
                                                       "evaluation": {
            "success": True, "private_canary": "hidden-result-784", "raw_costs": {
                "simulated_time_s": env.time_s, "pv_energy_j": 12.0}}})
        recorder.finish(env.metrics())
    finally:
        env.close()
        recorder.close()
    shutil.copytree(tmp_path / "runs/episode", tmp_path / "runs/episodeA")
    shutil.copytree(tmp_path / "private/episode", tmp_path / "private/episodeA")
    result_path = tmp_path / "private/episodeA/result.json"
    result = json.loads(result_path.read_text())
    result["arm"] = "A"
    dump(result_path, result)
    manifest_path = tmp_path / "private/episodeA/manifest.json"
    original = json.loads(manifest_path.read_text())
    for item in original["artifacts"]:
        if item["scope"] == "private" and item["path"] == "result.json":
            item["sha256"] = sha256(result_path.read_bytes())
            item["bytes"] = result_path.stat().st_size
    dump(manifest_path, original)
    manifest_path.with_suffix(".sha256").write_text(sha256(manifest_path.read_bytes()))
    manifest = {
        "schema_version": "paired_investigation.v1",
        "cases": [{"case_id": "C01", "label": "Hidden condition 784", "arms": {
            arm: {"public_dir": f"runs/episode{suffix}/public",
                  "evaluator_dir": f"private/episode{suffix}",
                  "summary_path": f"private/episode{suffix}/result.json"}
            for arm, suffix in (("R", ""), ("A", "A"))}}],
    }
    path = tmp_path / "paired_manifest.json"
    dump(path, manifest)
    return path


def rewrite_unbound(path, stem, edit):
    p = path.parent / "runs/episode/public" / stem
    value = json.loads(p.read_text())
    edit(value)
    dump(p, value)


def test_real_trace_choices_pause_and_verification_have_exact_availability(recorded):
    index = build_comparison_index(recorded)
    episode = index["cases"][0]["arms"]["R"]
    reply = next(e for e in episode["public"]["exchanges"] if e["phase"] == "completed")
    before = comparison_state(index, "C01", reply["available_s"] - 0.001)
    after = comparison_state(index, "C01", reply["available_s"])
    assert not any(e["phase"] == "completed" for e in before["arms"]["R"]["exchanges"])
    assert after["arms"]["R"]["exchanges"][-1]["reply"]["text"] == "Hold instruction."
    check = episode["public"]["verifications"][0]
    assert not comparison_state(index, "C01", check["available_s"] - .001)["arms"]["R"][
        "verifications"]
    assert comparison_state(index, "C01", check["available_s"])["arms"]["R"][
        "verifications"][0]["observed"] == check["observed"]
    assert episode["evaluator"]["pairing"]["verified_artifacts"] >= 10
    assert "disconnected" in episode["evaluator"]["truth"][-1]
    assert "terminal_reason" in episode["evaluator"]["truth"][-1]


def test_public_export_physically_removes_all_private_values_sources_and_labels(recorded):
    index = build_comparison_index(recorded)
    exported = public_export(index)
    encoded = json.dumps(exported)
    assert "hidden-result-784" not in encoded
    assert "Hidden condition 784" not in encoded
    assert '"geometry"' not in encoded
    assert '"truth"' not in encoded
    assert '"camera_position_m"' not in encoded
    assert '"private_evaluator"' not in encoded
    assert '"evaluator_label"' not in encoded
    assert "Hold instruction." in encoded
    assert "evaluator" in index["cases"][0]["arms"]["R"]
    assert "evaluator" not in exported["cases"][0]["arms"]["R"]


def test_public_build_does_not_open_private_inputs(recorded):
    shutil.rmtree(recorded.parent / "private")
    index = build_comparison_index(recorded, evaluator=False)
    assert index["export_kind"] == "public_only"
    assert "evaluator" not in index["cases"][0]["arms"]["A"]


@pytest.mark.parametrize("filename", ["investigation.json", "decision_timing.json",
                                      "policy_audit.json", "verification.json", "assessment.json",
                                      "public_brief.json"])
def test_changed_retained_artifact_is_rejected_even_if_semantically_equivalent(recorded, filename):
    path = recorded.parent / "runs/episode/public" / filename
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="hash binding failed"):
        build_comparison_index(recorded)


def test_changed_private_result_is_not_accepted_as_original(recorded):
    path = recorded.parent / "private/episode/result.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="hash binding failed"):
        build_comparison_index(recorded)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("observed", 999.0, "exactly one public sample"),
    ("predicted_capture_s", 0.6, "precommitted horizon"),
    ("fresh_after_s", 0.0, "own completed action terminal"),
    ("freshness_action_id", 2, "match prediction action"),
    ("passed", False, "passed flag"),
    ("residual", 10.0, "residual"),
    ("available_s", 0.02, "available observation"),
])
def test_verification_does_not_invent_evidence(recorded, field, value, message):
    rewrite_unbound(recorded, "verification.json", lambda rows: rows[0].update({field: value}))
    with pytest.raises(ValueError, match=message):
        build_comparison_index(recorded, evaluator=False)


def test_missing_prediction_outcome_is_visible_only_at_episode_end(recorded):
    def missing(rows):
        for key in ("capture_s", "available_s", "delivery_s", "observed", "residual",
                    "observation_sequence_id"):
            rows[0][key] = None
        rows[0]["passed"] = False
    rewrite_unbound(recorded, "verification.json", missing)
    index = build_comparison_index(recorded, evaluator=False)
    end = index["cases"][0]["duration_s"]
    assert not comparison_state(index, "C01", end - .001)["arms"]["R"]["verifications"]
    checks = comparison_state(index, "C01", end)["arms"]["R"]["verifications"]
    assert checks[0]["outcome_status"] == "missing" and not checks[0]["passed"]


def test_audit_future_state_cannot_be_presented_as_current(recorded):
    rewrite_unbound(recorded, "policy_audit.json",
                    lambda rows: rows[0].update(simulation_time_s=999))
    with pytest.raises(ValueError, match="committed boundary"):
        build_comparison_index(recorded, evaluator=False)


def test_case_and_common_horizon_validation(recorded):
    raw = json.loads(recorded.read_text())
    raw["cases"].append(raw["cases"][0])
    dump(recorded, raw)
    with pytest.raises(ValueError, match="unique"):
        build_comparison_index(recorded)


def test_seek_is_pure_and_does_not_carry_future_private_state_backward(recorded):
    index = build_comparison_index(recorded)
    state = comparison_state(index, "C01", .02)
    comparison_state(index, "C01", 100, evaluator=True)
    assert comparison_state(index, "C01", .02) == state
    assert "truth" not in state["arms"]["R"]
    assert not state["arms"]["R"]["assessment"]
    assert not state["arms"]["R"]["exchanges"]
    assert "result" not in state["arms"]["R"]
    with pytest.raises(ValueError, match="Unknown"):
        comparison_state(index, "unrecorded", 1)


def test_html_escapes_recorded_text_and_refuses_retained_output_overwrite(recorded, tmp_path):
    index = build_comparison_index(recorded)
    index["cases"][0]["label"] = '</script><img src=x onerror="alert(1)">'
    output = tmp_path / "replay.html"
    manifest = write_comparison(index, output)
    text = output.read_text()
    assert '</script><img' not in text
    assert '\\u003c/script>' in text
    assert manifest["html_sha256"] == sha256(output.read_bytes())
    assert "connect-src 'none'" in text
    assert "https://" not in text
    with pytest.raises(FileExistsError):
        write_comparison(index, output)


def test_actual_shipped_javascript_seek_matches_python_and_excludes_future_scale(recorded):
    node = shutil.which("node")
    assert node, "Existing Node runtime is needed for the shipped JavaScript regression"
    index = build_comparison_index(recorded)
    template = (ROOT / "src/pv_sim/assets/comparison_viewer.html").read_text()
    script = template.split('<script>')[1].split('</script>')[0]
    program = "const window={__COMPARISON_TEST__:true};const Dfixture=" + json.dumps(index) + ";"
    program += "const document={getElementById:()=>({textContent:JSON.stringify(Dfixture)})};"
    program += script
    program += '''
const unknown=window.comparisonReplay.predictionLabel(
 {channel:'current_a',status:'not_predictable',mean:null,horizon_s:.5},2.82);
if(!unknown.includes('not predictable (declared)')||unknown.includes('unrecorded'))
 throw Error('explicit nonprediction was mislabelled');
const numeric=window.comparisonReplay.predictionLabel(
 {channel:'voltage_v',status:'predicted',mean:1.8,horizon_s:1},.02);
if(!numeric.includes('1.800 at 1.020'))throw Error('recorded numeric prediction was lost');
const early=window.comparisonReplay.stateAt('C01',.02,false);
const range=window.comparisonReplay.plotData('power_w','C01',.02,false);
window.comparisonReplay.stateAt('C01',100,true);
const repeated=window.comparisonReplay.stateAt('C01',.02,false);
for(const arm of Object.values(Dfixture.cases[0].arms)){
  arm.public.power.push({value:1e12,available_s:99});
  arm.evaluator.truth.push({time_s:99,power_w:1e12});
}
const after=window.comparisonReplay.plotData('power_w','C01',.02,false);
if(JSON.stringify(early)!==JSON.stringify(repeated))throw Error('non-deterministic seek');
if(range.lo!==after.lo||range.hi!==after.hi)throw Error('future plot scale leak');
console.log(JSON.stringify(early));
'''
    run = subprocess.run([node, "-"], input=program, text=True, capture_output=True, check=True)
    actual = json.loads(run.stdout)
    expected = comparison_state(index, "C01", .02)
    for arm in ("R", "A"):
        for field in ("samples", "power", "decisions", "exchanges", "verifications", "assessment"):
            assert actual["arms"][arm][field] == expected["arms"][arm][field]


def test_swapped_evaluator_arm_is_rejected(recorded):
    manifest = json.loads(recorded.read_text())
    manifest["cases"][0]["arms"]["A"]["summary_path"] = "private/episode/result.json"
    dump(recorded, manifest)
    with pytest.raises(ValueError, match="case and arm"):
        build_comparison_index(recorded)


def test_unequal_authorized_prior_is_not_a_matched_pair(recorded):
    path = recorded.parent / "runs/episodeA/public/public_brief.json"
    dump(path, {"known_instruction": "hold"})
    with pytest.raises(ValueError, match="same authorized public prior"):
        build_comparison_index(recorded, evaluator=False)
