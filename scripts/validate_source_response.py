#!/usr/bin/env python3
"""Record and validate the controlled source response; --render needs desktop GL."""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import source_response_reference as reference
from source_response_fixture import (
    PROTOCOL_PATH,
    ROOT,
    Trace,
    check_real_images,
    protocol,
    run_fixture,
    write_trace,
)

from pv_sim.recorder import runtime_metadata, sha256_file, source_fingerprint


def check_numeric(trace, ledger, *, changed):
    p = protocol()
    tolerance = p["tolerances"]
    kwargs = dict(duration_s=p["duration_s"], event_s=p["event_s"] if changed else None)
    coarse = reference.integrate(step_s=p["reference_step_s"], **kwargs)
    fine = reference.integrate(step_s=p["reference_refinement_step_s"], **kwargs)
    if len(trace.rows) != 4001 or [r["tick"] for r in trace.rows] != list(range(4001)):
        raise AssertionError("missing or repeated physical ticks")
    if len(coarse) != len(trace.rows) or len(fine) != len(coarse):
        raise AssertionError("independent reference sample grid differs")
    errors = {
        "current_a": 0.0,
        "power_w": 0.0,
        "temperature_c": 0.0,
        "reference_refinement_c": 0.0,
        "sensor_state": 0.0,
    }
    for row, expected, refined in zip(trace.rows, coarse, fine, strict=True):
        time = row["time_s"]
        irradiance = 500.0 if changed and row["tick"] >= 1000 else 900.0
        if abs(expected["time_s"] - time) > 1e-12:
            raise AssertionError("reference timestamps differ from physical ticks")
        if tuple(row["irradiance_w_m2"]) != (irradiance,) * 8:
            raise AssertionError("irradiance event mismatch")
        if row["reference_w_m2"] != irradiance:
            raise AssertionError("reference sensor source differs from panel source")
        if row["applied_voltage_v"] != 1.8 or row["disconnected"] or row["terminal_reason"]:
            raise AssertionError("fixed operating conditions changed")
        point, temperature = row["point"], row["temperature_c"]
        if abs(point["voltage_v"] - 1.8) > 1e-12:
            raise AssertionError("terminal voltage differs from fixed load")
        for name, actual, wanted in (
            ("current_a", point["current_a"], reference.current(irradiance, temperature)),
            ("power_w", point["power_w"], reference.power(irradiance, temperature)),
            ("temperature_c", temperature, expected["temperature_c"]),
            ("reference_refinement_c", expected["temperature_c"], refined["temperature_c"]),
        ):
            errors[name] = max(errors[name], abs(actual - wanted))
        if abs(point["power_w"] - point["voltage_v"] * point["current_a"]) > 1e-12:
            raise AssertionError("P=VI failed")
    for name, error in errors.items():
        if name != "sensor_state" and error > tolerance[name]:
            raise AssertionError(f"{name} error {error} exceeds frozen {tolerance[name]}")
    samples = [s for obs in trace.observations for s in obs["payload"]["scalars"]]
    identifiers = {(s["channel"], round(s["t_capture_s"] / 0.002)) for s in samples}
    expected_identifiers = {
        (channel, tick)
        for channel in ("voltage_v", "current_a", "temperature_c", "reference_w_m2")
        for tick in range(0, 4000, 50)
    }
    if len(samples) != 320 or identifiers != expected_identifiers:
        raise AssertionError("scalar acquisition coverage differs from the 10Hz protocol")
    previous_observation_s = -1.0
    for observation in trace.observations:
        observation_s = observation["payload"]["t_deliver_s"]
        if (
            observation_s <= previous_observation_s
            or abs(observation_s - observation["tick"] * 0.002) > 1e-12
        ):
            raise AssertionError("observation times are not increasing physical tick endpoints")
        for sample in observation["payload"]["scalars"]:
            if not previous_observation_s < sample["t_deliver_s"] <= observation_s:
                raise AssertionError("sample is not in its first eligible observation")
        previous_observation_s = observation_s
    for sample in samples:
        capture_tick = round(sample["t_capture_s"] / 0.002)
        if capture_tick % 50 or abs(sample["t_capture_s"] - capture_tick * 0.002) > 1e-12:
            raise AssertionError("capture timestamp is off the exact 10Hz acquisition grid")
        row = trace.rows[capture_tick]
        expected = {
            "voltage_v": row["point"]["voltage_v"],
            "current_a": row["point"]["current_a"],
            "temperature_c": row["temperature_c"],
            "reference_w_m2": row["reference_w_m2"],
        }[sample["channel"]]
        errors["sensor_state"] = max(errors["sensor_state"], abs(sample["value"] - expected))
        if sample["validity"] != "valid":
            raise AssertionError("noise-free nominal sample is invalid")
        delay = sample["t_deliver_s"] - sample["t_capture_s"]
        if abs(delay - 0.02) > tolerance["sensor_latency_s"]:
            raise AssertionError("capture/delivery delay is inconsistent")
    if errors["sensor_state"] > 1e-12:
        raise AssertionError("delivered measurement differs from original captured state")
    event_samples = [s for s in samples if abs(s["t_capture_s"] - 2.0) < 1e-12]
    if len(event_samples) != 4 or any(s["t_deliver_s"] != 2.02 for s in event_samples):
        raise AssertionError("the source-boundary capture is not delivered at 2.02s")
    absorbed = 259.2 if changed else 388.8
    energy_errors = {
        "absorbed_energy_j": abs(ledger["absorbed_j"] - absorbed),
        "electrical_energy_j": abs(ledger["pv_energy_j"] - fine[-1]["electrical_j"]),
        "energy_balance_j": abs(
            ledger["absorbed_j"]
            - ledger["pv_energy_j"]
            - ledger["heat_loss_j"]
            - ledger["storage_j"]
        ),
    }
    for name, error in energy_errors.items():
        if error > tolerance[name]:
            raise AssertionError(f"{name} error {error} exceeds frozen {tolerance[name]}")
    event_row, end = trace.rows[1000], trace.rows[-1]
    return {
        "checks": "passed",
        "physical_ticks": len(trace.rows),
        "scalar_samples": len(samples),
        "maximum_errors": errors | energy_errors,
        "at_event": {"temperature_c": event_row["temperature_c"], **event_row["point"]},
        "at_end": {"temperature_c": end["temperature_c"], **end["point"]},
        "ledger": ledger,
    }, fine


def check_pair(control, changed):
    if control.task != changed.task:
        raise AssertionError("private schedule altered public task capabilities")
    for a, b in zip(control.rows[:1000], changed.rows[:1000], strict=True):
        if a != b:
            raise AssertionError("paired world differs before scheduled source change")
    a, b = control.rows[1000], changed.rows[1000]
    if a["temperature_c"] != b["temperature_c"]:
        raise AssertionError("source event backdated temperature integration")
    if not b["point"]["power_w"] < a["point"]["power_w"]:
        raise AssertionError("fixed-load power did not fall at source event")
    if (
        not b["temperature_c"]
        < changed.rows[-1]["temperature_c"]
        < control.rows[-1]["temperature_c"]
    ):
        raise AssertionError("expected slower warming relative to control is absent")
    return {
        "pre_event_truth_identical": True,
        "temperature_continuous_at_event": True,
        "power_drops_at_event": True,
        "slower_warming_after_event": True,
        "public_tasks_identical": True,
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "runs") or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", output.name
    ):
        parser.error("output must be a new directory under runs with a bounded safe name")
    private = ROOT / "private_eval" / output.name
    if output.exists() or private.exists():
        parser.error("output or private companion already exists; preserve previous evidence")
    output.mkdir(parents=True)
    private.mkdir(parents=True)
    report = {
        "protocol": protocol(),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime_metadata(),
        "mode": "real_rgb" if args.render else "core_numeric_only",
        "scope": "paired evaluator fixtures; no complete policy pilot or physical calibration",
        "status": "running",
        "cases": {},
    }
    inputs = source_fingerprint()
    for folder, pattern in (("scripts", "*source*.py"), ("tests", "*source*.py")):
        for file in (ROOT / folder).rglob(pattern):
            inputs[str(file.relative_to(ROOT))] = sha256_file(file)
    inputs["configs/pilot.toml"] = sha256_file(ROOT / "configs/pilot.toml")
    inputs[str(PROTOCOL_PATH.relative_to(ROOT))] = sha256_file(PROTOCOL_PATH)
    write_json(private / "input-hashes.json", inputs)
    write_json(output / "report.json", report)
    traces = []
    try:
        for index, changed in enumerate((False, True)):
            trace = Trace()
            try:
                _, ledger = run_fixture(changed, render=args.render, trace=trace)
            finally:
                if hasattr(trace, "task"):
                    write_trace(
                        trace, output / f"case_{index}" / "public", private / f"case_{index}"
                    )
            result, ref = check_numeric(trace, ledger, changed=changed)
            report["cases"]["source_step" if changed else "control"] = result
            write_json(private / f"case_{index}" / "independent-reference.json", ref)
            traces.append(trace)
            write_json(output / "report.json", report)
        report["paired_checks"] = check_pair(*traces)
        report["render"] = (
            check_real_images(*traces)
            if args.render
            else {
                "status": "not_run",
                "reason": "core mode does not invoke or substitute a renderer",
            }
        )
        report["status"] = (
            "passed_pending_visual_and_independent_review"
            if args.render
            else "core_passed_desktop_render_pending"
        )
    except Exception as exc:
        report["status"] = "failed"
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        (output / "failure.txt").write_text(traceback.format_exc())
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(output / "report.json", report)
    artifacts = []
    for scope, directory in (("review_and_public", output), ("private", private)):
        for file in sorted(directory.rglob("*")):
            if file.is_file():
                artifacts.append(
                    {
                        "scope": scope,
                        "path": str(file.relative_to(directory)),
                        "bytes": file.stat().st_size,
                        "sha256": sha256_file(file),
                    }
                )
    write_json(private / "artifact-hashes.json", artifacts)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(output / "report.json"),
                "failure": report.get("failure"),
            },
            indent=2,
        )
    )
    return 4 if report["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
