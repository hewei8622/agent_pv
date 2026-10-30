"""IP1 controller isolation, evidence retention and fail-fast tests; no GL."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "source_desktop_controller", ROOT / "scripts/run_source_response_desktop.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "artifact_bytes", lambda: 0)
    return module


def test_dry_run_exposes_exact_scope_commands_and_clean_environment_without_writes(
    controller, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(sys, "argv", ["controller", "--dry-run", "--batch-id", "source-check"])
    monkeypatch.setattr(controller, "run_recorder", lambda *a, **k: pytest.fail("must not execute"))
    assert controller.main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert [label for label, _ in plan["commands"]] == ["schemas", "tests"]
    assert plan["commands"][0][1] == [
        "uv", "run", "--locked", "python", "scripts/export_schemas.py", "--check"
    ]
    assert plan["commands"][1][1] == [
        "uv", "run", "--locked", "python", "-m", "pytest", "tests/unit", "tests/integration",
        "tests/render", "tests/security", "-q", "--junitxml=runs/source-check/tests.xml",
    ]
    assert set(plan["environment_removed"]) == {
        "MUJOCO_GL", "UV_PROJECT_ENVIRONMENT", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"
    }
    assert plan["environment_overrides"] == {
        "PV_SOURCE_RESPONSE_EVIDENCE_DIR": str(tmp_path / "runs/source-check-source-response"),
        "PV_M2_RENDER_EVIDENCE_DIR": str(tmp_path / "runs/source-check/m2-regression-images"),
    }
    assert plan["max_wall_s"] == 1800 and plan["automatic_retries"] == 0
    assert "no complete policy pilots" in plan["scope"]
    assert not list(tmp_path.iterdir())


def test_real_child_failure_stops_next_dispatch_and_retains_pending_report(
    controller, monkeypatch, tmp_path
):
    monkeypatch.setattr(sys, "argv", ["controller", "--batch-id", "source-failure"])
    for name in controller.REMOVED_ENVIRONMENT:
        monkeypatch.setenv(name, "must_not_reach_child")
    monkeypatch.setenv("PV_SOURCE_RESPONSE_EVIDENCE_DIR", "old_output_must_not_be_used")
    monkeypatch.setenv("PV_M2_RENDER_EVIDENCE_DIR", "old_images_must_not_be_used")
    script = (
        "import os; from pathlib import Path; "
        "assert all(n not in os.environ for n in "
        "('MUJOCO_GL','UV_PROJECT_ENVIRONMENT','PYTEST_ADDOPTS','PYTEST_PLUGINS')); "
        "assert Path(os.environ['PV_SOURCE_RESPONSE_EVIDENCE_DIR']).name == "
        "'source-failure-source-response'; "
        "assert Path(os.environ['PV_M2_RENDER_EVIDENCE_DIR']).name == 'm2-regression-images'; "
        "raise SystemExit(7)"
    )
    monkeypatch.setattr(controller, "commands", lambda _: [
        ("failure", [sys.executable, "-c", script]), ("must-not-run", ["never"])
    ])
    calls = []

    def dispatch(command, environment, *, timeout):
        # The shared recorder/cleanup helper has its own real-process tests.
        # Here a real harmless child checks the controller's sanitized env.
        calls.append(command)
        assert 0 < timeout < 1800
        argv = command[command.index("--") + 1:]
        return subprocess.run(argv, cwd=tmp_path, env=environment, timeout=5).returncode

    monkeypatch.setattr(controller, "run_recorder", dispatch)
    assert controller.main() == 7
    assert len(calls) == 1
    output = tmp_path / "runs/source-failure"
    report = json.loads((output / "batch-report.json").read_text())
    assert report["status"] == "stopped_at_first_failure"
    assert len(report["results"]) == 1 and report["results"][0]["exit_code"] == 7
    assert report["visual_review"] == report["independent_review"] == "pending"
    assert json.loads((output / "progress.json").read_text())["active_command"] is None
    assert (output / "planned.json").exists()


@pytest.mark.parametrize("collision", [
    "runs/source-collision", "runs/source-collision-source-response",
    "private_eval/source-collision-source-response",
])
def test_existing_outputs_are_retained_before_any_dispatch(
    controller, monkeypatch, tmp_path, collision
):
    directory = tmp_path / collision
    directory.mkdir(parents=True)
    evidence = directory / "retained.txt"
    evidence.write_text("prior evidence")
    monkeypatch.setattr(sys, "argv", ["controller", "--batch-id", "source-collision"])
    monkeypatch.setattr(controller, "run_recorder", lambda *a, **k: pytest.fail("must not execute"))
    with pytest.raises(SystemExit) as error:
        controller.main()
    assert error.value.code == 2 and evidence.read_text() == "prior evidence"
    assert not (tmp_path / "runs/source-collision/batch-report.json").exists()


def test_expired_shared_deadline_does_not_start_a_command(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["controller", "--batch-id", "source-deadline"])
    times = iter([0.0, 1790.0, 1790.0])
    monkeypatch.setattr(controller.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(controller, "run_recorder", lambda *a, **k: pytest.fail("must not execute"))
    assert controller.main() == 4
    report = json.loads((tmp_path / "runs/source-deadline/batch-report.json").read_text())
    assert report["status"] == "work_limit_reached" and report["results"] == []


def test_success_keeps_review_pending_and_never_dispatches_pilots(
    controller, monkeypatch, tmp_path
):
    monkeypatch.setattr(sys, "argv", ["controller", "--batch-id", "source-success"])
    calls = []

    def dispatch(command, environment, *, timeout):
        calls.append((command, timeout))
        return 0

    monkeypatch.setattr(controller, "run_recorder", dispatch)
    assert controller.main() == 0
    assert len(calls) == 2
    report = json.loads((tmp_path / "runs/source-success/batch-report.json").read_text())
    assert report["status"] == "commands_passed_pending_visual_and_independent_review"
    assert report["visual_review"] == report["independent_review"] == "pending"
    assert [item["label"] for item in report["results"]] == ["schemas", "tests"]
    assert all("demo" not in item["argv"] for item in report["results"])
