"""Retain one short numeric shared-decision fixture and its exact replay.

The driver is an authored script, not an adaptive agent. The single external
reply is simulated. No rendering, network access, training or hardware is used.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from pv_sim.config import Config, load_config
from pv_sim.contracts import ACTION_ADAPTER, Decision, Prediction
from pv_sim.env import PVEnv
from pv_sim.information_transport import RecordedExchange, RecordedTransport
from pv_sim.interaction_contracts import InformationReply, InformationSource, InteractionRequest
from pv_sim.investigation import (
    InformationChoice,
    InvestigationSession,
    PhysicalChoice,
    SelfModel,
    WorldBelief,
    load_investigation,
    replay_investigation,
)
from pv_sim.policies.protocol import matched_pairs
from pv_sim.recorder import runtime_metadata, sha256_file, source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def physical(session, identity, kind, rationale, *, prediction=None, refs=(), **fields):
    context = session.context()
    action = ACTION_ADAPTER.validate_python({
        "schema_version": "1.0", "action_id": context.next_action_id,
        "kind": kind, "timeout_s": 3.0, **fields,
    })
    expected = () if prediction is None else (Prediction(
        query_id=identity + "_voltage", action_id=action.action_id,
        channel="voltage_v",
        horizon_s=round(
            math.ceil((context.history[-1].t_deliver_s + 1.0) * 10) / 10
            - context.history[-1].t_deliver_s, 12,
        ),
        mean=prediction, sigma=None,
        interval_90=None, status="predicted",
    ),)
    return PhysicalChoice(
        choice_id=identity, context_sequence_id=context.history[-1].sequence_id,
        information_refs=refs,
        decision=Decision(
            schema_version="1.0", action=action, predictions=expected,
            hypothesis_probabilities=None,
            unresolved_hypotheses=context.task.hypothesis_classes,
            evidence_refs=(context.history[-1].sequence_id,), rationale=rationale,
        ),
    )


def run(output: Path):
    if output.is_absolute() or output.parent != Path("runs") or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", output.name
    ):
        raise ValueError("output must be a new direct child of runs with a safe name")
    dest = (ROOT / output).resolve()
    private = (ROOT / "private_eval" / output.name).resolve()
    if dest.parent != ROOT / "runs" or private.parent != ROOT / "private_eval":
        raise ValueError("evidence must remain inside the project")
    if dest.exists() or private.exists():
        raise FileExistsError("preserve existing evidence; choose a fresh output")
    dest.mkdir()
    private.mkdir()
    public = dest / "public"
    public.mkdir()
    report = {
        "schema_version": "investigation-fixture/1.0", "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Scripted shared-decision integration fixture; not adaptive or live.",
        "rendering": "disabled; no new camera image",
        "live_calls": 0, "training": False, "cross_episode_memory": False,
    }
    env = repeat = session = None
    try:
        raw = load_config(ROOT / "configs/pilot.toml").model_dump()
        raw["simulation"]["horizon_s"] = 8.0
        raw["budgets"]["time_s"] = 8.0
        config = Config.model_validate(raw)
        write_new(private / "config.json", json.loads(config.canonical_json()))
        write_new(private / "runtime.json", runtime_metadata())
        write_new(private / "episode.json", {"seed": 20261019, "episode_id": "bridge_asset"})
        inputs = source_fingerprint()
        inputs["scripts/validate_investigation.py"] = sha256_file(Path(__file__))
        for name in (
            "configs/pilot.toml", "configs/interaction_protocol.json",
            "schemas/agent_context.schema.json", "schemas/investigation_choice.schema.json",
            "schemas/investigation_transcript.schema.json",
            "tests/unit/test_investigation_contracts.py",
            "tests/unit/test_investigation_schema_exports.py",
            "tests/integration/test_investigation_session.py",
            "tests/security/test_investigation_boundary.py",
        ):
            inputs[name] = sha256_file(ROOT / name)
        write_new(private / "inputs.json", inputs)
        env = PVEnv(config, enable_rendering=False)
        _, initial = env.reset(20261019, episode_id="bridge_asset")
        session = InvestigationSession(env, initial)
        session.submit(physical(
            session, "observe", "wait", "Collect an ordinary delivered numeric sample.",
            duration_s=0.4,
        ))
        context = session.context()
        boundary = context.history[-1].sequence_id
        request = InteractionRequest(
            episode_id=context.task.episode_id, request_id="verification_guidance",
            channel="internet", question="How should a requested voltage be verified?",
            information_gap="An acknowledgement alone does not confirm applied voltage.",
            intended_decision="Use fresh measured voltage/current after the command.",
        )
        reply = InformationReply(
            outcome="available", provenance="simulated",
            text="Authored test guidance: require a valid fresh measured voltage after "
            "application; pair it with current at the same capture time.",
            sources=(InformationSource(title="Authored shared-decision fixture"),),
        )
        receipt = session.submit(InformationChoice(
            choice_id="ask", context_sequence_id=boundary, request=request,
            observation_refs=(boundary,),
            world_belief=WorldBelief(
                as_of_sequence_id=boundary,
                summary="The authored script has no causal diagnosis of panel condition.",
                information_gap="How to verify a requested operating point.",
                observation_refs=(boundary,),
            ),
            self_model=SelfModel(
                as_of_sequence_id=boundary,
                summary="Numeric sensing and bounded voltage control are advertised; "
                "RGB is absent.",
                unavailable_tools=("capture_rgb",), observation_refs=(boundary,),
            ),
        ), transport=RecordedTransport((RecordedExchange(request=request, reply=reply),)))
        if session.context().completed_information != (receipt,):
            raise AssertionError("completed reply was not supplied in the public context")
        setting = physical(
            session, "apply", "set_voltage", "Apply the authored 1.2 V test point; predict "
            "the measured voltage before dispatch, then verify it from new samples.",
            voltage_v=1.2, prediction=1.2, refs=(request.request_id,),
        )
        prediction_committed_at_s = session.context().history[-1].t_deliver_s
        predicted_capture_s = (
            prediction_committed_at_s + setting.decision.predictions[0].horizon_s
        )
        applied = session.submit(setting)
        set_terminal = applied.feedback[-1].t_terminal_s
        if applied.feedback[-1].code != "completed":
            raise AssertionError("set-voltage fixture did not complete")
        later = session.submit(physical(
            session, "verify", "wait", "Obtain newer matched V/I for the committed prediction.",
            duration_s=1.0, refs=(request.request_id,),
        ))
        pairs = [(v, i) for v, i in matched_pairs(later.scalars)
                 if v.t_capture_s > set_terminal
                 and abs(v.t_capture_s - predicted_capture_s) < 1e-9]
        if not pairs:
            raise AssertionError("no fresh matched verification after set completion")
        voltage, current = pairs[-1]
        residual = voltage.value - 1.2
        if abs(residual) > 0.02:
            raise AssertionError("measured voltage failed the predeclared tolerance")
        verification = {
            "choice_id": setting.choice_id,
            "prediction": setting.decision.predictions[0].model_dump(mode="json"),
            "prediction_committed_at_s": prediction_committed_at_s,
            "predicted_capture_s": predicted_capture_s,
            "action_terminal_s": set_terminal,
            "observation_sequence_id": later.sequence_id,
            "returned_at_s": later.t_deliver_s,
            "voltage_sample": voltage.model_dump(mode="json"),
            "current_sample": current.model_dump(mode="json"),
            "residual_v": residual, "absolute_tolerance_v": 0.02,
        }
        session.submit(physical(
            session, "finish", "finish", "The applied point is verified; causal diagnosis "
            "remains unresolved in this authored fixture.", resolution="unresolved",
        ))
        trace_path = public / "investigation.json"
        session.save(trace_path)
        write_new(public / "verification.json", verification)
        trace = load_investigation(trace_path)
        metrics = env.metrics()
        write_new(private / "metrics.json", metrics)
        repeat = PVEnv(config, enable_rendering=False)
        _, second_initial = repeat.reset(20261019, episode_id="bridge_asset")
        replay = replay_investigation(repeat, second_initial, trace)
        if repeat.metrics() != metrics:
            raise AssertionError("replay metrics differ from the original")
        if not metrics["verification_tail_complete"]:
            raise AssertionError("final verification tail incomplete")
        if env.backend._renderer is not None or repeat.backend._renderer is not None:
            raise AssertionError("numeric fixture unexpectedly initialized rendering")
        write_new(dest / "replay.json", replay)
        changed = [name for name, digest in inputs.items()
                   if sha256_file(ROOT / name) != digest]
        if changed:
            raise AssertionError(f"source changed during execution: {changed}")
        report.update({
            "status": "passed", "simulated_time_s": env.time_s,
            "information_requests": 1, "physical_choices": 4,
            "prediction_count": replay["full_predictions_retained"],
            "verification": verification, "replay": replay,
            "replay_metrics_equal": True, "inputs_unchanged": True,
            "transcript": str(trace_path.relative_to(ROOT)),
            "private_evidence": str(private.relative_to(ROOT)),
        })
        write_new(dest / "summary.json", report)
        write_new(private / "artifact-manifest.json", {
            "sha256": {str(p.relative_to(ROOT)): sha256_file(p)
                       for base in (dest, private) for p in sorted(base.rglob("*")) if p.is_file()}
        })
        return report
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        if session is not None and not (public / "investigation.json").exists():
            try:
                session.save(public / "investigation.json")
            except Exception as partial_error:
                report["partial_trace_error"] = type(partial_error).__name__
        if not (dest / "summary.json").exists():
            write_new(dest / "summary.json", report)
        raise
    finally:
        if repeat is not None:
            repeat.close()
        if env is not None:
            env.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
