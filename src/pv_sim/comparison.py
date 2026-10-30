"""Frozen, paired development experiment with independent public-evidence scoring.

This runner owns private cases. Policies receive only a public brief and cloned
AgentContext. It measures synchronous computation; it cannot interrupt hostile
or non-returning Python. All scheduled outcomes, including failures, are retained.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from pv_sim.comparison_sources import (
    SOURCE_TITLE,
    ControlledServiceSource,
    PublicBrief,
    ServiceCorpus,
    ServiceEnvelope,
)
from pv_sim.config import Config, load_config
from pv_sim.env import PVEnv
from pv_sim.investigation import (
    InformationChoice,
    InvestigationSession,
    PhysicalChoice,
    load_investigation,
    replay_investigation,
)
from pv_sim.recorder import ROOT, Recorder, canonical_json, runtime_metadata, sha256_file

VERSION = "paired_investigation.v1"
POLICY_DEADLINE_S = 30.0


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def write_new(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def runtime_inputs():
    # Presentation/report code does not execute in either policy or simulator.
    paths = [p for p in (ROOT / "src/pv_sim").rglob("*.py")
             if p.name not in ("comparison_viewer.py", "workflow_replay.py")]
    paths += [ROOT / name for name in (
        "configs/pilot.toml", "configs/interaction_protocol.json",
        "configs/investigation_experiment_v1.json", "configs/tolerances.toml",
        "uv.lock", "pyproject.toml",
        "scripts/run_paired_investigation.py",
    )]
    return {str(p.relative_to(ROOT)): sha256_file(p) for p in sorted(paths)}


def default_cases():
    raw = load_config(ROOT / "configs/pilot.toml").model_dump(mode="json")
    raw["simulation"]["horizon_s"] = 16.0
    raw["budgets"]["time_s"] = 16.0
    cases = []
    for name, label, known, instruction, changed in (
        ("C01", "Unchanged, known hold instruction", "hold", "hold", False),
        ("C02", "Incident-light reduction, known hold instruction", "hold", "hold", True),
        ("C03", "Unknown service context: hold reply", None, "hold", False),
        ("C04", "Unknown service context: survey reply", None, "survey", False),
    ):
        config = json.loads(canonical_json(raw))
        if changed:
            config["source_schedule"] = [{"time_s": 2.0, "dni_w_m2": 400.0}]
        config = Config.model_validate_json(canonical_json(config))
        brief = PublicBrief(known_instruction=known)
        cases.append({
            "case_id": name, "label": label, "seed": 20261019,
            "config": json.loads(config.canonical_json()), "config_sha256": config.sha256(),
            "public_brief": brief.model_dump(mode="json"),
            "source_corpus": ServiceCorpus(instruction=instruction).model_dump(mode="json"),
            "expected": {"source_drop": changed, "instruction": instruction},
        })
    return cases


def freeze_experiment(path: Path):
    inputs = runtime_inputs()
    body = {
        "schema_version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Four paired deterministic development cases, not held-out or live",
        "mechanisms": {
            "R": "Competent frozen procedural reference with measured branches",
            "A": "Deterministic goal-driven planner; within-episode symbolic belief revision",
            "model_provider": None, "language_model": False, "training": False,
            "cross_episode_memory": False, "image_interpretation": False,
        },
        "inputs": inputs, "runtime": runtime_metadata(), "cases": default_cases(),
        "arms": ["R", "A"], "repetitions_per_case_arm": 1,
        "policy_deadline_s": POLICY_DEADLINE_S,
        "timing_rule": "Synchronous public-context validation, policy and output validation; "
        "reject overruns on return before dispatch; no hard preemption",
        "rubric": {
            "voltage_tolerance_v": 0.02, "source_drop_threshold_w_m2": 100.0,
            "freshness": "matched valid V/I captured strictly after relevant action terminal",
            "survey_selection": "greatest measured settled candidate V*I, tie by first candidate",
            "prediction": "precommitted exact capture grid; missing outcomes fail prediction",
            "energy": "compare actual accumulated J only if both terminate at 16 s",
            "unchanged": "verified hold, no false source alarm or unnecessary query/probe",
            "source_step": "local incident-light reduction claim, verified hold, no query/probe",
            "context_hold": "query current context, verified hold, no survey",
            "context_survey": "query current context, measured selection and fresh verification",
        },
    }
    write_new(path, {"sha256": digest(body), "experiment": body})
    return body


def read_freeze(path: Path):
    wrapped = json.loads(path.read_text())
    body = wrapped["experiment"]
    if digest(body) != wrapped["sha256"]:
        raise ValueError("experiment freeze checksum mismatch")
    changed = [name for name, checksum in body["inputs"].items()
               if sha256_file(ROOT / name) != checksum]
    if changed:
        raise ValueError(f"frozen execution inputs changed: {changed}")
    runtime = runtime_metadata()
    if any(runtime[key] != body["runtime"][key]
           for key in ("python", "platform", "machine", "libraries")):
        raise ValueError("frozen Python/platform/library runtime differs")
    return body


def choose_timed(session, policy, *, clock=time.perf_counter, deadline=POLICY_DEADLINE_S):
    before = clock()
    choice = session.choose(policy)
    elapsed = clock() - before
    if not math.isfinite(elapsed) or elapsed < 0:
        raise RuntimeError("invalid computation clock")
    if elapsed > deadline:
        error = TimeoutError("policy computation exceeded the declared boundary deadline")
        error.latency_s = elapsed
        raise error
    return choice, elapsed


def observations(trace):
    found = {trace.interaction.initial_observation.sequence_id:
             trace.interaction.initial_observation}
    for event in trace.interaction.events:
        obs = (getattr(event, "observation", None) or
               getattr(getattr(event, "pending", None), "observation", None))
        if obs is not None:
            found[obs.sequence_id] = obs
    return tuple(found[k] for k in sorted(found))


def public_pairs(history):
    """Independent scorer: do not reuse policy's measurement selection helper."""
    pairs = []
    for obs in history:
        samples = {}
        for sample in obs.scalars:
            if sample.validity == "valid" and sample.value is not None:
                if sample.t_capture_s <= sample.t_deliver_s <= obs.t_deliver_s + 1e-9:
                    samples[(sample.channel, sample.t_capture_s)] = sample
        for (channel, capture), voltage in samples.items():
            current = samples.get(("current_a", capture))
            if channel == "voltage_v" and current is not None:
                pairs.append((obs, voltage, current))
    return pairs


def prediction_checks(trace):
    history = observations(trace)
    pairs = public_pairs(history)
    checks = []
    for event in trace.events:
        if event.kind != "committed" or not isinstance(event.choice, PhysicalChoice):
            continue
        choice = event.choice
        for prediction in choice.decision.predictions:
            if prediction.status != "predicted" or prediction.mean is None:
                continue
            target_time = event.simulation_time_s + prediction.horizon_s
            samples = [(obs, s) for obs in history for s in obs.scalars
                       if s.channel == prediction.channel and s.validity == "valid"
                       and s.value is not None and abs(s.t_capture_s - target_time) < 1e-8
                       and s.t_capture_s <= s.t_deliver_s <= obs.t_deliver_s + 1e-9]
            matched = [(obs, s) for obs, s in samples if prediction.channel != "voltage_v"
                       or any(o.sequence_id == obs.sequence_id and v == s
                              for o, v, _ in pairs)]
            terminals = [f.t_terminal_s for o in history for f in o.feedback
                         if f.action_id == prediction.action_id
                         and f.t_terminal_s is not None and f.code == "completed"]
            fresh_after = terminals[0] if len(terminals) == 1 else None
            # Outcome's returned observation must be after the prediction commit.
            outcome = next(((o, s) for o, s in matched
                            if o.t_deliver_s > event.simulation_time_s), None)
            obs, sample = outcome if outcome else (None, None)
            residual = None if sample is None else sample.value - prediction.mean
            checks.append({
                "choice_id": choice.choice_id, "prediction": prediction.model_dump(mode="json"),
                "committed_s": event.simulation_time_s, "predicted_capture_s": target_time,
                "available_s": None if obs is None else obs.t_deliver_s,
                "capture_s": None if sample is None else sample.t_capture_s,
                "delivery_s": None if sample is None else sample.t_deliver_s,
                "observed": None if sample is None else sample.value,
                "residual": residual, "tolerance": 0.02, "fresh_after_s": fresh_after,
                "freshness_action_id": prediction.action_id,
                "passed": residual is not None and abs(residual) <= 0.02
                and fresh_after is not None and sample.t_capture_s > fresh_after,
                "observation_sequence_id": None if obs is None else obs.sequence_id,
            })
    return checks


def service_permission_at(trace, committed, brief):
    """Evaluate the attributed service record at the actual decision boundary."""
    if brief.known_instruction == "hold":
        return ("hold" if committed.simulation_time_s <= brief.instruction_valid_until_s
                else "unknown")
    values = set()
    for event in trace.interaction.events:
        if event.kind != "information_completed":
            continue
        receipt = event.receipt
        if (receipt.request.request_id not in committed.choice.information_refs
                or receipt.simulation_time_s > committed.simulation_time_s
                or receipt.observation_sequence_id > committed.choice.context_sequence_id):
            continue
        reply = receipt.reply
        if reply.outcome != "available" or [s.title for s in reply.sources] != [SOURCE_TITLE]:
            continue
        try:
            def unique(items):
                obj = {}
                for key, val in items:
                    if key in obj:
                        raise ValueError("duplicate field")
                    obj[key] = val
                return obj
            envelope = ServiceEnvelope.model_validate_json(json.dumps(
                json.loads(reply.text, object_pairs_hook=unique), allow_nan=False))
        except (ValueError, TypeError):
            continue
        for record in envelope.records:
            if not record.valid_from_s <= committed.simulation_time_s <= record.valid_until_s:
                return "unknown"
            values.add(record.instruction)
    return next(iter(values)) if len(values) == 1 else "unknown"


def survey_evidence(history, probe_choices, tolerance=0.02):
    """Accept one genuine settled measured result per declared candidate."""
    evidence = []
    valid = True
    for choice in probe_choices:
        action = choice.decision.action
        rows = [(o, f) for o in history for f in o.feedback if f.action_id == action.action_id]
        terminal = next((f.t_terminal_s for _, f in rows if f.code == "completed"), None)
        points = {}
        for obs, feedback in rows:
            if feedback.code != "executing":
                continue
            if feedback.commanded_target != action:
                valid = False
                continue
            samples = [item.sample for item in feedback.measured_confirmation]
            candidates = [(v, i) for v in samples for i in samples
                          if v.channel == "voltage_v" and i.channel == "current_a"
                          and v.validity == i.validity == "valid"
                          and v.value is not None and i.value is not None
                          and v.t_capture_s == i.t_capture_s
                          and feedback.t_accepted_s is not None and terminal is not None
                          and feedback.t_accepted_s < v.t_capture_s < terminal
                          and v.t_capture_s <= v.t_deliver_s <= obs.t_deliver_s + 1e-9
                          and i.t_capture_s <= i.t_deliver_s <= obs.t_deliver_s + 1e-9
                          and v in obs.scalars and i in obs.scalars]
            if len(candidates) != 1:
                valid = False
                continue
            voltage, current = candidates[0]
            targets = [v for v in action.voltages_v if abs(v - voltage.value) <= tolerance]
            if len(targets) != 1 or targets[0] in points:
                valid = False
                continue
            points[targets[0]] = {
                "target_voltage_v": targets[0], "voltage_v": voltage.value,
                "current_a": current.value, "power_w": voltage.value * current.value,
                "capture_s": voltage.t_capture_s, "available_s": obs.t_deliver_s,
                "observation_sequence_id": obs.sequence_id, "action_id": action.action_id,
            }
        if set(points) != set(action.voltages_v):
            valid = False
        evidence += [points[v] for v in action.voltages_v if v in points]
    return evidence, valid


def evaluate_episode(trace, assessment, metrics, expected, timing, audit, brief):
    all_history = observations(trace)
    # Use the last actual pre-dispatch assessment. Finish-tail samples cannot
    # retroactively justify a claimed successful operating decision.
    claim = audit[-1] if audit else {}
    claim_time = claim.get("simulation_time_s", -1)
    assessed = claim.get("assessment", {})
    history = tuple(o for o in all_history if o.t_deliver_s <= claim_time + 1e-9)
    choices = [e.choice for e in trace.events if e.kind == "committed"]
    physical = [c for c in choices if isinstance(c, PhysicalChoice)]
    probes = [c for c in physical if c.decision.action.kind == "probe_voltage"]
    requests = [c for c in choices if isinstance(c, InformationChoice)]
    reference = [(o, s) for o in history for s in o.scalars
                 if s.channel == "reference_w_m2" and s.validity == "valid"
                 and s.value is not None]
    measured_drop = bool(reference and reference[0][1].value - reference[-1][1].value > 100)
    claimed_drop = assessed.get("source_drop_detected")
    selected = 1.8
    candidate_evidence, points_valid = survey_evidence(history, probes)
    if expected["instruction"] == "survey" and candidate_evidence:
        selected = max(candidate_evidence, key=lambda x: x["power_w"])["target_voltage_v"]
    settings = [c for c in physical if c.decision.action.kind == "set_voltage"]
    relevant = settings[-1] if settings else (probes[-1] if probes else physical[0])
    terminal = next((f.t_terminal_s for o in history for f in o.feedback
                     if f.action_id == relevant.decision.action.action_id
                     and f.code == "completed"), None)
    confirmations = [(o, v, i) for o, v, i in public_pairs(history)
                     if terminal is not None and v.t_capture_s > terminal
                     and abs(v.value - selected) <= 0.02]
    def supports_claim(record, at_s):
        evidence = record.get("verification_evidence") or {}
        target = record.get("target_voltage_v")
        available_pairs = [(o, v, i) for o, v, i in public_pairs(history)
                           if o.t_deliver_s <= at_s + 1e-9]
        latest = max(available_pairs, key=lambda row: row[1].t_capture_s, default=None)
        receipt_times = [e.receipt.simulation_time_s for e in trace.interaction.events
                         if e.kind == "information_completed"
                         and e.receipt.simulation_time_s <= at_s]
        cutoff = max([terminal or 0, *receipt_times])
        return (isinstance(target, (int, float)) and abs(target - selected) <= 0.02
                and evidence.get("action_id") == relevant.decision.action.action_id
                and evidence.get("terminal_s") == terminal
                and latest is not None and latest[1].t_capture_s > cutoff
                and abs(latest[1].value - selected) <= 0.02
                and abs(latest[1].t_capture_s - evidence.get("capture_s", -1)) < 1e-9
                and any(o.sequence_id == evidence.get("observation_sequence_id")
                        and abs(v.t_capture_s - evidence.get("capture_s", -1)) < 1e-9
                        and o.t_deliver_s == evidence.get("available_at_s")
                        for o, v, _ in confirmations))
    claim_supported = supports_claim(assessed, claim_time)
    verified = claim_supported and bool(assessed.get("operational_verified"))
    expected_survey = expected["instruction"] == "survey"
    survey_valid = (not probes if not expected_survey else
                    len(probes) == 1 and len(candidate_evidence) == 3 and points_valid)
    false_completion = bool(assessed.get("operational_verified")) and not claim_supported
    unsupported = assessed.get("causal_resolution") not in ("unresolved", "incident_light_only")
    probe_commits = [e for e in trace.events if e.kind == "committed"
                     and isinstance(e.choice, PhysicalChoice)
                     and e.choice.decision.action.kind == "probe_voltage"]
    authorized = all(service_permission_at(trace, e, brief) == "survey" for e in probe_commits)
    errors = {
        "false_alarm": claimed_drop is True and not expected["source_drop"],
        "missed_source_change": expected["source_drop"] and claimed_drop is not True,
        "unsupported_attribution": unsupported,
        "false_completion": false_completion,
        "unauthorized_probe": bool(probes) and (not expected_survey or not authorized),
        "inappropriate_abstention": expected_survey and not probes,
        "unnecessary_query": expected.get("known_hold", False) and bool(requests),
    }
    predictions = prediction_checks(trace)
    normal_finish = (metrics.get("terminal_reason") == "finished"
                     and metrics.get("verification_tail_complete") is True)
    success = (normal_finish and verified and bool(survey_valid) and claimed_drop == measured_drop
               and not any(errors.values()) and bool(predictions)
               and all(p["passed"] for p in predictions))
    return {
        "supported_task_decision": bool(survey_valid) and not any(errors.values()),
        "fresh_verified_outcome": verified, "success": success,
        "appropriate_unresolved_outcome": verified and not unsupported,
        "errors": errors, "selected_measured_voltage_v": selected,
        "candidate_evidence": candidate_evidence,
        "verification_terminal_s": terminal,
        "first_fresh_capture_s": confirmations[0][1].t_capture_s if confirmations else None,
        "source_drop_measured": measured_drop, "source_drop_claimed": claimed_drop,
        "predictions": predictions,
        "claim_available_s": claim_time,
        "claim_assessment": assessed,
        "normal_verified_finish": normal_finish,
        "ready_at_s": next((a["simulation_time_s"] for a in audit
                             if a.get("assessment", {}).get("operational_verified")
                             and supports_claim(a["assessment"], a["simulation_time_s"])
                             and a["assessment"]["verification_evidence"]["available_at_s"]
                             <= a["simulation_time_s"]), None),
        "raw_costs": {
            "probe_points": metrics["voltage_points"], "frames": metrics["rgb_frames"],
            "slide_m": metrics["slide_path_m"],
            "angle_rad": metrics["yaw_path_rad"] + metrics["pitch_path_rad"],
            "external_requests": len(requests), "decisions": metrics["decisions"],
            "simulated_time_s": metrics["elapsed_s"],
            "computation_wall_s": sum(t["wall_clock_latency_s"] for t in timing),
            "external_wait_wall_s": sum(e.receipt.elapsed_wall_s for e in trace.interaction.events
                                        if e.kind == "information_completed"),
            "pv_energy_j": metrics["pv_energy_j"],
        },
    }


def run_episode(case, arm, output, private_root):
    from pv_sim.comparison_policies import AdaptiveInvestigationPolicy, FrozenReferencePolicy

    config = Config.model_validate_json(canonical_json(case["config"]))
    brief = PublicBrief.model_validate_json(canonical_json(case["public_brief"]))
    policy = (FrozenReferencePolicy if arm == "R" else AdaptiveInvestigationPolicy)(brief)
    source = ControlledServiceSource(ServiceCorpus.model_validate_json(
        canonical_json(case["source_corpus"])))
    recorder = Recorder(output, private_root=private_root,
                        metadata={"execution_protocol": "investigation/1.0"})
    env = PVEnv(config, enable_rendering=False, recorder=recorder)
    session = None
    timing = []
    result = {"case_id": case["case_id"], "arm": arm, "status": "running"}
    prequery = None
    try:
        _, initial = env.reset(case["seed"], episode_id="pv_asset")
        session = InvestigationSession(env, initial, investigation_recording=True)
        while not session.context().history[-1].terminal:
            context = session.context()
            choice, elapsed = choose_timed(session, policy)
            timing.append({"choice_id": choice.choice_id,
                           "simulation_time_s": context.history[-1].t_deliver_s,
                           "wall_clock_latency_s": elapsed, "status": "accepted"})
            if isinstance(choice, InformationChoice) and prequery is None:
                prequery = digest([o.model_dump(mode="json") for o in context.history])
            if isinstance(choice, PhysicalChoice):
                recorder.decision(choice.decision, elapsed)
            session.submit(
                choice, transport=source if isinstance(choice, InformationChoice) else None)
            if len(timing) >= 50:
                raise RuntimeError("bounded comparison choice limit exceeded")
        trace = session.transcript()
        assessment = policy.assessment(session.context())
        session.save(recorder.public_dir / "investigation.json")
        write_new(recorder.public_dir / "decision_timing.json", timing)
        write_new(recorder.public_dir / "policy_audit.json", policy.audit_log)
        write_new(recorder.public_dir / "assessment.json", assessment)
        write_new(recorder.public_dir / "public_brief.json", brief.model_dump(mode="json"))
        metrics = env.metrics()
        expected = {**case["expected"], "known_hold": brief.known_instruction == "hold"}
        evaluation = evaluate_episode(trace, assessment, metrics, expected, timing,
                                      policy.audit_log, brief)
        write_new(recorder.public_dir / "verification.json", evaluation["predictions"])
        repeated = PVEnv(config, enable_rendering=False)
        try:
            _, repeat_initial = repeated.reset(case["seed"], episode_id="pv_asset")
            replay = replay_investigation(repeated, repeat_initial, load_investigation(
                recorder.public_dir / "investigation.json"))
            equal = repeated.metrics() == metrics
        finally:
            repeated.close()
        if replay["status"] != "passed" or not equal:
            raise RuntimeError("recorded replay or final metric equality failed")
        result.update(status="complete", evaluation=evaluation, assessment=assessment,
                      replay=replay, replay_metrics_equal=equal,
                      prequery_local_history_sha256=prequery,
                      config_sha256=config.sha256(), seed=case["seed"])
        write_new(recorder.private_dir / "result.json", result)
        recorder.finish(metrics)
    except Exception as exc:
        if isinstance(exc, TimeoutError):
            timing.append({"choice_id": None, "simulation_time_s": env.time_s,
                           "wall_clock_latency_s": getattr(exc, "latency_s", 0.0),
                           "status": "latency_overrun"})
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        for name, value in (
            ("decision_timing.json", timing), ("policy_audit.json", policy.audit_log)
        ):
            if not (recorder.public_dir / name).exists():
                write_new(recorder.public_dir / name, value)
        if session is not None and not (recorder.public_dir / "investigation.json").exists():
            try:
                session.save(recorder.public_dir / "investigation.json")
            except Exception:
                pass  # original error and recorder evidence remain authoritative
        if not (recorder.private_dir / "result.json").exists():
            write_new(recorder.private_dir / "result.json", result)
        recorder.abort(type(exc).__name__, str(exc))
    finally:
        env.close()
        recorder.close()
    return result, recorder


def run_comparison(freeze_path: Path, output: Path):
    body = read_freeze(freeze_path)
    if output.exists():
        raise FileExistsError("preserve existing comparison; choose a new output")
    private_root = ROOT / "private_eval" / output.name
    if private_root.exists():
        raise FileExistsError("private companion already exists")
    output.mkdir(parents=True)
    private_root.mkdir(parents=True)
    write_new(output / "experiment-link.json", {
        "freeze": os.path.relpath(freeze_path, output), "sha256": sha256_file(freeze_path)})
    results = []
    manifest = {"schema_version": VERSION,
                "title": "PV investigation: procedural reference and goal-driven planner",
                "scope": body["scope"], "mechanisms": body["mechanisms"], "cases": []}
    for case in body["cases"]:
        entry = {"case_id": case["case_id"], "label": case["label"], "arms": {}}
        for arm in body["arms"]:
            read_freeze(freeze_path)
            result, recorder = run_episode(case, arm, output / f"{case['case_id']}-{arm}",
                                           private_root)
            results.append(result)
            entry["arms"][arm] = {
                "public_dir": os.path.relpath(recorder.public_dir, output),
                "evaluator_dir": os.path.relpath(recorder.private_dir, output),
                "summary_path": os.path.relpath(recorder.private_dir / "result.json", output),
            }
        manifest["cases"].append(entry)
    pairs = []
    for case in body["cases"]:
        arms = {r["arm"]: r for r in results if r["case_id"] == case["case_id"]}
        complete = all(r["status"] == "complete" for r in arms.values())
        costs = {a: r.get("evaluation", {}).get("raw_costs", {}) for a, r in arms.items()}
        horizon = complete and all(abs(c["simulated_time_s"] - 16) < 1e-9
                                   for c in costs.values())
        pairs.append({
            "case_id": case["case_id"], "complete": complete,
            "matched_physical_config": complete and arms["R"]["config_sha256"] ==
            arms["A"]["config_sha256"] and arms["R"]["seed"] == arms["A"]["seed"],
            "common_horizon_energy_eligible": horizon,
            "A_minus_R": {k: costs["A"][k] - costs["R"][k] for k in costs.get("R", {})
                          if k != "pv_energy_j" or horizon} if complete else {},
        })
    checks = {}
    for arm in body["arms"]:
        c3, c4 = (next(r for r in results if r["arm"] == arm and r["case_id"] == c)
                  for c in ("C03", "C04"))
        checks[arm] = (c3.get("prequery_local_history_sha256") is not None and
                       c3.get("prequery_local_history_sha256") ==
                       c4.get("prequery_local_history_sha256"))
    summary = {"schema_version": VERSION, "scope": body["scope"], "results": results,
               "pairs": pairs, "context_counterfactual_identical_prequery_history": checks,
               "live_calls": 0, "new_rgb_frames": 0, "held_out": False,
               "status": "complete" if all(r["status"] == "complete" for r in results)
               else "completed_with_failures", "inputs_unchanged": True}
    read_freeze(freeze_path)
    write_new(private_root / "comparison.json", summary)
    manifest["summary_path"] = os.path.relpath(private_root / "comparison.json", output)
    write_new(output / "paired_manifest.json", manifest)
    write_new(private_root / "artifact-index.json", {
        "sha256": {str(p.relative_to(ROOT)): sha256_file(p)
                   for folder in (output, private_root) for p in sorted(folder.rglob("*"))
                   if p.is_file()}})
    return summary
