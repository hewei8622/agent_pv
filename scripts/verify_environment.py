"""Real import/render probe with immutable evidence directories and exit status."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
from importlib import metadata
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.exit(2, "output already exists; evidence will not be overwritten\n")
    root = Path(__file__).resolve().parents[1]
    report = {
        "incomplete": True,
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "python": sys.version,
        "python_executable": sys.executable,
        "uv": subprocess.check_output(["uv", "--version"], text=True).strip(),
        "mujoco_gl_override": os.environ.get("MUJOCO_GL"),
        "render_requested": args.render,
        "checks": {},
    }
    report_path = args.output / "environment.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    code = 0
    try:
        import mujoco
        import numpy
        import PIL
        import pydantic

        import pv_sim
        from pv_sim.config import load_config

        if sys.version_info[:2] != (3, 11) or mujoco.__version__ != "3.3.7":
            raise AssertionError("wrong Python/MuJoCo baseline")
        report["checks"]["imports"] = "passed"
        report["core_versions"] = dict(
            python=platform.python_version(),
            mujoco=mujoco.__version__,
            numpy=numpy.__version__,
            pillow=PIL.__version__,
            pydantic=pydantic.__version__,
            pv_sim=pv_sim.__version__,
        )
        config = load_config(root / "configs/pilot.toml")
        (args.output / "expanded_config.json").write_text(config.canonical_json() + "\n")
        report["expanded_config_sha256"] = config.sha256()
        report["packages"] = []
        notices = args.output / "dependency_notices"
        notices.mkdir()
        for dist in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
            name = dist.metadata["Name"]
            record = {
                "name": name,
                "version": dist.version,
                "license_expression": dist.metadata.get("License-Expression"),
                "license": dist.metadata.get("License"),
                "notices": [],
            }
            for file in dist.files or []:
                if (
                    "license" in Path(str(file)).name.lower()
                    or "notice" in Path(str(file)).name.lower()
                ):
                    source = Path(dist.locate_file(file))
                    if source.is_file():
                        folder = notices / name
                        folder.mkdir(exist_ok=True)
                        target = folder / f"{len(record['notices']):02}-{source.name}"
                        shutil.copyfile(source, target)
                        record["notices"].append(
                            {"path": str(target.relative_to(args.output)), "sha256": sha256(target)}
                        )
            report["packages"].append(record)
        report["input_hashes"] = {
            str(p.relative_to(root)): sha256(p)
            for p in (
                root / "uv.lock",
                root / "pyproject.toml",
                root / ".python-version",
                root / "configs/pilot.toml",
                root / "configs/tolerances.toml",
                *sorted((root / "docs/handoff").glob("*.md")),
            )
        }
        if args.render:
            from PIL import Image

            from pv_sim.calibration import render_calibration

            rgb, details, xml = render_calibration()
            image_path = args.output / "agent_rgb.png"
            Image.fromarray(rgb).save(image_path)
            (args.output / "calibration.xml").write_text(xml)
            report["render"] = details
            report["render"]["png_sha256"] = sha256(image_path)
            report["checks"]["real_rgb"] = "passed"
        else:
            report["checks"]["real_rgb"] = "not_run"
        report["incomplete"] = False
    except AssertionError:
        code = 4
        report["checks"]["invariant"] = "failed"
        (args.output / "failure.txt").write_text(traceback.format_exc())
    except Exception:
        code = 3
        report["checks"]["environment"] = "blocked"
        (args.output / "failure.txt").write_text(traceback.format_exc())
    report["exit_code"] = code
    report["ended_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    temp = report_path.with_suffix(".tmp")
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    temp.replace(report_path)
    print(
        json.dumps(
            {
                "checks": report["checks"],
                "exit_code": code,
                "versions": report.get("core_versions"),
                "render": report.get("render"),
            },
            indent=2,
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
