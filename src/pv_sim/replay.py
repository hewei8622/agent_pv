"""Recorded-action replay on the same pinned host, without policy re-querying.

The versioned limits in configs/tolerances.toml are engineering replay checks,
not cross-driver image equivalence or physical-model accuracy. Core-only traces
are labelled explicitly and cannot satisfy the required rendered M1 pilot gate.
"""

from __future__ import annotations

import base64
import io
import json
import math
import tomllib
from itertools import zip_longest
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pv_sim.config import Config
from pv_sim.contracts import Decision, Observation, PublicTask
from pv_sim.recorder import (
    ROOT,
    Recorder,
    _atomic,
    canonical_json,
    runtime_metadata,
    sha256_file,
    source_fingerprint,
)


class ReplayError(RuntimeError):
    """Recorded evidence is incomplete, corrupt or unsuitable for replay."""


def _safe_child(directory: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ReplayError("artifact path must stay within its declared directory")
    result = (directory / path).resolve()
    if directory.resolve() not in result.parents:
        raise ReplayError("artifact path escapes its declared directory")
    return result


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def verify_recording(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = Path(manifest_path).resolve()
    expected_digest = (manifest_path.parent / "manifest.sha256").read_text().strip()
    if sha256_file(manifest_path) != expected_digest:
        raise ReplayError("manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("incomplete", True) or manifest.get("status") != "complete":
        raise ReplayError("recording is incomplete")
    output = (manifest_path.parent / manifest["public_relative_path"]).resolve()
    for artifact in manifest["artifacts"]:
        directory = output if artifact["scope"] == "public" else manifest_path.parent
        path = _safe_child(directory, artifact["path"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise ReplayError(f"recorded artifact hash mismatch: {artifact['scope']}")
    return manifest, output


def read_observation(event: dict[str, Any], public_dir: Path) -> Observation:
    payload = json.loads(canonical_json(event["payload"]))
    for frame in payload["rgb"]:
        relative = frame.pop("png_file")
        digest = frame.pop("png_sha256")
        if relative is None:
            frame["png_base64"] = None
        else:
            if relative != f"frames/{frame['frame_id']}.png":
                raise ReplayError("frame reference disagrees with its opaque identifier")
            path = _safe_child(public_dir, relative)
            if sha256_file(path) != digest:
                raise ReplayError("frame hash mismatch")
            frame["png_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return Observation.model_validate_json(canonical_json(payload))


def compare_observations(
    expected: Observation, actual: Observation, tolerances: dict[str, Any]
) -> dict[str, Any]:
    """Compare public values and times, and decode actual recorded/rendered RGB."""
    errors: list[str] = []
    numeric_count, maximum_numeric_error = 0, 0.0
    frame_count, maximum_pixel_error, maximum_frame_mean_error = 0, 0, 0.0

    def mismatch(path: str) -> None:
        if len(errors) < 20:
            errors.append(path)

    def compare(left: Any, right: Any, path: str) -> None:
        nonlocal numeric_count, maximum_numeric_error
        if type(left) is not type(right):
            mismatch(path + ":type")
        elif isinstance(left, dict):
            if left.keys() != right.keys():
                mismatch(path + ":keys")
                return
            for key in left:
                compare(left[key], right[key], f"{path}.{key}")
        elif isinstance(left, list):
            if len(left) != len(right):
                mismatch(path + ":length")
                return
            for index, (a, b) in enumerate(zip(left, right, strict=True)):
                compare(a, b, f"{path}[{index}]")
        elif isinstance(left, float):
            numeric_count += 1
            maximum_numeric_error = max(maximum_numeric_error, abs(left - right))
            # All capture/delivery/acceptance/terminal timestamps are exact tick projections.
            if path.rsplit(".", 1)[-1].startswith("t_"):
                if left != right:
                    mismatch(path + ":timestamp")
            elif not math.isclose(
                left,
                right,
                rel_tol=tolerances["numeric_relative"],
                abs_tol=tolerances["numeric_absolute"],
            ):
                mismatch(path + ":numeric")
        elif left != right:
            mismatch(path + ":value")

    left = expected.model_dump(mode="json")
    right = actual.model_dump(mode="json")
    if len(left["rgb"]) == len(right["rgb"]):
        for index, (a, b) in enumerate(zip(left["rgb"], right["rgb"], strict=True)):
            a_raw, b_raw = a.pop("png_base64"), b.pop("png_base64")
            if a_raw is None or b_raw is None:
                if a_raw != b_raw:
                    mismatch(f"rgb[{index}]:missingness")
                continue
            with Image.open(io.BytesIO(base64.b64decode(a_raw))) as image:
                a_pixels = np.asarray(image, dtype=np.int16)
            with Image.open(io.BytesIO(base64.b64decode(b_raw))) as image:
                b_pixels = np.asarray(image, dtype=np.int16)
            difference = np.abs(a_pixels - b_pixels)
            frame_count += 1
            pixel_error = int(difference.max())
            mean_error = float(difference.mean())
            maximum_pixel_error = max(maximum_pixel_error, pixel_error)
            maximum_frame_mean_error = max(maximum_frame_mean_error, mean_error)
            if (
                pixel_error > tolerances["pixel_max_absolute"]
                or mean_error > tolerances["pixel_mean_absolute"]
            ):
                mismatch(f"rgb[{index}]:pixels")
    else:
        # Avoid reporting huge base64 strings while identifying frame-count changes.
        for frames in (left["rgb"], right["rgb"]):
            for frame in frames:
                frame.pop("png_base64")
    compare(left, right, "observation")
    return {
        "passed": not errors,
        "mismatches": errors,
        "numeric_values_compared": numeric_count,
        "maximum_numeric_absolute_error": maximum_numeric_error,
        "frames_compared": frame_count,
        "maximum_pixel_absolute_error": maximum_pixel_error,
        "maximum_frame_mean_absolute_error": maximum_frame_mean_error,
    }


def compare_private_values(
    expected: Any, actual: Any, tolerances: dict[str, Any]
) -> dict[str, Any]:
    """Compare all runtime private fields; integers/ticks and timestamps are exact."""
    mismatches: list[str] = []
    numeric_count, maximum_error = 0, 0.0

    def fail(path: str) -> None:
        if len(mismatches) < 20:
            mismatches.append(path)

    def compare(left: Any, right: Any, path: str) -> None:
        nonlocal numeric_count, maximum_error
        if type(left) is not type(right):
            fail(path + ":type")
        elif isinstance(left, dict):
            if left.keys() != right.keys():
                fail(path + ":keys")
            for key in left.keys() & right.keys():
                compare(left[key], right[key], f"{path}.{key}")
        elif isinstance(left, list):
            if len(left) != len(right):
                fail(path + ":length")
            for index, (a, b) in enumerate(zip(left, right)):
                compare(a, b, f"{path}[{index}]")
        elif isinstance(left, float):
            numeric_count += 1
            maximum_error = max(maximum_error, abs(left - right))
            key = path.rsplit(".", 1)[-1]
            if key.startswith("t_") or key in ("time_s", "elapsed_s"):
                if left != right:
                    fail(path + ":timestamp")
            elif not math.isclose(
                left, right,
                rel_tol=tolerances["numeric_relative"],
                abs_tol=tolerances["numeric_absolute"],
            ):
                fail(path + ":numeric")
        elif left != right:
            fail(path + ":value")

    compare(expected, actual, "private")
    return {
        "passed": not mismatches,
        "mismatches": mismatches,
        "numeric_values_compared": numeric_count,
        "maximum_numeric_absolute_error": maximum_error,
    }


def compare_truth(
    expected_path: Path, actual_path: Path, tolerances: dict[str, Any]
) -> dict[str, Any]:
    """Stream every truth event, retaining bounded comparison summaries only."""
    report: dict[str, Any] = {
        "passed": True,
        "expected_records": 0,
        "actual_records": 0,
        "records_compared": 0,
        "numeric_values_compared": 0,
        "maximum_numeric_absolute_error": 0.0,
        "mismatches": [],
    }
    if not expected_path.is_file() or not actual_path.is_file():
        report.update(passed=False, mismatches=["truth file missing"])
        return report
    with expected_path.open() as expected, actual_path.open() as actual:
        for index, (a_line, b_line) in enumerate(zip_longest(expected, actual)):
            report["expected_records"] += a_line is not None
            report["actual_records"] += b_line is not None
            if a_line is None or b_line is None:
                report["passed"] = False
                if len(report["mismatches"]) < 20:
                    report["mismatches"].append({"record": index, "error": "missing record"})
                continue
            a, b = json.loads(a_line), json.loads(b_line)
            # Global sequence includes copied policy-evidence events. All other
            # event metadata and every private state field must reproduce.
            a.pop("sequence")
            b.pop("sequence")
            comparison = compare_private_values(a, b, tolerances)
            report["records_compared"] += 1
            report["numeric_values_compared"] += comparison["numeric_values_compared"]
            report["maximum_numeric_absolute_error"] = max(
                report["maximum_numeric_absolute_error"],
                comparison["maximum_numeric_absolute_error"],
            )
            if not comparison["passed"]:
                report["passed"] = False
                if len(report["mismatches"]) < 20:
                    report["mismatches"].append(
                        {"record": index, "fields": comparison["mismatches"]}
                    )
    return report


def replay(
    manifest_path: Path,
    output: Path,
    private_root: Path = Path("private_eval"),
) -> dict[str, Any]:
    """Replay all recorded step payloads into a new run; never invoke a policy."""
    # This import is intentionally lazy: the recorder and its tests need no renderer.
    from pv_sim.env import PVEnv

    manifest_path = Path(manifest_path).resolve()
    manifest, original_output = verify_recording(manifest_path)
    if manifest.get("metadata", {}).get("execution_protocol") == "investigation/1.0":
        raise ReplayError("investigation recording requires replay_investigation, "
                          "not physical-only action replay")
    public = original_output / "public"
    config = Config.model_validate_json((manifest_path.parent / "config.json").read_text())
    if config.sha256() != manifest["config_sha256"]:
        raise ReplayError("configuration hash mismatch")
    task = PublicTask.model_validate_json((public / "task.json").read_text())
    events = _jsonl(public / "observations.jsonl")
    actions = _jsonl(public / "actions.jsonl")
    decisions = _jsonl(public / "decisions.jsonl")
    if len(events) != len(actions) + 1:
        raise ReplayError("replay requires reset plus one recorded observation per action attempt")
    with (ROOT / "configs/tolerances.toml").open("rb") as stream:
        tolerances = tomllib.load(stream)["m1_replay"]
    original_runtime = manifest["runtime"]
    current_runtime = runtime_metadata()
    provenance = {
        "source_matches": source_fingerprint() == manifest["source_fingerprint"],
        "libraries_match": current_runtime["libraries"] == original_runtime["libraries"],
        "python_matches": current_runtime["python"] == original_runtime["python"],
        "platform_matches": current_runtime["platform"] == original_runtime["platform"],
        "renderer_matches": current_runtime["mujoco_gl"] == original_runtime["mujoco_gl"],
    }
    core_only = "rgb" not in task.sensors
    recorder = Recorder(
        output,
        private_root,
        source_manifest=manifest_path,
        metadata={"purpose": "m2_replay" if config.m2 is not None else "m1_replay"},
    )
    evidence = recorder.output / "evidence"
    evidence.mkdir()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "failed",
        "source_manifest_sha256": sha256_file(manifest_path),
        "tolerances": tolerances,
        "same_pinned_host_only": True,
        "core_only": core_only,
        "policy_requeried": False,
        "provenance": provenance,
        "observations": [],
        "tick_mismatches": [],
        "task_matches": False,
        "rendered_gate_satisfied": False,
        "policy_wall_time_source": "recorded decision latency; no new policy computation",
        "truth_comparison": {"passed": False, "status": "not_run"},
        "metrics_comparison": {"passed": False, "status": "not_run"},
    }
    env = None
    try:
        env = PVEnv(config, enable_rendering=not core_only, recorder=recorder)
        replay_task, observation = env.reset(manifest["seed"], episode_id=task.episode_id)
        report["task_matches"] = replay_task == task
        if env.tick != events[0]["tick"]:
            report["tick_mismatches"].append({"observation": 0, "actual_tick": env.tick})
        report["observations"].append(
            compare_observations(read_observation(events[0], public), observation, tolerances)
        )
        decision_index = 0

        def restore_decision(entry: dict[str, Any]) -> None:
            recorder.decision(
                Decision.model_validate_json(canonical_json(entry["decision"])),
                entry["wall_clock_latency_s"],
                entry["failure"],
            )
            # This reproduces the measured cost in the authoritative trace.
            # Re-querying a policy or timing replay would be a different trial.
            env.ledger.policy_wall_s += entry["wall_clock_latency_s"]

        for index, event in enumerate(actions):
            if env.tick != event["tick"]:
                report["tick_mismatches"].append({"action": index, "actual_tick": env.tick})
            while (
                decision_index < len(decisions)
                and decisions[decision_index]["sequence"] < event["sequence"]
            ):
                entry = decisions[decision_index]["payload"]
                restore_decision(entry)
                decision_index += 1
            observation = env.step(json.loads(event["payload"]["raw_json"]))
            if env.tick != events[index + 1]["tick"]:
                report["tick_mismatches"].append(
                    {"observation": index + 1, "actual_tick": env.tick}
                )
            report["observations"].append(
                compare_observations(
                    read_observation(events[index + 1], public), observation, tolerances
                )
            )
        for decision_event in decisions[decision_index:]:
            restore_decision(decision_event["payload"])
        runtime_metrics = json.loads(canonical_json(env.metrics()))
        original_metrics = json.loads((manifest_path.parent / "metrics.json").read_text())
        expected_runtime_metrics = {
            key: original_metrics[key] for key in runtime_metrics if key in original_metrics
        }
        report["metrics_comparison"] = compare_private_values(
            expected_runtime_metrics, runtime_metrics, tolerances
        )
        report["original_metric_annotations"] = {
            key: value for key, value in original_metrics.items() if key not in runtime_metrics
        }
        report["metric_annotation_policy"] = (
            "Original CLI annotations retained separately; every runtime env.metrics key compared."
        )
        report["truth_comparison"] = compare_truth(
            manifest_path.parent / "truth.jsonl", recorder.private_dir / "truth.jsonl", tolerances
        )
        if config.m2 is not None:
            report["actuation_comparison"] = compare_private_values(
                _jsonl(manifest_path.parent / "actuation.jsonl"),
                _jsonl(recorder.private_dir / "actuation.jsonl"),
                tolerances,
            )
        frame_count = sum(item["frames_compared"] for item in report["observations"])
        report["rendered_gate_satisfied"] = not core_only and frame_count > 0
        report["status"] = (
            "passed"
            if all(provenance.values())
            and report["task_matches"]
            and not report["tick_mismatches"]
            and all(item["passed"] for item in report["observations"])
            and report["truth_comparison"]["passed"]
            and report["metrics_comparison"]["passed"]
            and report.get("actuation_comparison", {"passed": True})["passed"]
            and (core_only or report["rendered_gate_satisfied"])
            else "failed"
        )
        _atomic(evidence / "replay.json", (canonical_json(report) + "\n").encode())
        recorder.finish(runtime_metrics)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        if not (evidence / "replay.json").exists():
            _atomic(evidence / "replay.json", (canonical_json(report) + "\n").encode())
        recorder.abort(type(exc).__name__, str(exc))
        raise
    finally:
        if env is not None:
            env.close()
        recorder.close()
    return report
