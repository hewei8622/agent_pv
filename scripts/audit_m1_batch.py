#!/usr/bin/env python3
"""Read-only machine audit of a completed M1 desktop batch; never runs simulation.

A passing report still requires visual inspection and fresh independent review.
Recorded hashes establish integrity against the saved manifest, not authenticity
against a malicious evidence author. This tool does not manufacture absent data.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pv_sim.config import Config, load_config
from pv_sim.contracts import ACTION_ADAPTER, Decision, PublicTask, validate_observation_context
from pv_sim.recorder import runtime_metadata, sha256_file
from pv_sim.replay import ReplayError, read_observation, verify_recording

ROOT = Path(__file__).resolve().parents[1]
PASS_STATUS = "machine_checks_passed_pending_visual_and_independent_review"
SEEDS = (11, 23, 47)
RUNTIME_KEYS = ("python", "platform", "machine", "libraries", "renderer", "mujoco_gl")

# Frozen by collect-only evidence on 2026-10-17; no renderer runs during this audit.
REQUIRED_RENDER_CASES = {
    ("tests.render.test_calibration", "test_required_real_named_rgb"),
    ("tests.render.test_calibration", "test_actual_camera_basis_independent_expectation"),
    ("tests.render.test_m1_camera", "test_required_rgb_actual_body_fixed_camera_and_motion"),
    (
        "tests.render.test_m1_loop",
        "test_actual_rgb_scan_probe_and_new_operating_point_verification",
    ),
    *(
        (
            "tests.render.test_calibration",
            f"test_fiducial_projection_from_analytic_geometry[{case}]",
        )
        for case in ("0--0.1", "1-0.0", "2-0.1")
    ),
    *(
        (
            "tests.render.test_m1_camera",
            f"test_fiducials_follow_measured_pose_analytic_projection[{case}-{view}]",
        )
        for case in ("0--0.1", "1-0.0", "2-0.1")
        for view in range(5)
    ),
}


class AuditError(ValueError):
    pass


class IncompleteAudit(AuditError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def json_file(path: Path) -> Any:
    def invalid_constant(value):
        raise AuditError(f"nonfinite JSON constant: {value}")

    return json.loads(path.read_text(), parse_constant=invalid_constant)


def json_lines(path: Path) -> list[dict]:
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def child(root: Path, relative: str) -> Path:
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "unsafe relative evidence path")
    result = (root / path).resolve()
    require(root.resolve() in result.parents, "evidence path escapes its declared directory")
    return result


def finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def aligned(value: float, dt: float) -> int:
    require(finite(value) and value >= 0, "timestamp is not finite and nonnegative")
    tick = round(value / dt)
    require(math.isclose(value, tick * dt, rel_tol=0, abs_tol=1e-10), "timestamp off tick grid")
    return tick


def expected_commands(batch_id: str) -> list[tuple[str, list[str]]]:
    commands = [
        (
            "tests",
            [
                "uv",
                "run",
                "--locked",
                "python",
                "-m",
                "pytest",
                "tests",
                "-q",
                f"--junitxml=runs/{batch_id}/tests.xml",
            ],
        )
    ]
    for seed in SEEDS:
        run_id = f"{batch_id}-s{seed}"
        commands.extend(
            [
                (
                    f"pilot-{seed}",
                    [
                        "uv",
                        "run",
                        "--locked",
                        "pv-sim",
                        "demo",
                        "--config",
                        "configs/pilot.toml",
                        "--seed",
                        str(seed),
                        "--policy",
                        "scan",
                        "--output",
                        f"runs/{run_id}",
                    ],
                ),
                (
                    f"replay-{seed}",
                    [
                        "uv",
                        "run",
                        "--locked",
                        "pv-sim",
                        "replay",
                        "--manifest",
                        f"private_eval/{run_id}/manifest.json",
                        "--output",
                        f"runs/{run_id}-replay",
                    ],
                ),
            ]
        )
    return commands


def load_test_inventory(path: Path) -> set[tuple[str, str]]:
    inventory = json_file(path)
    require(inventory["schema_version"] == "1.0", "unknown test inventory schema")
    cases = inventory["cases"]
    require(isinstance(cases, list) and bool(cases), "test inventory is empty")
    require(
        all(
            isinstance(case, dict)
            and set(case) == {"classname", "name"}
            and all(isinstance(value, str) and value for value in case.values())
            for case in cases
        ),
        "malformed test inventory identity",
    )
    identities = {(case["classname"], case["name"]) for case in cases}
    require(
        len(identities) == len(cases) == inventory["collected_testcases"],
        "test inventory count or uniqueness mismatch",
    )
    require(REQUIRED_RENDER_CASES <= identities, "test inventory omits required render cases")
    return identities


def check_junit(
    path: Path, *, inventory_path: Path = ROOT / "configs/m1_test_inventory.json"
) -> dict:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    require(bool(cases), "JUnit has no executed testcase records")
    for node in root.iter():
        require(
            node.tag not in {"failure", "error", "skipped"}, "JUnit contains failure/error/skip"
        )
        for name in ("failures", "errors", "skipped"):
            require(int(node.attrib.get(name, 0)) == 0, f"JUnit reports {name}")
    for suite in root.iter("testsuite"):
        direct_cases = suite.findall("testcase")
        if direct_cases:
            require(int(suite.attrib["tests"]) == len(direct_cases), "JUnit test count mismatch")
    identities = [(case.attrib.get("classname", ""), case.attrib.get("name", "")) for case in cases]
    require(len(set(identities)) == len(identities), "JUnit contains duplicate testcase identities")
    missing = REQUIRED_RENDER_CASES - set(identities)
    require(not missing, "required render testcase absent: " + repr(sorted(missing)))
    inventory = load_test_inventory(inventory_path)
    require(
        set(identities) == inventory,
        "complete-suite inventory mismatch: "
        f"{len(inventory - set(identities))} missing, "
        f"{len(set(identities) - inventory)} unexpected",
    )
    return {
        "test_inventory_sha256": sha256_file(inventory_path),
        "required_total_cases": len(inventory),
        "executed_testcases": len(cases),
        "required_render_cases": len(REQUIRED_RENDER_CASES),
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }


def check_pytest_summary(stdout: str, executed_cases: int) -> int:
    # Colours are presentation only; collection filters must never be hidden by them.
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", stdout)
    require(
        re.search(r"\b\d+\s+deselected\b", clean, re.IGNORECASE) is None,
        "recorded pytest stdout reports deselected tests",
    )
    summaries = re.findall(
        r"^\s*(?:=+\s*)?(\d+)\s+passed(?:,\s+\d+\s+warnings?)?\s+in\s+"
        r"\d+(?:\.\d+)?s(?:\s+\([^)]*\))?\s*(?:=+)?\s*$",
        clean,
        re.MULTILINE,
    )
    require(len(summaries) == 1, "pytest stdout lacks one unambiguous all-passed summary")
    passed = int(summaries[0])
    require(passed == executed_cases, "pytest passed count disagrees with complete JUnit inventory")
    return passed


def check_commands(root: Path, batch_id: str, batch: dict) -> dict:
    directory = root / "runs" / batch_id
    expected = expected_commands(batch_id)
    require(
        batch["results"] == [{"label": label, "exit_code": 0} for label, _ in expected],
        "batch results do not contain exactly the seven successful commands",
    )
    planned = json_file(directory / "planned.json")
    require(
        planned["commands"] == [[label, argv] for label, argv in expected],
        "planned command list disagrees with the frozen batch",
    )
    all_entries = json_lines(directory / "evidence/commands.jsonl")
    entries = [entry for entry in all_entries if entry.get("label") != "audit"]
    for entry in all_entries:
        if entry.get("label") == "audit":
            require(
                any(str(value).endswith("audit_m1_batch.py") for value in entry.get("argv", [])),
                "extra audit entry does not invoke the audit tool",
            )
    require(len(entries) == len(expected), "command evidence is missing, duplicated or unexpected")
    previous_end = None
    for entry, (label, argv) in zip(entries, expected, strict=True):
        require(
            entry["label"] == label and entry["argv"] == argv and entry["exit_code"] == 0,
            f"recorded command mismatch or failure: {label}",
        )
        require(
            Path(entry["cwd"]).resolve() == root.resolve(),
            "recorded command used another workspace",
        )
        start, end = (datetime.fromisoformat(entry[key]) for key in ("started_utc", "ended_utc"))
        require(
            start.tzinfo is not None and end.tzinfo is not None and end >= start,
            "invalid command wall-clock interval",
        )
        require(previous_end is None or start >= previous_end, "recorded command intervals overlap")
        previous_end = end
        require(
            finite(entry["elapsed_s"]) and 0 <= entry["elapsed_s"] <= 1800,
            "command duration exceeds work bound",
        )
        for stream in ("stdout", "stderr"):
            path = child(root, entry[stream])
            require(
                path.is_file() and path.parent == directory / "evidence",
                f"recorded {stream} file is absent or misplaced",
            )
    junit = check_junit(
        directory / "tests.xml", inventory_path=root / "configs/m1_test_inventory.json"
    )
    passed = check_pytest_summary(
        child(root, entries[0]["stdout"]).read_text(), junit["executed_testcases"]
    )
    return {"successful_recorded_commands": len(entries), "reported_pytest_passes": passed}


def check_rendered_metrics(metrics: dict, *, replay_run: bool = False) -> None:
    require(metrics["core_only"] is False, "core-only evidence cannot satisfy the rendered M1 gate")
    require(
        metrics["terminal_reason"] == "finished" and metrics["verification_tail_complete"] is True,
        "episode did not finish a complete verification tail",
    )
    require(
        metrics["voltage_points"] == 4 and metrics["rgb_frames"] >= 2,
        "pilot requires exactly four voltage tokens and at least two RGB frames",
    )
    if not replay_run:
        require(
            metrics["pilot_passed"] is True and metrics["policy_adapter_failure"] is None,
            "pilot checks or policy adapter failed",
        )
        expected_checks = {
            "finished",
            "verification_tail",
            "no_adapter_failure",
            "energy_balance",
            "home_and_side_images",
            "measured_choice",
            "newer_verification",
            "four_voltage_points",
        }
        require(
            expected_checks <= metrics["pilot_checks"].keys()
            and all(metrics["pilot_checks"][key] is True for key in expected_checks),
            "required pilot check is absent or false",
        )


def check_declared_config(config: Config, root: Path) -> None:
    expected = load_config(root / "configs/pilot.toml")
    require(
        config.sha256() == expected.sha256(),
        "recorded configuration differs from the declared configs/pilot.toml",
    )


def inspect_recording(root: Path, run_id: str, seed: int, *, replay_run: bool = False) -> dict:
    private = root / "private_eval" / run_id
    manifest, output = verify_recording(private / "manifest.json")
    require(output == (root / "runs" / run_id).resolve(), "manifest points to another public run")
    require(manifest["run_id"] == run_id and manifest["seed"] == seed, "run ID or seed mismatch")
    purpose = "m1_replay" if replay_run else "m1_pilot"
    require(manifest["metadata"].get("purpose") == purpose, "wrong recording purpose")
    if not replay_run:
        require(manifest["metadata"].get("policy") == "scan", "pilot is not B1 scan")
    artifacts = {(item["scope"], item["path"]) for item in manifest["artifacts"]}
    require(all(scope in {"public", "private"} for scope, _ in artifacts), "unknown artifact scope")
    required = {("private", name) for name in ("config.json", "metrics.json", "truth.jsonl")}
    required |= {
        ("public", f"public/{name}")
        for name in (
            "task.json",
            "observations.jsonl",
            "actions.jsonl",
            "decisions.jsonl",
            "feedback.jsonl",
        )
    }
    if replay_run:
        required.add(("public", "evidence/replay.json"))
    require(required <= artifacts, "required run evidence is missing from manifest hash coverage")
    for artifact in manifest["artifacts"]:
        directory = output if artifact["scope"] == "public" else private
        require(
            child(directory, artifact["path"]).stat().st_size == artifact["bytes"],
            "artifact byte count mismatch",
        )
    config = Config.model_validate_json((private / "config.json").read_text())
    require(config.sha256() == manifest["config_sha256"], "config hash mismatch")
    check_declared_config(config, root)
    require(manifest["dt_s"] == config.simulation.dt_s, "manifest clock/config mismatch")
    source = manifest["source_fingerprint"]
    expected_sources = {str(p.relative_to(root)) for p in (root / "src/pv_sim").rglob("*.py")}
    expected_sources |= {"uv.lock", "pyproject.toml", "configs/tolerances.toml"}
    require(
        set(source) == expected_sources,
        "source fingerprint coverage differs from current workspace",
    )
    for relative, digest in source.items():
        require(
            sha256_file(child(root, relative)) == digest, "recorded source differs from workspace"
        )
    runtime = manifest["runtime"]
    current_runtime = runtime_metadata()
    require(
        all(runtime[key] == current_runtime[key] for key in RUNTIME_KEYS),
        "runtime differs from the current pinned audit host",
    )
    metrics = json_file(private / "metrics.json")
    check_rendered_metrics(metrics, replay_run=replay_run)
    public = output / "public"
    task = PublicTask.model_validate_json((public / "task.json").read_text())
    require(task.episode_id == manifest["episode_id"], "task/manifest episode mismatch")
    require(
        "rgb" in task.sensors and "capture_rgb" in task.available_actions, "RGB capability absent"
    )
    events = json_lines(public / "observations.jsonl")
    actions = json_lines(public / "actions.jsonl")
    decisions = json_lines(public / "decisions.jsonl")
    require(
        len(events) == len(actions) + 1 and len(actions) == len(decisions) and bool(actions),
        "reset/action/observation/decision record counts disagree",
    )
    dt = config.simulation.dt_s
    observations, frames, needed_ticks = [], [], set()
    for index, event in enumerate(events):
        observation = read_observation(event, public)
        validate_observation_context(observation, task)
        require(observation.sequence_id == index, "observation sequence is discontinuous")
        require(
            event["tick"] == aligned(observation.t_deliver_s, dt),
            "observation event clock mismatch",
        )
        require(
            not observations or observation.t_deliver_s > observations[-1].t_deliver_s,
            "pilot observation delivery must increase",
        )
        for sample in observation.scalars + observation.encoders:
            capture, deliver = aligned(sample.t_capture_s, dt), aligned(sample.t_deliver_s, dt)
            latency = (
                config.sensors.numeric_latency_s
                if hasattr(sample, "channel")
                else config.sensors.encoder_latency_s
            )
            require(deliver - capture == round(latency / dt), "sensor latency differs from config")
            needed_ticks.add(capture)
        for feedback in observation.feedback:
            for value in (feedback.t_accepted_s, feedback.t_terminal_s):
                if value is not None:
                    aligned(value, dt)
            require(feedback.code in {"accepted", "executing", "completed"}, "pilot action failed")
        for frame in observation.rgb:
            start, capture, end, deliver = (
                aligned(value, dt)
                for value in (frame.t_start_s, frame.t_capture_s, frame.t_end_s, frame.t_deliver_s)
            )
            require(
                frame.validity == "valid" and frame.png_base64 is not None,
                "RGB frame is unavailable",
            )
            require(
                end - start == round(config.sensors.rgb_exposure_s / dt)
                and capture * 2 == start + end
                and deliver - end == round(config.sensors.rgb_latency_s / dt),
                "RGB timing mismatch",
            )
            require(
                ("public", f"public/frames/{frame.frame_id}.png") in artifacts,
                "frame is absent from manifest hash coverage",
            )
            with Image.open(io.BytesIO(base64.b64decode(frame.png_base64))) as image:
                pixels = np.asarray(image)
                require(
                    image.mode == "RGB"
                    and pixels.shape == (480, 640, 3)
                    and pixels.dtype == np.uint8,
                    "invalid real-camera PNG dimensions/format",
                )
                require(
                    float(pixels.std()) > 1.0
                    and len(np.unique(pixels.reshape(-1, 3), axis=0)) >= 16,
                    "RGB frame is blank or has insufficient variation",
                )
            frames.append((frame, observation))
            needed_ticks.add(capture)
        observations.append(observation)
    require(
        observations[-1].terminal_reason == "finished", "final public observation is not finished"
    )
    require(
        len(frames) == manifest["frame_count"] == metrics["rgb_frames"] >= 2,
        "frame counts disagree across public trace, manifest and metrics",
    )
    require(len({frame.frame_id for frame, _ in frames}) == len(frames), "pilot reused a frame ID")
    for action_event, decision_event in zip(actions, decisions, strict=True):
        action = ACTION_ADAPTER.validate_json(action_event["payload"]["raw_json"])
        decision = Decision.model_validate_json(
            json.dumps(decision_event["payload"]["decision"], allow_nan=False)
        )
        require(
            decision.action == action and decision_event["payload"]["failure"] is None,
            "recorded policy decision does not match applied action",
        )
    selected_truth = {}
    last_tick = -1
    with (private / "truth.jsonl").open() as stream:
        for line in stream:
            event = json.loads(line)
            state = event["payload"]
            tick = state["tick"]
            require(
                type(tick) is int and tick == last_tick + 1 and tick == event["tick"],
                "truth clock is missing, duplicated or out of order",
            )
            require(aligned(state["time_s"], dt) == tick, "truth time disagrees with tick")
            point = state["point"]
            require(
                all(
                    finite(point[key])
                    for key in ("voltage_v", "current_a", "power_w", "open_circuit_voltage_v")
                ),
                "nonfinite private operating point",
            )
            require(
                math.isclose(
                    point["power_w"],
                    point["voltage_v"] * point["current_a"],
                    rel_tol=1e-10,
                    abs_tol=1e-10,
                ),
                "private P=VI identity failed",
            )
            require(state["dynamics"]["tick"] == tick, "dynamics snapshot tick mismatch")
            if tick in needed_ticks:
                selected_truth[tick] = state
            last_tick = tick
    require(
        last_tick == manifest["final_tick"] == metrics["tick"],
        "final truth/manifest/metric tick differs",
    )
    require(needed_ticks <= selected_truth.keys(), "capture tick absent from actual-state truth")
    for observation in observations:
        for sample in observation.scalars:
            state = selected_truth[aligned(sample.t_capture_s, dt)]
            expected = {
                "voltage_v": state["point"]["voltage_v"],
                "current_a": state["point"]["current_a"],
                "temperature_c": state["temperature_c"],
                "reference_w_m2": state["reference_w_m2"],
            }
            require(
                sample.validity == "valid"
                and math.isclose(
                    sample.value, expected[sample.channel], rel_tol=1e-10, abs_tol=1e-10
                ),
                "scalar sample does not match its capture-time state",
            )
    side_seen, home_seen = False, False
    for frame, observation in frames:
        state = selected_truth[aligned(frame.t_capture_s, dt)]["dynamics"]
        q = state["q"]
        require(len(q) == 3 and all(finite(value) for value in q), "frame truth pose is invalid")
        require(
            np.allclose(state["camera_position_m"], (q[0], -0.45, 0.35), rtol=0, atol=1e-10),
            "camera position is not tied to actual captured slide",
        )
        if abs(q[0]) <= 0.001 and abs(q[1]) <= 0.01:
            home_seen = True
        if abs(q[0] - 0.12) <= 0.002 and abs(q[1] - math.atan(0.12 / 0.45)) <= 0.01:
            matches = [
                f
                for f in observation.feedback
                if f.code == "completed"
                and f.commanded_target is not None
                and f.commanded_target.kind == "move_camera"
                and f.commanded_target.capture_after_settle
            ]
            require(
                matches
                and any(
                    hasattr(m.sample, "slide_m")
                    and m.sample.validity == "valid"
                    and abs(m.sample.slide_m - 0.12) <= 0.002
                    for f in matches
                    for m in f.measured_confirmation
                ),
                "side image lacks measured movement completion",
            )
            side_seen = True
    require(
        home_seen and side_seen, "home and measured side capture-time poses are not both present"
    )
    finish = [
        f
        for f in observations[-1].feedback
        if f.code == "completed"
        and f.commanded_target is not None
        and f.commanded_target.kind == "finish"
    ]
    require(
        len(finish) == 1
        and math.isclose(
            finish[0].t_terminal_s - finish[0].t_accepted_s,
            config.simulation.verification_tail_s,
            rel_tol=0,
            abs_tol=1e-10,
        ),
        "finish tail timing mismatch",
    )
    return {
        "manifest": manifest,
        "config": config,
        "metrics": metrics,
        "runtime": runtime,
        "output": output,
        "summary": {
            "run_id": run_id,
            "seed": seed,
            "frames": len(frames),
            "truth_ticks_checked": last_tick + 1,
            "capture_times_matched": len(needed_ticks),
            "core_only": False,
            "hashes_verified": True,
        },
    }


def check_replay(root: Path, run_id: str, seed: int, pilot: dict) -> dict:
    replay_run = inspect_recording(root, run_id, seed, replay_run=True)
    manifest = replay_run["manifest"]
    source_path = root / "private_eval" / pilot["manifest"]["run_id"] / "manifest.json"
    source = manifest["replay_source"]
    require(
        Path(source["manifest"]).resolve() == source_path.resolve()
        and source["sha256"] == sha256_file(source_path)
        and source["policy_requeried"] is False,
        "replay source provenance mismatch",
    )
    report = json_file(replay_run["output"] / "evidence/replay.json")
    require(
        report["status"] == "passed"
        and report["core_only"] is False
        and report["rendered_gate_satisfied"] is True
        and report["policy_requeried"] is False,
        "replay did not pass the rendered gate",
    )
    require(
        report["source_manifest_sha256"] == sha256_file(source_path),
        "replay report source hash mismatch",
    )
    provenance_keys = {
        "source_matches",
        "libraries_match",
        "python_matches",
        "platform_matches",
        "renderer_matches",
    }
    require(
        provenance_keys <= report["provenance"].keys()
        and all(report["provenance"][key] is True for key in provenance_keys),
        "replay provenance failed",
    )
    require(
        report["truth_comparison"]["passed"] is True
        and report["truth_comparison"]["records_compared"] > 0
        and report["metrics_comparison"]["passed"] is True
        and report["task_matches"] is True
        and report["tick_mismatches"] == [],
        "replay truth, metrics, task or ticks failed comparison",
    )
    require(
        report["observations"] and all(item["passed"] is True for item in report["observations"]),
        "replay observation comparison absent or failed",
    )
    require(
        sum(item["frames_compared"] for item in report["observations"]) > 0,
        "replay compared no actual frames",
    )
    require(
        replay_run["config"].sha256() == pilot["config"].sha256()
        and manifest["source_fingerprint"] == pilot["manifest"]["source_fingerprint"],
        "pilot and replay config/source differ",
    )
    return replay_run


def audit_batch(batch_report: Path, *, root: Path = ROOT) -> dict:
    root, batch_report = root.resolve(), batch_report.resolve()
    checks = []
    report = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "batch_report": str(batch_report),
        "status": "incomplete",
        "checks": checks,
        "visual_inspection": "not_performed",
        "independent_review": "pending",
        "scope": "Read-only machine evidence checks; no simulation or renderer execution.",
    }

    def check(name, function):
        try:
            value = function()
            checks.append(
                {"check": name, "status": "passed", "details": value.get("summary", value)}
            )
            return value
        except IncompleteAudit as exc:
            checks.append({"check": name, "status": "incomplete", "error": str(exc)})
        except FileNotFoundError as exc:
            checks.append(
                {
                    "check": name,
                    "status": "incomplete",
                    "error": f"missing evidence: {exc.filename}",
                }
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
            ReplayError,
            ET.ParseError,
        ) as exc:
            checks.append({"check": name, "status": "failed", "error": str(exc)[:1000]})
        return None

    def batch_check():
        batch = json_file(batch_report)
        report["batch_report_sha256"] = sha256_file(batch_report)
        batch_id = batch["batch_id"]
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,90}", batch_id) is not None,
            "invalid batch ID",
        )
        require(
            batch_report == root / "runs" / batch_id / "batch-report.json", "batch path/ID mismatch"
        )
        if batch["status"] != "commands_passed_pending_image_inspection_and_independent_review":
            raise IncompleteAudit("batch commands are incomplete or failed")
        require(
            batch["seeds"] == list(SEEDS) and batch["max_complete_pilots"] == 3,
            "batch seed/repetition allowance mismatch",
        )
        require(
            finite(batch["elapsed_wall_s"]) and 0 <= batch["elapsed_wall_s"] <= 1800,
            "batch exceeded 30 minute bound",
        )
        require(
            type(batch["artifact_bytes"]) is int and 0 <= batch["artifact_bytes"] < 2_000_000_000,
            "batch exceeded 2 GB bound",
        )
        return batch

    batch = check("batch_completed", batch_check)
    if batch is not None:
        batch_id = batch["batch_id"]
        report["batch_id"] = batch_id
        check("recorded_commands", lambda: check_commands(root, batch_id, batch))
        check(
            "executed_junit",
            lambda: check_junit(
                batch_report.parent / "tests.xml",
                inventory_path=root / "configs/m1_test_inventory.json",
            ),
        )
        pilots = []
        for seed in SEEDS:
            run_id = f"{batch_id}-s{seed}"
            pilot = check(f"pilot_{seed}", lambda r=run_id, s=seed: inspect_recording(root, r, s))
            if pilot is not None:
                pilots.append(pilot)
                check(
                    f"replay_{seed}",
                    lambda r=run_id, s=seed, p=pilot: check_replay(root, r + "-replay", s, p),
                )
            else:
                checks.append(
                    {
                        "check": f"replay_{seed}",
                        "status": "incomplete",
                        "error": "pilot evidence not validated",
                    }
                )
        if len(pilots) == 3:

            def consistency():
                first = pilots[0]
                require(
                    all(
                        p["config"].sha256() == first["config"].sha256()
                        and p["manifest"]["source_fingerprint"]
                        == first["manifest"]["source_fingerprint"]
                        and all(p["runtime"][key] == first["runtime"][key] for key in RUNTIME_KEYS)
                        for p in pilots[1:]
                    ),
                    "pilot config/source/runtime differs across seeds",
                )
                return {"paired_seeds": list(SEEDS)}

            check("cross_pilot_consistency", consistency)
    if checks and all(item["status"] == "passed" for item in checks):
        report["status"] = PASS_STATUS
    elif any(item["status"] == "incomplete" for item in checks):
        report["status"] = "incomplete"
    else:
        report["status"] = "failed"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("audit output already exists; prior evidence is never overwritten")
    report = audit_batch(args.batch_report)
    try:
        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        print(f"Cannot create new audit output: {type(exc).__name__}", file=sys.stderr)
        return 4
    print(json.dumps({"status": report["status"], "output": str(args.output)}, indent=2))
    return 0 if report["status"] == PASS_STATUS else 4


if __name__ == "__main__":
    raise SystemExit(main())
