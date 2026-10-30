import base64
import copy
import hashlib
import json
import math
import tomllib
from pathlib import Path

import pytest

from pv_sim.config import load_config
from pv_sim.contracts import Decision, Observation
from pv_sim.recorder import Recorder, sha256_file
from pv_sim.replay import ReplayError, compare_observations, read_observation, verify_recording

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config():
    return load_config(ROOT / "configs/pilot.toml")


@pytest.fixture
def tolerances():
    return tomllib.loads((ROOT / "configs/tolerances.toml").read_text())["m1_replay"]


def valid(model, value):
    return model.model_validate_json(json.dumps(value))


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_recording_separates_private_data_and_finalizes_hashes(
    tmp_path, config, task, observation, decision
):
    recorder = Recorder(
        tmp_path / "runs" / "sample",
        tmp_path / "private",
        metadata={"purpose": "core_test", "policy": "fixture"},
    )
    assert json.loads(recorder.manifest_path.read_text())["incomplete"]
    recorder.start(config, 9864321, task)
    recorder.truth({"tick": 0, "private_canary": "PRIVATE_TRUTH_CANARY"})
    recorder.observation(valid(Observation, observation), tick=10)
    recorder.decision(valid(Decision, decision), 0.001, None)
    recorder.action(decision["action"], 10)
    returned = copy.deepcopy(observation)
    returned.update(sequence_id=1, t_deliver_s=0.04)
    recorder.observation(valid(Observation, returned), tick=20)
    recorder.finish({"private_canary": "PRIVATE_METRIC_CANARY", "energy_j": 0.1})
    manifest, original = verify_recording(recorder.manifest_path)
    assert original == recorder.output
    assert not manifest["incomplete"] and manifest["status"] == "complete"
    assert manifest["metadata"]["purpose"] == "core_test"
    assert manifest["seed"] == 9864321
    assert manifest["episode_id"] == task.episode_id
    assert manifest["config_sha256"] == config.sha256()
    assert manifest["initial_state"]["private_canary"] == "PRIVATE_TRUTH_CANARY"
    assert manifest["final_tick"] == 20
    initial = recorder.private_dir / "manifest.initial.json"
    assert sha256_file(initial) == manifest["initial_manifest_sha256"]
    assert json.loads(initial.read_text())["incomplete"]
    public_text = "".join(path.read_text() for path in recorder.public_dir.glob("*.json*"))
    assert "PRIVATE_TRUTH_CANARY" not in public_text
    assert "PRIVATE_METRIC_CANARY" not in public_text
    assert "9864321" not in public_text
    assert "private_world" not in public_text
    sequence = []
    for directory in (recorder.public_dir, recorder.private_dir):
        for path in directory.glob("*.jsonl"):
            sequence.extend(item["sequence"] for item in events(path))
    assert sorted(sequence) == list(range(manifest["event_count"]))
    with pytest.raises(RuntimeError, match="running"):
        recorder.observation(valid(Observation, returned), tick=20)


def test_overwrite_and_companion_collisions_refused(tmp_path):
    output = tmp_path / "runs" / "same"
    recorder = Recorder(output, tmp_path / "private")
    with pytest.raises(FileExistsError):
        Recorder(output, tmp_path / "other_private")
    with pytest.raises(FileExistsError):
        Recorder(tmp_path / "other_runs" / "same", tmp_path / "private")
    assert json.loads(recorder.manifest_path.read_text())["incomplete"]


@pytest.mark.parametrize("name", ["invalid.name", "with space", ".hidden"])
def test_invalid_run_names_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="identifier"):
        Recorder(tmp_path / name, tmp_path / "private")


def test_nested_public_private_directories_rejected(tmp_path):
    with pytest.raises(ValueError, match="separate"):
        Recorder(tmp_path / "run", tmp_path / "run" / "private")


def test_incomplete_and_failed_runs_remain_explicit(tmp_path, config, task):
    recorder = Recorder(tmp_path / "runs" / "interrupted", tmp_path / "private")
    recorder.start(config, 11, task)
    recorder.truth({"tick": 0, "state": "initial"})
    recorder.close()
    with pytest.raises(ReplayError, match="incomplete"):
        verify_recording(recorder.manifest_path)
    recorder.abort("FixtureFailure", "deliberate private test failure")
    manifest = json.loads(recorder.manifest_path.read_text())
    assert manifest["status"] == "failed" and manifest["incomplete"]
    assert manifest["failure"]["type"] == "FixtureFailure"
    assert (recorder.private_dir / "truth.jsonl").is_file()
    assert sha256_file(recorder.manifest_path) == (
        recorder.private_dir / "manifest.sha256"
    ).read_text().strip()
    with pytest.raises(RuntimeError):
        recorder.finish({})


def test_raw_invalid_actions_and_duplicate_observations_are_preserved(
    tmp_path, config, task, observation
):
    recorder = Recorder(tmp_path / "runs" / "invalid_actions", tmp_path / "private")
    recorder.start(config, 11, task)
    obs = valid(Observation, observation)
    recorder.observation(obs, tick=10)
    recorder.action({"action_id": 1, "voltage_v": float("nan")}, 10)
    recorder.observation(obs, tick=10)
    recorder.action("not JSON", 10)
    recorder.observation(obs, tick=10)
    recorder.finish({})
    actions = events(recorder.public_dir / "actions.jsonl")
    assert math.isnan(json.loads(actions[0]["payload"]["raw_json"])["voltage_v"])
    assert json.loads(actions[1]["payload"]["raw_json"]) == "not JSON"
    observed = events(recorder.public_dir / "observations.jsonl")
    assert len(observed) == 3 and observed[0]["payload"] == observed[2]["payload"]


def test_nonmonotonic_and_nonfinite_events_rejected(tmp_path, config, task):
    recorder = Recorder(tmp_path / "runs" / "ordering", tmp_path / "private")
    recorder.start(config, 11, task)
    recorder.truth({"tick": 5, "temperature_c": 25.0})
    with pytest.raises(ValueError, match="monotonic"):
        recorder.truth({"tick": 4})
    with pytest.raises(ValueError):
        recorder.truth({"tick": 6, "temperature_c": float("nan")})
    assert len(events(recorder.private_dir / "truth.jsonl")) == 1
    recorder.close()


def add_real_frame(observation, task):
    # This is the retained, provenance-backed M0 real-render fixture, not a stand-in render.
    raw = (ROOT / "tests/fixtures/m0_agent_rgb.png").read_bytes()
    result = copy.deepcopy(observation)
    result["rgb"] = [
        {
            "frame_id": "opaque_frame_1",
            "camera_id": "agent_rgb",
            "width": 640,
            "height": 480,
            "encoding": "png_rgb8",
            "png_base64": base64.b64encode(raw).decode("ascii"),
            "calibration_id": task.nominal_calibration.calibration_id,
            "k": task.nominal_calibration.k,
            "t_start_s": 0.004,
            "t_capture_s": 0.010,
            "t_end_s": 0.016,
            "t_deliver_s": 0.020,
            "validity": "valid",
            "exposure": {"duration_s": 0.012, "approximation": "midpoint_snapshot"},
        }
    ]
    return valid(Observation, result), raw


def test_real_png_saved_once_and_hydrated_without_host_path_leakage(
    tmp_path, config, task, observation, tolerances
):
    recorder = Recorder(tmp_path / "runs" / "frames", tmp_path / "private")
    recorder.start(config, 11, task)
    obs, raw = add_real_frame(observation, task)
    recorder.observation(obs, tick=10)
    recorder.observation(obs, tick=10)
    recorder.finish({})
    logged = events(recorder.public_dir / "observations.jsonl")
    frame = logged[0]["payload"]["rgb"][0]
    assert frame["png_file"] == "frames/opaque_frame_1.png"
    assert frame["png_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "png_base64" not in frame
    assert str(tmp_path) not in json.dumps(logged)
    assert len(list((recorder.public_dir / "frames").iterdir())) == 1
    hydrated = read_observation(logged[0], recorder.public_dir)
    assert hydrated == obs
    comparison = compare_observations(obs, hydrated, tolerances)
    assert comparison["passed"] and comparison["frames_compared"] == 1
    assert comparison["maximum_pixel_absolute_error"] == 0
    assert comparison["maximum_frame_mean_absolute_error"] == 0


def test_hash_mutation_detected(tmp_path, config, task, observation):
    recorder = Recorder(tmp_path / "runs" / "tampered", tmp_path / "private")
    recorder.start(config, 11, task)
    recorder.observation(valid(Observation, observation), tick=10)
    recorder.finish({})
    path = recorder.public_dir / "observations.jsonl"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ReplayError, match="artifact hash mismatch"):
        verify_recording(recorder.manifest_path)


def test_comparison_detects_numeric_timestamp_and_feedback_changes(observation, tolerances):
    expected = valid(Observation, observation)
    numeric = copy.deepcopy(observation)
    numeric["scalars"][0]["value"] += 1e-7
    assert not compare_observations(expected, valid(Observation, numeric), tolerances)["passed"]
    timestamp = copy.deepcopy(observation)
    timestamp["t_deliver_s"] += 1e-12
    comparison = compare_observations(expected, valid(Observation, timestamp), tolerances)
    assert comparison["mismatches"] == ["observation.t_deliver_s:timestamp"]
    feedback = copy.deepcopy(observation)
    feedback["feedback"] = [
        {
            "action_id": 1,
            "code": "rejected",
            "reason": "invalid_payload",
            "t_accepted_s": None,
            "t_terminal_s": 0.02,
            "commanded_target": None,
            "measured_confirmation": [],
        }
    ]
    assert not compare_observations(expected, valid(Observation, feedback), tolerances)["passed"]


def test_frame_path_escape_refused(tmp_path, config, task, observation):
    recorder = Recorder(tmp_path / "runs" / "frame_paths", tmp_path / "private")
    recorder.start(config, 11, task)
    obs, _ = add_real_frame(observation, task)
    recorder.observation(obs, tick=10)
    event = events(recorder.public_dir / "observations.jsonl")[0]
    event["payload"]["rgb"][0]["png_file"] = "../private.png"
    with pytest.raises(ReplayError, match="frame reference"):
        read_observation(event, recorder.public_dir)
    recorder.close()
