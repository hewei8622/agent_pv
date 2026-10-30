"""M1 CLI input boundaries; real pilot execution belongs to desktop evidence."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pv_sim.cli import _pilot_limit

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("subcommand", ["demo", "replay"])
def test_m1_help(subcommand):
    result = subprocess.run(
        [sys.executable, "-m", "pv_sim.cli", subcommand, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "--output" in result.stdout
    assert "--no-render" not in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["demo", "--seed", "99", "--config", "configs/pilot.toml", "--output", "runs/no-run"],
        ["demo", "--seed", "11", "--config", "absent.toml", "--output", "runs/no-run"],
        ["replay", "--manifest", "absent.json", "--output", "runs/no-run"],
    ],
)
def test_m1_invalid_input(arguments):
    result = subprocess.run(
        [sys.executable, "-m", "pv_sim.cli", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (ROOT / "runs/no-run").exists()


def test_pilot_cap_counts_complete_pilots_not_replays(tmp_path):
    for index, (seed, purpose, status) in enumerate(
        [
            (11, "m1_pilot", "complete"),
            (23, "m1_pilot", "failed"),
            (47, "m1_replay", "complete"),
        ]
    ):
        directory = tmp_path / str(index)
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "seed": seed,
                    "metadata": {"purpose": purpose},
                    "status": status,
                }
            )
        )
    with pytest.raises(ValueError, match="allowance"):
        _pilot_limit(tmp_path, 11)
    _pilot_limit(tmp_path, 23)
    _pilot_limit(tmp_path, 47)
