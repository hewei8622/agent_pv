#!/usr/bin/env python3
"""Execute M2 schema and integrity checks in the known working desktop context."""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from run_m1_desktop import MAX_BYTES, ROOT, artifact_bytes, run_recorder, write_progress


def commands(batch_id):
    return [
        ("schemas", ["uv", "run", "--locked", "python", "scripts/export_schemas.py", "--check"]),
        (
            "verification",
            [
                "uv",
                "run",
                "--locked",
                "pv-sim",
                "verify",
                "--suite",
                "development",
                "--config",
                "configs/dev.toml",
                "--seed",
                "20261016",
                "--output",
                f"runs/{batch_id}-verification",
            ],
        ),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    batch_id = (
        args.batch_id
        or datetime.now(timezone.utc).strftime("m2-desktop-%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", batch_id):
        parser.error("batch ID must be a short safe identifier")
    jobs = commands(batch_id)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "commands": jobs,
                    "scope": "M2 fixtures; no complete policy pilots",
                },
                indent=2,
            )
        )
        return 0
    output = ROOT / "runs" / batch_id
    if output.exists() or (ROOT / "runs" / f"{batch_id}-verification").exists():
        parser.error("output exists; previous evidence retained")
    if artifact_bytes() >= MAX_BYTES:
        parser.error("artifact cap reached; review required")
    output.mkdir(parents=True)
    environment = dict(os.environ)
    for name in ("MUJOCO_GL", "UV_PROJECT_ENVIRONMENT", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(name, None)
    report = {"batch_id": batch_id, "milestone": "M2", "status": "running", "results": []}
    started = time.monotonic()
    deadline = started + 1800
    write_progress(output, report)
    for label, argv in jobs:
        remaining = deadline - time.monotonic()
        if remaining <= 10:
            report["status"] = "failed"
            report["failure"] = "shared 30-minute batch deadline exhausted"
            break
        # Leave ten seconds for recorder/process-group cleanup and final logs.
        timeout = min(180 if label == "schemas" else 1780, remaining - 10)
        command = [
            sys.executable,
            "scripts/record_command.py",
            "--label",
            label,
            "--evidence-dir",
            str(output.relative_to(ROOT) / "evidence"),
            "--timeout",
            str(timeout),
            "--",
            *argv,
        ]
        code = run_recorder(command, environment, timeout=timeout + 4)
        report["results"].append({"label": label, "argv": argv, "exit_code": code})
        write_progress(output, report)
        if code != 0:
            report["status"] = "failed"
            break
    else:
        report["status"] = "passed_pending_visual_and_independent_review"
    report["verification_report"] = f"runs/{batch_id}-verification/verification-report.json"
    report["m3_authorized"] = False
    report["elapsed_s"] = time.monotonic() - started
    (output / "batch-report.json").write_text(json.dumps(report, indent=2) + "\n")
    write_progress(output, report)
    print(json.dumps(report, indent=2))
    return 0 if report["status"].startswith("passed_") else 4


if __name__ == "__main__":
    raise SystemExit(main())
