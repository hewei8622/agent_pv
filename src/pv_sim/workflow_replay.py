"""Read-only presentation of retained evidence; this module never runs a simulator.

The public builder reads only explicitly supplied public files. Evaluator inputs are
opt-in and kept in a separate payload, not removed with a cosmetic UI toggle.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image

SCHEMA = "workflow_replay.v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _records(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = _json(path)
    if not isinstance(rows, list):
        raise ValueError(f"Expected an array of records: {path}")
    return rows


def _select(directory: Path, stem: str, required: bool = True) -> Path | None:
    for suffix in (".jsonl", ".json"):
        p = directory / (stem + suffix)
        if p.is_file():
            return p
    if required:
        raise FileNotFoundError(f"Missing {stem}.jsonl or {stem}.json in {directory}")
    return None


def _source(path: Path, visibility: str, directory: Path) -> dict:
    return {
        "file": path.relative_to(directory).as_posix(),
        "artifact_path": str(path),
        "sha256": sha256(path.read_bytes()),
        "visibility": visibility,
    }


def _ref(source: dict, row: int, field: str = "payload") -> dict:
    return {
        "file": source["file"],
        "sha256": source["sha256"],
        "row": row,
        "field": field,
        "visibility": source["visibility"],
    }


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Non-finite or missing {label}")
    return float(value)


def _availability(sample: dict, returned: float) -> float:
    capture = _number(sample["t_capture_s"], "capture time")
    delivery = _number(sample["t_deliver_s"], "delivery time")
    if capture < 0 or delivery < capture - 1e-9 or returned < delivery - 1e-9:
        raise ValueError("Capture / delivery / return times are inconsistent")
    return returned


def _feedback_timing(feedback: dict, returned: float) -> None:
    accepted, terminal = feedback.get("t_accepted_s"), feedback.get("t_terminal_s")
    for name, value in (("acceptance", accepted), ("terminal", terminal)):
        if value is not None:
            value = _number(value, f"feedback {name} time")
            if value < 0 or value > returned + 1e-9:
                raise ValueError(f"Feedback {name} time is later than return or negative")
    if accepted is not None and terminal is not None and accepted > terminal + 1e-9:
        raise ValueError("Feedback acceptance occurs after terminal time")
    for item in feedback.get("measured_confirmation", []):
        _availability(item["sample"], returned)


def _verify_pairing(directory: Path, episode_id: str, sources: list[dict]) -> tuple[dict, dict]:
    """Bind consumed streams to one completed original recorder manifest.

    Merely selecting two directories is not evidence that their clocks or episodes
    match. Unmanifested fixtures can be displayed public-only until a separately
    reviewed pairing format is implemented.
    """
    path = directory / "manifest.json"
    if not path.is_file():
        raise ValueError("Evaluator overlay requires a completed episode manifest for pairing")
    detached = directory / "manifest.sha256"
    if detached.is_file() and detached.read_text().strip() != sha256(path.read_bytes()):
        raise ValueError("Evaluator manifest detached SHA256 does not match")
    manifest = _json(path)
    if manifest.get("episode_id") != episode_id:
        raise ValueError("Evaluator manifest episode does not match the public task")
    if manifest.get("status") != "complete" or manifest.get("incomplete") is not False:
        raise ValueError("Evaluator overlay requires a completed episode manifest for pairing")
    entries = {}
    for artifact in manifest.get("artifacts", []):
        key = (artifact["scope"], artifact["path"])
        if key in entries:
            raise ValueError("Ambiguous duplicate artifact in evaluator manifest")
        entries[key] = artifact
    verified = set()
    for source in sources:
        is_public = source["visibility"] == "public"
        key = (
            "public" if is_public else "private",
            ("public/" if is_public else "") + source["file"],
        )
        recorded = entries.get(key)
        if recorded is None or recorded.get("sha256") != source["sha256"]:
            raise ValueError(f"Evaluator manifest artifact hash binding failed: {key[1]}")
        size = Path(source["artifact_path"]).stat().st_size
        if recorded.get("bytes") != size:
            raise ValueError(f"Evaluator manifest artifact byte count failed: {key[1]}")
        verified.add(key)
    source = _source(path, "private_evaluator", directory)
    return (
        {
            "episode_id": episode_id,
            "manifest_source_ref": _ref(source, 1, "$"),
            "verified_artifacts": len(verified),
            "rule": "Every consumed public and evaluator artifact matches one completed manifest",
        },
        source,
    )


def derive_power(samples: list[dict]) -> list[dict]:
    """Pair valid V/I at exactly equal capture times, without borrowing truth.

    Duplicate/conflicting channel samples at one capture are rejected as ambiguous.
    Availability is the later observation return, not the acquisition or delivery.
    """
    groups: dict[float, dict[str, dict]] = {}
    for s in samples:
        if s.get("validity") != "valid" or s.get("channel") not in {"voltage_v", "current_a"}:
            continue
        channels = groups.setdefault(s["capture_s"], {})
        if s["channel"] in channels:
            previous = channels[s["channel"]]
            if previous["value"] != s["value"]:
                raise ValueError("Conflicting samples at one capture cannot derive public power")
            if s["available_s"] >= previous["available_s"]:
                continue
        channels[s["channel"]] = s
    result = []
    for capture, channels in sorted(groups.items()):
        if set(channels) != {"voltage_v", "current_a"}:
            continue
        v, i = channels["voltage_v"], channels["current_a"]
        result.append(
            {
                "id": f"power-{len(result)}",
                "channel": "power_w",
                "value": v["value"] * i["value"],
                "capture_s": capture,
                "delivery_s": max(v["delivery_s"], i["delivery_s"]),
                "available_s": max(v["available_s"], i["available_s"]),
                "validity": "valid",
                "source_refs": [v["source_ref"], i["source_ref"]],
                "derivation": "P = V * I; valid public samples with identical capture time",
            }
        )
    return result


def replay_state(index: dict, time_s: float, *, evaluator: bool = False) -> dict:
    """Pure seek oracle, also used by tests. Future returns cannot enter public state."""
    t = max(0.0, min(_number(time_s, "seek time"), index["duration_s"]))
    public = index["public"]

    def visible(rows):
        return [r for r in rows if r["available_s"] <= t + 1e-10]

    frames = visible(public["frames"])
    observations = visible(public["observations"])
    decisions = visible(public["decisions"])
    valid_frames = [f for f in frames if f["validity"] == "valid" and f.get("data_url")]
    state = {
        "time_s": t,
        "samples": visible(public["samples"]),
        "power": visible(public["power"]),
        "encoders": visible(public["encoders"]),
        "frames": frames,
        "frame": valid_frames[-1] if valid_frames else None,
        "decisions": decisions,
        "decision": decisions[-1] if decisions else None,
        "observation": observations[-1] if observations else None,
        "events": [
            e
            for e in index["events"]
            if e["visibility"] == "public" and e["available_s"] <= t + 1e-10
        ],
    }
    if evaluator and index.get("evaluator"):
        rows = [r for r in index["evaluator"]["truth"] if r["time_s"] <= t + 1e-10]
        state["truth"] = rows[-1] if rows else None
        state["geometry"] = index["evaluator"]["geometry"]
    return state


def validate_presentation_events(events: list[dict]) -> None:
    """Minimal versioned event bridge for later coordinator records.

    A producer supplies original source refs and actual availability; this validator
    does not infer causal claims or create retrospective predictions.
    """
    ids = set()
    for event in events:
        if event["id"] in ids:
            raise ValueError("Duplicate presentation event ID")
        ids.add(event["id"])
        if event["visibility"] not in {"public", "private_evaluator", "annotation"}:
            raise ValueError("Invalid visibility")
        event_time = _number(event["time_s"], "event time")
        availability = _number(event["available_s"], "event availability")
        if event_time < 0 or availability < 0:
            raise ValueError("Presentation times must be nonnegative")
        if event["visibility"] == "public" and event_time > availability + 1e-9:
            raise ValueError("Public event occurs after its declared availability")
        if not event.get("source_ref", {}).get("sha256"):
            raise ValueError("Every presentation event must reference a hashed record")


def build_replay_index(
    public_dir: Path,
    *,
    evaluator_dir: Path | None = None,
    title: str = "PV investigation workflow",
    policy_label: str = "B1 fixed procedural scan",
) -> dict:
    public_dir = Path(public_dir).resolve()
    task_path = public_dir / "task.json"
    task = _json(task_path)
    obs_path = _select(public_dir, "observations")
    obs_records = _records(obs_path)
    obs_source = _source(obs_path, "public", public_dir)
    sources = [_source(task_path, "public", public_dir), obs_source]
    out = {
        "observations": [],
        "samples": [],
        "encoders": [],
        "frames": [],
        "decisions": [],
        "feedback": [],
        "actions": [],
        "task": task,
    }
    events = []
    tick_returns: dict[int, float] = {}
    observation_returns: dict[int, float] = {}

    def event(
        identifier: str,
        role: str,
        kind: str,
        time: float,
        available: float,
        ref: dict,
        payload: dict,
        visibility: str = "public",
    ) -> None:
        events.append(
            {
                "id": identifier,
                "role": role,
                "kind": kind,
                "time_s": time,
                "available_s": available,
                "source_ref": ref,
                "payload": payload,
                "visibility": visibility,
                "stable_sequence": len(events),
            }
        )

    for row, record in enumerate(obs_records, 1):
        o = record.get("payload", record)
        returned = _number(o["t_deliver_s"], "observation return")
        if returned < 0 or (observation_returns and returned < max(observation_returns.values())):
            raise ValueError("Observation returns must be monotonically nondecreasing")
        if o.get("episode_id", task["episode_id"]) != task["episode_id"]:
            raise ValueError("Observation episode does not match public task")
        ref = _ref(obs_source, row)
        sid = o["sequence_id"]
        if sid in observation_returns:
            raise ValueError("Duplicate observation sequence ID")
        observation_returns[sid] = returned
        if "tick" in record:
            if record["tick"] in tick_returns:
                raise ValueError("Ambiguous duplicate observation tick for issue-time mapping")
            tick_returns[record["tick"]] = returned
        summary = {
            "id": sid,
            "available_s": returned,
            "remaining_budgets": o["remaining_budgets"],
            "terminal": o.get("terminal", False),
            "source_ref": ref,
        }
        out["observations"].append(summary)
        event(
            f"observation-{sid}",
            "SENSOR",
            "observation_return",
            returned,
            returned,
            ref,
            {
                "observation_id": sid,
                "scalars": len(o.get("scalars", [])),
                "frames": len(o.get("rgb", [])),
                "remaining_budgets": o["remaining_budgets"],
            },
        )
        for j, s in enumerate(o.get("scalars", [])):
            available = _availability(s, returned)
            out["samples"].append(
                {
                    "id": f"o{sid}-scalar-{j}",
                    "channel": s["channel"],
                    "value": (
                        None
                        if s.get("value") is None and s["validity"] != "valid"
                        else _number(s["value"], "sample value")
                    ),
                    "validity": s["validity"],
                    "sigma": s.get("sigma"),
                    "capture_s": s["t_capture_s"],
                    "delivery_s": s["t_deliver_s"],
                    "available_s": available,
                    "source_ref": _ref(obs_source, row, f"payload.scalars[{j}]"),
                }
            )
        for j, s in enumerate(o.get("encoders", [])):
            out["encoders"].append(
                {
                    **s,
                    "capture_s": s["t_capture_s"],
                    "delivery_s": s["t_deliver_s"],
                    "available_s": _availability(s, returned),
                    "source_ref": _ref(obs_source, row, f"payload.encoders[{j}]"),
                }
            )
        for j, f in enumerate(o.get("rgb", [])):
            frame = {
                **f,
                "capture_s": f["t_capture_s"],
                "delivery_s": f["t_deliver_s"],
                "available_s": _availability(f, returned),
                "source_ref": _ref(obs_source, row, f"payload.rgb[{j}]"),
            }
            filename = f.get("png_file")
            frame["asset_status"] = "unavailable"
            if filename:
                asset = (public_dir / filename).resolve()
                if not asset.is_relative_to(public_dir):
                    raise ValueError("Frame asset escapes the public artifact directory")
                if asset.is_file():
                    blob = asset.read_bytes()
                    if sha256(blob) != f.get("png_sha256"):
                        raise ValueError(f"Frame hash mismatch: {filename}")
                    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError("Frame is not a PNG")
                    with Image.open(io.BytesIO(blob)) as image:
                        if image.size != (f["width"], f["height"]) or image.mode != "RGB":
                            raise ValueError(
                                "Frame dimensions or RGB encoding do not match metadata"
                            )
                        image.verify()
                    frame["data_url"] = "data:image/png;base64," + base64.b64encode(blob).decode()
                    frame["asset_status"] = "hash_verified_original_bytes"
                    sources.append(_source(asset, "public", public_dir))
            out["frames"].append(frame)
            for kind, when in (
                ("capture", frame["capture_s"]),
                ("delivery", frame["delivery_s"]),
                ("available", returned),
            ):
                event(
                    f"frame-{frame['frame_id']}-{kind}",
                    "SENSOR",
                    f"rgb_{kind}",
                    when,
                    returned,
                    frame["source_ref"],
                    {
                        "frame_id": frame["frame_id"],
                        "capture_s": frame["capture_s"],
                        "delivery_s": frame["delivery_s"],
                        "available_s": returned,
                        "validity": frame["validity"],
                    },
                )
        for j, feedback in enumerate(o.get("feedback", [])):
            _feedback_timing(feedback, returned)
            f = {
                **feedback,
                "available_s": returned,
                "source_ref": _ref(obs_source, row, f"payload.feedback[{j}]"),
            }
            out["feedback"].append(f)
            if f.get("t_terminal_s") is not None:
                when = f["t_terminal_s"]
                basis = "recorded terminal time"
            elif f["code"] == "accepted" and f.get("t_accepted_s") is not None:
                when = f["t_accepted_s"]
                basis = "recorded acceptance time; agent learns at observation return"
            elif f.get("measured_confirmation"):
                when = max(item["sample"]["t_capture_s"] for item in f["measured_confirmation"])
                basis = "latest confirmation capture; original progress-emission time unknown"
            else:
                when = returned
                basis = "observation return; original progress-emission time unknown"
            event(
                f"feedback-{sid}-{j}",
                "INTERFACE",
                f"action_{f['code']}",
                when,
                returned,
                f["source_ref"],
                feedback,
            )
            events[-1]["time_basis"] = basis
    out["power"] = derive_power(out["samples"])
    for stem in ("decisions", "actions"):
        p = _select(public_dir, stem, required=False)
        if p is None:
            continue
        source = _source(p, "public", public_dir)
        sources.append(source)
        for row, record in enumerate(_records(p), 1):
            payload = record.get("payload", record)
            tick = record.get("tick")
            if tick not in tick_returns:
                raise ValueError(
                    f"Cannot derive {stem} issue time from matching public return tick"
                )
            issue = tick_returns[tick]
            ref = _ref(source, row)
            if stem == "decisions":
                decision = payload["decision"]
                if any(
                    observation_returns[r] > issue + 1e-9 for r in decision.get("evidence_refs", [])
                ):
                    raise ValueError("Decision references a future observation")
                d = {
                    **decision,
                    "id": decision["action"]["action_id"],
                    "available_s": issue,
                    "time_s": issue,
                    "source_ref": ref,
                    "wall_clock_latency_s": payload.get("wall_clock_latency_s"),
                    "failure": payload.get("failure"),
                    "time_rule": "issue tick equals a retained public observation-return tick",
                }
                out["decisions"].append(d)
                event(f"decision-{d['id']}", "PROCEDURE", "decision", issue, issue, ref, d)
            else:
                action = json.loads(payload["raw_json"]) if "raw_json" in payload else payload
                a = {"action": action, "time_s": issue, "available_s": issue, "source_ref": ref}
                out["actions"].append(a)
                event(
                    f"command-{action['action_id']}",
                    "INTERFACE",
                    "command_issued",
                    issue,
                    issue,
                    ref,
                    action,
                )
    index = {
        "schema_version": SCHEMA,
        "title": title,
        "policy_label": policy_label,
        "episode_id": task["episode_id"],
        "export_kind": "public_only",
        "duration_s": max(o["available_s"] for o in out["observations"]),
        "public": out,
        "events": events,
        "sources": sources,
        "limitations": [
            "Read-only replay; no control commands or new simulation.",
            "Retained procedural episode; no adaptive-agent comparison is claimed.",
            "B1 checks image presence, not pixel content. Missing predictions stay missing.",
            "Public evidence appears only at observation return; delivery can be earlier.",
            "Current public prior has camera calibration but no complete scene geometry.",
            "This replay has no external information exchange or cross-episode memory.",
        ],
    }
    if evaluator_dir is not None:
        directory = Path(evaluator_dir).resolve()
        config_path = directory / "config.json"
        truth_path = _select(directory, "truth")
        config = _json(config_path)
        truth_source = _source(truth_path, "private_evaluator", directory)
        config_source = _source(config_path, "private_evaluator", directory)
        sources.extend([truth_source, config_source])
        pairing, manifest_source = _verify_pairing(directory, task["episode_id"], sources)
        sources.append(manifest_source)
        detached = directory / "manifest.sha256"
        if detached.is_file():
            detached_source = _source(detached, "private_evaluator", directory)
            sources.append(detached_source)
            pairing["detached_hash_source_ref"] = _ref(detached_source, 1, "$")
        truth = []
        for row, record in enumerate(_records(truth_path), 1):
            p = record.get("payload", record)
            truth.append(
                {
                    "time_s": p["time_s"],
                    "voltage_v": p["point"]["voltage_v"],
                    "current_a": p["point"]["current_a"],
                    "power_w": p["point"]["power_w"],
                    "temperature_c": p["temperature_c"],
                    "reference_w_m2": p["reference_w_m2"],
                    "requested_voltage_v": p["requested_voltage_v"],
                    "applied_voltage_v": p["applied_voltage_v"],
                    "camera_position_m": p["dynamics"]["camera_position_m"],
                    "camera_rotation": p["dynamics"]["camera_rotation"],
                    "q": p["dynamics"]["q"],
                    "source_ref": _ref(truth_source, row),
                }
            )
        index["evaluator"] = {
            "pairing": pairing,
            "truth": truth,
            "geometry": config["private_world"],
            "camera": config["camera"],
            "geometry_source_ref": _ref(config_source, 1, "private_world"),
            "pose_rule": "Last retained true pose at or before cursor; no interpolation.",
            "visibility": "private_evaluator",
            "source_schedule": config.get("source_schedule"),
        }
        previous = None
        for r in truth:
            if previous is not None and r["reference_w_m2"] != previous:
                event(
                    f"world-source-{r['time_s']}",
                    "WORLD",
                    "reference_truth_change",
                    r["time_s"],
                    r["time_s"],
                    r["source_ref"],
                    {"before_w_m2": previous, "after_w_m2": r["reference_w_m2"]},
                    "private_evaluator",
                )
            previous = r["reference_w_m2"]
        index["export_kind"] = "evaluator_contains_private_data"
    index["events"] = sorted(events, key=lambda e: (e["time_s"], e["stable_sequence"]))
    validate_presentation_events(index["events"])
    json.dumps(index, allow_nan=False)
    return index


def public_export(index: dict) -> dict:
    """Create an actual separate payload. All evaluator fields and refs are omitted."""
    result = copy.deepcopy(index)
    result.pop("evaluator", None)
    result["export_kind"] = "public_only"
    result["sources"] = [s for s in result["sources"] if s["visibility"] == "public"]
    result["events"] = [e for e in result["events"] if e["visibility"] == "public"]
    return result


def write_replay(index: dict, output_html: Path) -> dict:
    template = Path(__file__).with_name("assets") / "workflow_viewer.html"
    data = json.dumps(index, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    # Prevent a recorded string from ending the inert JSON script block.
    data = data.replace("<", "\\u003c").replace("&", "\\u0026")
    rendered = template.read_text().replace("__WORKFLOW_DATA__", data)
    output_html = Path(output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    with output_html.open("x") as stream:
        stream.write(rendered)
    return {
        "schema_version": SCHEMA,
        "html": str(output_html),
        "html_sha256": sha256(output_html.read_bytes()),
        "template_sha256": sha256(template.read_bytes()),
        "builder_sha256": sha256(Path(__file__).read_bytes()),
        "export_kind": index["export_kind"],
        "events": len(index["events"]),
        "frames": len(index["public"]["frames"]),
        "power_pairs": len(index["public"]["power"]),
        "sources": index["sources"],
    }
