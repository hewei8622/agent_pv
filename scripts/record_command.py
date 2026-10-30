"""Record a real command without shell interpretation; retain failures. Python 3.9+."""

import argparse
import datetime
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


def stop_group(process):
    """Stop only the subprocess group created by this recorder, including children."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # The leader can exit while an ignoring grandchild keeps the group alive.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


def group_alive(process):
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("runs/m0-setup/evidence"),
        help="project-relative directory for this milestone's command evidence",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", args.label):
        parser.error("label must contain letters, digits, underscores or hyphens")
    if not command:
        parser.error("a command is required")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be positive and finite")
    root = Path(__file__).resolve().parents[1]
    evidence = (root / args.evidence_dir).resolve()
    if not evidence.is_relative_to(root):
        parser.error("evidence directory must stay inside the project")
    evidence.mkdir(parents=True, exist_ok=True)
    prefix = evidence / args.label
    stdout_path = prefix.with_suffix(".stdout.txt")
    stderr_path = prefix.with_suffix(".stderr.txt")
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    env = os.environ.copy()
    overrides = {
        "UV_CACHE_DIR": str(root / ".tools/uv-cache"),
        "UV_PYTHON_INSTALL_DIR": str(root / ".tools/python"),
        "UV_PYTHON_BIN_DIR": str(root / ".tools/bin"),
        "UV_TOOL_DIR": str(root / ".tools/uv-tools"),
        "UV_TOOL_BIN_DIR": str(root / ".tools/bin"),
        "UV_NO_MODIFY_PATH": "1",
        "UV_LINK_MODE": "copy",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_CACHE_DIR": str(root / ".tools/pip-cache"),
        "HYPOTHESIS_STORAGE_DIRECTORY": str(root / ".hypothesis"),
    }
    env.update(overrides)
    env["PATH"] = str(root / ".tools/bootstrap/bin") + os.pathsep + env["PATH"]
    clock = time.monotonic()
    process = None
    interruption = None
    command_exit_code = None
    remaining_descendants_terminated = False

    def interrupted(signum, _frame):
        nonlocal interruption
        interruption = signum
        raise InterruptedError("recorder interrupted")

    previous_term = signal.signal(signal.SIGTERM, interrupted)
    with stdout_path.open("x") as out, stderr_path.open("x") as err:
        try:
            process = subprocess.Popen(
                command,
                cwd=root,
                env=env,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            code = command_exit_code = process.wait(timeout=min(args.timeout, 1800))
            if group_alive(process):
                stop_group(process)
                remaining_descendants_terminated = True
                code = code or 125
                err.write(
                    "Command exited with remaining descendants; owned process group terminated\n"
                )
        except subprocess.TimeoutExpired:
            stop_group(process)
            code = 124
            err.write("Command exceeded recorded timeout; owned process group terminated\n")
        except (KeyboardInterrupt, InterruptedError):
            if process is not None:
                stop_group(process)
            code = 128 + (interruption or signal.SIGINT)
            err.write("Recorder interrupted; owned process group terminated\n")
        except OSError as exc:
            code = 127
            err.write(str(exc) + "\n")
        finally:
            signal.signal(signal.SIGTERM, previous_term)
    entry = {
        "label": args.label,
        "argv": command,
        "cwd": str(root),
        "started_utc": started,
        "ended_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "elapsed_s": time.monotonic() - clock,
        "exit_code": code,
        "command_exit_code": command_exit_code,
        "remaining_descendants_terminated": remaining_descendants_terminated,
        "stdout": str(stdout_path.relative_to(root)),
        "stderr": str(stderr_path.relative_to(root)),
        "runner_python": sys.version,
        "environment_overrides": {
            key: value
            for key, value in overrides.items()
            if key.startswith("UV_") or key == "PIP_CACHE_DIR"
        },
    }
    with (evidence / "commands.jsonl").open("a") as file:
        file.write(json.dumps(entry, sort_keys=True) + "\n")
    print(json.dumps(entry, indent=2))
    print(stdout_path.read_text())
    print(stderr_path.read_text(), file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
