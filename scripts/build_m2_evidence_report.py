"""Build M2's read-only evidence PDF from retained desktop outputs.

This report builder imports no simulator or graphics runtime. It validates saved
hashes/inventory, freezes an immutable input manifest before PDF assembly, and
keeps post-build QA in a separate file. Run with .tools/pdf-report/bin/python.
Use new --work-dir and --output paths for every build; existing files are refused.
"""
# Select headless plotting before importing pyplot.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
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
os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/m2-pdf-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PIL import Image
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

NAVY, TEAL, AMBER = "#17334A", "#087F8C", "#B86424"
GREY, PALE, LINE = "#566B7A", "#EDF3F6", "#D6E1E8"
BATCH = "m2-desktop-20261018T043656Z-85952"
DEFAULT_RUN = ROOT / "runs" / (BATCH + "-verification")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(data, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def inspect_inputs(run, review, draft):
    report = load(run / "verification-report.json")
    assert report["command_exit_code"] == 0 and report["source_unchanged"]
    assert report["status"] == "passed_pending_visual_and_independent_review"
    changed = [p for p, h in report["source_fingerprint"].items() if sha(ROOT / p) != h]
    if changed:
        raise ValueError(f"Retained execution inputs changed: {changed}")
    for item in report["rendered_artifacts"]:
        assert sha(run / item["path"]) == item["sha256"], item["path"]
    actual_files = sorted(
        str(p.relative_to(run)) for p in (run / "render").rglob("*") if p.is_file()
    )
    assert actual_files == sorted(x["path"] for x in report["rendered_artifacts"])
    pngs = sorted((run / "render").rglob("*.png"))
    jsons = sorted((run / "render").rglob("*.json"))
    assert len(pngs) == 29 and len(jsons) == 27
    for path in pngs:
        with Image.open(path) as image:
            assert image.mode == "RGB" and image.size == (640, 480)
            assert np.asarray(image).std() > 1
    xml = ET.parse(run / "tests.xml").getroot()
    cases = list(xml.iter("testcase"))
    assert all(
        c.find("failure") is None and c.find("error") is None and c.find("skipped") is None
        for c in cases
    )
    identities = [(c.attrib["classname"], c.attrib["name"]) for c in cases]
    inventory = load(ROOT / "configs/m2_test_inventory.json")["testcases"]
    assert len(identities) == len(set(identities)) == 519
    assert set(identities) == {(c["classname"], c["name"]) for c in inventory}
    assert sum(".render." in c for c, _ in identities) == 33
    config = load(ROOT / "private_eval" / run.name / "config.json")
    assert hashlib.sha256(canonical(config).encode()).hexdigest() == report["config_sha256"]
    assert sha(ROOT / "configs/dev.toml") == report["input_config_file_sha256"]
    views = {p.stem: load(p) for p in (run / "render").glob("*.json")}
    for name, v in views.items():
        assert v["capture_mode"] == "direct_actual_pose_snapshot; not a sensor exposure"
        assert v["seed"] == 20261016 and v["headlight_active"] == 0
        assert v["calibration_only_fiducial"] == (v["variant"] == "calibration")
        assert sha(run / "render" / v["image"]) == v["image_sha256"]
    timelines = {
        p.parent.name: load(p) for p in (run / "render/sensor_delivery").glob("*/timeline.json")
    }
    timing = {}
    for name, trace in timelines.items():
        assert trace["seed"] == 61 and trace["truth"] and trace["actions"] and trace["observations"]
        expected_roles = ["actual_midpoint_capture"] + (
            [] if name == "dropped" else ["evaluator_only_delivery_pose"]
        )
        assert [i["role"] for i in trace["images"]] == expected_roles
        for image in trace["images"]:
            assert sha(run / "render/sensor_delivery" / name / image["file"]) == image["sha256"]
        packets = [
            (o["observation"], f) for o in trace["observations"] for f in o["observation"]["rgb"]
        ]
        assert len(packets) == 1
        observation, packet = packets[0]
        assert (
            packet["t_start_s"] == 0.220
            and packet["t_capture_s"] == 0.226
            and packet["t_end_s"] == 0.232
        )
        assert packet["png_sha256"] == (None if name == "dropped" else trace["images"][0]["sha256"])
        assert all(
            o["observation"]["remaining_budgets"]["rgb_frames"] == 19
            for o in trace["observations"][1:]
        )
        timing[name] = {
            **packet,
            "returned_observation_s": observation["t_deliver_s"],
            "midpoint_x_m": trace["images"][0]["snapshot"]["q"][0],
            "delivery_x_m": None if name == "dropped" else trace["images"][1]["snapshot"]["q"][0],
            "truth_rows": len(trace["truth"]),
        }
    review_text = review.read_text() if review.exists() else "Review not yet available."
    verdict_match = re.search(r"(?im)^\s*VERDICT:\s*(.+)$", review_text)
    verdict = (
        verdict_match.group(1).strip() if verdict_match else "PENDING_INDEPENDENT_DESKTOP_REVIEW"
    )
    if not draft and verdict != "PASS_M2":
        raise ValueError(f"Final report requires actual independent PASS_M2; found {verdict!r}")
    stdout = (run / "evidence/development-tests.stdout.txt").read_text()
    elapsed_match = re.search(r"519 passed in ([\d.]+)s", stdout)
    return {
        "report": report,
        "config": config,
        "views": views,
        "timelines": timelines,
        "timing": timing,
        "verdict": verdict,
        "review": review_text,
        "test_counts": dict(Counter(c.split(".")[1] for c, _ in identities)),
        "junit_s": sum(float(x.attrib.get("time", 0)) for x in xml.iter("testsuite")),
        "pytest_s": float(elapsed_match.group(1)) if elapsed_match else None,
        "pngs": pngs,
        "jsons": jsons,
    }


def make_figures(data, directory):
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.labelcolor": NAVY,
            "text.color": NAVY,
            "axes.edgecolor": LINE,
            "xtick.color": GREY,
            "ytick.color": GREY,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    cfg = data["config"]
    world = cfg["private_world"]
    # Scientific geometry from retained private config and actual pose metadata.
    fig = plt.figure(figsize=(10.4, 5.9), facecolor="white")
    ax = fig.add_subplot(111, projection="3d")
    w, h = world["panel_size_m"]
    cx, cy, cz = world["panel_center_m"]
    for r in range(world["rows"]):
        for c in range(world["columns"]):
            x0, x1 = cx - w / 2 + c * w / 4, cx - w / 2 + (c + 1) * w / 4
            y0, y1 = cy - h / 2 + r * h / 2, cy - h / 2 + (r + 1) * h / 2
            ax.add_collection3d(
                Poly3DCollection(
                    [[(x0, y0, cz), (x1, y0, cz), (x1, y1, cz), (x0, y1, cz)]],
                    facecolor="#456989",
                    edgecolor="white",
                    linewidth=0.8,
                    alpha=0.9,
                )
            )
    screen = data["views"]["m2_narrow_screen_production_home"]["screen"]
    sx, sy, sz = screen["center_m"]
    sh = screen["half_height_m"]
    for hw, col, alpha in [(screen["half_width_m"], AMBER, 0.6), (0.06, GREY, 0.14)]:
        sd = screen["half_depth_m"]
        vertices = [
            [
                (sx - hw, sy - sd, sz - sh),
                (sx + hw, sy - sd, sz - sh),
                (sx + hw, sy - sd, sz + sh),
                (sx - hw, sy - sd, sz + sh),
            ],
            [
                (sx - hw, sy + sd, sz - sh),
                (sx + hw, sy + sd, sz - sh),
                (sx + hw, sy + sd, sz + sh),
                (sx - hw, sy + sd, sz + sh),
            ],
        ]
        ax.add_collection3d(
            Poly3DCollection(vertices, facecolor=col, edgecolor=col, alpha=alpha, lw=0.6)
        )
    centres = [
        data["views"][f"m2_narrow_screen_production_{v}"]["camera_position_m"]
        for v in ["left", "home", "right"]
    ]
    pts = np.array(centres)
    ax.plot(*pts.T, color=TEAL, lw=4, label="Actual optical centres on rail")
    for point, label, col in zip(pts, ["left", "home", "right"], [TEAL, AMBER, TEAL]):
        ax.scatter(*point, s=34, color=col)
        ax.plot(*np.array([point, [0, 0, 0]]).T, color=col, ls="--", lw=1.4)
        ax.text(point[0], point[1] - 0.025, point[2] + 0.055, label, fontsize=9)
    ref = (0.40, 0.10, 0.01)
    ax.scatter(*ref, color=AMBER, s=35, marker="s", label="F1 reference patch centre")
    ax.plot(*np.array([pts[1], ref]).T, color=AMBER, lw=1.2, ls=":")
    ax.quiver(-0.11, 0.06, 0.03, 0, 0, 0.25, color="#9C8A26", arrow_length_ratio=0.13, lw=2)
    ax.text(-0.11, 0.065, 0.30, "Toward source +z", fontsize=9)
    ax.text(0.10, 0.035, 0.04, "8 cells / 0.30 x 0.20 m", fontsize=9)
    ax.text(0.07, -0.16, 0.25, "Screen: narrow + wide outline", fontsize=9)
    ax.set(
        xlim=(-0.22, 0.44),
        ylim=(-0.52, 0.18),
        zlim=(0, 0.44),
        xlabel="x (m)",
        ylabel="y (m)",
        zlabel="z (m)",
    )
    ax.set_box_aspect((0.66, 0.70, 0.44))
    ax.view_init(elev=27, azim=-66)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    fig.subplots_adjust(left=0, right=1, bottom=0.03, top=0.98)
    fig.savefig(directory / "geometry_3d.png", dpi=210)
    plt.close(fig)
    # Actual saved dynamics; no simulation and no new camera capture.
    fig, axes = plt.subplots(
        2, 1, figsize=(10.2, 6.3), gridspec_kw={"height_ratios": [1, 1.12]}, constrained_layout=True
    )
    ax = axes[0]
    for j, (name, label, col) in enumerate(
        [
            ("late_valid", "Late valid", TEAL),
            ("late_stale", "Late stale", AMBER),
            ("dropped", "Dropped", GREY),
        ]
    ):
        p = data["timing"][name]
        ax.plot([p["t_capture_s"], p["t_deliver_s"]], [2 - j, 2 - j], color=col, lw=3)
        ax.scatter([p["t_capture_s"], p["t_deliver_s"]], [2 - j, 2 - j], s=45, color=col, zorder=3)
        ax.text(
            p["t_deliver_s"] + 0.025,
            2 - j + 0.06,
            f"{p['validity']}: {p['t_deliver_s']:.3f} s",
            fontsize=9,
        )
    ax.axvspan(0.220, 0.232, color=TEAL, alpha=0.22)
    ax.axvline(0.42, color=GREY, ls="--", lw=1)
    ax.text(0.435, 2.5, "Late capture action timeout: 0.420 s", fontsize=9, color=GREY)
    ax.text(0.226, -0.54, "0.226 s midpoint", ha="center", fontsize=9)
    ax.set(
        yticks=[2, 1, 0],
        yticklabels=["Late valid", "Late stale", "Dropped"],
        xlim=(0, 1.50),
        ylim=(-0.7, 2.8),
        xlabel="Simulation time (s)",
    )
    ax.grid(axis="x", alpha=0.25)
    ax = axes[1]
    trace = data["timelines"]["late_valid"]["truth"]
    t = np.array([r["time_s"] for r in trace])
    x = np.array([r["dynamics"]["q"][0] * 1000 for r in trace])
    setpoint = np.array([r["dynamics"]["setpoint"][0] * 1000 for r in trace])
    ax.plot(t, x, color=TEAL, lw=2, label="Recorded actual slide")
    ax.plot(t, setpoint, color=GREY, ls="--", lw=1, label="Recorded drive setpoint")
    for tt, label, col in [
        (0.226, "Midpoint: 0 mm", TEAL),
        (1.132, "Delivery: 16.956 mm", AMBER),
        (2.31, "Observation returned", GREY),
    ]:
        xx = np.interp(tt, t, x)
        ax.scatter([tt], [xx], color=col, s=35, zorder=3)
        ax.annotate(
            label,
            (tt, xx),
            xytext=(8, 12 if tt != 2.31 else -29),
            textcoords="offset points",
            fontsize=9,
            color=col,
        )
    ax.set(
        xlim=(0, 3.02),
        ylim=(-6, 72),
        xlabel="Simulation time (s)",
        ylabel="Slide displacement (mm)",
    )
    ax.grid(alpha=0.22)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    fig.savefig(directory / "capture_delivery_timeline.png", dpi=210)
    plt.close(fig)
    return [directory / "geometry_3d.png", directory / "capture_delivery_timeline.png"]


class Report:
    def __init__(self, path, draft):
        fonts = Path("/System/Library/Fonts/Supplemental")
        for name, filename in [
            ("Body", "Arial.ttf"),
            ("Bold", "Arial Bold.ttf"),
            ("Mono", "Courier New.ttf"),
        ]:
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
        pdfmetrics.registerFontFamily("Body", normal="Body", bold="Bold")
        self.c = Canvas(str(path), pagesize=A4, pageCompression=1, invariant=1)
        self.c.setTitle("PV investigation simulator - M2 rendered evidence")
        self.c.setAuthor("Prepared for Wei He")
        self.draft = draft
        self.used = []

    def text(self, text, y, x=42, width=None, size=10, color=NAVY, bold=False, leading=None):
        width = width or self.w - 84
        style = ParagraphStyle(
            "body",
            fontName="Bold" if bold else "Body",
            fontSize=size,
            leading=leading or size * 1.35,
            textColor=colors.HexColor(color),
            splitLongWords=True,
        )
        p = Paragraph(text, style)
        _, h = p.wrap(width, self.h)
        if y + h > self.h - 45:
            raise ValueError(f"Overflow page {self.page}: {y + h}: {text[:100]}")
        p.drawOn(self.c, x, self.h - y - h)
        return y + h

    def box(self, x, y, w, h, color=PALE):
        self.c.setFillColor(colors.HexColor(color))
        self.c.roundRect(x, self.h - y - h, w, h, 5, stroke=0, fill=1)

    def image(self, path, x, y, w, h, actual=False):
        if y + h > self.h - 43:
            raise ValueError(f"Image overflows {self.page}")
        self.c.drawImage(
            str(path),
            x,
            self.h - y - h,
            width=w,
            height=h,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        if actual:
            self.used.append(relative(path))

    def table(self, headers, rows, y, widths, size=9):
        body = ParagraphStyle(
            "cell",
            fontName="Body",
            fontSize=size,
            leading=size * 1.35,
            textColor=colors.HexColor(NAVY),
        )
        head = ParagraphStyle("head", parent=body, fontName="Bold", textColor=colors.white)
        values = [[Paragraph(escape(str(v)), head) for v in headers]] + [
            [Paragraph(escape(str(v)), body) for v in row] for row in rows
        ]
        tab = Table(values, colWidths=widths)
        tab.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor(PALE), colors.white]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        _, h = tab.wrap(self.w - 84, self.h)
        if y + h > self.h - 45:
            raise ValueError(f"Table overflow {self.page}")
        tab.drawOn(self.c, 42, self.h - y - h)
        return y + h

    def start(self, page, kicker, title, subtitle, wide=False):
        self.w, self.h = landscape(A4) if wide else A4
        self.c.setPageSize((self.w, self.h))
        self.page = page
        self.box(0, 0, self.w, 7, TEAL)
        self.text(
            "PV INVESTIGATION SIMULATOR / M2 RENDERED EVIDENCE", 24, size=8.2, color=TEAL, bold=True
        )
        self.text(f"{page:02d}  {kicker.upper()}", 54, size=8.6, color=TEAL, bold=True)
        self.text(title, 75, size=24, bold=True, leading=28)
        self.text(subtitle, 111, size=9.8, color=GREY)
        self.c.bookmarkPage(str(page))
        self.c.addOutlineEntry(title, str(page), level=0)

    def end(self):
        self.c.setStrokeColor(colors.HexColor(LINE))
        self.c.line(42, 37, self.w - 42, 37)
        self.c.setFillColor(colors.HexColor(GREY))
        self.c.setFont("Body", 7.5)
        self.c.drawString(42, 23, "18 OCT 2026 | PRIVATE EVALUATOR EVIDENCE | TRUSTED LOCAL")
        self.c.drawRightString(
            self.w - 42, 23, ("DRAFT | " if self.draft else "") + f"{self.page} / 10"
        )
        self.c.showPage()


def view_page(r, data, run, name, title, description, number):
    views = (
        ["home", "reframed"]
        if name == "reframe"
        else ["home", "rotation_only"]
        if name == "rail_locked"
        else ["home", "rotation_only", "right", "left"]
    )
    wide = len(views) == 4
    r.start(number, "Actual MuJoCo RGB / direct pose snapshots", title, description, wide=wide)
    if wide:
        gap = 12
        cw = (r.w - 84 - 3 * gap) / 4
        image_h = cw * 0.75
        for row, variant in enumerate(["production", "calibration"]):
            y = 164 + row * 182
            for col, view in enumerate(views):
                x = 42 + col * (cw + gap)
                m = data["views"][f"m2_{name}_{variant}_{view}"]
                r.text(
                    f"{variant.upper()} / {view.replace('_', ' ')}",
                    y,
                    x,
                    cw,
                    size=8.0,
                    bold=True,
                    color=TEAL if row == 0 else AMBER,
                )
                r.image(run / "render" / m["image"], x, y + 18, cw, image_h, actual=True)
                r.text(
                    (
                        f"t={m['t_capture_s']:.0f} s; x={m['actual_q'][0]:+.3f} "
                        f"m<br/>yaw={m['actual_q'][1]:+.3f}; pitch={m['actual_q'][2]:+.3f} rad"
                    ),
                    y + image_h + 22,
                    x,
                    cw,
                    size=7.8,
                )
        r.text(
            (
                "Production contains no green fiducial. Calibration adds a locator solely to "
                "test projection/visibility; identical blocked views can therefore share the "
                "same PNG hash. [S4, S8]"
            ),
            535,
            size=8.4,
            color=GREY,
        )
    else:
        cw = (r.w - 98) / 2
        ih = cw * 0.75
        for row, view in enumerate(views):
            y = 168 + row * 250
            for col, variant in enumerate(["production", "calibration"]):
                x = 42 + col * (cw + 14)
                m = data["views"][f"m2_{name}_{variant}_{view}"]
                r.text(
                    f"{variant.upper()} / {view.replace('_', ' ')}",
                    y,
                    x,
                    cw,
                    size=8.7,
                    bold=True,
                    color=TEAL if col == 0 else AMBER,
                )
                r.image(run / "render" / m["image"], x, y + 20, cw, ih, actual=True)
                q = m["actual_q"]
                r.text(
                    f"t={m['t_capture_s']:.0f} s; q=({q[0]:+.3f} m, {q[1]:+.3f}, {q[2]:+.3f} rad)",
                    y + ih + 27,
                    x,
                    cw,
                    size=8,
                )
        if name == "reframe":
            r.box(42, 687, r.w - 84, 72)
            r.text(
                (
                    "The home view misses the reference patch at (0.40, 0.10, 0.01) m. Bounded "
                    "yaw/pitch brings it into frame at the same optical centre. The bright green "
                    "calibration locator is separate from production RGB. [S4, S8]"
                ),
                700,
                x=54,
                width=r.w - 108,
                size=9.4,
            )
        else:
            r.box(42, 687, r.w - 84, 72)
            r.text(
                (
                    "The rail-locked fixture advertises slide limits (0, 0). Pan/tilt can "
                    "reframe the screen, but cannot change the ray from this optical centre to "
                    "the same panel point. No lateral endpoint view is available. [S4, S8]"
                ),
                700,
                x=54,
                width=r.w - 108,
                size=9.4,
            )
    r.end()


def assemble(data, run, work, output, provenance_hash, draft):
    r = Report(output, draft)
    width = A4[0] - 84
    half = (width - 14) / 2
    v = data["report"]
    r.start(
        1,
        "M2 decision record",
        "Rendered evidence closes M2",
        "Observation/action integrity, finite visibility fixtures and delayed RGB delivery.",
    )
    r.box(42, 154, width, 76, NAVY)
    r.text(
        "PASS_M2" if not draft else "DESKTOP COMPLETE / REVIEW PENDING",
        166,
        x=56,
        width=width - 28,
        size=20,
        color="#FFFFFF",
        bold=True,
    )
    r.text(
        "Independent desktop gate reviewed the retained run. Stop before M3."
        if not draft
        else "Draft layout only. Acceptance waits for the independent desktop gate.",
        199,
        x=56,
        width=width - 28,
        size=10,
        color="#FFFFFF",
    )
    for i, (num, label) in enumerate(
        [
            ("519", "tests passed"),
            ("33", "render cases"),
            ("29", "original PNGs"),
            ("27", "JSON records"),
        ]
    ):
        x = 42 + i * (width / 4)
        r.text(num, 251, x, width / 4, size=27, bold=True, color=TEAL)
        r.text(label, 287, x, width / 4, size=9, color=GREY)
    r.text(
        (
            "The full development suite passed with zero failures, errors or skips. It "
            "executed 486 non-render and 33 real-render cases. The exact frozen 519-case "
            "inventory matched, and all 84 recorded effective source/input hashes "
            "remained unchanged. [S1, S2]"
        ),
        323,
        size=11,
    )
    # Hero duplicates are clearly part of the retained 29, not extra evidence.
    for x, name, label in [
        (42, "m2_narrow_screen_production_left", "Narrow screen / lateral view"),
        (42 + half + 14, "m2_reframe_production_reframed", "Reframed reference patch"),
    ]:
        r.image(run / "render" / (name + ".png"), x, 407, half, half * 0.75)
        r.text(label, 600, x, half, size=8.6, bold=True)
    r.text("What the image count means", 638, size=12, bold=True)
    r.text(
        (
            "24 direct snapshots compare production and calibration geometry at actual "
            "settled poses. Five sensor images comprise three actual exposure-midpoint "
            "captures plus two evaluator-only delivery-pose comparisons. These are "
            "bounded deterministic fixtures, not new complete policy pilots. [S4, S5]"
        ),
        661,
        size=10.2,
    )
    r.text(
        (
            "Execution: 18 October 2026, 04:36:57 UTC | source revision 34eee53dc38a | "
            "desktop macOS / MuJoCo 3.3.7"
        ),
        751,
        size=8,
        color=GREY,
    )
    r.end()

    r.start(
        2,
        "Scientific schematic / not RGB",
        "Geometry explains the visibility cases",
        (
            "Coordinates and camera centres from retained configuration and pose "
            "records. [S3, S4, S8]"
        ),
    )
    r.image(work / "figures/geometry_3d.png", 42, 151, width, 323)
    r.text(
        (
            "Figure 1. Actual optical centres lie on a 0.30 m rail at y=-0.45 m, z=0.35 "
            "m. Dashed rays connect those centres to the panel centre; the F1 reference "
            "ray uses the displaced patch. This Matplotlib schematic is explanatory "
            "geometry, not a camera image."
        ),
        481,
        size=9.1,
        color=GREY,
    )
    rows = [
        ("F1 reframe", "No screen; patch x=0.40 m", "Rotate at fixed centre; patch enters FOV."),
        ("F2 narrow", "Screen half-width 0.03 m", "Endpoint rays clear the panel centre."),
        (
            "F2 rail locked",
            "Same narrow screen; x=0 only",
            "Rotation retains the blocked target ray.",
        ),
        ("F2 wide", "Screen half-width 0.06 m", "Target remains blocked over the full rail."),
    ]
    y = r.table(
        ["Fixture", "Declared geometry", "Interpretation"],
        rows,
        540,
        [85, 184, width - 269],
        size=8.5,
    )
    r.text(
        (
            "Screen centre (0,-0.15,0.125) m; half-depth 0.001 m; half-height 0.125 m. "
            "At the screen faces, endpoint centre-ray |x| spans 0.049667-0.050333 m: "
            "clear of narrow, inside wide. Toward-source direction is +z; all 8 cells "
            "remain at 900 W/m2. These screens occlude camera views without adding "
            "source shading. [S7, S8]"
        ),
        y + 17,
        size=9.1,
    )
    r.end()

    view_page(
        r,
        data,
        run,
        "reframe",
        "F1: rotation recovers framing",
        "Four original images; home and reframed poses share the same optical centre.",
        3,
    )
    view_page(
        r,
        data,
        run,
        "narrow_screen",
        "F2: translation clears a narrow screen",
        (
            "Eight original images. Green calibration locator appears at both lateral "
            "endpoints; home and rotation remain blocked."
        ),
        4,
    )
    view_page(
        r,
        data,
        run,
        "wide_screen",
        "F2: the wide screen blocks the full rail",
        (
            "Eight original images. The same finite rail endpoints cannot clear a screen "
            "of 0.06 m half-width."
        ),
        5,
    )
    view_page(
        r,
        data,
        run,
        "rail_locked",
        "F2: the rail limit removes translation",
        (
            "Four original images; production and calibration are separate runs at "
            "matching actual poses."
        ),
        6,
    )

    r.start(
        7,
        "Actual sensor renders / five retained images",
        "Historical pixels survive late delivery",
        (
            "Exposure-midpoint capture and evaluator-only delivery-pose comparison are "
            "different evidence roles. [S5]"
        ),
    )
    cw = (width - 14) / 2
    ih = 173
    for row, name in enumerate(["late_valid", "late_stale"]):
        y = 158 + row * 218
        for col, image in enumerate(data["timelines"][name]["images"]):
            x = 42 + col * (cw + 14)
            s = image["snapshot"]
            label = "ACTUAL MIDPOINT CAPTURE" if col == 0 else "EVALUATOR-ONLY DELIVERY POSE"
            r.text(
                f"{name.replace('_', ' ').upper()} / {label}",
                y,
                x,
                cw,
                size=7.6,
                bold=True,
                color=TEAL if col == 0 else AMBER,
            )
            r.image(
                run / "render/sensor_delivery" / name / image["file"],
                x,
                y + 17,
                cw,
                ih,
                actual=True,
            )
            r.text(
                f"t={s['time_s']:.3f} s; slide={s['q'][0] * 1000:.3f} mm",
                y + ih + 22,
                x,
                cw,
                size=8,
            )
    image = data["timelines"]["dropped"]["images"][0]
    r.image(run / "render/sensor_delivery/dropped" / image["file"], 42, 602, 184, 138, actual=True)
    r.text(
        "DROPPED / ACTUAL MIDPOINT CAPTURE", 748, x=42, width=190, size=7.6, bold=True, color=TEAL
    )
    r.text(
        (
            "The dropped capture was rendered at 0.226 s and retained privately. The "
            "public record delivered at 0.332 s is missing with a null PNG payload. No "
            "delivery-pose diagnostic was created for this case."
        ),
        610,
        x=242,
        width=width - 200,
        size=10,
    )
    r.text(
        (
            "For late valid and late stale, delivered PNG hashes equal the original "
            "midpoint PNG, and differ from the delivery-pose diagnostic. Identical "
            "fixture images across cases are expected. Saved timelines store hashes; "
            "the executed tests decode public payloads and check pixel equality."
        ),
        695,
        x=242,
        width=width - 200,
        size=9.2,
    )
    r.end()

    r.start(
        8,
        "Timing and immutable capture",
        "Delivery does not recapture the scene",
        (
            "Charts are calculated from the saved timeline JSON and actual dynamics; no "
            "simulation was rerun. [S5]"
        ),
    )
    r.image(work / "figures/capture_delivery_timeline.png", 42, 151, width, 328)
    y = r.table(
        ["Case", "Capture / exposure end", "Transport delivery", "Returned observation"],
        [
            ("Late valid", "0.226 / 0.232 s", "1.132 s; valid", "2.310 s"),
            ("Late stale", "0.226 / 0.232 s", "1.132 s; stale", "2.310 s"),
            ("Dropped", "0.226 / 0.232 s", "0.332 s; missing/null", "0.332 s"),
        ],
        499,
        [85, 145, 138, width - 368],
        size=8.7,
    )
    r.text(
        (
            "The late cases time out at 0.420 s, then move to x=0.060 m without "
            "requesting another RGB capture. Delivery occurs during motion at x=0.016956 "
            "m; the policy receives the historical packet in the completed move "
            "observation at 2.310 s. A later wait creates no RGB frame."
        ),
        y + 17,
        size=10,
    )
    r.text(
        (
            "Each attempted capture consumes one frame: remaining RGB budget is 19/20 in "
            "all later observations, including missing/stale cases. Exposure remains 12 "
            "ms with a midpoint approximation. Staleness is age at transport delivery, "
            "not age at the later observation. [S5, S9]"
        ),
        y + 89,
        size=9.6,
    )
    r.end()

    r.start(
        9,
        "Execution and contract integrity",
        "The desktop result completes the core gate",
        (
            "The full suite count is one execution; overlapping reviewer selections are "
            "not added. [S1, S2, S6, S7]"
        ),
    )
    rows = [
        (
            "Full desktop regression",
            f"519 passed; 33 render; 0 skipped; stdout {data['pytest_s']:.2f} s",
            "Exact inventory; JUnit elapsed %.3f s" % data["junit_s"],
        ),
        (
            "Desktop wrapper",
            "Schema export --check + verification; exit 0",
            "26.339 s total; shared bounded deadline",
        ),
        (
            "Independent core review",
            "486 passed; 33 deselected; 19.08 s",
            "Core ready; previous desktop block now addressed",
        ),
        ("Independent desktop review", data["verdict"], "Retained evidence and images reviewed"),
        (
            "Short core replay fixture",
            "729 truth rows; exact numeric replay",
            "1.456 s fixture; not a complete pilot",
        ),
    ]
    y = r.table(["Evidence", "Result", "Scope"], rows, 154, [128, 210, width - 338], size=8.8)
    r.text("Implemented observation and action contracts", y + 25, size=13, bold=True)
    r.text(
        (
            "Capture-indexed noise uses versioned seed/channel/tick/purpose inputs. "
            "Numeric and encoder noise are separate from transport decisions; RGB pixels "
            "remain noise-free. Late, stale and missing records preserve their capture "
            "identity. Fresh valid measured feedback is required for confirmation. [S7, "
            "S9]"
        ),
        y + 52,
        size=10.1,
    )
    r.text(
        (
            "Finite drive-command inhibition models movement stalls. Private load "
            "commands can drop or delay; a nominal acknowledgement does not prove "
            "application. Bounded restoration/disconnection, cancellation, narrowed "
            "advertised limits and terminal no-resume behavior are covered by the "
            "core/full regression evidence. [S7, S9]"
        ),
        y + 137,
        size=10.1,
    )
    r.box(42, y + 226, width, 91)
    r.text(
        (
            "No additional complete B0/B1 policy pilot was run. Report production used "
            "retained PNGs, JSON, scientific plotting and PDF rasterization. The 0.05 "
            "m/s slide cap applies to the drive setpoint ramp: recorded finite-servo "
            "velocity peaks at 0.051243 m/s. Trusted-policy/local is not hostile-code OS "
            "isolation."
        ),
        y + 240,
        x=54,
        width=width - 24,
        size=10,
    )
    r.end()

    r.start(
        10,
        "Provenance, limits and handoff",
        "A bounded PASS_M2, then stop",
        (
            "Immutable source snapshots precede this PDF; rendering and visual QA are "
            "recorded separately."
        ),
    )
    r.text("Source key", 153, size=12, bold=True)
    refs = [
        ("S1", "Desktop verification-report.json and batch-report.json"),
        ("S2", "tests.xml, command logs and frozen m2_test_inventory.json"),
        ("S3", "Expanded private config.json; configs/dev.toml and pilot.toml"),
        ("S4", "24 view PNG/JSON pairs in the retained render/ directory"),
        ("S5", "3 sensor timelines and 5 PNGs in render/sensor_delivery/"),
        ("S6", "M2_DESKTOP_GATE_REVIEW_20261018.txt (fresh desktop gate)"),
        ("S7", "M2_CORE_REVIEW_20261017.txt (prior core review)"),
        ("S8", "m2_fixtures.py, scene.py, optics.py and visibility test source"),
        ("S9", "ADR 0010/0011, M2-core-and-desktop.md; sensor delivery test"),
    ]
    y = r.table(["Key", "Retained source"], refs, 176, [42, width - 42], size=8.1)
    r.text("Identity and reproducibility", y + 17, size=12, bold=True)
    r.text(
        (
            f"Source revision: "
            f"<b>{v['runtime']['git']['revision']}</b><br/>View/verification seed: "
            f"<b>20261016</b>; sensor fixture seed: <b>61</b>.<br/>Expanded verification "
            f"config SHA256: {v['config_sha256']}<br/>Each view JSON also records its "
            f"fixture config and MJCF hashes; each sensor timeline records its own "
            f"fixture config hash."
        ),
        y + 40,
        size=8.5,
    )
    r.text(
        (
            f"Immutable provenance snapshot "
            f"SHA256:<br/><b>{provenance_hash}</b><br/>runs/m2-desktop-report-20261018/pro"
            f"venance.json<br/>Rebuild: .tools/pdf-report/bin/python "
            f"scripts/build_m2_evidence_report.py<br/>Use new --work-dir and --output "
            f"paths; existing outputs are refused."
        ),
        y + 126,
        size=8.3,
    )
    r.text("Retained limits", y + 219, size=12, bold=True)
    r.text(
        (
            "Extremely large finite private timing values can exceed integer/runtime "
            "ranges instead of receiving a clean rejection; this nonblocking core-review "
            "limitation remains. Bounded fixtures do not establish general adversarial "
            "numeric robustness. This is a deterministic synthetic surrogate: physical "
            "calibration, source shading, causal performance, scenario corpus and M3 "
            "refinement are outside this acceptance. Stop before M3 for Wei's decision. "
            "[S6, S7, S9]"
        ),
        y + 242,
        size=9.1,
    )
    r.end()
    r.c.save()
    assert set(r.used) == {relative(p) for p in data["pngs"]}, (
        "Every retained PNG must appear in contact sheets"
    )
    assert len(r.used) == 29
    return r.used


def build(args):
    run = args.run.resolve()
    work = args.work_dir.resolve()
    output = args.output.resolve()
    if work.exists() or output.exists():
        raise FileExistsError("Use a new report work directory and PDF path")
    data = inspect_inputs(run, args.review.resolve(), args.draft)
    work.mkdir(parents=True)
    (work / "figures").mkdir()
    (work / "snapshots").mkdir()
    figures = make_figures(data, work / "figures")
    # Freeze original inputs and authoring code before assembling the PDF.
    paths = set(run.rglob("*"))
    paths.update((ROOT / "runs" / BATCH).rglob("*"))
    paths.update((ROOT / "private_eval" / run.name).rglob("*"))
    paths.update(ROOT / p for p in data["report"]["source_fingerprint"])
    paths.update(
        ROOT / p
        for p in [
            "docs/decisions/0010-m2-scope.md",
            "docs/decisions/0011-m2-integrity-conventions.md",
            "docs/evidence/M2-core-and-desktop.md",
            "output/review/M2_CORE_REVIEW_20261017.txt",
            "scripts/build_m2_evidence_report.py",
        ]
    )
    if args.review.exists():
        paths.add(args.review.resolve())
    for directory in (
        ROOT / "runs/m2-desktop-acceptance-20261018",
        ROOT / "runs/m2-independent-desktop-review-20261018",
    ):
        if directory.exists():
            paths.update(directory.rglob("*"))
    sources = []
    for source in sorted(p for p in paths if p.is_file()):
        target = work / "snapshots" / relative(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        sources.append(
            {
                "source": relative(source),
                "snapshot": str(target.relative_to(work)),
                "sha256": sha(source),
                "bytes": source.stat().st_size,
            }
        )
    provenance = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Read-only M2 desktop evidence report; no new graphics context or policy pilot",
        "draft": args.draft,
        "execution_revision": data["report"]["runtime"]["git"]["revision"],
        "desktop_run": relative(run),
        "review_verdict": data["verdict"],
        "source_fingerprint_verified": len(data["report"]["source_fingerprint"]),
        "original_pngs": 29,
        "view_metadata": 24,
        "sensor_timelines": 3,
        "config_sha256": data["report"]["config_sha256"],
        "input_config_file_sha256": data["report"]["input_config_file_sha256"],
        "seeds": {"verification_views": 20261016, "sensor_fixtures": 61},
        "timing": data["timing"],
        "sources": sources,
        "derived_figures": [{"path": str(p.relative_to(work)), "sha256": sha(p)} for p in figures],
        "builder_sha256": sha(Path(__file__)),
        "python": sys.version,
        "libraries": {
            k: importlib.metadata.version(k)
            for k in ["reportlab", "matplotlib", "pypdf", "Pillow", "numpy"]
        },
        "artifact_marker": {
            "path": (
                "<pdf-tool>/mark_artifact_operation_started.mjs"
            ),
            "operation": "create",
            "exit_code": 0,
            "expected_outputs": 1,
        },
    }
    write_new(work / "provenance.json", provenance)
    provenance_hash = sha(work / "provenance.json")
    (work / "provenance.sha256").write_text(provenance_hash + "\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    used = assemble(data, run, work, output, provenance_hash, args.draft)
    reader = PdfReader(output)
    assert len(reader.pages) == 10
    embedded = []
    for page in reader.pages:
        for image in page.images:
            pixels = image.image.convert("RGB")
            if pixels.size == (640, 480):
                embedded.append(hashlib.sha256(pixels.tobytes()).hexdigest())
    original_pixels = {
        relative(p): hashlib.sha256(Image.open(p).convert("RGB").tobytes()).hexdigest()
        for p in data["pngs"]
    }
    assert all(value in embedded for value in original_pixels.values()), (
        "Original camera pixels missing from PDF"
    )
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    for word in [
        "519",
        "33",
        "29",
        "27",
        "0.226",
        "1.132",
        "900",
        "PASS_M2" if not args.draft else "DRAFT",
    ]:
        assert word in text, word
    qa = {
        "pdf": relative(output),
        "pdf_sha256": sha(output),
        "pages": 10,
        "provenance_sha256": provenance_hash,
        "provenance_unchanged_after_pdf": sha(work / "provenance.json") == provenance_hash,
        "retained_png_coverage": used,
        "unique_retained_pngs_in_pdf": len(set(used)),
        "text_checks": "passed",
        "full_resolution_rgb_pixel_match": True,
        "original_rgb_pixel_sha256": original_pixels,
        "pdf_rendering": "pending",
        "visual_inspection": "pending",
    }
    write_new(work / "qa-build.json", qa)
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument(
        "--review", type=Path, default=ROOT / "output/review/M2_DESKTOP_GATE_REVIEW_20261018.txt"
    )
    parser.add_argument("--work-dir", type=Path, default=ROOT / "runs/m2-desktop-report-20261018")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "output/pdf/PV_M2_Rendered_Evidence_20261018.pdf"
    )
    parser.add_argument("--draft", action="store_true")
    build(parser.parse_args())
