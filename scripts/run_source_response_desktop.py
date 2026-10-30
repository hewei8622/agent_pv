#!/usr/bin/env python3
"""Run bounded IP1 source-response fixtures in the working desktop context.

Stop at the first failure without retries. Successful commands still require
visual and independent review; this controller runs no complete policy pilots.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from run_m1_desktop import MAX_BYTES, ROOT, artifact_bytes, run_recorder, write_progress

REMOVED_ENVIRONMENT = (
    "MUJOCO_GL", "UV_PROJECT_ENVIRONMENT", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"
)
SCOPE = "IP1 source-response fixtures; no complete policy pilots"
MAX_WALL_S = 1800
CLEANUP_ALLOWANCE_S = 12


def commands(batch_id: str) -> list[tuple[str, list[str]]]:
    return [
        ("schemas", ["uv", "run", "--locked", "python", "scripts/export_schemas.py", "--check"]),
        (
            "tests",
            [
                "uv", "run", "--locked", "python", "-m", "pytest",
                "tests/unit", "tests/integration", "tests/render", "tests/security", "-q",
                f"--junitxml=runs/{batch_id}/tests.xml",
            ],
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id")
    parser.add_argument(
        "--dry-run", action="store_true", help="print plan without execution or writes"
    )
    args = parser.parse_args()
    batch_id = args.batch_id or (
        datetime.now(timezone.utc).strftime("source-desktop-%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", batch_id):
        parser.error("batch ID must be a short safe identifier")
    output = ROOT / "runs" / batch_id
    source_output = ROOT / "runs" / f"{batch_id}-source-response"
    private_output = ROOT / "private_eval" / source_output.name
    overrides = {
        "PV_SOURCE_RESPONSE_EVIDENCE_DIR": str(source_output),
        "PV_M2_RENDER_EVIDENCE_DIR": str(output / "m2-regression-images"),
    }
    jobs = commands(batch_id)
    plan = {
        "batch_id": batch_id,
        "milestone": "IP1",
        "scope": SCOPE,
        "commands": jobs,
        "environment_removed": list(REMOVED_ENVIRONMENT),
        "environment_overrides": overrides,
        "output": str(output.relative_to(ROOT)),
        "source_response_report": str((source_output / "report.json").relative_to(ROOT)),
        "source_response_private": str(private_output.relative_to(ROOT)),
        "max_wall_s": MAX_WALL_S,
        "automatic_retries": 0,
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    for path in (output, source_output, private_output):
        if path.exists() or path.is_symlink():
            parser.error("output exists; prior evidence is never overwritten")
    started = time.monotonic()
    if artifact_bytes() >= MAX_BYTES:
        parser.error("2 GB artifact cap reached; review required")
    output.mkdir(parents=True)
    with (output / "planned.json").open("x") as stream:
        stream.write(json.dumps(plan, indent=2) + "\n")
    environment = dict(os.environ)
    for name in REMOVED_ENVIRONMENT:
        environment.pop(name, None)
    environment.update(overrides)
    report = plan | {
        "status": "running", "results": [], "independent_review": "pending",
        "visual_review": "pending",
    }
    write_progress(output, report | {"active_command": None})
    code = 0
    for label, argv in jobs:
        current_bytes = artifact_bytes()
        remaining = MAX_WALL_S - (time.monotonic() - started)
        if remaining <= CLEANUP_ALLOWANCE_S or current_bytes >= MAX_BYTES:
            code = 4
            report["status"] = "work_limit_reached"
            report["failure"] = "shared wall-time or artifact limit exhausted"
            break
        timeout = min(180 if label == "schemas" else MAX_WALL_S,
                      remaining - CLEANUP_ALLOWANCE_S)
        runner = [
            sys.executable, "scripts/record_command.py", "--label", label,
            "--evidence-dir", str(output.relative_to(ROOT) / "evidence"),
            "--timeout", str(timeout), "--", *argv,
        ]
        print(f"IP1 {label}: starting; evidence under runs/{batch_id}/evidence", flush=True)
        write_progress(output, report | {"active_command": label})
        code = run_recorder(runner, environment, timeout=timeout + 4)
        report["results"].append({"label": label, "argv": argv, "exit_code": code})
        write_progress(output, report | {"active_command": None})
        if code:
            report["status"] = "stopped_at_first_failure"
            break
    else:
        report["status"] = "commands_passed_pending_visual_and_independent_review"
    report["artifact_bytes"] = artifact_bytes()
    report["elapsed_s"] = time.monotonic() - started
    if code == 0 and (
        report["artifact_bytes"] >= MAX_BYTES or report["elapsed_s"] >= MAX_WALL_S
    ):
        report["status"] = "work_limit_reached"
        code = 4
    with (output / "batch-report.json").open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    write_progress(output, report | {"active_command": None})
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
