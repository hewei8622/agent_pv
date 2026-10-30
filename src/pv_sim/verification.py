"""Evaluator-only M2 desktop suite; no policy pilot, fallback images or retries."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from pv_sim.config import load_config
from pv_sim.recorder import runtime_metadata, sha256_file, source_fingerprint

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "configs/m2_test_inventory.json"


def assess_render_evidence(directory: Path) -> dict:
    """Check every frozen fixture artifact; visual/gate review remains separate."""
    expected = set()
    for fixture, views in (
        ("reframe", ("home", "reframed")),
        ("narrow_screen", ("home", "rotation_only", "right", "left")),
        ("rail_locked", ("home", "rotation_only")),
        ("wide_screen", ("home", "rotation_only", "right", "left")),
    ):
        for variant in ("production", "calibration"):
            for view in views:
                expected.update(
                    f"m2_{fixture}_{variant}_{view}.{suffix}" for suffix in ("png", "json")
                )
    for fixture in ("late_valid", "late_stale", "dropped"):
        base = f"sensor_delivery/{fixture}"
        expected.update((f"{base}/image_00.png", f"{base}/timeline.json"))
        if fixture != "dropped":
            expected.add(f"{base}/image_01.png")
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    errors = []
    if actual != expected:
        errors.append("missing or unexpected fixture files")
    for relative in sorted(expected & actual):
        path = directory / relative
        try:
            if path.is_symlink():
                raise ValueError("symlink evidence")
            if path.suffix == ".png":
                with Image.open(path) as image:
                    pixels = np.asarray(image)
                    if (
                        image.mode != "RGB"
                        or pixels.shape != (480, 640, 3)
                        or pixels.dtype != np.uint8
                        or pixels.std() <= 1
                    ):
                        raise ValueError("invalid/blank camera image")
            else:
                data = json.loads(path.read_text())
                if path.name == "timeline.json":
                    wanted = [{"file": "image_00.png", "role": "actual_midpoint_capture"}]
                    if path.parent.name != "dropped":
                        wanted.append(
                            {"file": "image_01.png", "role": "evaluator_only_delivery_pose"}
                        )
                    if [{"file": i["file"], "role": i["role"]} for i in data["images"]] != wanted:
                        raise ValueError("incomplete capture/delivery image references")
                    if not data["truth"] or not data["actions"] or not data["observations"]:
                        raise ValueError("empty sensor timeline")
                references = (
                    data["images"]
                    if path.name == "timeline.json"
                    else [{"file": data["image"], "sha256": data["image_sha256"]}]
                )
                for item in references:
                    target = path.parent / item["file"]
                    if target.parent != path.parent or sha256_file(target) != item["sha256"]:
                        raise ValueError("image reference/hash mismatch")
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(relative)
    return {
        "passed": not errors,
        "expected_pngs": 29,
        "expected_json": 27,
        "missing": sorted(expected - actual),
        "unexpected": sorted(actual - expected),
        "errors": errors,
    }


def assess_junit(path: Path, inventory: list[dict]) -> dict:
    cases = list(ET.parse(path).getroot().iter("testcase"))
    actual = Counter((c.get("classname"), c.get("name")) for c in cases)
    expected = Counter((c["classname"], c["name"]) for c in inventory)
    failures = sum(c.find("failure") is not None for c in cases)
    errors = sum(c.find("error") is not None for c in cases)
    skipped = sum(c.find("skipped") is not None for c in cases)
    return {
        "cases": len(cases),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "exact_inventory": actual == expected,
        "unique_cases": all(n == 1 for n in actual.values()),
        "render_cases": sum(c.get("classname", "").startswith("tests.render.") for c in cases),
        "passed": (
            bool(cases)
            and actual == expected
            and all(n == 1 for n in actual.values())
            and not (failures or errors or skipped)
        ),
    }


def _run_recorded(command: list[str], environment: dict) -> int:
    """Let the command recorder clean its process group on interruption."""
    process = subprocess.Popen(command, cwd=ROOT, env=environment)
    try:
        return process.wait(timeout=1790)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        return 124


def run_verification(config_path: Path, seed: int, output: Path) -> dict:
    config_path = config_path.resolve()
    config = load_config(config_path)
    if config.m2 is None or seed != 20261016:
        raise ValueError("development verification requires M2 config and frozen development seed")
    output = output.resolve()
    if output.parent != ROOT / "runs":
        raise ValueError("verification output must be a new direct child of project runs")
    private = ROOT / "private_eval" / output.name
    inventory = json.loads(INVENTORY.read_text())["testcases"]
    if output.exists() or private.exists():
        raise ValueError("verification output already exists")
    output.mkdir()
    private.mkdir(parents=True)
    (private / "config.json").write_text(config.canonical_json() + "\n")
    before = source_fingerprint()
    for name in ("tests", "configs", "schemas", "scripts"):
        before.update(
            {
                str(p.relative_to(ROOT)): sha256_file(p)
                for p in sorted((ROOT / name).rglob("*"))
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
            }
        )
    before[str(INVENTORY.relative_to(ROOT))] = sha256_file(INVENTORY)
    input_hash = sha256_file(config_path)
    metadata = {
        "schema_version": "1.0",
        "milestone": "M2",
        "suite": "development",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime_metadata(),
        "config_sha256": config.sha256(),
        "input_config_file_sha256": input_hash,
        "source_fingerprint": before,
        "seed": seed,
        "scope": (
            "deterministic integrity fixtures and full regression suite; no complete policy pilots"
        ),
        "status": "running",
        "m3_authorized": False,
    }
    (private / "verification.initial.json").write_text(json.dumps(metadata, indent=2) + "\n")
    environment = dict(os.environ)
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "UV_PROJECT_ENVIRONMENT"):
        environment.pop(name, None)
    environment.update(
        PV_M2_RENDER_EVIDENCE_DIR=str(output / "render"),
        PV_M2_VERIFY_CONFIG=str(config_path),
        PV_M2_VERIFY_SEED=str(seed),
    )
    command = [
        sys.executable,
        "scripts/record_command.py",
        "--label",
        "development-tests",
        "--evidence-dir",
        str(output.relative_to(ROOT) / "evidence"),
        "--timeout",
        "1740",
        "--",
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-q",
        f"--junitxml={output / 'tests.xml'}",
    ]
    code = _run_recorded(command, environment)
    summary = (
        assess_junit(output / "tests.xml", inventory)
        if (output / "tests.xml").exists()
        else {"passed": False}
    )
    unchanged = all(sha256_file(ROOT / name) == digest for name, digest in before.items())
    unchanged = unchanged and sha256_file(config_path) == input_hash
    # Render fixtures retain a private timeline beside their original PNGs.
    pngs = sorted((output / "render").rglob("*.png"))
    timelines = sorted((output / "render").rglob("*.json"))
    rendered = assess_render_evidence(output / "render")
    total = sum(p.stat().st_size for d in (output, private) for p in d.rglob("*") if p.is_file())
    passed = (
        code == 0
        and summary["passed"]
        and unchanged
        and rendered["passed"]
        and total < 2_000_000_000
    )
    metadata.update(
        status="passed_pending_visual_and_independent_review" if passed else "failed",
        command_exit_code=code,
        tests=summary,
        source_unchanged=unchanged,
        original_pngs=len(pngs),
        retained_timelines=len(timelines),
        render_evidence=rendered,
        artifact_bytes=total,
        rendered_artifacts=[
            {"path": str(p.relative_to(output)), "sha256": sha256_file(p)} for p in pngs + timelines
        ],
        independent_review="not_run",
        visual_inspection="not_run",
        exit_code=0 if passed else 4,
    )
    (output / "verification-report.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata
