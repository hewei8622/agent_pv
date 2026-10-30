"""Build the source-bound, evaluator-only paired-investigation evidence report.

This presentation script reads completed records. It never runs a policy or
simulator, and deliberately does not reuse old RGB images as new evidence.
"""

# Report-table prose is intentionally kept as whole human-readable strings.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp/pdfs/paired/matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "tmp/pdfs/paired/cache"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = "#17364A"
TEAL = "#087F8C"
ORANGE = "#D97932"
GREY = "#526572"
LIGHT = "#EDF4F6"
PALE = "#F7F9FA"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelcolor": NAVY,
        "text.color": NAVY,
        "axes.titlecolor": NAVY,
        "xtick.color": GREY,
        "ytick.color": GREY,
        "savefig.facecolor": "white",
    }
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def observations(trace):
    result = [trace["interaction"]["initial_observation"]]
    for event in trace["interaction"]["events"]:
        if event["kind"] == "physical_decision":
            result.append(event["observation"])
        elif event["kind"] == "information_started":
            result.append(event["pending"]["observation"])
    return result


def samples(episode, channel):
    result = []
    for obs in episode["observations"]:
        for sample in obs["scalars"]:
            if sample["channel"] == channel and sample["validity"] == "valid":
                result.append(
                    {
                        **sample,
                        "available_s": obs["t_deliver_s"],
                        "observation_sequence_id": obs["sequence_id"],
                    }
                )
    return result


def powers(episode):
    result = []
    for obs in episode["observations"]:
        valid = {
            (s["channel"], s["t_capture_s"]): s
            for s in obs["scalars"]
            if s["validity"] == "valid" and s["value"] is not None
        }
        for (channel, captured), v in valid.items():
            i = valid.get(("current_a", captured))
            if channel == "voltage_v" and i is not None:
                result.append(
                    {
                        "capture_s": captured,
                        "available_s": obs["t_deliver_s"],
                        "power_w": v["value"] * i["value"],
                    }
                )
    return result


def savefig(fig, work, name):
    path = work / f"{name}.png"
    fig.savefig(path, dpi=210, bbox_inches="tight", pad_inches=0.14)
    plt.close(fig)
    return path


def architecture(work):
    fig, ax = plt.subplots(figsize=(9, 4.45))
    ax.set(xlim=(-0.5, 10.5), ylim=(0, 6.6))
    ax.axis("off")
    boxes = [
        (
            0.1,
            4.05,
            3.0,
            1.65,
            "PRIVATE SIMULATOR",
            "Source, PV, thermal\nActuator dynamics\nSensor queues",
            ORANGE,
        ),
        (
            3.75,
            4.05,
            2.55,
            1.65,
            "PUBLIC INTERFACE",
            "Delivered samples\nAction feedback\nBudgets and tools",
            TEAL,
        ),
        (
            6.95,
            4.05,
            2.95,
            1.65,
            "DECISION SYSTEM",
            "World / self records\nR procedure or\nA goal planner",
            NAVY,
        ),
        (
            6.95,
            1.3,
            2.95,
            1.65,
            "COMMIT / EXECUTE",
            "Question or action\nPrediction and\nrecorded rationale",
            TEAL,
        ),
        (
            3.75,
            1.3,
            2.55,
            1.65,
            "SERVICE SOURCE",
            "Current service record\nHold / survey",
            NAVY,
        ),
        (
            0.1,
            1.3,
            3.0,
            1.65,
            "INDEPENDENT SCORER",
            "Private + public trace\nFreshness / authority\nCosts / replay",
            ORANGE,
        ),
    ]
    for x, y, w, h, title, body, colour in boxes:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=.02,rounding_size=.09",
                facecolor=LIGHT,
                edgecolor=colour,
                linewidth=1.4,
            )
        )
        ax.text(
            x + w / 2, y + h - 0.35, title, ha="center", fontsize=10, weight="bold", color=colour
        )
        ax.text(x + w / 2, y + 0.65, body, ha="center", va="center", fontsize=9.5, linespacing=1.3)
    for p1, p2 in [
        ((3.12, 4.9), (3.7, 4.9)),
        ((6.32, 4.9), (6.9, 4.9)),
        ((8.4, 4.02), (8.4, 3.0)),
        ((6.92, 2.1), (6.35, 2.1)),
        ((1.6, 4.02), (1.6, 3.0)),
        ((5.0, 2.98), (5.0, 4.0)),
    ]:
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=13, color=GREY))
    ax.text(4.9, 3.5, "reply", ha="right", fontsize=8, color=GREY)
    ax.text(6.65, 1.85, "ask", ha="center", fontsize=8, color=GREY)
    ax.plot([9.93, 10.2, 10.2, -0.25, -0.25], [2.1, 2.1, 6.1, 6.1, 4.9], color=TEAL, linewidth=1)
    ax.add_patch(
        FancyArrowPatch((-0.25, 4.9), (0.07, 4.9), arrowstyle="-|>", mutation_scale=13, color=TEAL)
    )
    ax.text(
        5,
        6.25,
        "Validated physical action returns to the same digital asset",
        ha="center",
        fontsize=8,
        color=TEAL,
    )
    ax.text(
        5,
        0.55,
        "Recorded evidence, not private state, is the input to both policies.",
        ha="center",
        fontsize=10,
        weight="bold",
        color=NAVY,
    )
    return savefig(fig, work, "architecture")


def geometry(episode, work):
    config = episode["config"]
    world = config["private_world"]
    first = episode["truth"][0]
    centre = np.array(world["panel_center_m"])
    w, h = world["panel_size_m"]
    normal = np.array(world["panel_normal"])
    if not np.allclose(normal, [0, 0, 1]):
        raise ValueError("This report geometry expects the frozen horizontal panel")
    fig = plt.figure(figsize=(8.8, 4.7))
    ax = fig.add_subplot(111, projection="3d")
    for column in range(world["columns"]):
        for row in range(world["rows"]):
            x0 = centre[0] - w / 2 + w * column / world["columns"]
            y0 = centre[1] - h / 2 + h * row / world["rows"]
            x1, y1 = x0 + w / world["columns"], y0 + h / world["rows"]
            z = centre[2]
            ax.add_collection3d(
                Poly3DCollection(
                    [[(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]],
                    facecolors=TEAL,
                    edgecolors="white",
                    alpha=0.85,
                    linewidths=1,
                )
            )
    camera = np.array(first["dynamics"]["camera_position_m"])
    rotation = np.array(first["dynamics"]["camera_rotation"]).reshape(3, 3)
    depth = 0.48
    half_y = np.tan(np.deg2rad(config["camera"]["fovy_deg"]) / 2) * depth
    half_x = half_y * config["camera"]["width"] / config["camera"]["height"]
    corners = [
        camera + rotation @ np.array([sx * half_x, sy * half_y, -depth])
        for sx, sy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    ]
    for point in corners:
        ax.plot(*np.stack([camera, point]).T, color=GREY, lw=0.8, alpha=0.65)
    ax.plot(*np.stack([*corners, corners[0]]).T, color=GREY, lw=0.8, alpha=0.65)
    ax.scatter(*camera, color=NAVY, s=55, label="Recorded camera pose (unused by policies)")
    reference = np.array(world["reference_position_m"])
    ax.scatter(*reference, color=ORANGE, s=50, marker="s", label="Reference sensor location")
    ax.text(centre[0] - 0.12, centre[1] + 0.13, centre[2], "8-cell PV panel", fontsize=8)
    direction = np.array(world["source_direction"])
    for x in [-0.11, 0, 0.11]:
        start = np.array([x, 0.01, 0.29])
        ax.quiver(*start, *(-direction * 0.14), color=ORANGE, arrow_length_ratio=0.2, linewidth=1.5)
    ax.text(-0.12, 0.01, 0.32, "Incident-light direction", fontsize=8, color=ORANGE)
    ax.set(
        xlabel="x (m)",
        ylabel="y (m)",
        zlabel="z (m)",
        xlim=(-0.3, 0.3),
        ylim=(-0.55, 0.25),
        zlim=(-0.02, 0.45),
    )
    ax.set_box_aspect((0.6, 0.8, 0.47))
    ax.view_init(elev=27, azim=-55)
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.06), fontsize=8, frameon=False)
    return savefig(fig, work, "recorded-geometry")


def source_change(episode, work):
    truth = episode["truth"]
    measured = samples(episode, "reference_w_m2")
    fig, axes = plt.subplots(2, 1, figsize=(8.7, 4.9), sharex=True, constrained_layout=True)
    t = [p["time_s"] for p in truth]
    axes[0].plot(
        t, [p["reference_w_m2"] for p in truth], color=ORANGE, lw=1.6, label="Private truth"
    )
    axes[0].scatter(
        [p["t_capture_s"] for p in measured],
        [p["value"] for p in measured],
        s=10,
        color=TEAL,
        label="Public sample, placed at capture time",
    )
    axes[0].set(ylabel="Irradiance (W/m2)", ylim=(425, 975))
    public_power = powers(episode)
    axes[1].plot(
        t, [p["point"]["power_w"] for p in truth], color=ORANGE, lw=1.6, label="Private PV power"
    )
    axes[1].scatter(
        [p["capture_s"] for p in public_power],
        [p["power_w"] for p in public_power],
        s=10,
        color=TEAL,
        label="Matched public V x I",
    )
    axes[1].set(xlabel="Simulation time (s)", ylabel="Power (W)", xlim=(0, 5))
    first = next(a for a in episode["audit"] if a["source_assessment"]["incident_light_reduction"])
    available = first["source_assessment"]["first_detected_available_s"]
    for ax in axes:
        ax.axvline(2, color=ORANGE, linestyle="--", alpha=0.7)
        ax.axvline(available, color=NAVY, linestyle=":", alpha=0.8)
        ax.grid(alpha=0.16)
        ax.legend(fontsize=8, frameon=False, loc="upper right")
    axes[1].annotate(
        f"Agent can assess change at {available:.2f} s",
        xy=(available, 0.55),
        xytext=(available + 0.22, 0.8),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "color": NAVY},
    )
    return savefig(fig, work, "source-change")


def branch_timeline(episodes, work):
    fig, axes = plt.subplots(2, 1, figsize=(8.7, 3.5), sharex=True, constrained_layout=True)
    colours = {
        "observe": TEAL,
        "ask_context": "#89529B",
        "survey": TEAL,
        "apply_target": NAVY,
        "verify": TEAL,
        "pad_horizon": GREY,
        "finish": GREY,
    }
    for ax, case in zip(axes, ("C03", "C04"), strict=True):
        audit = episodes[(case, "A")]["audit"]
        ax.axhline(0, color="#B8C8D0", linewidth=1)
        for a in audit:
            t = a["simulation_time_s"]
            op = a["selected_operator"]
            ax.scatter(t, 0, color=colours.get(op, NAVY), s=38, zorder=3)
            if op == "pad_horizon":
                continue
            label = op.replace("_", " ")
            below = op in ("ask_context", "verify")
            ax.annotate(
                label,
                (t, 0),
                xytext=(-16 if op == "ask_context" else 0, -22 if below else 14),
                textcoords="offset points",
                fontsize=8,
                ha="right" if op == "ask_context" else "center",
                arrowprops={"arrowstyle": "-", "color": GREY, "linewidth": 0.6}
                if op == "ask_context"
                else None,
            )
        ax.set(ylim=(-1, 1), yticks=[], ylabel=case + " / A", xlim=(-0.5, 16.3))
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
    axes[-1].set_xlabel("Decision commit time (s); response contents determine the branch")
    axes[0].set_title("Grey intermediate points: preserve the verified operating point", fontsize=8)
    return savefig(fig, work, "context-branches")


def performance(summary, work):
    fig, axes = plt.subplots(1, 2, figsize=(8.7, 3.15), constrained_layout=True)
    results = {(r["case_id"], r["arm"]): r for r in summary["results"]}
    x = np.arange(4)
    for arm, offset, colour in [("R", -0.18, NAVY), ("A", 0.18, TEAL)]:
        costs = [results[(f"C0{i}", arm)]["evaluation"]["raw_costs"] for i in range(1, 5)]
        ready = [results[(f"C0{i}", arm)]["evaluation"]["ready_at_s"] for i in range(1, 5)]
        axes[0].bar(
            x + offset, [c["pv_energy_j"] for c in costs], width=0.34, color=colour, label=arm
        )
        axes[1].bar(x + offset, ready, width=0.34, color=colour, label=arm)
    for ax in axes:
        ax.set_xticks(x, ["C01", "C02", "C03", "C04"])
        ax.grid(axis="y", alpha=0.16)
        ax.set_axisbelow(True)
    axes[0].set(ylabel="PV energy over common 16 s (J)")
    axes[1].set(ylabel="First supported verified decision (s)")
    axes[0].legend(frameon=False, ncol=2, loc="lower left", bbox_to_anchor=(0, 1.01))
    return savefig(fig, work, "paired-performance")


def test_result(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    counts = {
        key: sum(int(s.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    counts["seconds"] = sum(float(s.get("time", "0")) for s in suites)
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--test-xml", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    for key in ("manifest", "freeze", "test_xml", "output", "work"):
        setattr(args, key, getattr(args, key).resolve())
    if args.output.exists():
        raise FileExistsError("Preserve prior evidence reports; choose a new PDF path")
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest = read(args.manifest)
    summary_path = (args.manifest.parent / manifest["summary_path"]).resolve()
    summary = read(summary_path)
    freeze_wrapper = read(args.freeze)
    freeze = freeze_wrapper["experiment"]
    frozen_digest = hashlib.sha256(
        json.dumps(freeze, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    experiment_link_path = args.manifest.parent / "experiment-link.json"
    experiment_link = read(experiment_link_path)
    if frozen_digest != freeze_wrapper["sha256"]:
        raise ValueError("Frozen experiment content checksum mismatch")
    if sha(args.freeze) != experiment_link["sha256"]:
        raise ValueError("The report freeze does not match the experiment's recorded link")
    index_path = summary_path.parent / "artifact-index.json"
    artifact_index = read(index_path)["sha256"]
    for name, checksum in artifact_index.items():
        if sha(ROOT / name) != checksum:
            raise ValueError(f"Retained paired artifact changed: {name}")
    if summary["status"] != "complete" or len(summary["results"]) != 8:
        raise ValueError("The completed four-pair evidence is required")
    if not all(
        p["matched_physical_config"] and p["common_horizon_energy_eligible"]
        for p in summary["pairs"]
    ):
        raise ValueError("Matched configuration and common horizons are required for these figures")
    source_paths = {
        args.manifest,
        summary_path,
        args.freeze,
        args.test_xml,
        Path(__file__).resolve(),
        experiment_link_path,
        index_path,
    }
    episodes = {}
    for case in manifest["cases"]:
        for arm, paths in case["arms"].items():
            public = (args.manifest.parent / paths["public_dir"]).resolve()
            private = (args.manifest.parent / paths["evaluator_dir"]).resolve()
            files = {
                "trace": public / "investigation.json",
                "audit": public / "policy_audit.json",
                "verification": public / "verification.json",
                "config": private / "config.json",
                "truth": private / "truth.jsonl",
                "result": private / "result.json",
            }
            source_paths.update(files.values())
            e = {k: read(p) for k, p in files.items() if k != "truth"}
            wrapped_trace = e["trace"]
            e["trace"] = wrapped_trace["transcript"]
            transcript_hash = hashlib.sha256(
                json.dumps(
                    e["trace"], sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            ).hexdigest()
            if transcript_hash != wrapped_trace["sha256"]:
                raise ValueError("Investigation transcript content checksum mismatch")
            e["truth"] = [r.get("payload", r) for r in rows(files["truth"])]
            e["observations"] = observations(e["trace"])
            e["public_dir"] = public
            episodes[(case["case_id"], arm)] = e
    tests = test_result(args.test_xml)
    review_text = None
    if args.review:
        args.review = args.review.resolve()
        review_text = args.review.read_text()
        source_paths.add(args.review)
    before_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sorted(source_paths)}
    figs = {
        "architecture": architecture(args.work),
        "geometry": geometry(episodes[("C04", "A")], args.work),
        "source": source_change(episodes[("C02", "A")], args.work),
        "branches": branch_timeline(episodes, args.work),
        "performance": performance(summary, args.work),
    }
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "TitlePV",
            fontName="Helvetica-Bold",
            fontSize=27,
            leading=31,
            textColor=colors.HexColor(NAVY),
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            "H1PV",
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=23,
            textColor=colors.HexColor(NAVY),
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            "H2PV",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor(TEAL),
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            "BodyPV",
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor(NAVY),
            spaceAfter=9,
        )
    )
    styles.add(
        ParagraphStyle(
            "SmallPV",
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor(GREY),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            "CellPV", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor(NAVY)
        )
    )
    styles.add(
        ParagraphStyle(
            "MetricPV",
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=24,
            textColor=colors.HexColor(TEAL),
            alignment=TA_CENTER,
        )
    )
    story = []

    def p(text, style="BodyPV"):
        story.append(Paragraph(text, styles[style]))

    def h(text):
        p(text, "H2PV")

    def new(title, subtitle=None):
        if story:
            story.append(PageBreak())
        p(title, "H1PV")
        if subtitle:
            p(subtitle, "SmallPV")

    def figure(path, width=493, max_height=300):
        from PIL import Image as PILImage

        with PILImage.open(path) as image:
            height = width * image.height / image.width
        if height > max_height:
            width *= max_height / height
            height = max_height
        story.append(Image(str(path), width=width, height=height))
        story.append(Spacer(1, 5))

    def table(data, widths, *, font=8):
        cells = [[Paragraph(escape(str(v)), styles["CellPV"]) for v in row] for row in data]
        result = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(LIGHT)),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PALE)]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(TEAL)),
                ]
            )
        )
        story.append(result)
        story.append(Spacer(1, 8))

    results = {(r["case_id"], r["arm"]): r for r in summary["results"]}
    success = sum(r["evaluation"]["success"] for r in summary["results"])
    checks = [v for r in summary["results"] for v in r["evaluation"]["predictions"]]
    errors = sum(
        sum(bool(v) for v in r["evaluation"]["errors"].values()) for r in summary["results"]
    )
    tied = all(abs(p["A_minus_R"].get("pv_energy_j", 1)) < 1e-10 for p in summary["pairs"])
    label = (
        "Equal physical outcomes; the investigation mechanism is now observable."
        if tied
        else ("A complete paired measurement of investigation decisions and physical outcomes.")
    )
    p("PV investigation\n<br/>Paired development evidence", "TitlePV")
    p("19 OCTOBER 2026  /  CONTROLLED FIRST SLICE", "SmallPV")
    p(label, "H2PV")
    p(
        f"The procedural reference (R) and bounded goal planner (A) completed four matched "
        f"development cases: <b>{success}/8 episodes met the frozen success rubric</b>. "
        f"The records expose sensing, external questions, decisions, predictions, physical execution "
        f"and fresh verification on the same 16-second simulation horizon."
    )
    table(
        [
            ["Measured result", "This batch"],
            ["Cases and repetitions", "4 cases x 2 arms x 1 episode; one declared seed"],
            [
                "Prediction outcomes",
                f"{sum(v['passed'] for v in checks)}/{len(checks)} numerical precommitments verified",
            ],
            ["Recorded rubric errors", str(errors)],
            [
                "Exact record replay",
                f"{sum(r['replay_metrics_equal'] for r in summary['results'])}/8 metric-equal replays",
            ],
            [
                "Live information calls / new camera frames",
                f"{summary['live_calls']} / {summary['new_rgb_frames']}",
            ],
            [
                "Matched PV energy",
                "Equal in all four pairs"
                if tied
                else "See case-specific paired differences on page 8",
            ],
        ],
        [230, 263],
    )
    p(
        "<b>C01:</b> unchanged asset, known hold instruction. <b>C02:</b> hidden light reduction, "
        "known hold instruction. <b>C03:</b> missing service context, returned hold instruction. "
        "<b>C04:</b> the same local physical evidence, returned permission to survey."
    )
    h("What the outcome means")
    p(
        "This is evidence that the common investigation loop can execute, retain its reasoning "
        "state and verify a permitted action. The competent reference succeeds too. These cases "
        "therefore establish an auditable comparison and <b>do not establish an adaptive performance "
        "advantage</b>, open-ended intelligence or transfer to a real PV asset."
    )
    h("How to read the evidence")
    p(
        "Orange denotes evaluator-only knowledge; teal denotes public evidence or action. "
        "Every 3D view in this report is a reconstruction from recorded geometry, not a newly "
        "captured camera image. The paired interactive viewer is the companion for inspecting "
        "the same decisions at their actual availability times."
    )

    new("1. The two systems and the evidence boundary")
    figure(figs["architecture"], max_height=270)
    table(
        [
            ["Component", "Implemented role"],
            [
                "Environment world model",
                "Private source, optics, piecewise electrical model, thermal dynamics, actuators and measurement timing generate the digital world.",
            ],
            [
                "Agent world belief",
                "A source-linked summary of reference evidence, unresolved physical cause, current service permission and measured operating target.",
            ],
            [
                "Agent self model",
                "Advertised tools, remaining requests / probe points, observed failures and the requirement for fresh V/I verification.",
            ],
            [
                "R: procedural reference",
                "Fixed observe -> resolve missing permission -> survey or hold -> verify procedure, with competent measured branches and bounded clarification.",
            ],
            [
                "A: bounded goal planner",
                "Re-evaluates unsatisfied goals and eligible operators after each returned context; fixed explicit priorities choose the next operation.",
            ],
        ],
        [123, 370],
    )
    p(
        "Both arms use the same evidence-validation helpers, public brief, tools, source record, "
        "seed and physical configuration. Neither receives the private case label or hidden source "
        "schedule. A is deterministic symbolic planning: there is no language model, learned policy, "
        "probabilistic belief calibration, cross-episode memory or image interpretation.",
        "SmallPV",
    )

    new(
        "2. The digital asset, sensors and 3D scene",
        "Evaluator reconstruction from C04-A config.json and recorded truth; geometry is not policy input.",
    )
    figure(figs["geometry"], max_height=290)
    p(
        "The frozen scene contains a 0.30 x 0.20 m panel with eight cells arranged in two series "
        "substrings, a reference irradiance sensor and the recorded camera mechanism. The frustum "
        "uses the camera's recorded position and rotation plus its declared field of view. Rays "
        "illustrate the configured source direction; they do not imply a measured light-source position."
    )
    table(
        [
            ["Digital mechanism", "What this comparison exercises"],
            [
                "Incident light and PV response",
                "A source step changes irradiance and the piecewise-cell current/power response; thermal state evolves with input and cooling.",
            ],
            [
                "Voltage actuator",
                "Delay, slew and settling separate a requested voltage from its measured effect. A three-point probe returns settled V/I confirmations.",
            ],
            [
                "Public numeric sensing",
                "10 Hz scalar captures; 0.02 s numeric delivery latency. The policy receives batches only when an action returns.",
            ],
            [
                "Camera / RGB",
                "The scene has a camera pose, but the batch runs with rendering disabled and records zero new RGB frames. No camera decision or visual diagnosis is tested.",
            ],
        ],
        [133, 360],
    )
    p(
        "The pilot disables numeric noise and actuator failures. This controlled simulator evidence "
        "tests internal digital consistency, not agreement with calibrated hardware.",
        "SmallPV",
    )

    new(
        "3. A hidden physical change becomes evidence",
        "C02-A: source schedule is evaluator-only; the policy learns from delivered measurements.",
    )
    figure(figs["source"], max_height=290)
    src = next(
        a["source_assessment"]
        for a in episodes[("C02", "A")]["audit"]
        if a["source_assessment"]["incident_light_reduction"]
    )
    p(
        f"At 2.00 s the hidden direct component changes from 800 to 400 W/m2 while diffuse light "
        f"remains 100 W/m2. The reference therefore changes from 900 to 500 W/m2. "
        f"The first changed public capture is at <b>{src['first_detected_capture_s']:.2f} s</b>; "
        f"the policy can use it at <b>{src['first_detected_available_s']:.2f} s</b>, when the local "
        "observation action returns. The chart places public points at capture time only to compare "
        "their values with truth; they were not visible to the agent at all those earlier times."
    )
    table(
        [
            ["Step", "Recorded interpretation and decision"],
            [
                "Sense",
                f"Compare valid reference samples: {src['initial_reference_w_m2']:.1f} to {src['latest_reference_w_m2']:.1f} W/m2; threshold is 100 W/m2.",
            ],
            [
                "Analyse",
                "Report measured incident-light reduction. Do not turn this into an unsupported claim of dirt, panel damage, cloud or a unique external cause.",
            ],
            [
                "Act",
                "The public instruction already says hold 1.8 V. Both arms avoid an unnecessary external query or voltage survey.",
            ],
            [
                "Verify",
                "Require matched valid voltage/current captured after the relevant action completed; preserve the unique physical cause as unresolved.",
            ],
        ],
        [70, 423],
    )

    new(
        "4. Why external information changes the action",
        "C03 and C04 share the same local physical evidence before the query. Only the service record changes.",
    )
    figure(figs["branches"], max_height=205)
    a4 = episodes[("C04", "A")]
    question = next(
        e["choice"]["request"]["question"]
        for e in a4["trace"]["events"]
        if e["kind"] == "committed" and e["choice"]["kind"] == "information"
    )
    h("Actual A question")
    p(escape(question))
    table(
        [
            ["Returned authoritative record", "Decision consequence"],
            [
                "C03: hold",
                "Preserve nominal voltage; collect fresh matched V/I after the reply; no survey.",
            ],
            [
                "C04: survey",
                "Run the permitted 0.8, 1.8 and 3.0 V survey; rank measured settled power; apply the best candidate if necessary; verify.",
            ],
            [
                "Counterfactual check",
                "Pre-query local-history SHA-256 is identical between C03 and C04 for each arm. The branch cannot be explained by different local measurements.",
            ],
        ],
        [160, 333],
    )
    h("What this source is")
    p(
        "The internet-labelled channel calls a <b>controlled current-record lookup</b>. It accepts "
        "newly worded questions but returns the same corpus record for that case; it performs no "
        "semantic web search or human reasoning. Typed current hold/survey fields and declared "
        "fixture source identity determine permission. The original text is retained. Source-title "
        "matching is not cryptographic authentication, and prose/typed-field disagreement is not "
        "interpreted semantically."
    )
    p(
        "External waiting is recorded in wall-clock time while the simulator is paused. This "
        "protocol prevents fictitious sunlight changes during a local fixture lookup; it does not "
        "measure real-world energy loss from a slow human or internet reply.",
        "SmallPV",
    )

    new(
        "5. The agent's recorded model and choice",
        "C04-A at the decision after the controlled survey permission is received.",
    )
    survey_audit = next(a for a in a4["audit"] if a["selected_operator"] == "survey")
    h(f"World belief at {survey_audit['simulation_time_s']:.2f} s")
    p(escape(survey_audit["world_model"]["summary"]))
    h("Self model")
    p(escape(survey_audit["self_model"]["summary"]))
    h("Alternatives actually evaluated")
    table(
        [["Operator", "Eligible / priority", "Recorded reason"]]
        + [
            [a["operator"], f"{'yes' if a['eligible'] else 'no'} / {a['priority']}", a["reason"]]
            for a in survey_audit["alternatives"]
        ],
        [82, 86, 325],
    )
    p(
        "The selected action is determined by the highest declared priority among eligible "
        "operators. Priorities are design choices, not learned value-of-information estimates. "
        "The record makes the next-step selection inspectable; it is not a private chain of thought "
        "or an after-the-fact explanation."
    )
    h("What differs from the reference")
    p(
        "R reaches a competent measured branch through its fixed procedure. A recomputes goals "
        "and eligibility at each context boundary. On these simple cases the resulting choices "
        "are equivalent. Demonstrating replanning under interruption or failure requires additional "
        "cases that challenge the procedure without handicapping its evidence checks."
    )

    new(
        "6. Predict, execute, then verify",
        "C04-A: the voltage survey creates measured evidence; a later commitment tests the applied target.",
    )
    ev = results[("C04", "A")]["evaluation"]
    table(
        [
            [
                "Survey target (V)",
                "Measured V",
                "Measured I (A)",
                "Measured power (W)",
                "Captured / usable (s)",
            ]
        ]
        + [
            [
                f"{v['target_voltage_v']:.1f}",
                f"{v['voltage_v']:.3f}",
                f"{v['current_a']:.5f}",
                f"{v['power_w']:.5f}",
                f"{v['capture_s']:.2f} / {v['available_s']:.2f}",
            ]
            for v in ev["candidate_evidence"]
        ],
        [90, 80, 91, 111, 121],
    )
    p(
        f"The selected candidate is <b>{ev['selected_measured_voltage_v']:.1f} V</b>, based on "
        "the greatest settled measured V x I. It is the best of three measured candidates, not "
        "proof of the continuous global maximum-power point. The policy does not manufacture a "
        "current prediction before the probe: that prediction is explicitly marked not predictable."
    )
    p(
        "Here the probe restores the nominal 1.8 V operating point, which is also the measured "
        "best candidate. Both arms avoid a redundant set-voltage command and perform a fresh "
        "verification wait. A separate regression forces a different best candidate to test "
        "application and verification; this batch does not show a benefit from adopting a new voltage.",
        "SmallPV",
    )
    table(
        [["Prediction", "Commit (s)", "Target capture (s)", "Observed / tolerance", "Usable (s)"]]
        + [
            [
                v["prediction"]["query_id"],
                f"{v['committed_s']:.2f}",
                f"{v['predicted_capture_s']:.2f}",
                f"{v['observed']:.3f} V / +/- {v['tolerance']:.2f} V",
                f"{v['available_s']:.2f}",
            ]
            for v in ev["predictions"]
        ],
        [150, 65, 85, 120, 73],
    )
    ready = ev["ready_at_s"]
    ready_measurement = next(
        a["assessment"]["verification"] for a in a4["audit"] if a["simulation_time_s"] == ready
    )
    p(
        f"Two checks occur at different times. The operating point is already supported at "
        f"{ready:.2f} s by a fresh matched pair captured at "
        f"{ready_measurement['voltage']['t_capture_s']:.2f} s. The separate precommitted "
        f"prediction for {ev['predictions'][-1]['capture_s']:.2f} s becomes assessable only at "
        f"{ev['predictions'][-1]['available_s']:.2f} s. That later outcome is not used to justify "
        "the earlier operating-point decision.",
        "SmallPV",
    )
    h("The verification contract")
    p(
        "A numerical prediction is committed before dispatch. Its target is an exact advertised "
        "capture-grid time. The evaluator looks for that valid voltage sample and a current sample "
        "with the same capture time, captured strictly after the relevant successful action terminal. "
        "It separately checks the sensor delivery and observation-availability times. Missing, stale "
        "or contradictory measurements cannot be replaced by an accepted-command acknowledgement."
    )
    p(
        f"Across all eight episodes, <b>{sum(v['passed'] for v in checks)}/{len(checks)} numerical "
        "predictions pass</b>. These are deterministic voltage-effect checks with a fixed 0.02 V "
        "tolerance; they are not calibrated probabilistic predictions of power, fault identity or "
        "future weather. Finish-tail samples cannot retroactively justify an earlier success claim."
    )

    new(
        "7. Paired performance and investigation costs",
        "One deterministic episode per case and arm; no confidence intervals or statistical superiority claim.",
    )
    figure(figs["performance"], max_height=230)
    perf_rows = [
        [
            "Case",
            "R / A success",
            "R / A energy (J)",
            "R / A ready (s)",
            "Queries / probe points per arm",
        ]
    ]
    for case in ("C01", "C02", "C03", "C04"):
        r, a = (results[(case, arm)]["evaluation"] for arm in ("R", "A"))
        perf_rows.append(
            [
                case,
                f"{r['success']} / {a['success']}",
                f"{r['raw_costs']['pv_energy_j']:.5f} / {a['raw_costs']['pv_energy_j']:.5f}",
                f"{r['ready_at_s']:.2f} / {a['ready_at_s']:.2f}",
                f"{r['raw_costs']['external_requests']} / {r['raw_costs']['probe_points']}",
            ]
        )
    table(perf_rows, [42, 77, 146, 90, 138])
    p(
        "All episodes reach the same 16 s horizon, including the two-second verification tail. "
        "Once ready, both systems preserve the operating point to that horizon. Energy is the "
        "simulator's accumulated PV production; it is not net plant service after subtracting real "
        "compute, communications or actuator electricity. Frame and camera-motion costs are zero "
        "because this batch uses numeric sensing only."
    )
    p(
        "At exactly 16 s, terminal cleanup disconnects the simulated plant after the last "
        "integrated interval. Verified operation and accumulated energy refer to the completed "
        "episode; the records do not claim continued post-episode generation.",
        "SmallPV",
    )
    costs = [r["evaluation"]["raw_costs"] for r in summary["results"]]
    p(
        f"Measured policy-boundary computation totals range from "
        f"{min(c['computation_wall_s'] for c in costs) * 1000:.2f} to "
        f"{max(c['computation_wall_s'] for c in costs) * 1000:.2f} ms per episode. "
        "These single-run wall-clock measurements include context and output validation and are "
        "sensitive to process scheduling. They do not establish a speed ranking. Overruns are "
        "rejected on return before dispatch; hostile or non-returning code is not forcibly preempted.",
        "SmallPV",
    )

    new("8. What the tests measure, and what they do not")
    p(
        f"The supplied regression evidence records <b>{tests['passed']} passed, "
        f"{tests['failures']} failed, {tests['errors']} errors and {tests['skipped']} skipped</b> "
        f"in {tests['seconds']:.2f} s (JUnit suite time). This count is read from the retained XML, "
        "not inferred from the number of test functions. The paired batch separately retains "
        "eight exact replay checks and the numerical predictions reported above."
    )
    runtime = freeze["runtime"]
    p(
        "Frozen execution runtime: Python "
        + escape(runtime["python"].split()[0])
        + "; "
        + escape(runtime["platform"])
        + "; MuJoCo "
        + escape(runtime["libraries"]["mujoco"])
        + "; NumPy "
        + escape(runtime["libraries"]["numpy"])
        + "; Pydantic "
        + escape(runtime["libraries"]["pydantic"])
        + ". Rendering was disabled for this batch.",
        "SmallPV",
    )
    table(
        [
            ["Evidence layer", "Checks and interpretation"],
            [
                "Environment and observation contracts",
                "Existing unit/integration/security regressions check physical-model contracts, sample timing, action execution, data separation and retained record integrity. These are digital correctness checks.",
            ],
            [
                "Policy and source checks",
                "Controlled policy tests exercise hold/survey branches, irrelevant/unavailable/conflicting or stale information, bounded clarification, measured target selection and fresh verification. Source text is not allowed to grant permission by substring.",
            ],
            [
                "Independent scoring",
                "The scorer reconstructs evidence from original public records, checks action authority and matched settled candidates, and rejects unsupported success. It does not simply trust the policy's final claim.",
            ],
            [
                "Paired batch invariants",
                "Same physical config and seed per pair; four 16 s paired horizons; identical local histories before the C03/C04 query; exact transcript replay and metric equality.",
            ],
            [
                "Viewer and evidence presentation",
                "Public/evaluator separation, time gating, artifact pairing and source validation are checked by viewer tests. Browser and page-render QA complement data checks.",
            ],
            [
                "Not established",
                "No hardware calibration, real sunlight disturbance, noisy repeated performance study, held-out distribution shift, live human/web interaction, continuous learning or open-ended reasoning.",
            ],
        ],
        [130, 363],
    )
    if review_text:
        p(
            "An independent review record accompanies this batch. Its exact text and hash are retained "
            "in the report input manifest; the report does not substitute a test count for that review.",
            "SmallPV",
        )
    p(
        "A passing simulation test shows that the specified digital change produces the specified "
        "digital effect. Demonstrating agreement with real PV requires synchronized independent "
        "physical measurements, uncertainty bounds and model validation against those measurements."
    )

    new("9. The next experiments should test useful differences")
    table(
        [
            ["Priority", "Experiment", "Evidence needed before a claim"],
            [
                "1",
                "Interrupted investigation and capability changes",
                "Disable a probe, expire service permission, or return conflicting context after planning. Measure supported replanning, false completion, unnecessary actions and safe unresolved outcomes against a strong reference.",
            ],
            [
                "2",
                "Noise and difficult sensing",
                "Repeat paired seeds with noise, drift, dropped/late observations and partial actuation. Score detection errors, verification reliability, decision delay and uncertainty calibration where probabilistic outputs exist.",
            ],
            [
                "3",
                "Withheld physical combinations",
                "Freeze development and evaluation cases separately. Test source changes combined with transmission or resistance changes without letting the policy read evaluator labels.",
            ],
            [
                "4",
                "Real external interaction",
                "Add a bounded human or web session with retained questions, provenance, replies, latency, costs and permission checks. Test whether new information improves a decision, not just whether a response is produced.",
            ],
            [
                "5",
                "Real-PV validation",
                "Use an instrumented reference panel/load and independent irradiance and temperature measurements. Apply controlled source/load changes and compare predicted versus measured I-V, power and thermal transients with error bars.",
            ],
            [
                "6",
                "Memory and transfer",
                "Only after the single-episode comparison is stable, introduce explicitly versioned learned state and compare later related encounters, forgetting and required human assistance.",
            ],
        ],
        [42, 157, 294],
    )
    h("Decision at this checkpoint")
    p(
        "The first controlled comparison is complete and inspectable. Retain the equal-result "
        "finding rather than weakening the reference to manufacture a win. The next scientific "
        "step is to preregister a small set of disruptions that require revising a plan, then test "
        "whether the explicit goal model improves outcomes or reduces unnecessary intervention."
    )
    p(
        "The report addresses the first five requested development items within this controlled "
        "slice: both decision systems, physical/context cases, complete investigation records, "
        "paired explanatory visuals and measured evaluation. The broader open-world research "
        "programme remains future work.",
        "SmallPV",
    )

    new("10. Evidence map and reproducibility")
    p(
        "This report is generated from retained records without re-running the simulator. "
        "Paths below are relative to the env workspace. The companion JSON manifest contains "
        "the full SHA-256 of every consumed input, figure and final PDF."
    )
    source_map = [
        ("Frozen experiment", args.freeze),
        ("Paired manifest", args.manifest),
        ("Evaluator summary", summary_path),
        ("Regression JUnit", args.test_xml),
    ]
    if args.review:
        source_map.append(("Independent review", args.review))
    for label, path in source_map:
        h(label)
        p(escape(str(path.relative_to(ROOT))), "SmallPV")
        p("SHA-256 " + sha(path), "SmallPV")
    h("Per-episode records")
    p(
        "Each C01-R through C04-A public directory contains investigation.json, policy_audit.json, "
        "verification.json, decision_timing.json, public_brief.json and original observation / "
        "decision streams. The private companion contains config.json, truth.jsonl, metrics.json "
        "and result.json. Hidden schedules, scene geometry and scoring labels remain evaluator-only.",
        "SmallPV",
    )
    h("Frozen execution and replay")
    p(
        f"The experiment records {len(freeze['inputs'])} execution-input hashes, runtime versions, "
        "both arm mechanisms, exact case configs/corpora, seed, rubric and one repetition per arm. "
        "The runner checks that freeze before execution and again before producing the summary. "
        "Exact replay reconstructs recorded choices without asking the policy or source to produce "
        "new answers. It verifies reproducibility within this declared runtime, not portability to "
        "other engines or real hardware.",
        "SmallPV",
    )
    h("Read-only report build")
    p(
        "scripts/build_paired_report.py consumes --manifest, --freeze and --test-xml, with optional "
        "--review; --output and --work must point to a new report and its figure workspace. "
        "A changed source or outcome requires a new retained report build, not silently relabelled evidence.",
        "SmallPV",
    )

    def page(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor("#D8E4E9"))
        canvas.line(50, height - 37, width - 50, height - 37)
        canvas.line(50, 42, width - 50, 42)
        canvas.setFillColor(colors.HexColor(GREY))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(50, height - 28, "PV INVESTIGATION  /  CONTROLLED PAIRED EVIDENCE")
        canvas.drawString(50, 29, "Evaluator report | 19 October 2026 | One development batch")
        canvas.drawRightString(width - 50, 29, str(doc.page))
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(args.output),
        pagesize=A4,
        rightMargin=50,
        leftMargin=50,
        topMargin=55,
        bottomMargin=55,
        title="PV investigation: paired development evidence",
        author="PV investigation project",
    )
    document.build(story, onFirstPage=page, onLaterPages=page)
    after_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sorted(source_paths)}
    if before_hashes != after_hashes:
        raise RuntimeError("Report source changed during the build; retain as invalid evidence")
    reader = PdfReader(args.output)
    text = "\n".join(p.extract_text() for p in reader.pages)
    if "\ufffd" in text:
        raise RuntimeError("PDF extraction contains replacement characters")
    evidence = {
        "scope": "Evaluator-only controlled paired report; no new camera frames or simulator run",
        "pdf": str(args.output.relative_to(ROOT)),
        "pdf_sha256": sha(args.output),
        "pages": len(reader.pages),
        "inputs_sha256": before_hashes,
        "inputs_unchanged": True,
        "figures_sha256": {str(p.relative_to(ROOT)): sha(p) for p in figs.values()},
        "tests_from_junit": tests,
        "comparison_successes": success,
        "comparison_episodes": len(summary["results"]),
        "all_energy_pairs_equal": tied,
        "numerical_predictions": len(checks),
        "numerical_predictions_passed": sum(v["passed"] for v in checks),
        "render_qa": "pending visual inspection of every page",
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    with manifest_path.open("x") as stream:
        json.dump(evidence, stream, indent=2)
        stream.write("\n")
    (args.work / "extracted-text.txt").write_text(text)
    print(
        json.dumps(
            {
                "status": "built",
                "pages": len(reader.pages),
                "pdf": str(args.output),
                "sha256": sha(args.output),
                "visual_qa": "required",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
