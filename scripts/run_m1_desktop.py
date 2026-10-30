#!/usr/bin/env python3
"""Run the bounded M1 graphics gate in Wei's known working desktop Terminal.

Stop on the first failure. Never retry a pilot automatically. Each command is
recorded, each output is new, and replay never queries the policy again.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2_000_000_000


def commands(batch_id: str) -> list[tuple[str, list[str]]]:
    items = [
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
    for seed in (11, 23, 47):
        run_id = f"{batch_id}-s{seed}"
        items.append(
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
            )
        )
        items.append(
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
            )
        )
    return items


def artifact_bytes() -> int:
    return sum(
        path.stat().st_size
        for directory in (ROOT / "runs", ROOT / "private_eval", ROOT / "output")
        if directory.exists()
        for path in directory.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def write_progress(output: Path, report: dict) -> None:
    """One explicitly mutable status file; command logs and final evidence stay intact."""
    temporary = output / ".progress.tmp"
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(output / "progress.json")


def run_recorder(command: list[str], environment: dict, *, timeout: float = 190) -> int:
    """Allow the recorder to stop its owned descendants before a final forced exit."""
    process = None
    interruption = None

    def interrupted(signum, _frame):
        nonlocal interruption
        interruption = signum
        raise InterruptedError("desktop controller interrupted")

    previous_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        process = subprocess.Popen(command, cwd=ROOT, env=environment)
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code = 124
    except (KeyboardInterrupt, InterruptedError):
        code = 128 + (interruption or signal.SIGINT)
    except OSError:
        code = 127
    finally:
        signal.signal(signal.SIGTERM, previous_term)
    if process is not None and process.poll() is None:
        # subprocess.run(timeout=...) would SIGKILL this recorder immediately,
        # preventing its SIGTERM handler from cleaning up the uv/pilot group.
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running")
    args = parser.parse_args()
    batch_id = args.batch_id or (
        datetime.now(timezone.utc).strftime("m1-desktop-%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,90}", batch_id):
        parser.error("batch ID must be a short letters/digits/underscore/hyphen identifier")
    planned = commands(batch_id)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "commands": planned,
                    "post_run_audit": [
                        "uv",
                        "run",
                        "--locked",
                        "python",
                        "scripts/audit_m1_batch.py",
                        "--batch-report",
                        f"runs/{batch_id}/batch-report.json",
                        "--output",
                        f"runs/{batch_id}/machine-audit.json",
                    ],
                },
                indent=2,
            )
        )
        return 0
    output = ROOT / "runs" / batch_id
    if output.exists():
        parser.error("batch output already exists; prior evidence is never overwritten")
    if artifact_bytes() >= MAX_BYTES:
        parser.error("2 GB artifact cap reached; review required")
    output.mkdir(parents=True)
    environment = dict(os.environ)
    environment.pop("MUJOCO_GL", None)
    environment.pop("UV_PROJECT_ENVIRONMENT", None)
    environment.pop("PYTEST_ADDOPTS", None)
    report = {
        "batch_id": batch_id,
        "status": "running",
        "results": [],
        "scope": "M1 only; stop for independent review before M2",
        "max_complete_pilots": 3,
        "seeds": [11, 23, 47],
        "environment_removed": ["MUJOCO_GL", "UV_PROJECT_ENVIRONMENT", "PYTEST_ADDOPTS"],
    }
    (output / "planned.json").write_text(json.dumps(report | {"commands": planned}, indent=2))
    started = time.monotonic()
    code = 0
    write_progress(output, report)
    for label, command in planned:
        if time.monotonic() - started + 196 > 1800 or artifact_bytes() >= MAX_BYTES:
            report["status"] = "work_limit_reached"
            code = 4
            break
        print(f"M1 {label}: starting; new evidence under runs/{batch_id}/evidence", flush=True)
        write_progress(output, report | {"active_command": label})
        runner = [
            sys.executable,
            "scripts/record_command.py",
            "--label",
            label,
            "--evidence-dir",
            f"runs/{batch_id}/evidence",
            "--timeout",
            "180",
            "--",
            *command,
        ]
        command_code = run_recorder(runner, environment)
        report["results"].append({"label": label, "exit_code": command_code})
        write_progress(output, report | {"active_command": None})
        if command_code:
            code = command_code
            report["status"] = "stopped_at_first_failure"
            break
    else:
        report["status"] = "commands_passed_pending_image_inspection_and_independent_review"
    report["elapsed_wall_s"] = time.monotonic() - started
    report["artifact_bytes"] = artifact_bytes()
    if report["artifact_bytes"] >= MAX_BYTES:
        report["status"] = "work_limit_reached"
        code = 4
    (output / "batch-report.json").write_text(json.dumps(report, indent=2) + "\n")
    write_progress(output, report | {"active_command": None})
    print(json.dumps(report, indent=2))
    if code == 0:
        if time.monotonic() - started + 196 > 1800 or artifact_bytes() >= MAX_BYTES:
            write_progress(
                output,
                report | {"active_command": None, "status": "work_limit_reached_before_audit"},
            )
            return 4
        write_progress(output, report | {"active_command": "audit"})
        audit_command = [
            sys.executable,
            "scripts/record_command.py",
            "--label",
            "audit",
            "--evidence-dir",
            f"runs/{batch_id}/evidence",
            "--timeout",
            "180",
            "--",
            "uv",
            "run",
            "--locked",
            "python",
            "scripts/audit_m1_batch.py",
            "--batch-report",
            f"runs/{batch_id}/batch-report.json",
            "--output",
            f"runs/{batch_id}/machine-audit.json",
        ]
        code = run_recorder(audit_command, environment)
        write_progress(
            output,
            report
            | {
                "active_command": None,
                "machine_audit_exit_code": code,
                "status": "machine_audit_passed_pending_review"
                if code == 0
                else "machine_audit_failed",
            },
        )
        print(
            json.dumps(
                {
                    "machine_audit_exit_code": code,
                    "machine_audit": f"runs/{batch_id}/machine-audit.json",
                    "independent_review": "pending",
                },
                indent=2,
            )
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
