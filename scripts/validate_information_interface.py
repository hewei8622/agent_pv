"""Retain a short Step 2 interface fixture and exact recorded replay.

Actual MuJoCo dynamics run without rendering. All replies are authored simulated
fixtures, including those tagged with the human/internet channel; there is no
human contact, network retrieval, adaptive AI policy or real-panel validation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pv_sim.config import Config, load_config
from pv_sim.contracts import Finish, ProbeVoltage
from pv_sim.env import PVEnv
from pv_sim.information_transport import RecordedExchange, RecordedTransport
from pv_sim.interaction import (
    InformationReceipt,
    InformationSession,
    PhysicalDecision,
    load_transcript,
    replay_interactions,
)
from pv_sim.interaction_contracts import (
    InformationReply,
    InformationSource,
    InteractionLimits,
    InteractionRequest,
)
from pv_sim.recorder import runtime_metadata, sha256_file, source_fingerprint

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261019
EPISODE = "interface_fixture_asset"
LOCAL_DELAY_S = 0.02


def _encoded(value):
    return json.dumps(value, indent=2, allow_nan=False) + "\n"


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(_encoded(value))


def _fixture_config():
    raw = load_config(ROOT / "configs/pilot.toml").model_dump()
    raw["simulation"]["horizon_s"] = 8.0
    raw["budgets"]["time_s"] = 8.0
    return Config.model_validate(raw)


def _exchanges():
    """Generic authored context: none of these replies encodes private truth."""
    rows = (
        (
            "context", "human", None,
            "What local observations could help choose another measurement?",
            "There is no independently verified local context.",
            "Decide whether a bounded electrical test would be useful.",
            "Authored hypothetical report: the surface appeared less bright briefly. "
            "This was only a visual impression and is not a measured cause of any change.",
        ),
        (
            "test_guidance", "internet", None,
            "How should a bounded voltage probe be checked using the public sensor records?",
            "An action acknowledgement alone does not establish the applied voltage.",
            "Choose how to verify a permitted voltage probe.",
            "Authored interface guidance: choose voltages inside the advertised limits, "
            "then inspect fresh voltage and current confirmations at the settled probe "
            "points. Guidance does not establish the current panel condition.",
        ),
        (
            "clarification", "human", "context",
            "Was the reported brightness impression instrumented or qualitative?",
            "The reliability of the earlier visual report is unclear.",
            "Decide whether the report can support a causal explanation.",
            "Authored hypothetical clarification: it was qualitative only, without an "
            "instrument or controlled viewpoint. It cannot distinguish an actual source "
            "change from an impression, so the cause remains unresolved.",
        ),
    )
    return tuple(
        RecordedExchange(
            request=InteractionRequest(
                episode_id=EPISODE, request_id=identity, channel=channel,
                parent_request_id=parent, question=question,
                information_gap=gap, intended_decision=decision,
            ),
            reply=InformationReply(
                outcome="available", provenance="simulated", text=answer,
                sources=(InformationSource(title="Authored Step 2 interface fixture"),),
            ),
        )
        for identity, channel, parent, question, gap, decision, answer in rows
    )


class _LocalTransport:
    """Count public requests; add a declared, actual 20 ms local fixture delay."""

    def __init__(self, exchanges):
        self._recorded = RecordedTransport(exchanges)
        self.calls = 0

    def request(self, request):
        self.calls += 1
        time.sleep(LOCAL_DELAY_S)
        return self._recorded.request(request)


def _pause_state(env):
    return copy.deepcopy({
        "tick": env.tick,
        "ledger": asdict(env.ledger),
        "dynamics": asdict(env.backend.snapshot()),
        "temperature_c": env.temperature_c,
        "point": asdict(env.point),
        "queue": env.clock._queue,
        "queue_serial": env.clock._serial,
        "delivered_scalars": env._latest_scalars,
        "delivered_encoder": env._latest_encoder,
        "buffer": env._buffer,
        "sequence": env._sequence,
    })


def _probe_check(observation):
    if observation.feedback[-1].code != "completed":
        raise AssertionError("bounded probe did not complete with restoration")
    points = [item for item in observation.feedback if item.code == "executing"]
    if len(points) != 2:
        raise AssertionError("expected two measured probe points")
    verified = []
    for point, target in zip(points, (1.2, 1.8), strict=True):
        samples = {item.sample.channel: item.sample for item in point.measured_confirmation}
        voltage, current = samples["voltage_v"], samples["current_a"]
        if (
            abs(voltage.value - target) > 1e-10
            or current.value < 0
            or voltage.t_capture_s != current.t_capture_s
            or voltage.t_capture_s <= point.t_accepted_s
            or voltage not in observation.scalars
            or current not in observation.scalars
        ):
            raise AssertionError("probe confirmation lacks fresh matched measured values")
        verified.append({
            "commanded_voltage_v": target,
            "measured_voltage_v": voltage.value,
            "measured_current_a": current.value,
            "t_capture_s": voltage.t_capture_s,
            "t_deliver_s": voltage.t_deliver_s,
        })
    return verified


def _paths(output: Path, artifact_root: Path):
    root = artifact_root.resolve()
    output = Path(output)
    if output.is_absolute():
        raise ValueError("output must be project-relative under runs")
    destination = (root / output).resolve()
    if destination.parent != root / "runs" or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", destination.name
    ):
        raise ValueError("output must be a new direct child of runs with a bounded safe name")
    private = (root / "private_eval" / destination.name).resolve()
    if private.parent != root / "private_eval":
        raise ValueError("private evidence companion must remain inside the project")
    if destination.exists() or private.exists():
        raise FileExistsError("output or private companion already exists; preserve prior evidence")
    return root, destination, private


def run_fixture(output: Path, *, artifact_root: Path = ROOT):
    """Run one original/replay pair; artifact_root permits isolated test storage."""
    root, output, private = _paths(output, artifact_root)
    output.mkdir(parents=True, exist_ok=False)
    env = repeat = session = None
    report = {
        "schema_version": "information-fixture/1.0",
        "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Short scripted interface fixture and replay; no complete policy pilot.",
        "driver": "fixed authored script; not an adaptive decision agent",
        "information_provenance": "simulated",
        "live_human_calls": 0,
        "live_internet_calls": 0,
        "rendering": "disabled explicitly; no images generated or camera claim",
        "physical_scope": "actual MuJoCo and simplified PV model; no real-panel calibration",
        "local_fixture_delay_s_per_request": LOCAL_DELAY_S,
        "wall_time_scope": "Real elapsed local computation and fixture delay, not human wait time.",
    }
    try:
        private.mkdir(parents=True, exist_ok=False)
        public = output / "public"
        public.mkdir()
        conf = _fixture_config()
        protocol_path = ROOT / "configs/interaction_protocol.json"
        protocol = InteractionLimits.model_validate_json(protocol_path.read_text())
        _write(private / "config.json", json.loads(conf.canonical_json()))
        _write(private / "episode.json", {"seed": SEED, "episode_id": EPISODE})
        inputs = source_fingerprint()
        for folder, patterns in (
            ("scripts", ("*information*.py", "*interaction*.py")),
            ("tests", ("*information*.py", "*interaction*.py")),
        ):
            for pattern in patterns:
                for path in (ROOT / folder).rglob(pattern):
                    inputs[str(path.relative_to(ROOT))] = sha256_file(path)
        inputs["configs/pilot.toml"] = sha256_file(ROOT / "configs/pilot.toml")
        inputs["configs/interaction_protocol.json"] = sha256_file(protocol_path)
        _write(private / "inputs.json", dict(sorted(inputs.items())))
        _write(private / "runtime.json", runtime_metadata())
        env = PVEnv(conf, enable_rendering=False)
        _, initial = env.reset(SEED, episode_id=EPISODE)
        session = InformationSession(env, initial)
        if protocol != session.limits:
            raise AssertionError("frozen interaction protocol differs from session limits")
        exchanges = _exchanges()
        transport = _LocalTransport(exchanges)

        # A real monotonic interval elapses while no physical step is running.
        # Keep the sensor queue and all state values, not just the displayed time.
        pending = session.begin(exchanges[0].request)
        frozen = _pause_state(env)
        wall_start = time.monotonic()
        first_reply = transport.request(exchanges[0].request)
        if session.poll() is not None or _pause_state(env) != frozen:
            raise AssertionError("local waiting changed physical state or timed out")
        observed_wait = time.monotonic() - wall_start
        first = session.complete(exchanges[0].request.request_id, first_reply)
        if _pause_state(env) != frozen or env.information_wait_pending:
            raise AssertionError("completion changed the frozen physical state")
        if first.simulation_time_s != pending.observation.t_deliver_s:
            raise AssertionError("completion advanced simulated time")
        retry_before = (_pause_state(env), transport.calls, session.transcript())
        retried = session.request(exchanges[0].request, transport)
        if retried != first or (_pause_state(env), transport.calls, session.transcript()) != (
            retry_before
        ):
            raise AssertionError("identical request retry repeated work or charged again")
        report["pause_check"] = {
            "status": "passed", "frozen_simulation_time_s": first.simulation_time_s,
            "observed_local_wait_s": observed_wait,
            "state_and_queue_exactly_unchanged": True,
            "additional_simulated_energy_j": 0.0,
        }
        report["retry_check"] = {
            "status": "passed", "cached_receipt_equal": True,
            "additional_transport_calls": 0, "additional_decisions": 0,
            "additional_simulated_ticks": 0, "additional_simulated_energy_j": 0.0,
        }
        for exchange in exchanges[1:]:
            receipt = session.request(exchange.request, transport)
            if not isinstance(receipt, InformationReceipt) or receipt.reply != exchange.reply:
                raise AssertionError("fixture reply was not retained exactly")
        refs = tuple(exchange.request.request_id for exchange in exchanges)
        measured = session.step(PhysicalDecision(
            action=ProbeVoltage(
                schema_version="1.0", action_id=1, kind="probe_voltage", timeout_s=3.0,
                voltages_v=(1.2, 1.8), dwell_s=0.2,
            ),
            information_refs=refs,
            interpretation="The context is uncertain. Follow the authored generic measurement "
            "guidance with two bounded probe points; verify measured voltage and current. "
            "This fixed fixture does not infer the cause of a panel condition.",
        ))
        confirmations = _probe_check(measured)
        before_finish = env.time_s
        final = session.step(PhysicalDecision(
            action=Finish(
                schema_version="1.0", action_id=2, kind="finish", timeout_s=2.0,
                resolution="unresolved",
            ),
            information_refs=refs,
            interpretation="The probe completed and returned to the original voltage, but "
            "the authored context does not establish a cause. Finish unresolved and retain "
            "the full physical verification tail.",
        ))
        metrics = env.metrics()
        if (
            final.terminal_reason != "finished"
            or not metrics["verification_tail_complete"]
            or abs(env.time_s - before_finish - 2.2) > 1e-10
            or env.time_s > 8.0
            or env.ledger.decisions != 5
            or transport.calls != 3
            or len(session.receipts) != 3
            or env.backend._renderer is not None
        ):
            raise AssertionError("fixture accounting, verification tail or scope mismatch")
        transcript_path = public / "interaction.json"
        digest = session.save(transcript_path)
        _write(private / "metrics.json", metrics)
        trace = load_transcript(transcript_path)
        repeat = PVEnv(conf, enable_rendering=False)
        _, repeated_initial = repeat.reset(SEED, episode_id=EPISODE)
        replay = replay_interactions(repeat, repeated_initial, trace)
        if repeat.metrics() != metrics or repeat.backend._renderer is not None:
            raise AssertionError("replay final metrics differ from the original fixture")
        _write(private / "replay-metrics.json", repeat.metrics())
        _write(output / "replay.json", replay)
        report.update({
            "status": "passed",
            "requests": 3,
            "request_channels": [exchange.request.channel for exchange in exchanges],
            "followup": {"request_id": "clarification", "parent_request_id": "context"},
            "transport_calls": transport.calls,
            "physical_decisions": 2,
            "total_decisions": env.ledger.decisions,
            "simulation_time_s": env.time_s,
            "original_information_elapsed_wall_s": sum(
                receipt.elapsed_wall_s for receipt in session.receipts
            ),
            "probe_verification": {
                "information_refs": refs, "action_id": 1,
                "result_observation_sequence_id": measured.sequence_id,
                "points": confirmations,
                "restoration_feedback": measured.feedback[-1].model_dump(mode="json"),
            },
            "finish_verification": {
                "action_id": 2, "result_observation_sequence_id": final.sequence_id,
                "resolution": "unresolved", "verification_tail_s": 2.0,
                "decision_overhead_s": 0.2, "complete": True,
            },
            "replay": replay,
            "replay_metrics_exactly_equal": True,
            "public_transcript": str(transcript_path.relative_to(root)),
            "canonical_transcript_sha256": digest,
            "transcript_file_sha256": sha256_file(transcript_path),
            "private_evidence": str(private.relative_to(root)),
            "configuration_sha256": conf.sha256(),
        })
        artifacts = {
            str(path.relative_to(root)): sha256_file(path)
            for directory in (output, private)
            for path in sorted(directory.rglob("*")) if path.is_file()
        }
        # Publish the success summary last. Its expected bytes are already in
        # the manifest, so a failed manifest write cannot leave a passed summary.
        artifacts[str((output / "summary.json").relative_to(root))] = hashlib.sha256(
            _encoded(report).encode("utf-8")
        ).hexdigest()
        _write(private / "artifact-manifest.json", {"sha256": artifacts})
        _write(output / "summary.json", report)
        return report
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        if session is not None and not (output / "public/interaction.json").exists():
            try:
                session.save(output / "public/interaction.json")
            except Exception as save_error:
                report["partial_transcript_error"] = type(save_error).__name__
        if not (output / "summary.json").exists():
            _write(output / "summary.json", report)
        raise
    finally:
        if repeat is not None:
            repeat.close()
        if env is not None:
            env.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_fixture(args.output)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
