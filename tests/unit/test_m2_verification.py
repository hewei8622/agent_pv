"""Reject incomplete/selected/skipped desktop evidence without invoking graphics."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pv_sim.verification import assess_junit, assess_render_evidence

ROOT = Path(__file__).resolve().parents[2]


def test_no_rendered_files_cannot_pass(tmp_path):
    report = assess_render_evidence(tmp_path)
    assert not report["passed"]
    assert len(report["missing"]) == 56


def test_empty_timeline_references_are_an_integrity_failure(tmp_path):
    path = tmp_path / "sensor_delivery/late_valid/timeline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"images": []}))
    report = assess_render_evidence(tmp_path)
    assert "sensor_delivery/late_valid/timeline.json" in report["errors"]
    assert not report["passed"]


@pytest.mark.parametrize(
    "body,passed",
    [
        ('<testcase classname="tests.render.fixture" name="camera"/>', True),
        ('<testcase classname="tests.render.fixture" name="camera"><skipped/></testcase>', False),
        ('<testcase classname="tests.render.fixture" name="camera"><failure/></testcase>', False),
        ('<testcase classname="tests.render.fixture" name="camera"><error/></testcase>', False),
        ('<testcase classname="tests.render.fixture" name="other"/>', False),
        ("", False),
        ('<testcase classname="tests.render.fixture" name="camera"/>' * 2, False),
    ],
)
def test_exact_inventory_required(tmp_path, body, passed):
    xml = tmp_path / "synthetic-audit-input.xml"
    xml.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    report = assess_junit(xml, [{"classname": "tests.render.fixture", "name": "camera"}])
    assert report["passed"] is passed


def test_verify_help_and_bad_inputs_do_not_start_tests(tmp_path):
    command = [sys.executable, "-m", "pv_sim.cli", "verify"]
    result = subprocess.run(command + ["--help"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and "--suite" in result.stdout
    for config, seed in (
        ("configs/pilot.toml", "20261016"),
        ("absent.toml", "20261016"),
        ("configs/dev.toml", "11"),
    ):
        output = tmp_path / "must-not-exist"
        result = subprocess.run(
            command
            + [
                "--suite",
                "development",
                "--config",
                config,
                "--seed",
                seed,
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert not output.exists()


def test_desktop_dry_run_has_no_pilot_and_no_skip_flags():
    result = subprocess.run(
        [sys.executable, "scripts/run_m2_desktop.py", "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert '"verify"' in result.stdout and '"--check"' in result.stdout
    assert '"demo"' not in result.stdout and '"--no-render"' not in result.stdout
