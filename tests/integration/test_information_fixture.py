"""Retained interface evidence integrity and honest fixture provenance."""

import json
import sys
from pathlib import Path

import pytest

from pv_sim.interaction import CompletedEvent, PhysicalEvent, load_transcript
from pv_sim.recorder import sha256_file

SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import validate_information_interface as fixture  # noqa: E402


def test_fixture_retains_exact_replay_provenance_links_and_artifact_hashes(tmp_path):
    report = fixture.run_fixture(Path("runs/interface-evidence"), artifact_root=tmp_path)
    output = tmp_path / "runs/interface-evidence"
    private = tmp_path / "private_eval/interface-evidence"
    assert report["status"] == "passed"
    assert report["driver"] == "fixed authored script; not an adaptive decision agent"
    assert report["information_provenance"] == "simulated"
    assert report["live_human_calls"] == report["live_internet_calls"] == 0
    assert report["requests"] == report["transport_calls"] == 3
    assert report["physical_decisions"] == 2 and report["total_decisions"] == 5
    assert report["simulation_time_s"] < 8
    assert report["request_channels"] == ["human", "internet", "human"]
    assert report["pause_check"]["observed_local_wait_s"] >= fixture.LOCAL_DELAY_S
    assert report["pause_check"]["state_and_queue_exactly_unchanged"]
    assert report["pause_check"]["additional_simulated_energy_j"] == 0
    assert report["retry_check"]["additional_transport_calls"] == 0
    assert report["replay"]["live_calls"] == 0
    assert report["replay"]["restored_original_wait_s"] == (
        report["original_information_elapsed_wall_s"]
    )
    assert report["replay"]["actual_replay_wall_s"] > 0
    assert report["replay_metrics_exactly_equal"]
    assert json.loads((private / "metrics.json").read_text()) == json.loads(
        (private / "replay-metrics.json").read_text()
    )
    assert report["finish_verification"]["verification_tail_s"] == 2
    assert report["finish_verification"]["resolution"] == "unresolved"
    trace = load_transcript(output / "public/interaction.json")
    receipts = [event.receipt for event in trace.events if isinstance(event, CompletedEvent)]
    physical = [event for event in trace.events if isinstance(event, PhysicalEvent)]
    assert len(receipts) == 3 and len(physical) == 2 and len(trace.events) == 8
    assert all(receipt.reply.provenance == "simulated" for receipt in receipts)
    assert receipts[-1].request.parent_request_id == receipts[0].request.request_id
    assert all(event.decision.information_refs == (
        "context", "test_guidance", "clarification"
    ) for event in physical)
    assert physical[0].observation.sequence_id == (
        report["probe_verification"]["result_observation_sequence_id"]
    )
    assert all(not event.observation.rgb for event in physical)
    assert not list(tmp_path.rglob("*.png"))
    public = (output / "public/interaction.json").read_text()
    for private_field in ("private_world", "source_schedule", "initial_temperature_c", "seed"):
        assert private_field not in public
    artifacts = json.loads((private / "artifact-manifest.json").read_text())["sha256"]
    assert artifacts and all(sha256_file(tmp_path / name) == value
                             for name, value in artifacts.items())
    inputs = json.loads((private / "inputs.json").read_text())
    assert "scripts/validate_information_interface.py" in inputs
    assert "tests/integration/test_information_fixture.py" in inputs
    assert "configs/interaction_protocol.json" in inputs
    # Both companion directories are protected, including the completed summary.
    before = {name: (tmp_path / name).read_bytes() for name in artifacts}
    with pytest.raises(FileExistsError, match="preserve prior evidence"):
        fixture.run_fixture(Path("runs/interface-evidence"), artifact_root=tmp_path)
    assert {name: (tmp_path / name).read_bytes() for name in artifacts} == before


@pytest.mark.parametrize("path", ["../escape", "/tmp/absolute", "output/evidence", "runs/a/b"])
def test_fixture_rejects_output_outside_new_project_run(tmp_path, path):
    with pytest.raises(ValueError, match="project-relative|direct child"):
        fixture.run_fixture(Path(path), artifact_root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_fixture_retains_failure_summary_and_preserves_private_existing_evidence(
    tmp_path, monkeypatch
):
    def fail_configuration():
        raise ValueError("deliberate fixture setup failure")

    monkeypatch.setattr(fixture, "_fixture_config", fail_configuration)
    with pytest.raises(ValueError, match="deliberate fixture"):
        fixture.run_fixture(Path("runs/failed-fixture"), artifact_root=tmp_path)
    report = json.loads((tmp_path / "runs/failed-fixture/summary.json").read_text())
    assert report["status"] == "failed" and report["error_type"] == "ValueError"
    private = tmp_path / "private_eval/existing-private"
    private.mkdir()
    (private / "marker").write_text("retain this")
    with pytest.raises(FileExistsError):
        fixture.run_fixture(Path("runs/existing-private"), artifact_root=tmp_path)
    assert (private / "marker").read_text() == "retain this"
    assert not (tmp_path / "runs/existing-private").exists()
