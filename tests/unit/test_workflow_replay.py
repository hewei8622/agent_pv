"""Evidence, visibility and seek regressions for the read-only workflow viewer."""

from __future__ import annotations

import base64
import copy
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from pv_sim.workflow_replay import (
    build_replay_index,
    derive_power,
    public_export,
    replay_state,
    sha256,
    validate_presentation_events,
    write_replay,
)


def dump_records(directory, stem, rows, json_array=False):
    suffix = ".json" if json_array else ".jsonl"
    data = json.dumps(rows) if json_array else "\n".join(json.dumps(r) for r in rows)
    (directory / (stem + suffix)).write_text(data)


@pytest.fixture
def retained(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    (public / "frames").mkdir()
    stream = io.BytesIO()
    Image.new("RGB", (4, 3), (24, 123, 67)).save(stream, "PNG")
    blob = stream.getvalue()
    (public / "frames/f.png").write_bytes(blob)
    task = {
        "episode_id": "test-episode",
        "budgets": {"time_s": 10.0, "rgb_frames": 4},
        "nominal_calibration": {"home_position_m": [0, -0.45, 0.35]},
    }
    (public / "task.json").write_text(json.dumps(task))

    def scalar(channel, value, capture, delivery):
        return {
            "channel": channel,
            "value": value,
            "sigma": 0.01,
            "t_capture_s": capture,
            "t_deliver_s": delivery,
            "validity": "valid",
        }

    obs = [
        {
            "tick": 10,
            "payload": {
                "sequence_id": 0,
                "t_deliver_s": 0.02,
                "remaining_budgets": {"time_s": 9.98, "rgb_frames": 4},
                "scalars": [scalar("voltage_v", 1.8, 0, 0.02), scalar("current_a", 0.5, 0, 0.02)],
            },
        },
        {
            "tick": 250,
            "payload": {
                "sequence_id": 1,
                "t_deliver_s": 0.5,
                "remaining_budgets": {"time_s": 9.5, "rgb_frames": 3},
                "scalars": [scalar("voltage_v", 2, 0.2, 0.3), scalar("current_a", 0.4, 0.2, 0.3)],
                "rgb": [
                    {
                        "frame_id": "f",
                        "width": 4,
                        "height": 3,
                        "t_start_s": 0.194,
                        "t_end_s": 0.206,
                        "t_capture_s": 0.2,
                        "t_deliver_s": 0.3,
                        "validity": "valid",
                        "png_file": "frames/f.png",
                        "png_sha256": sha256(blob),
                    }
                ],
                "feedback": [
                    {
                        "action_id": 1,
                        "code": "failed",
                        "t_accepted_s": 0.22,
                        "t_terminal_s": 0.4,
                        "commanded_target": {"slide_m": 0.12},
                        "measured_confirmation": [],
                        "reason": "actuator unavailable",
                    }
                ],
            },
        },
    ]
    decision = {
        "tick": 10,
        "payload": {
            "decision": {
                "action": {"kind": "move_camera", "action_id": 1, "slide_m": 0.12},
                "rationale": "Measure a different view.",
                "evidence_refs": [0],
                "predictions": [],
                "hypothesis_probabilities": None,
            },
            "wall_clock_latency_s": 0.003,
        },
    }
    actions = [
        {"tick": 10, "payload": {"raw_json": json.dumps(decision["payload"]["decision"]["action"])}}
    ]
    dump_records(public, "observations", obs)
    dump_records(public, "decisions", [decision])
    dump_records(public, "actions", actions)
    private = tmp_path / "evaluator"
    private.mkdir()
    config = {
        "private_world": {"hidden_secret": "TRUTH_CANARY", "panel_size_m": [0.3, 0.2]},
        "camera": {"home_position_m": [0, -0.45, 0.35]},
    }
    (private / "config.json").write_text(json.dumps(config))
    truth = []
    for t in [0, 0.5]:
        truth.append(
            {
                "payload": {
                    "time_s": t,
                    "point": {"voltage_v": 1.8, "current_a": 0.5, "power_w": 0.9},
                    "temperature_c": 25,
                    "reference_w_m2": 900 if t == 0 else 500,
                    "requested_voltage_v": 1.8,
                    "applied_voltage_v": 1.8,
                    "dynamics": {
                        "camera_position_m": [0, -0.45, 0.35],
                        "camera_rotation": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                        "q": [0, 0, 0],
                    },
                }
            }
        )
    dump_records(private, "truth", truth)
    artifacts = []
    for directory, scope in ((public, "public"), (private, "private")):
        for artifact in sorted(directory.rglob("*")):
            if artifact.is_file():
                artifacts.append(
                    {
                        "scope": scope,
                        "path": ("public/" if scope == "public" else "")
                        + artifact.relative_to(directory).as_posix(),
                        "sha256": sha256(artifact.read_bytes()),
                        "bytes": artifact.stat().st_size,
                    }
                )
    (private / "manifest.json").write_text(
        json.dumps(
            {
                "episode_id": task["episode_id"],
                "status": "complete",
                "incomplete": False,
                "artifacts": artifacts,
            }
        )
    )
    return public, private, obs, decision, blob


def test_power_uses_matched_public_values_and_both_references(retained):
    public, _, _, _, _ = retained
    data = build_replay_index(public)
    assert [p["value"] for p in data["public"]["power"]] == pytest.approx([0.9, 0.8])
    assert data["public"]["power"][1]["available_s"] == 0.5
    assert len(data["public"]["power"][1]["source_refs"]) == 2
    assert {r["visibility"] for r in data["public"]["power"][1]["source_refs"]} == {"public"}


@pytest.mark.parametrize("change", ["different_capture", "invalid_current", "missing_current"])
def test_power_does_not_fill_invalid_or_unmatched_pairs(retained, change):
    public, _, obs, _, _ = retained
    sample = obs[1]["payload"]["scalars"][1]
    if change == "different_capture":
        sample["t_capture_s"] = 0.25
    elif change == "invalid_current":
        sample["validity"] = "stale"
    else:
        obs[1]["payload"]["scalars"].pop()
    dump_records(public, "observations", obs)
    data = build_replay_index(public)
    assert len(data["public"]["power"]) == 1


def test_pair_uses_later_return_and_rejects_conflicting_duplicates():
    samples = [
        {
            "channel": channel,
            "value": value,
            "capture_s": 0.1,
            "delivery_s": 0.2,
            "available_s": available,
            "validity": "valid",
            "source_ref": {"row": row},
        }
        for row, (channel, value, available) in enumerate(
            [("voltage_v", 2, 0.3), ("current_a", 0.4, 0.8)]
        )
    ]
    assert derive_power(samples)[0]["available_s"] == 0.8
    with pytest.raises(ValueError, match="Conflicting"):
        derive_power(samples + [{**samples[0], "value": 3}])


@pytest.mark.parametrize("time", [0, 0.199, 0.2, 0.299, 0.3, 0.499])
def test_capture_and_delivery_do_not_advance_agent_availability(retained, time):
    data = build_replay_index(retained[0])
    state = replay_state(data, time)
    assert state["frame"] is None
    assert len(state["power"]) <= 1
    assert not any(e["kind"].startswith("rgb_") for e in state["events"])


def test_at_return_original_bytes_and_all_three_times_preserved(retained):
    data = build_replay_index(retained[0])
    frame = replay_state(data, 0.5)["frame"]
    assert (frame["capture_s"], frame["delivery_s"], frame["available_s"]) == (0.2, 0.3, 0.5)
    assert base64.b64decode(frame["data_url"].split(",", 1)[1]) == retained[4]
    assert frame["png_sha256"] == sha256(retained[4])


def test_seek_backwards_rebuilds_without_future_data(retained):
    data = build_replay_index(retained[0], evaluator_dir=retained[1])
    before = replay_state(data, 0.02)
    replay_state(data, 0.5, evaluator=True)
    assert replay_state(data, 0.02) == before
    assert before["decision"]["predictions"] == []
    assert "truth" not in before


def test_requested_pose_is_not_success_and_truth_stays_separate(retained):
    data = build_replay_index(retained[0], evaluator_dir=retained[1])
    state = replay_state(data, 0.5, evaluator=True)
    assert state["decision"]["action"]["slide_m"] == 0.12
    assert state["truth"]["camera_position_m"][0] == 0
    feedback = [e for e in state["events"] if e["kind"] == "action_failed"]
    assert feedback[0]["payload"]["measured_confirmation"] == []
    assert feedback[0]["time_s"] == 0.4 and feedback[0]["available_s"] == 0.5


def test_public_export_has_no_truth_private_geometry_sources_or_events(retained):
    data = build_replay_index(retained[0], evaluator_dir=retained[1])
    assert "TRUTH_CANARY" in json.dumps(data)
    public = public_export(data)
    serialized = json.dumps(public)
    assert "TRUTH_CANARY" not in serialized
    assert '"evaluator"' not in serialized
    assert "config.json" not in serialized and "truth.jsonl" not in serialized
    assert str(retained[1]) not in serialized
    assert all(e["visibility"] == "public" for e in public["events"])
    assert all(s["visibility"] == "public" for s in public["sources"])
    assert "evaluator" in data  # Export never mutates original evaluator data.


def test_public_build_does_not_read_adjacent_private_files(retained):
    (retained[1] / "config.json").write_text("NOT VALID JSON")
    data = build_replay_index(retained[0])
    assert data["export_kind"] == "public_only"
    assert "evaluator" not in data


def test_original_frame_hash_mismatch_fails_loudly(retained):
    (retained[0] / "frames/f.png").write_bytes(b"different")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_replay_index(retained[0])


def test_missing_frame_is_explicit_not_fabricated(retained):
    (retained[0] / "frames/f.png").unlink()
    data = build_replay_index(retained[0])
    state = replay_state(data, 0.5)
    assert state["frame"] is None
    assert state["frames"][0]["asset_status"] == "unavailable"


@pytest.mark.parametrize("validity", ["stale", "dropped", "invalid"])
def test_nonvalid_frame_not_presented_as_current_evidence(retained, validity):
    public, _, obs, _, _ = retained
    obs[1]["payload"]["rgb"][0]["validity"] = validity
    dump_records(public, "observations", obs)
    state = replay_state(build_replay_index(public), 0.5)
    assert state["frame"] is None
    assert state["frames"][0]["validity"] == validity


def test_frame_path_cannot_escape_public_directory(retained):
    public, _, obs, _, _ = retained
    obs[1]["payload"]["rgb"][0]["png_file"] = "../evaluator/config.json"
    dump_records(public, "observations", obs)
    with pytest.raises(ValueError, match="escapes"):
        build_replay_index(public)


def test_inconsistent_delivery_is_rejected(retained):
    public, _, obs, _, _ = retained
    obs[1]["payload"]["scalars"][0]["t_deliver_s"] = 0.6
    dump_records(public, "observations", obs)
    with pytest.raises(ValueError, match="inconsistent"):
        build_replay_index(public)


def test_missing_public_issue_time_is_not_guessed_from_private_dt(retained):
    public, private, _, decision, _ = retained
    decision["tick"] = 123
    dump_records(public, "decisions", [decision])
    with pytest.raises(ValueError, match="matching public return tick"):
        build_replay_index(public, evaluator_dir=private)


def test_decision_cannot_reference_future_observation(retained):
    public, _, _, decision, _ = retained
    decision["payload"]["decision"]["evidence_refs"] = [1]
    dump_records(public, "decisions", [decision])
    with pytest.raises(ValueError, match="future observation"):
        build_replay_index(public)


def test_source_fixture_array_format_and_direct_actions_supported(retained):
    public, _, obs, _, _ = retained
    (public / "observations.jsonl").unlink()
    (public / "decisions.jsonl").unlink()
    (public / "actions.jsonl").unlink()
    dump_records(public, "observations", obs, json_array=True)
    dump_records(
        public,
        "actions",
        [{"tick": 10, "payload": {"action_id": 1, "kind": "wait", "duration_s": 0.48}}],
        json_array=True,
    )
    data = build_replay_index(public, policy_label="Scripted source fixture; no policy")
    assert data["public"]["decisions"] == []
    assert data["public"]["actions"][0]["action"]["kind"] == "wait"


def test_write_offline_html_safe_json_and_exclusive_output(retained, tmp_path):
    public, _, _, decision, _ = retained
    attack = '</script><img src="https://example.invalid" onerror="alert(1)">'
    decision["payload"]["decision"]["rationale"] = attack
    dump_records(public, "decisions", [decision])
    data = build_replay_index(public)
    output = tmp_path / "viewer.html"
    manifest = write_replay(data, output)
    html = output.read_text()
    assert attack not in html
    assert "\\u003c/script>" in html
    assert "connect-src 'none'" in html
    assert "__WORKFLOW_DATA__" not in html
    assert manifest["html_sha256"] == sha256(output.read_bytes())
    start = html.index('<script id="workflow-data" type="application/json">')
    payload = html[start:].split(">", 1)[1].split("</script>", 1)[0]
    assert json.loads(payload)["public"]["decisions"][0]["rationale"] == attack
    with pytest.raises(FileExistsError):
        write_replay(data, output)


def test_generic_event_bridge_requires_hash_and_unique_id(retained):
    data = build_replay_index(retained[0])
    event = copy.deepcopy(data["events"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        validate_presentation_events([event, event])
    del event["source_ref"]["sha256"]
    with pytest.raises(ValueError, match="hashed record"):
        validate_presentation_events([event])


def test_progress_times_are_confirmations_not_inherited_acceptance(retained):
    public, _, obs, _, _ = retained
    obs[1]["payload"]["feedback"] = [
        {
            "action_id": 1,
            "code": "executing",
            "t_accepted_s": 0.1,
            "t_terminal_s": None,
            "commanded_target": {"kind": "probe_voltage"},
            "measured_confirmation": [
                {"sample": {"t_capture_s": capture, "t_deliver_s": capture + 0.01}}
            ],
        }
        for capture in [0.2, 0.3, 0.4]
    ]
    dump_records(public, "observations", obs)
    data = build_replay_index(public)
    progress = [e for e in data["events"] if e["kind"] == "action_executing"]
    assert [e["time_s"] for e in progress] == [0.2, 0.3, 0.4]
    assert all(e["available_s"] == 0.5 for e in progress)
    assert all(e["payload"]["t_accepted_s"] == 0.1 for e in progress)
    assert all("emission time unknown" in e["time_basis"] for e in progress)


def test_actual_viewer_javascript_hides_future_frames_and_future_plot_ranges(retained):
    """Execute the shipped JS with a tiny canvas sink; no browser/runtime dependency."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Optional Node JS QA unavailable; Python visibility contracts remain tested")
    data = build_replay_index(retained[0], evaluator_dir=retained[1])
    template = Path(__file__).parents[2] / "src/pv_sim/assets/workflow_viewer.html"
    script = template.read_text().split("</script><script>", 1)[1].split("</script>", 1)[0]
    script = script.replace("try{setup()}catch(e){fail(e)}", "")
    harness = r"""
const fs = require('fs'), vm = require('vm'), input = JSON.parse(fs.readFileSync(0,'utf8'));
let labels = [];
const ctx = {setTransform(){},clearRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},
  setLineDash(){},arc(){},fill(){},fillText(text){labels.push(text)}};
const canvas = {width:0,height:0,getBoundingClientRect(){return {width:400,height:145}},
  getContext(){return ctx}};
const context = {window:{devicePixelRatio:1},document:{getElementById(id){
  return id==='workflow-data'?{textContent:JSON.stringify(input.data)}:canvas}},console};
vm.createContext(context);
vm.runInContext(input.script,context);
const counts = vm.runInContext('[stateAt(.019).decisions.length,stateAt(.499).frames.length,'+
  'stateAt(.5).frames.length,stateAt(.02).power.length]',context);
vm.runInContext("time=.02;evaluator=false;plot('voltage_v',stateAt(.02))",context);
const before = labels; labels=[];
vm.runInContext("P.samples.filter(x=>x.available_s>.02).forEach(x=>x.value=999999);D.evaluator.truth.forEach(x=>x.voltage_v=888888);plot('voltage_v',stateAt(.02))",context);
const after = labels;labels=[];
vm.runInContext("evaluator=true;D.evaluator.truth[0].voltage_v=1.8;plot('voltage_v',stateAt(.02))",context);
const evalBefore=labels;labels=[];
vm.runInContext("D.evaluator.truth[1].voltage_v=999999999;plot('voltage_v',stateAt(.02))",context);
const missingEncoder=vm.runInContext("encoderSummary({validity:'missing',slide_m:null,"+
  "yaw_rad:null,pitch_rad:null,capture_s:.1,available_s:.2})",context);
const staleEncoder=vm.runInContext("encoderSummary({validity:'stale',slide_m:0,"+
  "yaw_rad:0,pitch_rad:0,capture_s:.1,available_s:.2})",context);
const missingWall=vm.runInContext("wallSummary([{wall_clock_latency_s:null}])",context);
process.stdout.write(JSON.stringify({counts,before,after,evalBefore,evalAfter:labels,
  missingEncoder,staleEncoder,missingWall}));
"""
    result = subprocess.run(
        [node, "-e", harness],
        input=json.dumps({"data": data, "script": script}),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    checked = json.loads(result.stdout)
    assert checked["counts"] == [0, 0, 1, 1]
    assert checked["before"] == checked["after"]
    assert checked["evalBefore"] == checked["evalAfter"]
    assert "missing" in checked["missingEncoder"] and "0.000" not in checked["missingEncoder"]
    assert "stale" in checked["staleEncoder"] and "valid current pose" in checked["staleEncoder"]
    assert "unrecorded" in checked["missingWall"] and "0.000" not in checked["missingWall"]


@pytest.mark.parametrize("validity", ["missing", "stale", "dropped", "invalid"])
def test_null_nonvalid_scalar_is_retained_as_a_gap(retained, validity):
    public, _, obs, _, _ = retained
    obs[1]["payload"]["scalars"][1].update(value=None, validity=validity)
    dump_records(public, "observations", obs)
    data = build_replay_index(public)
    assert data["public"]["samples"][-1]["value"] is None
    assert data["public"]["samples"][-1]["validity"] == validity
    assert len(data["public"]["power"]) == 1


def test_null_valid_scalar_is_an_invalid_record(retained):
    public, _, obs, _, _ = retained
    obs[1]["payload"]["scalars"][1]["value"] = None
    dump_records(public, "observations", obs)
    with pytest.raises(ValueError, match="missing sample value"):
        build_replay_index(public)


@pytest.mark.parametrize(
    "change",
    ["wrong_episode", "public_hash", "private_hash", "absent", "incomplete", "detached_hash"],
)
def test_evaluator_requires_verified_same_episode_and_artifact_manifest(retained, change):
    public, private, _, _, _ = retained
    manifest_path = private / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if change == "wrong_episode":
        manifest["episode_id"] = "different-episode"
    elif change in {"public_hash", "private_hash"}:
        scope = "public" if change == "public_hash" else "private"
        next(a for a in manifest["artifacts"] if a["scope"] == scope)["sha256"] = "0" * 64
    elif change == "incomplete":
        manifest["incomplete"] = True
    elif change == "detached_hash":
        (private / "manifest.sha256").write_text("0" * 64)
    manifest_path.write_text(json.dumps(manifest))
    if change == "absent":
        manifest_path.unlink()
    with pytest.raises(ValueError, match="manifest"):
        build_replay_index(public, evaluator_dir=private)
    assert build_replay_index(public)["export_kind"] == "public_only"


def test_verified_pairing_and_detached_hash_remain_evaluator_private(retained):
    public, private, _, _, _ = retained
    (private / "manifest.sha256").write_text(sha256((private / "manifest.json").read_bytes()))
    data = build_replay_index(public, evaluator_dir=private)
    assert data["evaluator"]["pairing"]["episode_id"] == "test-episode"
    assert data["evaluator"]["pairing"]["verified_artifacts"] == 7
    assert "detached_hash_source_ref" in data["evaluator"]["pairing"]
    export = public_export(data)
    assert "manifest.json" not in json.dumps(export)
    assert "manifest.sha256" not in json.dumps(export)
    assert '"pairing":' not in json.dumps(export)


@pytest.mark.parametrize(
    "change",
    [
        "acceptance_future",
        "terminal_future",
        "terminal_before_accept",
        "confirmation_capture_future",
        "confirmation_delivery_future",
    ],
)
def test_feedback_cannot_report_future_or_inconsistent_times(retained, change):
    public, _, obs, _, _ = retained
    feedback = obs[1]["payload"]["feedback"][0]
    if change == "acceptance_future":
        feedback["t_accepted_s"] = 0.6
    elif change == "terminal_future":
        feedback["t_terminal_s"] = 100
    elif change == "terminal_before_accept":
        feedback["t_terminal_s"] = 0.1
    else:
        feedback["measured_confirmation"] = [
            {
                "sample": {
                    "t_capture_s": 0.6 if change == "confirmation_capture_future" else 0.3,
                    "t_deliver_s": 0.7,
                }
            }
        ]
    dump_records(public, "observations", obs)
    with pytest.raises(ValueError):
        build_replay_index(public)


@pytest.mark.parametrize("change", ["decreasing_return", "duplicate_tick", "wrong_episode"])
def test_observation_identity_and_issue_time_mapping_unambiguous(retained, change):
    public, _, obs, _, _ = retained
    if change == "decreasing_return":
        obs.reverse()
    elif change == "duplicate_tick":
        obs[1]["tick"] = obs[0]["tick"]
    else:
        obs[1]["payload"]["episode_id"] = "wrong-episode"
    dump_records(public, "observations", obs)
    with pytest.raises(ValueError):
        build_replay_index(public)


def test_generic_public_event_cannot_precede_its_physical_time(retained):
    event = copy.deepcopy(build_replay_index(retained[0])["events"][0])
    event.update(time_s=100, available_s=0.5)
    with pytest.raises(ValueError, match="after its declared availability"):
        validate_presentation_events([event])


def test_actual_viewer_labels_follow_mode_without_stale_private_legend(retained):
    """Exercise actual DOM label updates for evaluator, public and public-only export."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Optional Node JS QA unavailable")
    data = build_replay_index(retained[0], evaluator_dir=retained[1])
    template = Path(__file__).parents[2] / "src/pv_sim/assets/workflow_viewer.html"
    script = template.read_text().split("</script><script>", 1)[1].split("</script>", 1)[0]
    script = script.replace("try{setup()}catch(e){fail(e)}", "")
    harness = r"""
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements={};
const context={window:{},document:{getElementById(id){
  if(id==='workflow-data')return {textContent:JSON.stringify(input.data)};
  return elements[id]||(elements[id]={textContent:'',hidden:false,disabled:false,style:{},
    setAttribute(name,value){this[name]=value}});
}}};
vm.createContext(context);vm.runInContext(input.script,context);
vm.runInContext('evaluator=true;renderPerspectiveLabels()',context);
const evaluator=JSON.parse(JSON.stringify(elements));
vm.runInContext('evaluator=false;renderPerspectiveLabels()',context);
const publicMode=JSON.parse(JSON.stringify(elements));
vm.runInContext('delete D.evaluator;evaluator=true;renderPerspectiveLabels()',context);
const publicExport=JSON.parse(JSON.stringify(elements));
process.stdout.write(JSON.stringify({evaluator,publicMode,publicExport}));
"""
    result = subprocess.run(
        [node, "-e", harness],
        input=json.dumps({"data": data, "script": script}),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    checked = json.loads(result.stdout)
    assert "actual private camera pose" in checked["evaluator"]["sceneLegend"]["textContent"]
    assert checked["evaluator"]["sceneControls"]["hidden"] is False
    assert "evaluator reconstruction" in checked["evaluator"]["scene"]["aria-label"]
    for name in ("publicMode", "publicExport"):
        view = checked[name]
        assert view["sceneControls"]["hidden"] is True
        assert view["reset"]["disabled"] is True
        assert "Delivered encoder evidence only" in view["sceneLegend"]["textContent"]
        assert "actual private camera pose" not in view["sceneLegend"]["textContent"]
        assert "No private traces" in view["plotLegend"]["textContent"]
        assert "Dotted gray" not in view["worldNote"]["textContent"]
        assert "Delivered voltage" in view["voltageHeading"]["textContent"]
        assert "geometry unavailable" in view["scene"]["aria-label"]
        assert "evaluator reconstruction" not in view["scene"]["aria-label"]
