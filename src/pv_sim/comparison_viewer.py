"""Source-bound offline comparison of two retained investigation episodes.

Presentation only: this module neither dispatches tools nor runs a simulator. Public
exports physically exclude evaluator state, geometry, result files and case labels.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from pv_sim.investigation import load_investigation
from pv_sim.workflow_replay import (
    _number,
    _records,
    _ref,
    _select,
    _source,
    _verify_pairing,
    build_replay_index,
    replay_state,
    sha256,
    validate_presentation_events,
)
from pv_sim.workflow_replay import (
    public_export as public_episode,
)

SCHEMA = "paired_investigation_viewer.v1"
MANIFEST_SCHEMA = "paired_investigation.v1"
ARMS = {"R": "Procedural reference", "A": "Goal-based adaptive policy"}


def _read(path: Path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"Duplicate JSON key: {key}")
            out[key] = value
        return out

    return json.loads(path.read_text(), object_pairs_hook=unique)


def _event(index, identifier, role, kind, time, source, payload, *, available=None):
    index["events"].append({
        "id": identifier,
        "role": role,
        "kind": kind,
        "time_s": time,
        "available_s": time if available is None else available,
        "source_ref": source,
        "payload": payload,
        "visibility": "public",
        "stable_sequence": len(index["events"]),
    })


def _trace_observations(trace):
    result = [trace["interaction"]["initial_observation"]]
    for row in trace["interaction"]["events"]:
        if row["kind"] == "physical_decision":
            result.append(row["observation"])
        elif row["kind"] == "information_started":
            result.append(row["pending"]["observation"])
    return result


def _episode(public: Path, private: Path | None, arm: str) -> dict:
    index = build_replay_index(public, evaluator_dir=private, policy_label=ARMS[arm])
    if private is not None:
        truth_path = _select(private, "truth")
        blob = truth_path.read_bytes()
        source = next(s for s in index["sources"] if s["artifact_path"] == str(truth_path))
        if sha256(blob) != source["sha256"]:
            raise ValueError("Truth changed while constructing the comparison view")
        raw_truth = ([json.loads(line) for line in blob.decode().splitlines() if line.strip()]
                     if truth_path.suffix == ".jsonl" else json.loads(blob))
        for rendered, original in zip(index["evaluator"]["truth"], raw_truth, strict=True):
            payload = original.get("payload", original)
            rendered["disconnected"] = payload.get("disconnected")
            rendered["terminal_reason"] = payload.get("terminal_reason")
    trace_path = public / "investigation.json"
    transcript = load_investigation(trace_path).model_dump(mode="json")
    if transcript["interaction"]["task"] != index["public"]["task"]:
        raise ValueError("Investigation task does not match the recorded episode")
    recorded = [r.get("payload", r) for r in _records(_select(public, "observations"))]
    # This first numeric comparison has no embedded image bytes to normalize.
    if recorded != _trace_observations(transcript):
        raise ValueError("Investigation observations do not match the recorder stream")
    trace_source = _source(trace_path, "public", public)
    index["sources"].append(trace_source)
    index["public"]["decisions"] = []
    index["public"]["exchanges"] = []
    index["public"]["verifications"] = []
    index["public"]["assessment"] = None
    index["public"]["policy_audit"] = []
    brief_path = public / "public_brief.json"
    index["public"]["brief"] = _read(brief_path)
    index["sources"].append(_source(brief_path, "public", public))
    index["events"] = [e for e in index["events"] if e["kind"] != "decision"]
    choices = {}
    for i, record in enumerate(transcript["events"]):
        if record["kind"] != "committed":
            continue
        choice = record["choice"]
        when = _number(record["simulation_time_s"], "choice time")
        ref = _ref(trace_source, 1, f"transcript.events[{i}]")
        decision = {
            **choice,
            "id": choice["choice_id"],
            "time_s": when,
            "available_s": when,
            "source_ref": ref,
            "context_sha256": record["context_sha256"],
            "wall_clock_latency_s": None,
        }
        choices[choice["choice_id"]] = decision
        index["public"]["decisions"].append(decision)
        _event(index, "choice-" + choice["choice_id"], arm, "choice_committed", when, ref, choice)
    timing_path = public / "decision_timing.json"
    timing = _read(timing_path)
    if not isinstance(timing, list):
        raise ValueError("decision_timing.json must be an array")
    timing_source = _source(timing_path, "public", public)
    index["sources"].append(timing_source)
    seen = set()
    for i, row in enumerate(timing):
        identity = row["choice_id"]
        if identity not in choices or identity in seen:
            raise ValueError("Unknown or duplicate timed decision")
        seen.add(identity)
        choice = choices[identity]
        latency = _number(row["wall_clock_latency_s"], "policy computation latency")
        if latency < 0 or row["simulation_time_s"] != choice["time_s"]:
            raise ValueError("Decision timing does not match its committed boundary")
        choice["wall_clock_latency_s"] = latency
        choice["timing_status"] = row.get("status", "unrecorded")
        choice["timing_source_ref"] = _ref(timing_source, i + 1, "$")
    if seen != set(choices):
        raise ValueError("Every committed choice must have its measured computation latency")
    audit_path = public / "policy_audit.json"
    audit = _read(audit_path)
    if not isinstance(audit, list):
        raise ValueError("policy_audit.json must be an array")
    audit_source = _source(audit_path, "public", public)
    index["sources"].append(audit_source)
    seen_audit = set()
    for i, row in enumerate(audit):
        identity = row["choice_id"]
        choice = choices.get(identity)
        if choice is None or identity in seen_audit:
            raise ValueError("Unknown or duplicate audited choice")
        seen_audit.add(identity)
        if (row["simulation_time_s"] != choice["time_s"]
                or row["context_sequence_id"] != choice["context_sequence_id"]):
            raise ValueError("Policy audit does not match its committed boundary")
        if (row["world_model"] != choice["world_belief"]
                or row["self_model"] != choice["self_model"]):
            raise ValueError("Policy audit state differs from its committed record")
        payload = {**row, "available_s": choice["time_s"],
                   "source_ref": _ref(audit_source, i + 1, "$")}
        index["public"]["policy_audit"].append(payload)
        choice["policy_audit"] = payload
    if seen_audit != set(choices):
        raise ValueError("Every committed choice requires its recorded policy audit")
    for i, row in enumerate(transcript["interaction"]["events"]):
        ref = _ref(trace_source, 1, f"transcript.interaction.events[{i}]")
        if row["kind"] == "information_started":
            pending = row["pending"]
            request = pending["request"]
            committed = next(
                d for d in choices.values()
                if d["kind"] == "information"
                and d["request"]["request_id"] == request["request_id"]
            )
            payload = {
                "request": request, "phase": "requested",
                "available_s": committed["time_s"],
                "pause_started_s": pending["observation"]["t_deliver_s"],
                "started_utc": pending["started_utc"], "source_ref": ref,
            }
            index["public"]["exchanges"].append(payload)
            _event(index, "ask-" + request["request_id"], "INFORMATION", "question",
                   committed["time_s"], ref, payload)
        elif row["kind"] == "information_completed":
            receipt = row["receipt"]
            payload = {**receipt, "phase": "completed",
                       "available_s": receipt["simulation_time_s"], "source_ref": ref}
            index["public"]["exchanges"].append(payload)
            _event(index, "reply-" + receipt["request"]["request_id"], "INFORMATION", "reply",
                   receipt["simulation_time_s"], ref, payload)
    verification_path = public / "verification.json"
    verifications = _read(verification_path)
    if not isinstance(verifications, list):
        raise ValueError("verification.json must be an array")
    source = _source(verification_path, "public", public)
    index["sources"].append(source)
    observations = {row["sequence_id"]: row for row in recorded}
    for i, row in enumerate(verifications):
        choice = choices.get(row["choice_id"])
        if choice is None or choice["kind"] != "physical":
            raise ValueError("Verification must identify a physical committed choice")
        if row["prediction"] not in choice["decision"]["predictions"]:
            raise ValueError("Verification prediction was not precommitted")
        ref = _ref(source, i + 1, "$")
        predicted = _number(row["predicted_capture_s"], "prediction target")
        expected = choice["time_s"] + row["prediction"]["horizon_s"]
        if (abs(predicted - expected) > 1e-9
                or row.get("committed_s", choice["time_s"]) != choice["time_s"]):
            raise ValueError("Verification must preserve its precommitted horizon and boundary")
        if row["capture_s"] is None:
            missing = ("available_s", "delivery_s", "observed", "residual",
                       "observation_sequence_id")
            if any(row[name] is not None for name in missing) or row["passed"] is not False:
                raise ValueError("Missing prediction outcome cannot have observed evidence or pass")
            payload = {**row, "source_ref": ref, "available_s": index["duration_s"],
                       "availability_rule": "Missing-outcome finding available at episode end",
                       "outcome_status": "missing"}
            index["public"]["verifications"].append(payload)
            _event(index, f"verification-{i}", "VERIFY", "prediction_outcome_missing",
                   index["duration_s"], ref, payload)
            continue
        when = _number(row["available_s"], "verification availability")
        captured = _number(row["capture_s"], "verification capture")
        predicted = _number(row["predicted_capture_s"], "prediction target")
        expected = choice["time_s"] + row["prediction"]["horizon_s"]
        if abs(predicted - expected) > 1e-9 or abs(captured - predicted) > 1e-9:
            raise ValueError("Verification capture must match its precommitted horizon")
        observed = observations.get(row["observation_sequence_id"])
        if observed is None or observed["t_deliver_s"] != when:
            raise ValueError("Verification must reference an available observation")
        if not choice["time_s"] < captured <= row["delivery_s"] <= when:
            raise ValueError("Verification timing cannot precede commitment or sensor delivery")
        action_id = row["prediction"]["action_id"]
        terminals = [f["t_terminal_s"] for o in recorded for f in o.get("feedback", [])
                     if f["action_id"] == action_id and f["code"] == "completed"
                     and f.get("t_terminal_s") is not None]
        terminal = terminals[-1] if terminals else None
        if row["fresh_after_s"] != terminal:
            raise ValueError("Verification freshness must bind its own completed action terminal")
        if row.get("freshness_action_id", action_id) != action_id:
            raise ValueError("Verification freshness action must match prediction action")
        fresh = terminal is not None and captured > terminal
        matches = [s for s in observed["scalars"] if (
            s["channel"] == row["prediction"]["channel"]
            and s["t_capture_s"] == captured and s["t_deliver_s"] == row["delivery_s"]
            and s["validity"] == "valid" and s["value"] == row["observed"]
        )]
        if len(matches) != 1:
            raise ValueError("Verification observed value must match exactly one public sample")
        residual = _number(row["observed"], "observed value") - row["prediction"]["mean"]
        tolerance = _number(row["tolerance"], "verification tolerance")
        if tolerance < 0 or abs(residual - row["residual"]) > 1e-9:
            raise ValueError("Verification residual is inconsistent")
        if row["passed"] is not (abs(residual) <= tolerance and fresh):
            raise ValueError("Verification passed flag is inconsistent")
        ref = _ref(source, i + 1, "$")
        payload = {**row, "source_ref": ref}
        index["public"]["verifications"].append(payload)
        _event(index, f"verification-{i}", "VERIFY", "prediction_check", captured,
               ref, payload, available=when)
    assessment_path = public / "assessment.json"
    if assessment_path.is_file():
        assessment = _read(assessment_path)
        source = _source(assessment_path, "public", public)
        index["sources"].append(source)
        index["public"]["assessment"] = {
            "available_s": index["duration_s"], "record": assessment,
            "source_ref": _ref(source, 1, "$"),
        }
    index["events"].sort(key=lambda e: (e["time_s"], e["stable_sequence"]))
    validate_presentation_events(index["events"])
    index["limitations"] = [
        "Numeric synthetic episode; RGB was not acquired when the retained frame list is empty.",
        "Adaptive arm is deterministic within-episode goal-based selection; no LLM or training.",
        "Information replies are authored recorded/simulated sources, not live human or web calls.",
        "External waiting uses wall time while physics is paused; no energy accrues during it.",
        "3D uses separately labelled evaluator geometry and last retained actual camera pose.",
        "A time cursor includes all recorded events at that simulation instant; tied events "
        "retain order in the inspector. A stationary wall-time pause is shown as a record.",
    ]
    return index


def build_comparison_index(manifest_path: Path, *, evaluator: bool = True) -> dict:
    """Build from a root-owned paired manifest with R/A public/evaluator directories."""
    manifest_path = Path(manifest_path).resolve()
    manifest = _read(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("Unsupported paired manifest schema")
    root = manifest_path.parent
    result = {
        "schema_version": SCHEMA,
        "title": "PV investigation: procedure and adaptive choices",
        "export_kind": "evaluator_contains_private_data" if evaluator else "public_only",
        "cases": [],
        "sources": [],
        "limitations": [
            "Matched executed numeric episodes; this viewer does not execute control actions.",
            "Common absolute simulation time; wall-time waits are recorded separately.",
            "No general agent superiority is implied by four authored deterministic cases.",
            "Case outcome summaries are withheld until the end of the displayed episode.",
        ],
    }
    seen = set()
    if evaluator:
        result["sources"].append(_source(manifest_path, "private_evaluator", root))
    for row in manifest["cases"]:
        identity = row["case_id"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Case IDs must be nonempty and unique")
        seen.add(identity)
        if set(row["arms"]) != set(ARMS):
            raise ValueError("Every comparison case requires exactly R and A")
        case = {"case_id": identity, "label": identity, "arms": {}}
        if evaluator:
            case["evaluator_label"] = row.get("label", identity)
        for arm, descriptor in row["arms"].items():
            public = (root / descriptor["public_dir"]).resolve()
            private = ((root / descriptor["evaluator_dir"]).resolve()
                       if evaluator and descriptor.get("evaluator_dir") else None)
            episode = _episode(public, private, arm)
            summary_path = descriptor.get("summary_path")
            if evaluator and summary_path:
                path = (root / summary_path).resolve()
                source = _source(path, "private_evaluator", path.parent)
                summary = _read(path)
                if summary.get("case_id") != identity or summary.get("arm") != arm:
                    raise ValueError("Evaluator result does not match its case and arm")
                episode["sources"].append(source)
                episode.setdefault("evaluator", {})["result"] = {
                    "available_s": episode["duration_s"], "record": summary,
                    "source_ref": _ref(source, 1, "$"),
                }
            if private is not None:
                bound = [s for s in episode["sources"]
                         if s["file"] not in ("manifest.json", "manifest.sha256")]
                pairing, _ = _verify_pairing(private, episode["episode_id"], bound)
                episode["evaluator"]["pairing"] = pairing
            case["arms"][arm] = episode
        tasks = [dict(e["public"]["task"]) for e in case["arms"].values()]
        for task in tasks:
            task.pop("episode_id", None)
        if tasks[0] != tasks[1]:
            raise ValueError("Paired arms must share the same public task and capabilities")
        if case["arms"]["R"]["public"]["brief"] != case["arms"]["A"]["public"]["brief"]:
            raise ValueError("Paired arms must share the same authorized public prior")
        if evaluator:
            summaries = [e.get("evaluator", {}).get("result", {}).get("record")
                         for e in case["arms"].values()]
            if all(summaries):
                for key in ("config_sha256", "seed"):
                    if summaries[0].get(key) != summaries[1].get(key):
                        raise ValueError("Paired evaluator results must share config and seed")
        horizons = {e["public"]["task"]["horizon_s"] for e in case["arms"].values()}
        if len(horizons) != 1:
            raise ValueError("Paired arms must share the same declared simulation horizon")
        case["duration_s"] = max(e["duration_s"] for e in case["arms"].values())
        case["horizon_s"] = horizons.pop()
        result["cases"].append(case)
    if not result["cases"]:
        raise ValueError("At least one paired case is required")
    json.dumps(result, allow_nan=False)
    return result


def public_export(index: dict) -> dict:
    result = copy.deepcopy(index)
    result["export_kind"] = "public_only"
    result["sources"] = [s for s in result["sources"] if s["visibility"] == "public"]
    for case in result["cases"]:
        case.pop("evaluator_label", None)
        case["label"] = case["case_id"]
        case["arms"] = {arm: public_episode(episode) for arm, episode in case["arms"].items()}
    return result


def comparison_state(index: dict, case_id: str, time_s: float, *, evaluator=False) -> dict:
    case = next((c for c in index["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise ValueError("Unknown case ID")
    t = max(0.0, min(_number(time_s, "seek time"), case["duration_s"]))
    result = {"case_id": case_id, "time_s": t, "arms": {}}
    for arm, episode in case["arms"].items():
        state = replay_state(episode, t, evaluator=evaluator)
        for field in ("exchanges", "verifications", "policy_audit"):
            state[field] = [r for r in episode["public"][field] if r["available_s"] <= t + 1e-10]
        state["assessment"] = None
        assessment = episode["public"]["assessment"]
        if assessment and assessment["available_s"] <= t + 1e-10:
            state["assessment"] = assessment
        outcome = episode.get("evaluator", {}).get("result")
        if evaluator and outcome and outcome["available_s"] <= t + 1e-10:
            state["result"] = outcome
        result["arms"][arm] = state
    return result


def write_comparison(index: dict, output_html: Path) -> dict:
    template = Path(__file__).with_name("assets") / "comparison_viewer.html"
    encoded = json.dumps(index, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    encoded = encoded.replace("<", "\\u003c").replace("&", "\\u0026")
    rendered = template.read_text().replace("__COMPARISON_DATA__", encoded)
    output_html = Path(output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    with output_html.open("x", encoding="utf-8") as stream:
        stream.write(rendered)
    sources = list(index["sources"])
    for case in index["cases"]:
        for arm in case["arms"].values():
            sources.extend(arm["sources"])
    return {
        "schema_version": SCHEMA, "html": str(output_html),
        "html_sha256": sha256(output_html.read_bytes()),
        "builder_sha256": sha256(Path(__file__).read_bytes()),
        "base_builder_sha256": sha256(Path(__file__).with_name("workflow_replay.py").read_bytes()),
        "template_sha256": sha256(template.read_bytes()),
        "export_kind": index["export_kind"], "cases": len(index["cases"]),
        "sources": sources,
    }
