"""Short real MuJoCo core traces; no GL, policy execution or complete pilot claim."""

import json
from pathlib import Path

import pytest

import pv_sim.recorder as recorder_module
from pv_sim.config import load_config
from pv_sim.contracts import Decision
from pv_sim.env import PVEnv
from pv_sim.recorder import ArtifactLimitError, Recorder, sha256_file
from pv_sim.replay import ReplayError, replay, verify_recording
from pv_sim.scenarios import BIT_GENERATOR, SEED_NAMESPACE, seed_streams

ROOT = Path(__file__).resolve().parents[2]


def command(action_id, kind, **kwargs):
    return dict(schema_version="1.0", action_id=action_id, kind=kind, timeout_s=3.0, **kwargs)


@pytest.fixture
def core_recording(tmp_path):
    config = load_config(ROOT / "configs/pilot.toml")
    recorder = Recorder(
        tmp_path / "runs" / "source",
        tmp_path / "private",
        metadata={"purpose": "core_test", "policy": "none_recorded_actions"},
    )
    env = PVEnv(config, enable_rendering=False, recorder=recorder)
    try:
        task, initial = env.reset(23, episode_id="core_replay_fixture")
        assert "rgb" not in task.sensors
        assert env.backend._renderer is None
        wait = command(1, "wait", duration_s=0.1)
        decision = Decision.model_validate_json(json.dumps({
            "schema_version": "1.0", "action": wait, "predictions": [],
            "hypothesis_probabilities": None, "unresolved_hypotheses": [],
            "evidence_refs": [initial.sequence_id], "rationale": "Recorded timing fixture.",
        }))
        env.ledger.policy_wall_s += 1.25
        recorder.decision(decision, 1.25, None)
        observed = env.step(wait)
        before_retry = env.tick
        duplicate = env.step(wait)
        assert duplicate == observed and env.tick == before_retry
        conflict = env.step(command(1, "wait", duration_s=0.2))
        assert conflict.feedback[-1].reason == "command_conflict"
        probed = env.step(command(2, "probe_voltage", voltages_v=[0.8], dwell_s=0.2))
        assert probed.feedback[-1].code == "completed"
        stopped = env.step(command(3, "safe_stop"))
        assert stopped.terminal and stopped.terminal_reason == "safe_stop"
        assert env.time_s <= 4.0
        assert env.backend._renderer is None
        metrics = env.metrics()
        assert metrics["core_only"] and not metrics["verification_tail_complete"]
        recorder.finish(metrics)
        yield recorder, initial, stopped, metrics
    finally:
        env.close()
        recorder.close()


def test_actual_mujoco_recorded_actions_replay_same_source_and_exact_ticks(
    core_recording, tmp_path
):
    recorder, _, _, metrics = core_recording
    manifest, _ = verify_recording(recorder.manifest_path)
    assert manifest["seed_streams"] == seed_streams(23)
    assert manifest["seed_namespace"] == SEED_NAMESPACE
    assert manifest["bit_generator"] == BIT_GENERATOR
    assert manifest["initial_state"]["tick"] == 0
    report = replay(
        recorder.manifest_path,
        tmp_path / "runs" / "replayed",
        private_root=tmp_path / "private",
    )
    assert report["status"] == "passed"
    assert all(report["provenance"].values())
    assert report["core_only"] and not report["rendered_gate_satisfied"]
    assert not report["policy_requeried"] and report["tick_mismatches"] == []
    assert len(report["observations"]) == 6  # reset, wait, duplicate, conflict, probe, stop
    assert all(item["passed"] for item in report["observations"])
    assert all(item["frames_compared"] == 0 for item in report["observations"])
    assert report["truth_comparison"]["passed"]
    assert report["truth_comparison"]["records_compared"] == metrics["tick"] + 1
    assert report["metrics_comparison"]["passed"]
    replay_private = tmp_path / "private" / "replayed"
    reproduced = json.loads((replay_private / "metrics.json").read_text())
    assert reproduced == json.loads((recorder.private_dir / "metrics.json").read_text())
    assert reproduced["policy_wall_s"] == metrics["policy_wall_s"] == 1.25
    replay_manifest, _ = verify_recording(replay_private / "manifest.json")
    assert replay_manifest["final_tick"] == manifest["final_tick"] == metrics["tick"]
    assert replay_manifest["metadata"]["purpose"] == "m1_replay"
    assert replay_manifest["replay_source"]["policy_requeried"] is False
    # Every private physical tick, including actual q/qdot and energy-independent
    # state, is reproduced exactly; global event sequence metadata is separate.
    original_truth = [
        json.loads(line)["payload"]
        for line in (recorder.private_dir / "truth.jsonl").read_text().splitlines()
    ]
    replay_truth = [
        json.loads(line)["payload"]
        for line in (replay_private / "truth.jsonl").read_text().splitlines()
    ]
    assert replay_truth == original_truth


@pytest.mark.parametrize("artifact", ["metrics.json", "truth.jsonl"])
def test_replay_reports_private_divergence_even_with_consistent_artifact_hashes(
    core_recording, tmp_path, artifact
):
    recorder, _, _, _ = core_recording
    path = recorder.private_dir / artifact
    if artifact == "metrics.json":
        altered = json.loads(path.read_text())
        altered["policy_wall_s"] = 9.25
        path.write_text(json.dumps(altered) + "\n")
    else:
        lines = path.read_text().splitlines()
        altered = json.loads(lines[1])
        altered["payload"]["temperature_c"] += 1.0
        lines[1] = json.dumps(altered)
        path.write_text("\n".join(lines) + "\n")
    # Deliberately construct a self-consistently hashed but semantically wrong
    # expected trace. This tests comparison, independently of integrity checks.
    manifest = json.loads(recorder.manifest_path.read_text())
    for item in manifest["artifacts"]:
        if item["scope"] == "private" and item["path"] == artifact:
            item.update(sha256=sha256_file(path), bytes=path.stat().st_size)
    recorder.manifest_path.write_text(json.dumps(manifest) + "\n")
    (recorder.private_dir / "manifest.sha256").write_text(
        sha256_file(recorder.manifest_path) + "\n"
    )
    verify_recording(recorder.manifest_path)
    report = replay(
        recorder.manifest_path,
        tmp_path / "runs" / "private_divergence",
        private_root=tmp_path / "private",
    )
    assert report["status"] == "failed"
    comparison = "metrics_comparison" if artifact == "metrics.json" else "truth_comparison"
    assert not report[comparison]["passed"]
    assert report[comparison]["mismatches"]


def test_replay_refuses_tampered_actions_before_creating_output(core_recording, tmp_path):
    recorder, _, _, _ = core_recording
    actions = recorder.public_dir / "actions.jsonl"
    actions.write_text(actions.read_text() + "\n")
    output = tmp_path / "runs" / "tampered_replay"
    with pytest.raises(ReplayError, match="artifact hash mismatch"):
        replay(recorder.manifest_path, output, private_root=tmp_path / "private")
    assert not output.exists()


def test_replay_refuses_existing_run_without_overwrite(core_recording, tmp_path):
    recorder, _, _, _ = core_recording
    output = tmp_path / "runs" / "existing"
    output.mkdir()
    evidence = output / "keep.txt"
    evidence.write_text("retain prior evidence")
    with pytest.raises(FileExistsError):
        replay(recorder.manifest_path, output, private_root=tmp_path / "private")
    assert evidence.read_text() == "retain prior evidence"


def test_artifact_cap_stops_append_and_preserves_failure_manifest(tmp_path, monkeypatch):
    config = load_config(ROOT / "configs/pilot.toml")
    recorder = Recorder(tmp_path / "runs" / "bounded", tmp_path / "private")
    env = PVEnv(config, enable_rendering=False, recorder=recorder)
    try:
        env.reset(47, episode_id="bounded_core_fixture")
        before = (recorder.private_dir / "truth.jsonl").read_bytes()
        # Reduce only the artifact budget in this resource-guard test; no physical
        # tolerance or renderer gate is changed and no large artifact is allocated.
        monkeypatch.setattr(
            recorder_module,
            "MAX_RUN_BYTES",
            recorder._written_bytes + recorder_module.MANIFEST_RESERVE_BYTES,
        )
        with pytest.raises(ArtifactLimitError, match="existing evidence retained"):
            recorder.truth({"tick": env.tick + 1, "additional": "guard fixture"})
        assert (recorder.private_dir / "truth.jsonl").read_bytes() == before
        recorder.abort("ArtifactLimitError", "test budget exhausted")
        manifest = json.loads(recorder.manifest_path.read_text())
        assert manifest["incomplete"] and manifest["status"] == "failed"
    finally:
        env.close()
        recorder.close()
