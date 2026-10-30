"""Create a read-only M1 evidence PDF from verified artifacts, without simulation.

Run with the existing .tools/pdf-report/bin/python report environment. No report
dependency is added to the simulator. Every output is exclusive; prior evidence
and PDFs are retained. Scientific trace/geometry figures are never labelled RGB.
"""
# The headless Matplotlib cache/backend must be selected before plotting imports.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".tools/matplotlib-cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

NAVY, TEAL, ORANGE = "#17334A", "#087F8C", "#B86424"
GREY, PALE, LINE = "#566B7A", "#EDF3F6", "#D6E1E8"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_json(path: Path):
    return json.loads(path.read_text())


def jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def checked_path(directory: Path, relative: str) -> Path:
    child = Path(relative)
    if child.is_absolute() or ".." in child.parts:
        raise ValueError("artifact path escapes its declared directory")
    result = (directory / child).resolve()
    if directory.resolve() not in result.parents:
        raise ValueError("artifact path escapes its declared directory")
    return result


def verify_manifest(path: Path) -> dict:
    """Integrity verification uses only recorded hashes, never a new world run."""
    path = path.resolve()
    if digest(path) != (path.parent / "manifest.sha256").read_text().strip():
        raise ValueError(f"manifest hash mismatch: {path}")
    manifest = load_json(path)
    if manifest.get("incomplete", True) or manifest.get("status") != "complete":
        raise ValueError(f"incomplete recording: {path}")
    output = (path.parent / manifest["public_relative_path"]).resolve()
    for item in manifest["artifacts"]:
        if item["scope"] not in ("public", "private"):
            raise ValueError("unknown artifact scope")
        base = output if item["scope"] == "public" else path.parent
        artifact = checked_path(base, item["path"])
        if not artifact.is_file() or digest(artifact) != item["sha256"]:
            raise ValueError(f"artifact hash mismatch: {artifact}")
    config = load_json(path.parent / "config.json")
    if hashlib.sha256(canonical(config).encode()).hexdigest() != manifest["config_sha256"]:
        raise ValueError("expanded configuration hash mismatch")
    changed = [
        name
        for name, expected in manifest["source_fingerprint"].items()
        if not (ROOT / name).is_file() or digest(ROOT / name) != expected
    ]
    return {
        "path": path,
        "manifest": manifest,
        "output": output,
        "config": config,
        "metrics": load_json(path.parent / "metrics.json"),
        "changed_sources": changed,
    }


def test_summary(path: Path) -> dict:
    xml = ET.parse(path).getroot()
    cases = list(xml.iter("testcase"))
    groups = Counter(case.attrib.get("classname", "unknown") for case in cases)
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    return {
        "total": len(cases),
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": len(cases) - failures - errors - skipped,
        "groups": dict(groups),
        "render_cases": sum(n for name, n in groups.items() if ".render." in name),
        "time_s": sum(float(s.attrib.get("time", 0)) for s in xml.iter("testsuite")),
        "timestamps": [s.attrib.get("timestamp") for s in xml.iter("testsuite")],
    }


def review_summary(path: Path) -> dict:
    text = path.read_text()
    if path.suffix == ".json":
        data = json.loads(text)
        verdict = str(data.get("verdict", data.get("status", "UNSPECIFIED")))
    else:
        match = re.search(r"(?im)^\s*(?:\*\*)?Verdict\s*:\s*(.+)$", text)
        verdict = match.group(1).strip().strip("*") if match else "UNSPECIFIED"
    return {"verdict": verdict, "text": text}


def find_replay(source: dict) -> tuple[Path | None, dict | None]:
    expected = digest(source["path"])
    for path in sorted(source["output"].parent.glob("*/evidence/replay.json")):
        report = load_json(path)
        if report.get("source_manifest_sha256") != expected:
            continue
        companion = source["path"].parent.parent / path.parents[1].name / "manifest.json"
        if companion.exists():
            verify_manifest(companion)
            return path, report
    return None, None


def observation_details(source: dict) -> dict:
    """Summarize saved public confirmations without rerunning the policy."""
    observations = jsonl(source["output"] / "public/observations.jsonl")
    feedback = [f for event in observations for f in event["payload"]["feedback"]]
    completed = {f["commanded_target"]["kind"]: f for f in feedback if f["code"] == "completed"}
    points = []
    for item in feedback:
        if item["code"] != "executing" or item["commanded_target"]["kind"] != "probe_voltage":
            continue
        samples = {m["sample"].get("channel"): m["sample"] for m in item["measured_confirmation"]}
        voltage, current = samples.get("voltage_v"), samples.get("current_a")
        if voltage and current and voltage["t_capture_s"] == current["t_capture_s"]:
            points.append(
                {
                    "voltage_v": voltage["value"],
                    "current_a": current["value"],
                    "power_w": voltage["value"] * current["value"],
                    "t_capture_s": voltage["t_capture_s"],
                    "t_deliver_s": voltage["t_deliver_s"],
                }
            )
    finish = completed.get("finish")
    confirmations = (
        {m["sample"].get("channel"): m["sample"] for m in finish["measured_confirmation"]}
        if finish
        else {}
    )
    return {"probe_points": points, "completed": completed, "finish_confirmations": confirmations}


def batch_summary(path: Path | None) -> dict:
    if path is None:
        return {"present": False, "complete": False, "runs": [], "frames": []}
    batch = load_json(path)
    audit_path = path.resolve().parent / "machine-audit.json"
    audit = load_json(audit_path) if audit_path.is_file() else None
    machine_checks_passed = bool(
        audit
        and audit.get("status") == "machine_checks_passed_pending_visual_and_independent_review"
        and audit.get("checks")
        and all(check.get("status") == "passed" for check in audit["checks"])
        and Path(audit.get("batch_report", "")).resolve() == path.resolve()
        and audit.get("batch_report_sha256") == digest(path)
    )
    runs, frames = [], []
    for seed in (11, 23, 47):
        identifier = f"{batch['batch_id']}-s{seed}"
        manifest_path = ROOT / "private_eval" / identifier / "manifest.json"
        row = {"seed": seed, "run_id": identifier, "ready": False}
        if manifest_path.is_file():
            manifest = load_json(manifest_path)
            if (
                digest(manifest_path)
                != (manifest_path.parent / "manifest.sha256").read_text().strip()
            ):
                raise ValueError("batch companion manifest hash mismatch")
            if manifest.get("incomplete", True) or manifest.get("status") != "complete":
                row["recording_status"] = manifest.get("status", "unknown")
                runs.append(row)
                continue
            source = verify_manifest(manifest_path)
            replay_path = ROOT / "private_eval" / f"{identifier}-replay" / "manifest.json"
            replay_report = None
            if replay_path.is_file():
                replay_source = verify_manifest(replay_path)
                replay_report = load_json(replay_source["output"] / "evidence/replay.json")
            metrics = source["metrics"]
            row.update(
                source=source,
                replay=replay_report,
                observations=observation_details(source),
                ready=(
                    metrics.get("pilot_passed", False)
                    and not metrics.get("core_only", True)
                    and metrics.get("verification_tail_complete", False)
                    and source["manifest"]["frame_count"] >= 2
                    and not source["changed_sources"]
                    and replay_report is not None
                    and replay_report.get("status") == "passed"
                    and replay_report.get("rendered_gate_satisfied", False)
                    and replay_report.get("truth_comparison", {}).get("passed", False)
                    and replay_report.get("metrics_comparison", {}).get("passed", False)
                ),
            )
            truth = {
                event["tick"]: event["payload"]
                for event in jsonl(source["path"].parent / "truth.jsonl")
            }
            seen = set()
            for event in jsonl(source["output"] / "public/observations.jsonl"):
                for frame in event["payload"]["rgb"]:
                    if frame.get("png_file") and frame["frame_id"] not in seen:
                        png = checked_path(source["output"] / "public", frame["png_file"])
                        if digest(png) != frame["png_sha256"]:
                            raise ValueError("camera PNG hash mismatch")
                        seen.add(frame["frame_id"])
                        tick = round(frame["t_capture_s"] / source["manifest"]["dt_s"])
                        capture = truth[tick]
                        if not math.isclose(capture["time_s"], frame["t_capture_s"], abs_tol=1e-12):
                            raise ValueError("frame midpoint lacks an exact recorded state")
                        frames.append(
                            {
                                "path": png,
                                "frame": frame,
                                "seed": seed,
                                "pose": capture["dynamics"],
                                "view": "Home" if len(seen) == 1 else "Side",
                            }
                        )
        runs.append(row)
    return {
        "present": True,
        "complete": all(row["ready"] for row in runs) and machine_checks_passed,
        "raw": batch,
        "runs": runs,
        "frames": frames,
        "machine_audit": audit,
        "machine_audit_path": audit_path if audit else None,
        "machine_checks_passed": machine_checks_passed,
    }


def plots(rows: list[dict], config: dict, directory: Path) -> dict:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "text.color": NAVY,
            "axes.labelcolor": NAVY,
            "xtick.color": GREY,
            "ytick.color": GREY,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    time = np.array([row["time_s"] for row in rows])
    temperature = np.array([row["temperature_c"] for row in rows])
    power = np.array([row["point"]["power_w"] for row in rows])
    voltage = np.array([row["point"]["voltage_v"] for row in rows])
    current = np.array([row["point"]["current_a"] for row in rows])
    q = np.array([row["dynamics"]["q"] for row in rows])
    setpoint = np.array([row["dynamics"]["setpoint"] for row in rows])
    cameras = np.array([row["dynamics"]["camera_position_m"] for row in rows])
    fig, axes = plt.subplots(3, 1, figsize=(8.6, 5.35), sharex=True, layout="constrained")
    for ax, values, color, label in zip(
        axes,
        (temperature, power, voltage),
        (ORANGE, TEAL, NAVY),
        ("Module temperature (C)", "Delivered power (W)", "Actual terminal voltage (V)"),
        strict=True,
    ):
        ax.plot(time, values, color=color, lw=1.65)
        ax.set_ylabel(label)
        ax.grid(alpha=0.16)
    axes[-1].set(xlabel="Simulation time (s)", xlim=(time[0], time[-1]))
    energy_path = directory / "electrical_thermal.png"
    fig.savefig(energy_path, dpi=190, facecolor="white")
    plt.close(fig)
    fig, axes = plt.subplots(3, 1, figsize=(8.6, 5.2), sharex=True, layout="constrained")
    scales = (1000, 180 / math.pi, 180 / math.pi)
    for index, (ax, scale, name) in enumerate(
        zip(axes, scales, ("Slide (mm)", "Yaw (deg)", "Pitch (deg)"), strict=True)
    ):
        ax.plot(time, q[:, index] * scale, color=TEAL, lw=1.8, label="Actual q")
        ax.plot(
            time,
            setpoint[:, index] * scale,
            color=ORANGE,
            lw=1.15,
            ls="--",
            label="Finite servo setpoint",
        )
        ax.set_ylabel(name)
        ax.grid(alpha=0.16)
        if index > 0 and np.max(np.abs(q[:, index] * scale)) < 0.01:
            # Keep tiny floating-point drift visible as zero-scale motion rather
            # than visually magnifying ~1e-34 degrees into a spurious excursion.
            ax.set_ylim(-0.01, 0.01)
            ax.text(
                0.99,
                0.85,
                "Near zero at this scale",
                transform=ax.transAxes,
                ha="right",
                color=GREY,
                fontsize=8,
            )
    axes[0].legend(loc="lower right", frameon=False, ncol=2, fontsize=9)
    axes[-1].set(xlabel="Simulation time (s)", xlim=(time[0], time[-1]))
    motion_path = directory / "actual_joint_motion.png"
    fig.savefig(motion_path, dpi=190, facecolor="white")
    plt.close(fig)
    fig = plt.figure(figsize=(8.7, 5.5), facecolor="white")
    ax = fig.add_subplot(111, projection="3d", computed_zorder=False)
    world = config["private_world"]
    width, height = world["panel_size_m"]
    center = np.array(world["panel_center_m"])
    if tuple(world["panel_normal"]) != (0, 0, 1):
        raise ValueError("geometry figure supports the declared upward-facing initial panel only")
    for row in range(world["rows"]):
        for col in range(world["columns"]):
            x0 = center[0] - width / 2 + col * width / world["columns"]
            y0 = center[1] - height / 2 + row * height / world["rows"]
            x1, y1 = x0 + width / world["columns"], y0 + height / world["rows"]
            corners = [
                (x0, y0, center[2]),
                (x1, y0, center[2]),
                (x1, y1, center[2]),
                (x0, y1, center[2]),
            ]
            ax.add_collection3d(
                Poly3DCollection(
                    [corners],
                    facecolors="#B9D7E2",
                    edgecolors="white",
                    linewidths=1.2,
                    alpha=0.85,
                    zorder=2,
                )
            )
    ax.plot(cameras[:, 0], cameras[:, 1], cameras[:, 2], color=TEAL, lw=3, zorder=10)
    for position, label, color in (
        (cameras[0], "Recorded start", GREY),
        (cameras[-1], "Recorded final", ORANGE),
    ):
        ax.scatter(*position, color=color, marker="D", s=65, depthshade=False, zorder=11)
        height_offset = 0.055 if label == "Recorded start" else 0.008
        ax.text(
            position[0] + 0.016,
            position[1] - 0.015,
            position[2] + height_offset,
            label,
            fontsize=9,
            color=color,
            zorder=12,
        )
    for index in (0, len(rows) - 1):
        rotation = np.array(rows[index]["dynamics"]["camera_rotation"]).reshape(3, 3)
        forward = -rotation[:, 2]
        ray_end = cameras[index] + forward * 0.35
        ax.plot(*np.vstack((cameras[index], ray_end)).T, color=ORANGE, ls="--", lw=1.2)
    ax.text(-0.14, 0.13, 0.025, "0.30 x 0.20 m panel / 8 cells", fontsize=9, color=NAVY)
    ax.set(
        xlabel="x (m)",
        ylabel="y (m)",
        zlabel="z (m)",
        xlim=(-0.20, 0.23),
        ylim=(-0.53, 0.20),
        zlim=(-0.02, 0.43),
    )
    ax.set_box_aspect((0.43, 0.73, 0.45))
    ax.set_xticks([-0.15, 0, 0.15])
    ax.set_yticks([-0.4, -0.2, 0])
    ax.set_zticks([0, 0.2, 0.4])
    ax.view_init(elev=24, azim=-56)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.fill = False
    fig.subplots_adjust(left=0, right=0.96, bottom=0.04, top=0.98)
    geometry_path = directory / "recorded_camera_geometry.png"
    fig.savefig(geometry_path, dpi=190, facecolor="white")
    plt.close(fig)
    return {
        "electrical_thermal": energy_path,
        "motion": motion_path,
        "geometry": geometry_path,
        "sample_count": len(rows),
        "elapsed_s": float(time[-1] - time[0]),
        "temperature_start_c": float(temperature[0]),
        "temperature_final_c": float(temperature[-1]),
        "power_min_w": float(power.min()),
        "power_max_w": float(power.max()),
        "maximum_power_identity_error_w": float(np.max(np.abs(power - voltage * current))),
        "q_final": q[-1].tolist(),
        "setpoint_final": setpoint[-1].tolist(),
        "maximum_dynamic_tracking_error": np.max(np.abs(q - setpoint), axis=0).tolist(),
        "maximum_saved_joint_rates": np.max(
            np.abs([row["dynamics"]["qdot"] for row in rows]), axis=0
        ).tolist(),
        "maximum_saved_setpoint_rates": np.max(
            np.abs([row["dynamics"]["setpoint_rate"] for row in rows]), axis=0
        ).tolist(),
        "final_tracking_error": np.abs(q[-1] - setpoint[-1]).tolist(),
        "camera_start_m": cameras[0].tolist(),
        "camera_final_m": cameras[-1].tolist(),
    }


class Report:
    def __init__(self, path: Path, total_pages: int, draft: bool, build_time: datetime):
        fonts = Path("/System/Library/Fonts/Supplemental")
        for name, filename in (
            ("Body", "Arial.ttf"),
            ("Bold", "Arial Bold.ttf"),
            ("Italic", "Arial Italic.ttf"),
            ("Mono", "Courier New.ttf"),
        ):
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
        pdfmetrics.registerFontFamily("Body", normal="Body", bold="Bold", italic="Italic")
        self.canvas = Canvas(str(path), pagesize=A4, pageCompression=1)
        self.canvas.setTitle("PV investigation simulator - M1 evidence checkpoint")
        self.canvas.setAuthor("Prepared for Wei He")
        self.width, self.height = A4
        self.margin = 42
        self.content = self.width - 84
        self.total_pages, self.draft = total_pages, draft
        self.date_label = build_time.strftime("%d %b %Y").upper()

    def rect(self, x, y, width, height, color, radius=5):
        c = self.canvas
        c.setFillColor(colors.HexColor(color))
        c.roundRect(x, self.height - y - height, width, height, radius, stroke=0, fill=1)

    def text(self, text, y, *, x=None, width=None, size=10.3, color=NAVY, bold=False, leading=None):
        x = self.margin if x is None else x
        width = self.content if width is None else width
        style = ParagraphStyle(
            "body",
            fontName="Bold" if bold else "Body",
            fontSize=size,
            leading=leading or size * 1.37,
            textColor=colors.HexColor(color),
            alignment=TA_LEFT,
            wordWrap="CJK",
            splitLongWords=True,
        )
        paragraph = Paragraph(text, style)
        _, height = paragraph.wrap(width, self.height)
        if y + height > self.height - 48:
            raise ValueError(f"page text overflows at {y}: {text[:100]}")
        paragraph.drawOn(self.canvas, x, self.height - y - height)
        return y + height

    def image(self, path, y, height, *, x=None, width=None):
        self.canvas.drawImage(
            str(path),
            self.margin if x is None else x,
            self.height - y - height,
            width=self.content if width is None else width,
            height=height,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )

    def table(self, headers, rows, y, widths, size=9.2):
        body = ParagraphStyle(
            "cell",
            fontName="Body",
            fontSize=size,
            leading=size * 1.3,
            textColor=colors.HexColor(NAVY),
            wordWrap="CJK",
        )
        head = ParagraphStyle("head", parent=body, fontName="Bold", textColor=colors.white)
        values = [[Paragraph(escape(str(v)), head) for v in headers]]
        values += [[Paragraph(escape(str(v)), body) for v in row] for row in rows]
        table = Table(values, colWidths=widths, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor(PALE), colors.white]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor(LINE)),
                ]
            )
        )
        _, height = table.wrap(self.content, self.height)
        if y + height > self.height - 48:
            raise ValueError(f"page table overflows: {headers}")
        table.drawOn(self.canvas, self.margin, self.height - y - height)
        return y + height

    def start(self, number, kicker, title, subtitle):
        self.rect(0, 0, self.width, 7, TEAL, 0)
        self.text("PV INVESTIGATION SIMULATOR  /  M1 EVIDENCE", 25, size=8.3, color=TEAL, bold=True)
        c = self.canvas
        c.setStrokeColor(colors.HexColor(LINE))
        c.line(self.margin, self.height - 47, self.width - self.margin, self.height - 47)
        self.text(f"{number:02d}  {kicker.upper()}", 61, size=8.7, color=TEAL, bold=True)
        self.text(title, 83, size=24, bold=True, leading=28)
        self.text(subtitle, 120, size=10.2, color=GREY)
        c.bookmarkPage(f"page{number}")
        c.addOutlineEntry(title, f"page{number}", level=0)

    def end(self, number):
        c = self.canvas
        c.setStrokeColor(colors.HexColor(LINE))
        c.line(self.margin, 37, self.width - self.margin, 37)
        c.setFont("Body", 7.8)
        c.setFillColor(colors.HexColor(GREY))
        c.drawString(
            self.margin,
            23,
            f"{self.date_label}  |  PRIVATE EVALUATOR REPORT  |  TRUSTED LOCAL",
        )
        c.drawRightString(
            self.width - self.margin,
            23,
            f"{'DRAFT  |  ' if self.draft else ''}{number} / {self.total_pages}",
        )
        c.showPage()


def build(args) -> dict:
    build_time = datetime.now(timezone.utc)
    output = args.output.resolve()
    sidecar = output.with_suffix(".provenance.json")
    asset_root = (
        args.asset_dir.resolve() if args.asset_dir else ROOT / "runs/m1-followthrough/report"
    )
    asset_dir = asset_root / output.stem
    if output.exists() or sidecar.exists() or asset_dir.exists():
        raise FileExistsError("report output or asset directory exists; prior evidence retained")
    source = verify_manifest(args.manifest)
    complete_pilot = bool(
        source["manifest"].get("metadata", {}).get("purpose") == "m1_pilot"
        and source["metrics"].get("verification_tail_complete")
        and source["metrics"].get("terminal_reason") == "finished"
        and not source["metrics"].get("core_only", True)
    )
    tests = test_summary(args.tests)
    review = review_summary(args.review)
    replay_path, replay_report = find_replay(source)
    batch = batch_summary(args.batch_report)
    rows = [event["payload"] for event in jsonl(source["path"].parent / "truth.jsonl")]
    if not rows or any(row.get("point") is None for row in rows):
        raise ValueError("a complete finite electrical truth trace is required for these figures")
    if [row["tick"] for row in rows] != list(range(rows[0]["tick"], rows[-1]["tick"] + 1)):
        raise ValueError("truth trace is not contiguous in ticks")
    asset_dir.mkdir(parents=True)
    inputs = asset_dir / "inputs"
    inputs.mkdir()
    figure_dir = asset_dir / "figures"
    figure_dir.mkdir()
    sources: list[dict] = []

    def preserve(path, label, *, show_in_pdf=True):
        path = Path(path).resolve()
        target = inputs / f"S{len(sources) + 1:02d}-{path.name}"
        shutil.copyfile(path, target)
        entry = {
            "id": f"S{len(sources) + 1}",
            "label": label,
            "path": str(path),
            "sha256": digest(path),
            "snapshot": str(target),
            "bytes": path.stat().st_size,
            "show_in_pdf": show_in_pdf,
        }
        sources.append(entry)
        return entry["id"]

    preserve(source["path"], "Verified source recording manifest")
    preserve(source["path"].parent / "truth.jsonl", "Private actual-state trace")
    preserve(source["path"].parent / "metrics.json", "Recorded energy and cost metrics")
    preserve(source["path"].parent / "config.json", "Expanded private configuration")
    preserve(args.tests, "JUnit test evidence")
    preserve(args.review, "Independent review input")
    if replay_path:
        preserve(replay_path, "Matched recorded-action replay report")
    for filename in ("observations.jsonl", "actions.jsonl"):
        preserve(
            source["output"] / "public" / filename, f"Primary public {filename}", show_in_pdf=False
        )
    reproducer_id = None
    if args.reproducer:
        reproducer_id = preserve(args.reproducer, "Independent core replay fixture source")
    if args.batch_report:
        preserve(args.batch_report, "Desktop batch execution report")
        if batch["machine_audit_path"]:
            preserve(batch["machine_audit_path"], "Desktop machine evidence audit")
        for row in batch["runs"]:
            if "source" not in row:
                continue
            pilot_source = row["source"]
            for filename, label in (
                ("manifest.json", "pilot manifest"),
                ("metrics.json", "pilot metrics"),
            ):
                preserve(
                    pilot_source["path"].parent / filename,
                    f"Seed {row['seed']} {label}",
                    show_in_pdf=False,
                )
            preserve(
                pilot_source["output"] / "public/observations.jsonl",
                f"Seed {row['seed']} public observations",
                show_in_pdf=False,
            )
            replay_file = ROOT / "runs" / f"{row['run_id']}-replay/evidence/replay.json"
            if row.get("replay") is not None:
                preserve(replay_file, f"Seed {row['seed']} rendered replay", show_in_pdf=False)
    selected_frames = batch["frames"]
    for frame in selected_frames:
        preserve(
            frame["path"],
            f"Actual unmodified camera PNG, seed {frame['seed']}, {frame['view']}",
            show_in_pdf=False,
        )
    measures = plots(rows, source["config"], figure_dir)
    serialized_measures = {
        key: str(value) if isinstance(value, Path) else value for key, value in measures.items()
    }
    serialized_measures["captures"] = [
        {key: value for key, value in frame.items() if key != "path"} for frame in selected_frames
    ]
    serialized_measures["pilot_details"] = [
        {
            "seed": row["seed"],
            "observations": row.get("observations"),
            "metrics": row.get("source", {}).get("metrics"),
            "replay": row.get("replay"),
        }
        for row in batch["runs"]
    ]
    (asset_dir / "measurements.json").write_text(json.dumps(serialized_measures, indent=2) + "\n")
    full_pass = (
        batch["complete"]
        and tests["failed"] == tests["errors"] == tests["skipped"] == 0
        and tests["render_cases"] > 0
        and review["verdict"].upper() in ("PASS", "M1_PASS", "PASS_M1")
    )
    pages = 8 if batch["present"] else 6
    output.parent.mkdir(parents=True, exist_ok=True)
    report = Report(output, pages, args.draft, build_time)
    width, metrics, manifest = report.content, source["metrics"], source["manifest"]
    reviewed_scope = (
        "Historical reviewed core checkpoint"
        if source["changed_sources"]
        else (
            "Complete pilot - source hashes match at report build"
            if complete_pilot
            else "Recorded core checkpoint - source hashes match at report build"
        )
    )
    readable_verdict = review["verdict"].replace("_", " ").capitalize()
    if review["verdict"].upper() in ("PASS_M1", "M1_PASS"):
        readable_verdict = "M1 PASS"
    injected_wall_time = manifest.get("metadata", {}).get("purpose") in (
        "independent_partial_core_check",
        "core_test",
    )
    verdict = (
        "M1 PASS - REQUIRED EVIDENCE AND REVIEW PRESENT"
        if full_pass
        else (
            "M1 ACCEPTANCE PENDING - CORE EVIDENCE ONLY"
            if not batch["present"]
            else "M1 ACCEPTANCE PENDING - SEE DESKTOP GATES"
        )
    )

    report.start(
        1,
        "Decision snapshot",
        "M1 rendered evidence" if complete_pilot else "M1 evidence checkpoint",
        f"Prepared for Wei He | {build_time:%d %B %Y} | Synthetic PV investigation world",
    )
    report.rect(42, 155, width, 35, "#E8F2F1" if full_pass else "#FCF0E5")
    report.text(
        verdict,
        166,
        x=53,
        width=width - 22,
        size=9.3,
        color=TEAL if full_pass else ORANGE,
        bold=True,
    )
    cards = [
        (str(tests["passed"]), "Passed cases in supplied JUnit"),
        (
            f"{measures['elapsed_s']:.2f} s",
            "Complete pilot duration" if complete_pilot else "Actual partial trace duration",
        ),
        (
            str(len(selected_frames) if batch["present"] else manifest["frame_count"]),
            "Original M1 RGB frames in batch"
            if batch["present"]
            else "M1 RGB frames in core trace",
        ),
    ]
    card_width = (width - 20) / 3
    for index, (value, label) in enumerate(cards):
        x = 42 + index * (card_width + 10)
        report.rect(x, 205, card_width, 72, PALE)
        report.text(value, 215, x=x + 11, width=card_width - 22, size=25, bold=True)
        report.text(label, 250, x=x + 11, width=card_width - 22, size=8.1, color=GREY)
    y = report.text(reviewed_scope, 300, size=15, bold=True)
    y = report.text(
        f"The verified recording contains {len(rows):,} actual MuJoCo/PV/thermal states "
        f"through tick {manifest['final_tick']:,}. "
        + (
            f"Seed {manifest['seed']} finishes its recorded action sequence "
            "and verification tail. The batch and review gates are stated below. [S1-S4]"
            if complete_pilot
            else "It ends after a partial action sequence; a finalized recording file "
            "does not mean "
            "a completed pilot or milestone. [S1-S4]"
        ),
        y + 9,
    )
    y = report.text(
        f"The supplied test report records {tests['passed']} passed, {tests['failed']} failed, "
        f"{tests['errors']} errors and {tests['skipped']} skipped cases. Counts come from that "
        "single JUnit file; overlapping component and reviewer selections are not added. [S5]",
        y + 11,
    )
    recorded_pilots = sum(
        row.get("source", {}).get("metrics", {}).get("verification_tail_complete", False)
        and not row.get("source", {}).get("metrics", {}).get("core_only", True)
        for row in batch["runs"]
    )
    y = report.text(
        f"Complete development pilots supplied: {recorded_pilots}. "
        f"Captured M1 RGB frames in the {'primary pilot' if complete_pilot else 'core trace'}: "
        f"{manifest['frame_count']}.",
        y + 10,
        size=9.6,
        color=TEAL,
    )
    y = report.text("Scope of this report", y + 25, size=14, bold=True)
    requirements = (
        [
            "Real moving-camera images, three completed development pilots and rendered replay.",
            "Independent full M1 review and Wei's decision before any M2 work.",
        ]
        if not full_pass
        else [
            "Verified actual camera frames and three successful recorded pilot/replay pairs.",
            "Supplied independent M1 PASS; Wei's authorization is still required before M2.",
        ]
    )
    y = report.table(
        [
            "Established by recorded inputs",
            "Required separate evidence"
            if not full_pass
            else "Established by desktop/review inputs",
        ],
        [
            (
                "Finite actual motion and instrument timing; explicit surrogate output "
                "and heat accounting.",
                requirements[0],
            ),
            (
                "Recorded actions replayed without calling a policy; "
                + (
                    "injected accounting fixture retained."
                    if injected_wall_time
                    else "original recorded wall-clock cost retained."
                ),
                requirements[1],
            ),
        ],
        y + 10,
        [width / 2, width / 2],
        size=9.3,
    )
    report.text(
        "This is a private evaluator report under trusted-policy/local. It makes no physical "
        "validation, diagnosis-performance or hostile-code isolation claim.",
        y + 18,
        size=9.4,
        color=GREY,
    )
    report.end(1)

    report.start(
        2,
        "Evidence and readiness",
        "What passed, what remains",
        "Current report inputs are explicit; historical checkpoints remain labelled.",
    )
    replay_ok = bool(replay_report and replay_report.get("status") == "passed")
    table_rows = [
        (
            "Supplied automated suite",
            f"{tests['passed']} / {tests['total']} passed",
            "JUnit file; current-code scope depends on its own run provenance.",
        ),
        (
            "Primary action replay",
            "Passed" if replay_ok else "Not supplied / not passed",
            "Matched source recording; exact tick checks plus private state and runtime metrics.",
        ),
        (
            "Independent review",
            readable_verdict,
            "Review verdict applies only to its stated scope.",
        ),
        (
            "Original M1 RGB frames",
            str(len(selected_frames) if batch["present"] else manifest["frame_count"]),
            "No image can be inferred from numeric state or a scientific geometry plot.",
        ),
        (
            "Desktop batch",
            "Three completed pairs" if batch["complete"] else "Pending",
            "Three seed-specific pilot/replay pairs are required for the planned gate.",
        ),
        (
            "Full milestone gate",
            "Passed" if full_pass else "Pending",
            "M2 remains outside this report's authorization.",
        ),
    ]
    if batch["present"]:
        table_rows.insert(
            -1,
            (
                "Machine batch audit",
                "Passed" if batch["machine_checks_passed"] else "Pending / not passed",
                "Bound to this batch report by SHA-256; every recorded machine check must pass.",
            ),
        )
    y = report.table(
        ["Check", "Evidence state", "Interpretation"],
        table_rows,
        161,
        [122, 135, width - 257],
        size=8.9,
    )
    y = report.text("Recorded action chronology", y + 24, size=14, bold=True)
    action_rows = []
    for event in jsonl(source["output"] / "public/actions.jsonl"):
        action = json.loads(event["payload"]["raw_json"])
        if isinstance(action, dict):
            action_rows.append(
                (
                    f"{event['tick'] * manifest['dt_s']:.3f}",
                    str(action.get("action_id", "invalid")),
                    action.get("kind", "invalid"),
                )
            )
        else:
            action_rows.append((f"{event['tick'] * manifest['dt_s']:.3f}", "-", "invalid payload"))
    y = report.table(
        ["Attempt at (s)", "Action ID", "Recorded request"],
        action_rows[:7],
        y + 9,
        [125, 95, width - 220],
        size=8.8,
    )
    report.text(
        (
            f"All {tests['render_cases']} render cases are included in the supplied executed "
            "suite. The action table lists requests; completed feedback and delivered evidence "
            "are assessed separately."
            if complete_pilot
            else "Repeated IDs remain visible because accepted retries and conflicts are part "
            "of the authoritative trace. This table lists requests, not inferred action success."
        ),
        y + 10,
        size=8.8,
        color=GREY,
    )
    report.end(2)

    report.start(
        3,
        "Electrical and thermal state",
        "Energy through the complete pilot"
        if complete_pilot
        else "Energy through the partial trace",
        "Saved state at each 2 ms tick; plotting does not rerun the simulator. [S2-S4]",
    )
    report.image(measures["electrical_thermal"], 157, 328)
    y = report.text(
        f"Figure 1. Temperature rises from {measures['temperature_start_c']:.2f} to "
        f"{measures['temperature_final_c']:.2f} C while load/probe operations change delivered "
        "power. These are synthetic model states, not calibrated hardware measurements.",
        495,
        size=8.8,
        color=GREY,
    )
    energy_rows = [
        ("Absorbed incident energy", metrics["absorbed_j"]),
        ("Delivered electrical output", metrics["pv_energy_j"]),
        ("Integrated heat loss", metrics["heat_loss_j"]),
        ("Thermal storage change", metrics["storage_j"]),
    ]
    y = report.table(
        ["Recorded energy account", "Joules"],
        [(name, f"{value:.6f}") for name, value in energy_rows],
        y + 17,
        [width - 145, 145],
        size=9.2,
    )
    y = report.text(
        f"Residual = absorbed - output - heat loss - storage = "
        f"{metrics['energy_balance_residual_j']:.3e} J. Output integration freezes each tick's "
        "electrical input; the thermal step integrates linear cooling exactly. Plotted electrical "
        "values are end-of-tick samples, so integrating the plotted curve is not the ledger rule.",
        y + 13,
        size=9.3,
    )
    report.text(
        f"Across {len(rows):,} true samples, max |P - V x I| = "
        f"{measures['maximum_power_identity_error_w']:.3e} W.",
        y + 11,
        size=9.3,
        color=TEAL,
    )
    report.end(3)

    report.start(
        4,
        "Actual motion",
        "Servos follow finite trajectories",
        "Saved MuJoCo positions; dashed curves are saved finite servo setpoints. [S2]",
    )
    report.image(measures["motion"], 157, 326)
    y = report.text(
        "Figure 2. Slide, yaw and pitch evolve over simulation time. A setpoint curve is a "
        "command trajectory, while the solid curve is the achieved joint coordinate. Endpoint "
        "agreement alone does not establish settlement throughout every action.",
        494,
        size=8.8,
        color=GREY,
    )
    scales = (1000, 180 / math.pi, 180 / math.pi)
    motion_rows = []
    for index, (name, scale) in enumerate(
        zip(("Slide (mm)", "Yaw (deg)", "Pitch (deg)"), scales, strict=True)
    ):
        motion_rows.append(
            (
                name,
                f"{measures['q_final'][index] * scale:.6f}",
                f"{measures['setpoint_final'][index] * scale:.6f}",
                f"{measures['final_tracking_error'][index] * scale:.3e}",
            )
        )
    y = report.table(
        ["Coordinate", "Final actual", "Final setpoint", "Absolute error"],
        motion_rows,
        y + 18,
        [120, 125, 130, width - 375],
        size=9.0,
    )
    y = report.text(
        f"Recorded travel: slide {metrics['slide_path_m']:.6f} m, yaw "
        f"{metrics['yaw_path_rad']:.6f} rad, pitch {metrics['pitch_path_rad']:.6f} rad. "
        f"The actuator-work proxy is {metrics['actuator_work_j']:.6g} J. It is reported "
        "separately and is not deducted from PV output.",
        y + 16,
        size=9.5,
    )
    if complete_pilot:
        report.text(
            f"Largest saved slide rate: {measures['maximum_saved_joint_rates'][0]:.6f} m/s; "
            "largest saved setpoint rate: "
            f"{measures['maximum_saved_setpoint_rates'][0]:.6f} m/s. The trajectory rate cap "
            "applies to the commanded setpoint. Finite servo dynamics can briefly exceed that "
            "rate; the cap is not an exact bound on actual MuJoCo velocity.",
            y + 13,
            size=9.2,
            color=GREY,
        )
    report.end(4)

    report.start(
        5,
        "Scene and camera",
        "Recorded camera path in 3D",
        "Scientific geometry figure from configuration and actual pose records. [S2, S4]",
    )
    report.image(measures["geometry"], 151, 272 if selected_frames else 346)
    y = report.text(
        "Figure 3. Panel geometry comes from the recorded configuration; camera centres and "
        "orientation rays come from actual stored transforms. The drawing omits the rig housing, "
        "lighting and occluders. It is not a MuJoCo RGB image or a visibility test.",
        433 if selected_frames else 506,
        size=8.8,
        color=GREY,
    )
    if selected_frames:
        y = report.table(
            [
                "Seed / view",
                "Capture / delivery (s)",
                "Actual camera centre x, y, z (m)",
                "Yaw (rad)",
            ],
            [
                (
                    f"{frame['seed']} / {frame['view']}",
                    f"{frame['frame']['t_capture_s']:.3f} / {frame['frame']['t_deliver_s']:.3f}",
                    ", ".join(f"{v:.6f}" for v in frame["pose"]["camera_position_m"]),
                    f"{frame['pose']['q'][1]:.6f}",
                )
                for frame in selected_frames
            ],
            y + 14,
            [75, 112, width - 255, 68],
            size=8.2,
        )
        report.text(
            "Poses above are saved at the exposure midpoint, not the final action endpoint. "
            "Each recorded exposure lasts 12 ms under the midpoint-snapshot approximation; "
            "camera and sensor delivery remain distinct from capture time. Actual RGB follows.",
            y + 14,
            size=9.1,
            color=GREY,
        )
    else:
        y = report.table(
            ["Recorded camera centre", "x, y, z (m)"],
            [
                ("Start", ", ".join(f"{v:.3f}" for v in measures["camera_start_m"])),
                ("Final", ", ".join(f"{v:.3f}" for v in measures["camera_final_m"])),
            ],
            y + 16,
            [220, width - 220],
        )
        report.rect(42, y + 22, width, 74, "#FCF0E5")
        report.text(
            "M1 RGB not yet available",
            y + 34,
            x=55,
            width=width - 26,
            size=14,
            color=ORANGE,
            bold=True,
        )
        report.text(
            "The core recording has no RGB frames. No placeholder image has been generated.",
            y + 59,
            x=55,
            width=width - 26,
            size=9.3,
            color=GREY,
        )
    report.end(5)

    if batch["present"]:
        report.start(
            6,
            "Desktop camera evidence",
            "Home and side views: all three seeds",
            "Six original PNGs; scaled for page layout without pixel editing or overlays.",
        )
        if selected_frames:
            for index, frame in enumerate(selected_frames):
                x = 42 + (index % 2) * (width + 14) / 2
                y = 158 + (index // 2) * 202
                panel_width = (width - 14) / 2
                report.image(frame["path"], y, 165, x=x, width=panel_width)
                data = frame["frame"]
                report.text(
                    f"Seed {frame['seed']} / {frame['view']} / {escape(data['frame_id'])}<br/>"
                    f"Capture {data['t_capture_s']:.3f} s; delivered {data['t_deliver_s']:.3f} s.",
                    y + 167,
                    x=x,
                    width=panel_width,
                    size=8.1,
                    color=GREY,
                )
        else:
            report.rect(42, 167, width, 150, PALE)
            report.text(
                "No verified M1 RGB files in supplied batch", 222, size=15, color=ORANGE, bold=True
            )
        report.end(6)

        report.start(
            7,
            "Measured choice and replay",
            "A tested load, then fresh verification",
            "Public delivered readings support the choice; private state supports evaluation.",
        )
        details = observation_details(source)
        y = report.table(
            ["Probe V", "Measured I (A)", "V x I (W)", "Capture / delivery (s)"],
            [
                (
                    f"{point['voltage_v']:.3f}",
                    f"{point['current_a']:.6f}",
                    f"{point['power_w']:.6f}",
                    f"{point['t_capture_s']:.3f} / {point['t_deliver_s']:.3f}",
                )
                for point in details["probe_points"]
            ],
            157,
            [85, 115, 105, width - 305],
            size=9,
        )
        finish = details["completed"].get("finish")
        confirmation = details["finish_confirmations"]
        voltage, current = confirmation.get("voltage_v"), confirmation.get("current_a")
        if finish and voltage and current:
            y = report.text(
                f"Seed {manifest['seed']}: the selected {voltage['value']:.1f} V was one of the "
                "measured probe points. The completed finish action confirms a newer paired "
                f"reading: {voltage['value']:.3f} V x {current['value']:.6f} A = "
                f"{voltage['value'] * current['value']:.6f} W, captured at "
                f"{voltage['t_capture_s']:.3f} s and delivered at {voltage['t_deliver_s']:.3f} s. "
                f"Verification tail: {finish['t_accepted_s']:.3f} to "
                f"{finish['t_terminal_s']:.3f} s. "
                "This is a measured choice among tested loads, not proof of the global optimum.",
                y + 16,
                size=9.6,
            )
        y = report.text("Development pilot / replay pairs", y + 22, size=14, bold=True)
        replay_rows = []
        for row in batch["runs"]:
            replay = row.get("replay") or {}
            runtime = row.get("source", {}).get("metrics", {})
            observations = replay.get("observations", [])
            replay_rows.append(
                (
                    row["seed"],
                    "Passed" if row["ready"] else "Pending",
                    f"{runtime.get('elapsed_s', 0):.2f}",
                    replay.get("truth_comparison", {}).get("records_compared", 0),
                    sum(item.get("frames_compared", 0) for item in observations),
                    max(
                        (item.get("maximum_pixel_absolute_error", 0) for item in observations),
                        default=0,
                    ),
                )
            )
        y = report.table(
            ["Seed", "Pair gate", "Sim. s", "Truth rows", "RGB pairs", "Max pixel error"],
            replay_rows,
            y + 9,
            [46, 88, 64, 93, 86, width - 377],
            size=8.8,
        )
        maxima = [
            row["replay"][kind]["maximum_numeric_absolute_error"]
            for row in batch["runs"]
            if row.get("replay")
            for kind in ("truth_comparison", "metrics_comparison")
        ]
        y = report.text(
            "Maximum private truth/metric difference across supplied replays: "
            f"{max(maxima, default=0):.1g}. "
            "Exact action ticks, observations, feedback, capture/delivery times and saved "
            "decisions "
            "are replayed and compared without querying the policy again. Numeric tolerances are "
            "1e-10 absolute/relative; image limits are max 2 and mean 0.1 uint8 levels. "
            "These are same-pinned-host results, not a cross-platform guarantee.",
            y + 15,
            size=9.4,
        )
        final_point = metrics.get("final_operating_point")
        if final_point:
            y = report.text(
                f"Final private state at {metrics['elapsed_s']:.3f} s: "
                f"{final_point['voltage_v']:.3f} V, {final_point['current_a']:.6f} A, "
                f"{final_point['power_w']:.6f} W. This later state is distinct from the "
                "delivered verification sample above.",
                y + 12,
                size=9.3,
            )
        y = report.text("What this establishes", y + 22, size=14, bold=True)
        report.text(
            "The static synthetic scene now has actual rendered home/side evidence, finite "
            "camera motion, delivered probe readings, a fresh measured verification point and "
            "a completed tail for every development seed. The repeated deterministic scene "
            "does not establish causal diagnosis accuracy, hardware fidelity or broad scenario "
            "coverage. Reported policy wall time is local measured bookkeeping, not an inference "
            "benchmark. M2 still requires a separate user decision.",
            y + 9,
            size=9.5,
        )
        report.end(7)

    number = pages
    report.start(
        number,
        "Provenance and review",
        "A traceable checkpoint",
        "Source snapshots, figure measurements and hashes accompany this PDF.",
    )
    y = report.text("Independent review", 161, size=14, bold=True)
    y = report.text(
        f"Supplied verdict: <b>{escape(review['verdict'])}</b>. "
        "The review file is preserved without edits in the source snapshots. "
        "Its verdict is not promoted beyond the scope stated in that file. [S6]"
        + (
            " Wei executed the desktop suite, pilots and rendered replays. The independent "
            "review checked those retained artifacts and added separate non-GL tests; "
            "overlapping counts are not summed."
            if complete_pilot
            else ""
        ),
        y + 8,
        size=9.8,
    )
    if replay_report:
        truth = replay_report.get("truth_comparison", {})
        metric = replay_report.get("metrics_comparison", {})
        latency_text = (
            f"Injected replay-accounting value: {metrics.get('policy_wall_s', 0):.2f} s. "
            "This is a known test fixture, not measured policy runtime. No benchmark "
            "inference latency was measured. " + (f"[{reproducer_id}]" if reproducer_id else "")
            if injected_wall_time
            else f"Original recorded policy wall time: {metrics.get('policy_wall_s', 0):.2f} s. "
            "Replay reuses decisions and does not time a new policy call."
        )
        y = report.text(
            f"Matched replay report: {escape(replay_report['status'])}; "
            f"{truth.get('records_compared', 0):,} private truth records and "
            f"{metric.get('numeric_values_compared', 0)} numeric metric values compared. "
            "Maximum private metric difference: "
            f"{metric.get('maximum_numeric_absolute_error', 'n/a')}. "
            "[S7] " + latency_text,
            y + 12,
            size=9.8,
        )
    y = report.text("Integrity and version scope", y + 23, size=14, bold=True)
    y = report.text(
        f"Manifest and every listed public/private artifact passed SHA-256 verification before "
        f"plotting. The source checkpoint was completed at {escape(manifest['completed_utc'])}. "
        f"At this report build, {len(source['changed_sources'])} source/configuration paths differ "
        "from that checkpoint. Historical traces remain valid evidence of their recorded version; "
        "they do not establish successful execution of later code.",
        y + 8,
        size=9.8,
    )
    y = report.table(
        ["Source", "Retained input", "SHA-256 prefix"],
        [
            (item["id"], item["label"], item["sha256"][:16])
            for item in sources
            if item["show_in_pdf"]
        ],
        y + 17,
        [45, width - 173, 128],
        size=8.4,
    )
    y = report.text("Reproduction boundary", y + 19, size=13, bold=True)
    report.text(
        "The report generator reads artifacts only. It opens no graphics context, executes no "
        "policy and runs no new episode. Full hashes, input locations, preserved snapshots, "
        "figure hashes, measurements, runtime package versions and the generation command are "
        "in the adjacent provenance JSON. No M2 authorization is inferred from this report.",
        y + 8,
        size=9.3,
    )
    report.end(number)
    report.canvas.save()
    reader = PdfReader(output)
    if len(reader.pages) != pages:
        raise ValueError("unexpected PDF page count")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if "\u25a0" in text or any(not page.extract_text() for page in reader.pages):
        raise ValueError("PDF text extraction found a missing-glyph marker or empty page")
    provenance = {
        "schema_version": "1.0",
        "created_utc": build_time.isoformat(),
        "output": str(output),
        "pdf_sha256": digest(output),
        "pages": pages,
        "draft": args.draft,
        "full_m1_pass": full_pass,
        "primary_recording_scope": "complete rendered pilot"
        if complete_pilot
        else "partial core trace",
        "read_only_generation": True,
        "policy_wall_time_interpretation": (
            "injected replay-accounting fixture; no benchmark inference latency measured"
            if injected_wall_time
            else "original recorded policy wall time; not remeasured by replay"
        ),
        "sources": sources,
        "tests": tests,
        "review_verdict": review["verdict"],
        "historical_source_changes": source["changed_sources"],
        "measurements": serialized_measures,
        "figures": [
            {"path": str(path), "sha256": digest(path), "kind": "scientific plot, not MuJoCo RGB"}
            for path in figure_dir.glob("*.png")
        ],
        "command": {"argv": sys.argv, "cwd": str(Path.cwd()), "python": sys.version},
        "recorded_runtime": manifest["runtime"],
        "report_runtime": {
            name: importlib.metadata.version(name)
            for name in ("reportlab", "matplotlib", "pypdf", "Pillow", "numpy")
        },
        "generator": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))},
        "visual_qa": "pending rendered-page inspection",
    }
    shutil.copyfile(__file__, asset_dir / "build_m1_evidence_report.py")
    provenance["bundle_files"] = [
        {
            "path": str(path.relative_to(asset_dir)),
            "sha256": digest(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(asset_dir.rglob("*"))
        if path.is_file()
    ]
    sidecar.write_text(json.dumps(provenance, indent=2) + "\n")
    return {
        "pdf": str(output),
        "sha256": provenance["pdf_sha256"],
        "pages": pages,
        "provenance": str(sidecar),
        "assets": str(asset_dir),
        "full_m1_pass": full_pass,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-report", type=Path)
    parser.add_argument(
        "--asset-dir", type=Path, help="new asset root; each PDF gets an exclusive subdirectory"
    )
    parser.add_argument("--reproducer", type=Path)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args), indent=2))


if __name__ == "__main__":
    main()
