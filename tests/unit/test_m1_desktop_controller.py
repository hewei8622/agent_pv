"""Unattended orchestration negative paths; no renderer or pilot is invoked."""

import importlib.util
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def controller():
    spec = importlib.util.spec_from_file_location(
        "desktop_controller", ROOT / "scripts/run_m1_desktop.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_command_failure_stops_before_next_job_and_preserves_status(monkeypatch):
    module = controller()
    batch = "m1-controller-failure-" + uuid.uuid4().hex
    monkeypatch.setattr(sys, "argv", ["run_m1_desktop.py", "--batch-id", batch])
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k silently_select_a_subset")
    monkeypatch.setattr(
        module,
        "commands",
        lambda _: [
            (
                "unit-fixture-failure",
                [
                    sys.executable,
                    "-c",
                    "import os; assert 'PYTEST_ADDOPTS' not in os.environ; raise SystemExit(7)",
                ],
            ),
            ("must-not-run", [sys.executable, "-c", "raise SystemExit(99)"]),
        ],
    )
    assert module.main() == 7
    output = ROOT / "runs" / batch
    report = json.loads((output / "batch-report.json").read_text())
    assert report["status"] == "stopped_at_first_failure"
    assert report["results"] == [{"label": "unit-fixture-failure", "exit_code": 7}]
    assert json.loads((output / "progress.json").read_text())["active_command"] is None
    entries = (output / "evidence/commands.jsonl").read_text().splitlines()
    assert len(entries) == 1 and json.loads(entries[0])["exit_code"] == 7
    assert not (output / "machine-audit.json").exists()


def test_outer_timeout_retains_incomplete_report_without_retry(monkeypatch):
    module = controller()
    batch = "m1-controller-timeout-" + uuid.uuid4().hex
    monkeypatch.setattr(sys, "argv", ["run_m1_desktop.py", "--batch-id", batch])
    monkeypatch.setattr(module, "commands", lambda _: [("timeout-fixture", ["unused"])])
    calls = []

    def timeout(command, environment):
        calls.append(command)
        return 124

    monkeypatch.setattr(module, "run_recorder", timeout)
    assert module.main() == 124
    assert len(calls) == 1
    report = json.loads((ROOT / "runs" / batch / "batch-report.json").read_text())
    assert report["status"] == "stopped_at_first_failure"
    assert report["results"] == [{"label": "timeout-fixture", "exit_code": 124}]


def test_outer_watchdog_allows_recorder_to_stop_real_descendant():
    module = controller()
    output = ROOT / "runs/m1-followthrough/runner-testcases" / uuid.uuid4().hex
    output.mkdir(parents=True)
    heartbeat = output / "watchdog-heartbeat.txt"
    pid_path = output / "watchdog-child.pid"
    child = (
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "Path(sys.argv[2]).write_text(str(os.getpid()))\n"
        "for index in range(300):\n"
        "    Path(sys.argv[1]).write_text(str(index))\n"
        "    time.sleep(.02)\n"
    )
    command = [
        sys.executable,
        "scripts/record_command.py",
        "--label",
        "outer-watchdog",
        "--evidence-dir",
        str(output),
        "--timeout",
        "10",
        "--",
        sys.executable,
        "-c",
        child,
        str(heartbeat),
        str(pid_path),
    ]
    try:
        assert module.run_recorder(command, dict(os.environ), timeout=0.4) == 124
        assert heartbeat.exists(), "the actual owned descendant must have started"
        first = heartbeat.read_text()
        time.sleep(0.2)
        assert heartbeat.read_text() == first
        entry = json.loads((output / "commands.jsonl").read_text())
        assert entry["exit_code"] == 143 and entry["elapsed_s"] < 5
    finally:
        if pid_path.exists():
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_dry_run_discloses_live_commands_and_audit_without_writes(monkeypatch, capsys):
    module = controller()
    batch = "m1-controller-dryrun-" + uuid.uuid4().hex
    monkeypatch.setattr(sys, "argv", ["run_m1_desktop.py", "--dry-run", "--batch-id", batch])
    assert module.main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert [item[0] for item in plan["commands"]] == [
        "tests",
        "pilot-11",
        "replay-11",
        "pilot-23",
        "replay-23",
        "pilot-47",
        "replay-47",
    ]
    assert "scripts/audit_m1_batch.py" in plan["post_run_audit"]
    assert not (ROOT / "runs" / batch).exists()
