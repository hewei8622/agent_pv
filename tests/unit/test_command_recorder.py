"""Recorder process ownership: timeouts must stop descendants, not just uv."""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def invoke(arguments, *, environment=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/record_command.py"), *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=12,
    )


def directory():
    result = ROOT / "runs/m1-followthrough/runner-testcases" / uuid.uuid4().hex
    result.mkdir(parents=True)
    return result


def test_recorder_retains_failure_and_logs_only_declared_overrides():
    output = directory()
    result = invoke(
        [
            "--label",
            "child-failure",
            "--evidence-dir",
            str(output),
            "--",
            sys.executable,
            "-c",
            "import sys; print('real output'); sys.exit(7)",
        ],
        environment={**os.environ, "UV_PRIVATE_TOKEN": "DO_NOT_RECORD_THIS_CANARY"},
    )
    assert result.returncode == 7
    record = json.loads((output / "commands.jsonl").read_text())
    assert record["exit_code"] == 7
    assert (output / "child-failure.stdout.txt").read_text() == "real output\n"
    assert "DO_NOT_RECORD_THIS_CANARY" not in result.stdout
    assert "UV_PRIVATE_TOKEN" not in record["environment_overrides"]


def test_timeout_terminates_ignoring_descendant_process():
    output = directory()
    heartbeat = output / "heartbeat.txt"
    pid_path = output / "child.pid"
    child = textwrap.dedent("""
        import os, signal, sys, time
        from pathlib import Path
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        Path(sys.argv[2]).write_text(str(os.getpid()))
        for index in range(300):
            Path(sys.argv[1]).write_text(str(index))
            time.sleep(.02)
    """)
    parent = textwrap.dedent("""
        import signal, subprocess, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], sys.argv[3]])
        time.sleep(10)
    """)
    try:
        result = invoke(
            [
                "--label",
                "timeout-tree",
                "--evidence-dir",
                str(output),
                "--timeout",
                ".4",
                "--",
                sys.executable,
                "-c",
                parent,
                child,
                str(heartbeat),
                str(pid_path),
            ]
        )
        assert result.returncode == 124, result.stdout + result.stderr
        assert heartbeat.exists(), "the real descendant must start before timeout"
        first = heartbeat.read_text()
        time.sleep(0.2)
        assert heartbeat.read_text() == first, "descendant continued after recorded timeout"
        record = json.loads((output / "commands.jsonl").read_text())
        assert record["exit_code"] == 124 and record["elapsed_s"] < 5
    finally:
        # Only the exact test-owned child, in case this regression fails.
        if pid_path.exists():
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_successful_leader_cannot_leave_running_descendant():
    output = directory()
    heartbeat = output / "leader-exit-heartbeat.txt"
    pid_path = output / "leader-exit-child.pid"
    child = textwrap.dedent("""
        import os, signal, sys, time
        from pathlib import Path
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        Path(sys.argv[2]).write_text(str(os.getpid()))
        for index in range(300):
            Path(sys.argv[1]).write_text(str(index))
            time.sleep(.02)
    """)
    parent = textwrap.dedent("""
        import subprocess, sys, time
        from pathlib import Path
        subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], sys.argv[3]])
        for _ in range(100):
            if Path(sys.argv[2]).exists():
                break
            time.sleep(.01)
        else:
            raise SystemExit(9)
    """)
    try:
        result = invoke(
            [
                "--label",
                "leader-exit",
                "--evidence-dir",
                str(output),
                "--timeout",
                "10",
                "--",
                sys.executable,
                "-c",
                parent,
                child,
                str(heartbeat),
                str(pid_path),
            ]
        )
        assert result.returncode == 125, result.stdout + result.stderr
        assert heartbeat.exists()
        first = heartbeat.read_text()
        time.sleep(0.2)
        assert heartbeat.read_text() == first, "child outlived successful command leader"
        record = json.loads((output / "commands.jsonl").read_text())
        assert record["command_exit_code"] == 0
        assert record["remaining_descendants_terminated"] is True
        assert record["exit_code"] == 125
    finally:
        if pid_path.exists():
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize(
    "arguments",
    [
        ["--label", "../escape", "--", "true"],
        ["--label", "empty"],
        ["--label", "bad-time", "--timeout", "nan", "--", "true"],
        ["--label", "bad-time", "--timeout", "-1", "--", "true"],
    ],
)
def test_bad_recorder_input_is_rejected_before_launch(arguments):
    assert invoke(arguments).returncode == 2
