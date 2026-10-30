"""Explain current PV capabilities and case design using retained evidence only.

No simulation, policy execution, camera rendering or external call occurs here.
The old report is left untouched; retained experiment inputs are hash-checked.
"""

# Report prose is deliberately kept as complete editable sentences.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp/pdfs/capabilities/matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "tmp/pdfs/capabilities/cache"))

import build_paired_report as prior  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.lib import colors  # noqa: E402
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

NAVY, TEAL, ORANGE, GREY, LIGHT = prior.NAVY, prior.TEAL, prior.ORANGE, prior.GREY, prior.LIGHT
WIDTH = A4[0] - 96


def box(ax, x, y, w, h, title, body, colour=TEAL, body_size=12):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=.02,rounding_size=.08", facecolor=LIGHT, edgecolor=colour, linewidth=1.4))
    ax.text(x + w / 2, y + h - 0.30, title, ha="center", va="center", weight="bold", color=colour, fontsize=13)
    ax.text(x + w / 2, y + h / 2 - 0.16, body, ha="center", va="center", fontsize=body_size, color=NAVY, linespacing=1.35)


def arrow(ax, start, end, colour=GREY):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16, color=colour, linewidth=1.5))


def loop_figure(work):
    fig, ax = plt.subplots(figsize=(8.6, 4.1))
    ax.set(xlim=(-.1, 9.2), ylim=(0, 4.6))
    ax.axis("off")
    specs = [
        (0, 2.7, "1  SENSE", "What measurements\nare available?"),
        (3.15, 2.7, "2  ANALYSE", "What changed?\nWhat is missing?"),
        (6.3, 2.7, "3  DECIDE", "Which available step\naddresses the gap?"),
        (6.3, .45, "4  INTERACT", "Ask a source or\ntest the PV asset"),
        (3.15, .45, "5  VERIFY", "Did fresh evidence\nsupport the outcome?"),
        (0, .45, "6  UPDATE", "Revise the current\nstate and next step"),
    ]
    for x, y, title, body in specs:
        box(ax, x, y, 2.75, 1.45, title, body)
    for start, end in [((2.8, 3.4), (3.1, 3.4)), ((5.95, 3.4), (6.25, 3.4)), ((7.68, 2.65), (7.68, 1.95)), ((6.25, 1.17), (5.95, 1.17)), ((3.1, 1.17), (2.8, 1.17)), ((1.37, 1.95), (1.37, 2.65))]:
        arrow(ax, start, end)
    return prior.savefig(fig, work, "capability-loop")


def context_figure(work):
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    ax.set(xlim=(-.1, 9), ylim=(0, 5.3))
    ax.axis("off")
    box(ax, 1.95, 3.7, 4.9, 1.25, "SAME LOCAL OBSERVATIONS", "900 W/m2 reference; holding 1.8 V", body_size=12)
    box(ax, 1.95, 1.95, 4.9, 1.25, "SAME INFORMATION GAP", "Is a voltage survey currently permitted?", body_size=12)
    arrow(ax, (4.4, 3.65), (4.4, 3.25))
    box(ax, 0, .1, 4.1, 1.3, "C03: REPLY SAYS HOLD", "Keep 1.8 V; verify; no survey", colour=NAVY, body_size=11.5)
    box(ax, 4.75, .1, 4.1, 1.3, "C04: REPLY SAYS SURVEY", "Probe three points; select; verify", colour=ORANGE, body_size=11.5)
    arrow(ax, (3.35, 1.9), (2.05, 1.45), NAVY)
    arrow(ax, (5.45, 1.9), (6.8, 1.45), ORANGE)
    ax.text(4.4, 1.65, "ask once", ha="center", fontsize=11, color=GREY)
    return prior.savefig(fig, work, "context-decision-branches")


def mechanism_figure(work):
    fig, ax = plt.subplots(figsize=(8.6, 3.3))
    ax.set(xlim=(0, 9), ylim=(0, 3.55))
    ax.axis("off")
    box(ax, .1, .55, 4.05, 2.65, "R: FIXED PROCEDURE", "Read the shared assessment\nFollow the next procedure stage\nBranch on service permission\nProbe if allowed; verify; finish", NAVY, 11.8)
    box(ax, 4.85, .55, 4.05, 2.65, "A: GOAL-BASED SELECTION", "Read the same assessment\nRecompute unmet goals\nList eligible fixed operators\nChoose the highest fixed priority", TEAL, 11.8)
    ax.text(4.5, .15, "Same sensing, source, budgets, physical actions and verification rules", ha="center", fontsize=11, weight="bold", color=GREY)
    return prior.savefig(fig, work, "reference-versus-goal-policy")


def load_evidence(manifest_path, freeze_path, test_xml, review):
    manifest = prior.read(manifest_path)
    summary_path = (manifest_path.parent / manifest["summary_path"]).resolve()
    summary = prior.read(summary_path)
    index_path = summary_path.parent / "artifact-index.json"
    index = prior.read(index_path)["sha256"]
    for path, checksum in index.items():
        if prior.sha(ROOT / path) != checksum:
            raise ValueError(f"Retained artifact changed: {path}")
    wrapper = prior.read(freeze_path)
    content_hash = hashlib.sha256(json.dumps(wrapper["experiment"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    link = manifest_path.parent / "experiment-link.json"
    if wrapper["sha256"] != content_hash or prior.read(link)["sha256"] != prior.sha(freeze_path):
        raise ValueError("Experiment freeze checksum/link mismatch")
    sources = {manifest_path, freeze_path, summary_path, index_path, link, test_xml, review, Path(__file__).resolve(), Path(prior.__file__).resolve()}
    sources.update(ROOT / path for path in index)
    sources.update({ROOT / "src/pv_sim/comparison_policies.py", ROOT / "src/pv_sim/comparison_sources.py", ROOT / "src/pv_sim/comparison.py"})
    sources.update(ROOT / path for path in ("tests/unit/test_comparison_sources.py", "tests/integration/test_comparison_policies.py", "tests/integration/test_comparison_evaluator.py", "tests/unit/test_comparison_viewer.py"))
    episodes = {}
    for case in manifest["cases"]:
        for arm, paths in case["arms"].items():
            public = (manifest_path.parent / paths["public_dir"]).resolve()
            private = (manifest_path.parent / paths["evaluator_dir"]).resolve()
            episode = {"trace": prior.read(public / "investigation.json")["transcript"], "audit": prior.read(public / "policy_audit.json"), "verification": prior.read(public / "verification.json"), "config": prior.read(private / "config.json"), "truth": [r.get("payload", r) for r in prior.rows(private / "truth.jsonl")], "result": prior.read(private / "result.json")}
            episode["observations"] = prior.observations(episode["trace"])
            episodes[(case["case_id"], arm)] = episode
    for case in ("C01", "C02", "C03", "C04"):
        r = episodes[(case, "R")]["audit"]
        a = episodes[(case, "A")]["audit"]
        if [(x["selected_operator"], x["simulation_time_s"]) for x in r] != [(x["selected_operator"], x["simulation_time_s"]) for x in a]:
            raise ValueError("The report's identical workflow statement is no longer supported")
    if summary["status"] != "complete" or len(summary["results"]) != 8:
        raise ValueError("Requires the retained completed eight-episode batch")
    if not all(p["matched_physical_config"] and p["common_horizon_energy_eligible"] and p["A_minus_R"]["pv_energy_j"] == 0 for p in summary["pairs"]):
        raise ValueError("Matched physical inputs, horizons and energy equality required")
    if not all(summary["context_counterfactual_identical_prequery_history"].values()):
        raise ValueError("C03/C04 pre-query history identity is required")
    return summary, episodes, sources, prior.test_result(test_xml), len(index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "runs/paired-investigation-20261019/paired_manifest.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "private_eval/paired-investigation-freeze-20261019.json")
    parser.add_argument("--test-xml", type=Path, default=ROOT / "runs/paired-build-20261019/nonrender.xml")
    parser.add_argument("--review", type=Path, default=ROOT / "output/review/PAIRED_INVESTIGATION_REVIEW_20261019.txt")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    for key in vars(args):
        setattr(args, key, getattr(args, key).resolve())
    if args.output.exists() or args.output.with_suffix(".manifest.json").exists():
        raise FileExistsError("Preserve prior report builds; choose a new output")
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary, episodes, sources, tests, indexed = load_evidence(args.manifest, args.freeze, args.test_xml, args.review)
    before = {str(p.relative_to(ROOT)): prior.sha(p) for p in sorted(sources)}
    figs = {"loop": loop_figure(args.work), "context": context_figure(args.work), "mechanism": mechanism_figure(args.work), "source": prior.source_change(episodes[("C02", "A")], args.work), "geometry": prior.geometry(episodes[("C04", "A")], args.work)}
    styles = getSampleStyleSheet()
    for name, size, leading, colour, font, after in [("TitlePV", 28, 32, NAVY, "Helvetica-Bold", 13), ("HeadPV", 21, 25, NAVY, "Helvetica-Bold", 12), ("SubPV", 11.5, 15, TEAL, "Helvetica-Bold", 7), ("BodyPV", 10.2, 14.4, NAVY, "Helvetica", 9), ("SmallPV", 8.6, 11.5, GREY, "Helvetica", 7), ("CellPV", 9.2, 12.3, NAVY, "Helvetica", 0), ("CellHeadPV", 9.4, 12.5, "#FFFFFF", "Helvetica-Bold", 0)]:
        styles.add(ParagraphStyle(name, fontName=font, fontSize=size, leading=leading, textColor=colors.HexColor(colour), spaceAfter=after))
    story = []
    page_titles = []

    def p(text, style="BodyPV"):
        story.append(Paragraph(text, styles[style]))

    def title(number, heading, subtitle=None):
        if number > 1:
            story.append(PageBreak())
        page_titles.append(heading)
        p(f"{number:02d}  /  CAPABILITIES AND CASES", "SubPV")
        p(heading, "TitlePV" if number == 1 else "HeadPV")
        if subtitle:
            p(subtitle)

    def figure(key, height, caption):
        img = Image(str(figs[key]))
        ratio = min(WIDTH / img.imageWidth, height / img.imageHeight)
        img.drawWidth, img.drawHeight = img.imageWidth * ratio, img.imageHeight * ratio
        story.append(img)
        story.append(Spacer(1, 5))
        p(caption, "SmallPV")

    def table(headers, rows, widths):
        data = [[Paragraph(escape(x), styles["CellHeadPV"]) for x in headers]]
        data += [[Paragraph(str(x), styles["CellPV"]) for x in row] for row in rows]
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#EDF4F6"), colors.HexColor("#F8FAFB")]), ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor(TEAL))]))
        story.append(t)
        story.append(Spacer(1, 11))

    def callout(text):
        t = Table([[Paragraph(text, styles["BodyPV"])]], colWidths=[WIDTH])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT)), ("BOX", (0, 0), (-1, -1), .6, colors.HexColor(TEAL)), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(t)
        story.append(Spacer(1, 12))

    # Page 1: teach the purpose before presenting outcomes or test counts.
    title(1, "How the PV prototype senses, decides and investigates", "Capabilities, case design and the role of the agent | Version 2 | 19 October 2026")
    p("<b>The central question is: can the PV system use what it knows, recognise what is missing, choose a useful interaction, and check the result?</b> The prototype implements this chain in a controlled digital PV environment. It connects observations to a specific information gap, an allowed intervention and measured confirmation. This makes the investigation process testable and inspectable, so future AI methods can be compared fairly on the same PV world.")
    figure("loop", 222, "Conceptual workflow implemented by both comparison systems. Update means revising the present episode's structured state; it does not mean training a model.")
    p("<b>One concrete example:</b> the panel is operating at 1.8 V, but the system does not know whether an electrical survey is currently permitted. More voltage samples cannot answer that service question. It asks an external information source. A hold reply leads to continued operation; a survey reply leads to a three-point electrical test, measured selection and fresh verification.")
    callout("<b>What the current evidence says.</b> Both the competent reference R and the goal-based system A can sense, analyse, ask, probe and verify. They used identical operator sequences and times in all four cases. A changes how the next step is selected; this first batch does not show a performance advantage.")
    p("Read pages 2-3 for the capabilities and reasons for each case; pages 4-7 for the physical and information-driven workflows; pages 8-10 for the actual R/A difference, evidence and next experiments.", "SmallPV")

    # Page 2: avoid attributing shared functions exclusively to A.
    title(2, "What the system can do today", "The six capabilities below are present in both R and A. Each has a specific, limited implementation.")
    table(["Capability", "Current implementation", "Example and boundary"], [
        ("<b>Sense</b>", "Read valid measurements after they are available. Pair voltage and current captured at the same instant.", "Uses reference irradiance and V/I. Temperature and encoders are recorded but do not drive these case decisions."),
        ("<b>Analyse</b>", "Compare irradiance with its initial value; validate a current typed instruction; rank measured V x I; identify unmet verification.", "A 100 W/m2 drop threshold is prescribed. It does not discover a unique physical fault or infer causal probabilities."),
        ("<b>Decide</b>", "Select the next allowed action using the shared assessment and remaining resources.", "R follows stages; A selects eligible operators by fixed priorities. Neither calculates information value or optimises the cost of asking versus probing."),
        ("<b>Interact</b>", "Ask for the current service instruction or execute wait, voltage survey, target setting and finish operations.", "The external source is a controlled typed record. There is no live internet, human conversation or LLM in this batch."),
        ("<b>Verify</b>", "Require fresh matched V/I after the relevant action or instruction; separately check committed voltage predictions.", "An accepted command alone is insufficient. Current during the survey is declared not predictable; no power forecast is evaluated."),
        ("<b>Update</b>", "Replace the within-episode service state, evidence references, selected target, budgets and verification status.", "Unknown context becomes hold or survey. No learned weights, novel goals or cross-episode memory are added."),
    ], [74, 210, WIDTH - 284])
    p("<b>World model has two meanings here.</b> The private simulator computes the digital PV, illumination, thermal and actuator dynamics. The decision system cannot read that truth. Its own world model is a compact evidence-backed summary of observed light, unresolved causes, service context and operating target.")
    p("<b>The self model</b> records advertised tools, unavailable capabilities, failed actions and remaining budgets. Both systems use the same summary. It supports bounded action selection; it does not learn an actuator's physical capabilities from experience.")

    # Page 3: explain the experiment's scientific contrasts.
    title(3, "Why C01, C02, C03 and C04?", "Each case isolates a question about the workflow. Every case is run once with R and once with A, using matched physical conditions, sensing, tools and budgets.")
    table(["Case and question", "What the evaluator sets", "Behaviour that should follow", "What would fail"], [
        ("<b>C01: Nothing changed</b><br/>Can it avoid inventing a problem?", "Unchanged illumination. Hold instruction already known.", "Use local evidence, hold 1.8 V, verify. No question or survey.", "False source alarm, needless query or unnecessary probe."),
        ("<b>C02: Less light</b><br/>Can it notice what the sensors reveal?", "At 2 s, direct irradiance falls from 800 to 400 W/m2. Hold is still known.", "Report the observed reference reduction once evidence arrives; hold and verify without querying.", "Missed change, reading hidden truth early, or claiming a uniquely identified fault."),
        ("<b>C03: Ask, then hold</b><br/>Can it seek missing information and then abstain?", "Same physics as C01. Service instruction initially hidden; the source returns hold.", "Ask once. Respect hold, then verify. No voltage survey.", "Assuming permission, ignoring the reply or doing an unauthorized survey."),
        ("<b>C04: Ask, then experiment</b><br/>Can a reply justify physical investigation?", "Same physics, initial brief and pre-query evidence as C03; source returns the survey instruction.", "Ask once, probe three declared voltages, select the measured best and verify.", "Ignoring permission, choosing an unsupported point or declaring success from acknowledgement."),
    ], [109, 133, 143, WIDTH - 385])
    p("<b>Contrast 1: C01 versus C02</b> changes the physical illumination while keeping the service instruction fixed. It tests sensing and restrained interpretation; it is not a test of fault repair or maximum-power tracking.")
    p("<b>Contrast 2: C03 versus C04</b> keeps the physical situation and pre-query public history identical while changing only the returned service instruction. It tests whether information changes a justified physical decision. The unknown element is operational context, not a new PV fault.")
    callout("These are four development cases, not a full factorial experiment or a hidden open-world benchmark. They establish a readable baseline. They do not yet separate A's performance from a well-engineered reference.")

    # Page 4: connect hidden intervention, physical consequence and available observation.
    title(4, "C02 - Less light: sense and interpret", "The evaluator changes the digital world at 2.00 s. The decision system receives evidence of the change at 2.62 s.")
    figure("source", 279, "Recorded C02-A data; R has the same trajectory. Orange is private evaluator truth. Teal samples are plotted at capture time, which can precede their availability to the policy. The dotted line marks the first assessment at 2.62 s.")
    table(["Hidden change", "Observed effect", "Supported interpretation"], [
        ("Direct irradiance: 800 to 400 W/m2. Diffuse irradiance remains 100 W/m2.", "Reference measurement: 900 to 500 W/m2. Matched V/I also shows lower electrical output.", "Incident light at the reference has fallen. The system leaves the unique physical cause unresolved."),
    ], [WIDTH / 3] * 3)
    p("<b>Why does it continue holding 1.8 V?</b> Its current service instruction is hold, and the measurements do not create a missing permission question. The task is to notice and report the change, then verify the permitted operating state. A reduction in output does not by itself authorize a new experiment.")
    p("<b>Why does this matter?</b> It demonstrates a distinction between an observation, an interpretation and an action. The system does not label every power decrease as panel damage or automatically launch a survey. It also does not restore the lost power in this case.")
    p("The mechanism is a predefined reference-drop rule, not learned diagnosis. No injected noise is present in this batch; sensor uncertainty fields alone do not establish uncertainty-calibrated reasoning.", "SmallPV")

    # Page 5: explicitly name what external information contributes.
    title(5, "C03/C04 - Ask, then hold or experiment", "The same measurements can support different actions when the service instruction differs. The relevant missing information is whether a survey is permitted.")
    figure("context", 270, "Recorded decision structure shared by R and A. C03 and C04 have identical physical configurations, seeds, initial public briefs and pre-query local-history hashes. The arrows explain the observed branch; they do not represent learned semantic reasoning.")
    p("<b>The question is tied to a decision.</b> A asks whether the current service instruction requires holding 1.8 V or permits the declared bounded voltage survey. Its question template inserts the local reference assessment. R asks a fixed question addressing the same gap. Both parse typed reply fields; neither uses natural-language understanding.")
    p("<b>The answer changes what happens.</b> At 2.82 s, a valid hold reply leads to no survey in C03. A valid survey instruction leads to the required three-point electrical probe in C04. Both policies have read the reply before making that physical choice.")
    callout("<b>What 'external' means in this experiment:</b> a separate, controlled service-record fixture supplies a typed hold/survey instruction with source identity and validity interval. The trace labels the request channel internet, but no live website, human or large AI model is contacted. New question wording does not change the returned record through semantic search.")
    p("In C04, the predefined task requires the survey branch once that instruction is established. The system does not estimate whether the survey's information value outweighs its cost. The demonstrated capability is to obtain missing context and follow the justified branch; open-ended source selection remains future work.", "SmallPV")

    # Page 6: let the geometry explain embodiment without falsely claiming vision.
    title(6, "What is physical about this digital asset?", "The scene locates the PV module, illumination, reference sensor and camera. Physical actions affect the simulated asset; external questions affect what the decision system knows.")
    figure("geometry", 276, "Evaluator reconstruction from retained scene configuration and recorded camera pose. This is a 3D explanatory figure, not a camera image or an input used by either policy. No new RGB frames or camera movements occur in the paired batch.")
    table(["Element", "How it participates in the workflow"], [
        ("PV electrical operating point", "The survey changes voltage through 0.8, 1.8 and 3.0 V and measures current. Voltage multiplied by current supplies the candidate power ranking."),
        ("Reference light sensor", "Provides the public irradiance measurement used to detect C02's incident-light reduction. The policy never reads the hidden source-change schedule."),
        ("Camera and spatial tools", "The wider platform has RGB rendering and spatial action interfaces. They are available for future visual investigations, but capture_rgb is unavailable to these numeric-only policies."),
        ("Service information source", "Supplies an operating instruction rather than a physical sensor reading. It can change which electrical test is permitted without changing the starting PV state."),
    ], [135, WIDTH - 135])
    p("<b>Tool, skill and decision mechanism.</b> A tool is an executable interface such as probe_voltage. A skill is a bounded procedure such as survey three candidates and rank measured power. The decision mechanism chooses when to use those procedures. Current skills and goals are authored in code; A does not invent new tools or procedures.")

    # Page 7: one end-to-end story with concrete real numbers and distinct clocks.
    c04 = episodes[("C04", "A")]["result"]["evaluation"]
    candidates = c04["candidate_evidence"]
    title(7, "C04 - Ask, then experiment: the full loop", "This is the complete decision-relevant sequence for A. R selects the same operators at the same times. Times below are simulation times, not human response delays.")
    table(["Time", "Evidence / interpretation", "Chosen step and reason"], [
        ("0.02 s", "Only an initial sample is available; service instruction is unknown.", "Wait for the initial local evidence window. Another source cannot replace the required local observation."),
        ("2.62 s", "Reference remains 900 W/m2. The permission gap remains.", "Ask for the current service instruction. Local V/I cannot establish whether a survey is allowed."),
        ("2.82 s", "A current, attributed service record says survey.", "Probe 0.8, 1.8 and 3.0 V. Candidate electrical performance is still unmeasured."),
        ("6.22 s", "The complete probe returns all three candidate measurements. 1.8 V has the greatest measured power.", "Keep the already restored 1.8 V and request fresh verification. Avoid a redundant set command."),
        ("6.92 s", "The 6.90 s matched sample reports 1.8 V and about 0.5515 A after the probe completed.", "Mark the operating point verified. Continue holding to the common 16 s comparison horizon."),
    ], [55, 219, WIDTH - 274])
    p("What the electrical experiment actually measured", "SubPV")
    table(["Candidate voltage", "Matched current", "Measured power", "Capture time"], [[f"{v['target_voltage_v']:.1f} V", f"{v['current_a']:.6f} A", f"{v['power_w']:.6f} W", f"{v['capture_s']:.2f} s"] for v in candidates], [123, 125, 125, WIDTH - 373])
    p("<b>Best measured candidate is not a global optimum.</b> These are sequential measurements at three preset voltages. The best is the original 1.8 V point, so this case shows investigation and verification, not an improved final voltage or energy gain.")
    p("<b>Prediction and verification have different timestamps.</b> A voltage prediction committed at 6.22 s targets the 7.10 s sample, which is only returned to the policy at 12.12 s. It passes later, but cannot justify readiness at 6.92 s. Readiness uses the already available 6.90 s V/I pair. Survey current is explicitly marked not predictable.", "SmallPV")

    # Page 8: the scientific distinction must be honest and easy to locate.
    title(8, "What makes A different from the reference?", "The difference is the selection mechanism. It is not an exclusive ability to sense, analyse, maintain a world/self model, ask questions or verify a result.")
    figure("mechanism", 196, "Simplified explanation of the implemented algorithms. Both share the assessment helpers, tools, source parser, prediction construction and verification requirements.")
    p("<b>A concrete selection at 2.82 s in C04:</b> the service reply has resolved the permission goal, but the permitted survey has not been completed. A marks survey eligible with priority 80 and verification eligible with priority 60, then selects survey. After probe results return, the survey deficit is satisfied and verification becomes the next eligible step. R reaches the same choices through its authorized-survey stage.")
    table(["What A currently adds", "What that does not yet establish"], [
        ("Explicit unmet goals, eligible alternatives, priorities and a reason recorded before execution.", "The goals, operators and priorities are fixed in code. There is no invented goal, general planning search or learned priority."),
        ("Re-evaluation of the current structured state at each decision boundary; context-worded questions.", "No LLM, semantic retrieval, persistent learning or discovery of a novel fault model is operating here."),
        ("A form that can be extended to compare alternative interactions as evidence changes.", "A benefit from such flexibility is a research hypothesis. It must be demonstrated on cases that require it."),
    ], [WIDTH / 2] * 2)
    callout("<b>Observed difference in these cases: none in chosen operators or timing.</b> R and A take the same steps, reach the same verified states, and consume the same physical resources and energy. The present A is a bounded, handwritten symbolic controller. Calling it agentic describes the organised decision loop; it is not evidence of broader intelligence.")
    p("A competent reference is essential: R receives the same evidence and can ask, probe and verify. An artificially weak baseline would make a claimed agent benefit less informative.", "SmallPV")

    # Page 9: make outcomes serve the capability explanation.
    title(9, "What the evidence establishes", "The paired results validate a functioning investigation loop on these four cases. They provide no evidence that A is better than R.")
    result_rows = []
    for case in ("C01", "C02", "C03", "C04"):
        e = episodes[(case, "A")]["result"]["evaluation"]
        c = e["raw_costs"]
        result_rows.append([case, "R and A pass", f"{e['ready_at_s']:.2f} s", str(c["external_requests"]), str(c["probe_points"]), f"{c['pv_energy_j']:.6f}"])
    table(["Case", "Outcome", "Ready", "Queries", "Probe points", "PV energy (J)"], result_rows, [42, 103, 64, 64, 94, WIDTH - 367])
    p("Values are equal for R and A within every case. All episodes run to 16 s. C04 produces <b>0.376866 J less</b> than C03 over that common horizon because the survey changes the operating trajectory. This is a production cost in the simulator, not an agent advantage or a complete net-energy calculation.")
    table(["Capability claim", "Evidence that supports it", "What the check cannot prove"], [
        ("Sense / analyse / choose", "C01/C02 contrast; C03/C04 controlled branch; all 8 episodes reach supported outcomes.", "General diagnosis, robustness to unknown conditions or performance beyond one deterministic seed."),
        ("Interact / verify", "Permission is available before the probe; candidate samples are action-bound; fresh V/I supports completion; 16 numerical voltage predictions pass.", "Useful prediction of PV current/power, calibrated causal beliefs or open-ended external information use."),
        ("Record / replay / protect evidence", f"All 8 linked replays pass with equal metrics. Retained regression XML records {tests['passed']} tests passed. Separate tests reject stale, foreign or contradictory evidence.", "Agreement with a physical panel. Correct software behaviour is not experimental hardware validation."),
    ], [103, 223, WIDTH - 326])
    p("<b>Three levels of confidence must stay separate.</b> Engineering tests check that the software enforces its rules. The paired cases check behavioural decisions inside the digital world. Hardware validation must check whether the model's quantitative responses match a real panel under measured interventions.")
    p("The final 25-test viewer regression overlaps the 875-test suite and is not an additional 25 distinct tests. Robustness unit tests are not extra scored performance trials. No new experiments were run to produce this explanation.", "SmallPV")

    # Page 10: propose capability-discriminating tests, not a search for a forced win.
    title(10, "What should the next experiments establish?", "The next step is to test when choosing an interaction adds value, then test replanning when a useful plan is disrupted. Both systems must receive the same evidence, tools and budgets; a tie remains a valid result.")
    table(["Test to add", "Capability hypothesis", "Compare using the same resources"], [
        ("Two useful routes: a physical probe or an external question, with varying cost, reliability and delay.", "A new selector can choose the more useful route under the same service goal. This needs implementation beyond the present fixed-priority permission branch.", "Decision quality, information gained, production cost, delay and wasted calls. This directly tests the research aim without forcing A to win."),
        ("A tool fails, or a service instruction changes after a plan was formed.", "The system can revise its next step using current capability and instruction state.", "Supported recovery or abstention, actions under stale instructions and recovery cost. Give R the same feedback and a competent fallback."),
        ("Information is stale, irrelevant, conflicting or uncertain.", "The system distinguishes unavailable knowledge from permission and chooses another useful source or a justified stop.", "Unsupported actions, clarification quality, request cost and uncertainty calibration. Test noise and repeated seeds separately."),
        ("A live human or web source answers a genuinely open question.", "An interaction can obtain useful new information rather than retrieve a fixed hold/survey record.", "Decision relevance, source reliability, latency, human burden and factual grounding. Start with a bounded audited task."),
    ], [153, 170, WIDTH - 323])
    p("<b>Real-world validation is a separate workstream.</b> Apply measured irradiance and load changes to an instrumented panel, record independent voltage/current/temperature references, and compare predicted and observed responses. Define acceptable errors, sensor delays and uncertainty intervals before examining the results. This is needed before treating simulator agreement as physical accuracy.")
    p("Evidence and reproduction", "SubPV")
    p("This version re-explains the retained 19 October batch. It preserves the original report and experiment files. The companion manifest hashes the source records and figures. The experiment was frozen before the scored run, after development checks; it is not a held-out study.", "SmallPV")
    p("Workspace-relative sources: <b>runs/paired-investigation-20261019/paired_manifest.json</b>; <b>private_eval/paired-investigation-20261019/comparison.json</b>; <b>runs/paired-build-20261019/nonrender.xml</b>; <b>output/review/PAIRED_INVESTIGATION_REVIEW_20261019.txt</b>. The paired interactive viewer is <b>output/workflow/paired-03/paired-evaluator.html</b>. Its recorded scene is explanatory; manual orbit dragging remains unverified.", "SmallPV")

    def decorate(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setStrokeColor(colors.HexColor("#D7E3E8"))
        canvas.line(48, h - 35, w - 48, h - 35)
        canvas.line(48, 40, w - 48, 40)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(GREY))
        canvas.drawString(48, h - 26, "PV INVESTIGATION  /  CAPABILITIES, CASE DESIGN AND THE AGENT")
        canvas.drawString(48, 27, "Version 2 | Controlled digital prototype | 19 October 2026")
        canvas.drawRightString(w - 48, 27, f"{doc.page} / 10")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(args.output), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=51, bottomMargin=52, title="How the PV prototype senses, decides and investigates", author="PV investigation project")
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    reader = PdfReader(args.output)
    text = "\n".join(page.extract_text() for page in reader.pages)
    if len(reader.pages) != 10:
        raise ValueError(f"Unexpected pagination: {len(reader.pages)}, expected 10; retain build for correction")
    if "\ufffd" in text:
        raise ValueError("Invalid replacement character in PDF text")
    after = {str(p.relative_to(ROOT)): prior.sha(p) for p in sorted(sources)}
    if before != after:
        raise RuntimeError("An evidence source changed during report generation")
    checks = [v for e in episodes.values() for v in e["verification"]]
    manifest = {"pdf": str(args.output.relative_to(ROOT)), "pdf_sha256": prior.sha(args.output), "pages": len(reader.pages), "page_titles": page_titles, "scope": "Capability-led explanation of retained controlled evidence; no new experiments or camera rendering", "inputs_sha256": before, "inputs_unchanged": True, "retained_artifact_index_entries_verified": indexed, "figures_sha256": {str(path.relative_to(ROOT)): prior.sha(path) for path in figs.values()}, "comparison_episodes": len(summary["results"]), "successes": sum(r["evaluation"]["success"] for r in summary["results"]), "operator_sequences_and_times_equal": True, "numerical_predictions": len(checks), "numerical_predictions_passed": sum(v["passed"] for v in checks), "tests_from_retained_xml": tests, "render_qa": "pending visual inspection of every page"}
    with args.output.with_suffix(".manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    (args.work / "extracted-text.txt").write_text(text)
    print(json.dumps({"status": "built", "pdf": str(args.output), "pages": len(reader.pages), "sha256": prior.sha(args.output), "visual_qa": "required"}, indent=2))


if __name__ == "__main__":
    main()
