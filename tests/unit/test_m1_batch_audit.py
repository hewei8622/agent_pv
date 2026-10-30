"""Evidence-auditor input fixtures only; none represents a successful simulator run."""

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pv_sim.config import Config, load_config
from pv_sim.contracts import ACTION_ADAPTER, Decision, Observation
from pv_sim.recorder import Recorder, canonical_json, sha256_file
from pv_sim.sensors import build_public_task

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("m1_audit", ROOT / "scripts/audit_m1_batch.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def inventory_cases():
    inventory = json.loads((ROOT / "configs/m1_test_inventory.json").read_text())
    return [(case["classname"], case["name"]) for case in inventory["cases"]]


def junit(path, *, skipped=False, missing_render=False, cases=None):
    # Synthetic XML audit input only; these records do not claim executed simulation.
    cases = list(inventory_cases() if cases is None else cases)
    if missing_render:
        cases = [case for case in cases if not case[0].endswith("test_m1_loop")]
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root,
        "testsuite",
        tests=str(len(cases)),
        failures="0",
        errors="0",
        skipped=str(int(skipped)),
    )
    for index, (module, name) in enumerate(cases):
        case = ET.SubElement(suite, "testcase", classname=module, name=name)
        if skipped and index == 0:
            ET.SubElement(case, "skipped", message="synthetic audit input skip")
    path.write_text(ET.tostring(root, encoding="unicode"))


@pytest.fixture
def batch_fixture(tmp_path):
    """Only batch/JUnit/command audit input metadata; intentionally no pilot records."""
    batch_id = "audit-input-fixture"
    directory = tmp_path / "runs" / batch_id
    evidence = directory / "evidence"
    evidence.mkdir(parents=True)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/m1_test_inventory.json").write_bytes(
        (ROOT / "configs/m1_test_inventory.json").read_bytes()
    )
    expected = audit.expected_commands(batch_id)
    batch = dict(
        batch_id=batch_id,
        status="commands_passed_pending_image_inspection_and_independent_review",
        results=[{"label": label, "exit_code": 0} for label, _ in expected],
        seeds=[11, 23, 47],
        max_complete_pilots=3,
        elapsed_wall_s=7.0,
        artifact_bytes=1000,
    )
    write_json(directory / "batch-report.json", batch)
    write_json(directory / "planned.json", {"commands": expected})
    entries = []
    for index, (label, argv) in enumerate(expected):
        for stream in ("stdout", "stderr"):
            (evidence / f"{label}.{stream}.txt").write_text("audit input fixture\n")
        entries.append(
            dict(
                label=label,
                argv=argv,
                cwd=str(tmp_path),
                exit_code=0,
                started_utc=f"2026-10-17T10:00:{index * 2:02d}+00:00",
                ended_utc=f"2026-10-17T10:00:{index * 2 + 1:02d}+00:00",
                elapsed_s=1.0,
                stdout=f"runs/{batch_id}/evidence/{label}.stdout.txt",
                stderr=f"runs/{batch_id}/evidence/{label}.stderr.txt",
            )
        )
    (evidence / "commands.jsonl").write_text("".join(json.dumps(row) + "\n" for row in entries))
    junit(directory / "tests.xml")
    (evidence / "tests.stdout.txt").write_text(
        "SYNTHETIC AUDIT INPUT; NOT AN EXECUTED SIMULATOR OR TEST RUN\n"
        f"{len(inventory_cases())} passed in 1.0s\n"
    )
    return tmp_path, directory, batch, entries


def test_missing_batch_is_incomplete_and_does_not_create_evidence(tmp_path):
    missing = tmp_path / "runs/absent/batch-report.json"
    report = audit.audit_batch(missing, root=tmp_path)
    assert report["status"] == "incomplete"
    assert report["visual_inspection"] == "not_performed"
    assert report["independent_review"] == "pending"
    assert not missing.parent.exists()


def test_complete_command_metadata_without_pilots_never_passes(batch_fixture):
    root, directory, _, _ = batch_fixture
    report = audit.audit_batch(directory / "batch-report.json", root=root)
    assert report["status"] == "incomplete"
    assert next(c for c in report["checks"] if c["check"] == "executed_junit")["status"] == "passed"
    assert all(
        c["status"] == "incomplete" for c in report["checks"] if c["check"].startswith("pilot_")
    )
    assert not (root / "private_eval").exists()


def test_running_batch_is_explicitly_incomplete(batch_fixture):
    root, directory, batch, _ = batch_fixture
    write_json(directory / "batch-report.json", batch | {"status": "running"})
    assert audit.audit_batch(directory / "batch-report.json", root=root)["status"] == "incomplete"


@pytest.mark.parametrize("change", ["skip", "missing_render", "zero_cases", "bad_count"])
def test_junit_cannot_pass_when_required_execution_is_absent(tmp_path, change):
    path = tmp_path / "tests.xml"
    junit(path, skipped=change == "skip", missing_render=change == "missing_render")
    if change == "zero_cases":
        path.write_text(
            '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>'
        )
    elif change == "bad_count":
        tree = ET.parse(path)
        tree.getroot().find("testsuite").set("tests", "999999")
        tree.write(path, encoding="unicode")
    with pytest.raises(audit.AuditError):
        audit.check_junit(path)


def test_junit_child_skip_is_rejected_even_with_false_zero_summary(tmp_path):
    path = tmp_path / "tests.xml"
    junit(path, skipped=True)
    path.write_text(path.read_text().replace('skipped="1"', 'skipped="0"'))
    with pytest.raises(audit.AuditError, match="skip"):
        audit.check_junit(path)


@pytest.mark.parametrize(
    "change", ["nonzero", "wrong_seed", "duplicate", "missing_stdout", "extra"]
)
def test_command_records_must_match_executed_batch(batch_fixture, change):
    root, directory, batch, entries = batch_fixture
    if change == "nonzero":
        entries[1]["exit_code"] = 4
    elif change == "wrong_seed":
        entries[1]["argv"][entries[1]["argv"].index("--seed") + 1] = "99"
    elif change == "duplicate":
        entries.append(entries[-1])
    elif change == "missing_stdout":
        (root / entries[0]["stdout"]).unlink()
    else:
        entries.append({"label": "unrequested-pilot", "argv": ["anything"]})
    (directory / "evidence/commands.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in entries)
    )
    with pytest.raises(audit.AuditError):
        audit.check_commands(root, batch["batch_id"], batch)


def test_later_audit_metadata_is_allowed_without_weakening_seven_command_checks(batch_fixture):
    root, directory, batch, entries = batch_fixture
    entries.append(
        {
            "label": "audit",
            "argv": [
                "python",
                "scripts/audit_m1_batch.py",
                "--batch-report",
                str(directory / "batch-report.json"),
            ],
            "exit_code": 0,
        }
    )
    (directory / "evidence/commands.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in entries)
    )
    assert audit.check_commands(root, batch["batch_id"], batch)["successful_recorded_commands"] == 7


def test_rendered_metric_gate_rejects_core_or_unverified_claims():
    valid = dict(
        core_only=False,
        terminal_reason="finished",
        verification_tail_complete=True,
        voltage_points=4,
        rgb_frames=2,
        pilot_passed=True,
        policy_adapter_failure=None,
        pilot_checks={
            key: True
            for key in (
                "finished",
                "verification_tail",
                "no_adapter_failure",
                "energy_balance",
                "home_and_side_images",
                "measured_choice",
                "newer_verification",
                "four_voltage_points",
            )
        },
    )
    audit.check_rendered_metrics(valid)
    for update in (
        {"core_only": True},
        {"verification_tail_complete": False},
        {"pilot_passed": False},
        {"voltage_points": 3},
        {"rgb_frames": 0},
        {"pilot_checks": {}},
    ):
        with pytest.raises(audit.AuditError):
            audit.check_rendered_metrics(valid | update)


def make_audit_input_recording(root):
    """Minimal schema-valid recording solely to exercise integrity rejection."""
    config = load_config(ROOT / "configs/pilot.toml")
    task = build_public_task(config, "audit_fixture", enable_rendering=False)
    run_id = "audit-input-fixture-s11"
    recorder = Recorder(
        root / "runs" / run_id,
        root / "private_eval",
        metadata={
            "purpose": "m1_pilot",
            "policy": "scan",
            "fixture": "synthetic auditor input, not simulator evidence",
        },
    )
    recorder.start(config, 11, task)
    action = ACTION_ADAPTER.validate_python(
        dict(schema_version="1.0", action_id=1, kind="wait", timeout_s=1.0, duration_s=0.1)
    )
    decision = Decision(
        schema_version="1.0",
        action=action,
        predictions=(),
        hypothesis_probabilities=None,
        unresolved_hypotheses=(),
        evidence_refs=(),
        rationale="Audit fixture only.",
    )
    recorder.decision(decision, 0.0)
    recorder.action(action, 0)
    recorder.observation(
        Observation(
            schema_version="1.0",
            episode_id=task.episode_id,
            sequence_id=0,
            t_deliver_s=0.0,
            scalars=(),
            encoders=(),
            rgb=(),
            feedback=(),
            remaining_budgets=task.budgets,
            terminal=False,
            terminal_reason=None,
        ),
        tick=0,
    )
    recorder.truth({"tick": 0, "fixture": True})
    (recorder.public_dir / "feedback.jsonl").write_text("")
    recorder.finish({"core_only": True, "fixture": "not a pilot"})
    return recorder.manifest_path


def test_corrupt_recording_artifact_rejected_before_any_success_claim(tmp_path):
    manifest = make_audit_input_recording(tmp_path)
    metrics = manifest.parent / "metrics.json"
    metrics.write_text(metrics.read_text() + " ")
    with pytest.raises(audit.ReplayError, match="hash mismatch"):
        audit.inspect_recording(tmp_path, "audit-input-fixture-s11", 11)


def test_incomplete_manifest_rejected_even_if_hash_is_recomputed(tmp_path):
    manifest = make_audit_input_recording(tmp_path)
    value = json.loads(manifest.read_text())
    value["incomplete"] = True
    manifest.write_text(canonical_json(value) + "\n")
    manifest.with_name("manifest.sha256").write_text(sha256_file(manifest) + "\n")
    with pytest.raises(audit.ReplayError, match="incomplete"):
        audit.inspect_recording(tmp_path, "audit-input-fixture-s11", 11)


def test_cli_missing_evidence_returns_four_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    output = tmp_path / "audit.json"
    absent = tmp_path / "runs/absent/batch-report.json"
    assert audit.main(["--batch-report", str(absent), "--output", str(output)]) == 4
    before = output.read_bytes()
    assert json.loads(before)["status"] == "incomplete"
    with pytest.raises(SystemExit):
        audit.main(["--batch-report", str(absent), "--output", str(output)])
    assert output.read_bytes() == before


def test_three_arbitrary_render_module_cases_cannot_substitute_required_named_cases(tmp_path):
    path = tmp_path / "partial.xml"
    cases = "".join(
        f'<testcase classname="tests.render.{module}" name="arbitrary"/>'
        for module in ("test_calibration", "test_m1_camera", "test_m1_loop")
    )
    path.write_text(
        '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0">'
        + cases
        + "</testsuite></testsuites>"
    )
    with pytest.raises(audit.AuditError, match="required render testcase absent"):
        audit.check_junit(path)


def test_complete_frozen_render_inventory_has_22_named_cases(tmp_path):
    path = tmp_path / "complete.xml"
    junit(path)
    assert audit.check_junit(path)["required_render_cases"] == 22


def test_recorded_config_must_match_exact_cli_declared_config(tmp_path):
    config = load_config(ROOT / "configs/pilot.toml")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/pilot.toml").write_bytes((ROOT / "configs/pilot.toml").read_bytes())
    audit.check_declared_config(config, tmp_path)
    changed = config.model_dump()
    changed["sensors"]["voltage_sigma_v"] = 0.02
    with pytest.raises(audit.AuditError, match="declared configs/pilot.toml"):
        audit.check_declared_config(Config.model_validate(changed), tmp_path)


def test_render_only_junit_cannot_replace_frozen_complete_suite(tmp_path):
    path = tmp_path / "render-only.xml"
    junit(path, cases=sorted(audit.REQUIRED_RENDER_CASES))
    with pytest.raises(audit.AuditError, match="complete-suite inventory mismatch"):
        audit.check_junit(path)


@pytest.mark.parametrize("mutation", ["missing_core", "extra_case", "duplicate"])
def test_full_test_identity_inventory_rejects_coverage_changes(tmp_path, mutation):
    cases = inventory_cases()
    if mutation == "missing_core":
        cases.remove(next(case for case in cases if ".render." not in case[0]))
    elif mutation == "extra_case":
        cases.append(("tests.unrequested", "test_not_in_frozen_inventory"))
    else:
        cases.append(cases[0])
    path = tmp_path / "changed.xml"
    junit(path, cases=cases)
    with pytest.raises(audit.AuditError, match="inventory mismatch|duplicate testcase"):
        audit.check_junit(path)


@pytest.mark.parametrize(
    "summary",
    [
        "22 passed, 377 deselected in 2.0s",
        "1 passed in 1.0s",
        "no executed summary",
        "1 passed, 1 xfailed in 1.0s",
    ],
)
def test_command_stdout_cannot_conceal_incomplete_test_execution(batch_fixture, summary):
    root, directory, batch, entries = batch_fixture
    (root / entries[0]["stdout"]).write_text(
        "SYNTHETIC AUDIT INPUT; NOT AN EXECUTED TEST RUN\n" + summary + "\n"
    )
    with pytest.raises(audit.AuditError):
        audit.check_commands(root, batch["batch_id"], batch)


def test_inventory_and_junit_summary_match_complete_synthetic_input(batch_fixture):
    root, directory, batch, _ = batch_fixture
    junit_report = audit.check_junit(directory / "tests.xml")
    command_report = audit.check_commands(root, batch["batch_id"], batch)
    assert junit_report["executed_testcases"] == len(inventory_cases())
    assert command_report["reported_pytest_passes"] == len(inventory_cases())
    assert junit_report["required_render_cases"] == 22
