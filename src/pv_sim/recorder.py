"""Durable trusted-local recording with separate public and evaluator artifacts.

Public JSONL envelopes contain only public payloads and schema/config *versions*.
Offline observations replace PNG bytes with relative public frame references;
wire observations still carry bytes. Private configuration, seeds, truth, source
fingerprints and metrics never enter these public files. This is a data boundary,
not an OS sandbox. An interrupted run retains an incomplete private manifest.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from pv_sim.config import Config
from pv_sim.contracts import Decision, Observation, PublicTask, Record
from pv_sim.scenarios import BIT_GENERATOR, CAPTURE_NAMESPACE, SEED_NAMESPACE, seed_streams

ROOT = Path(__file__).resolve().parents[2]
MAX_RUN_BYTES = 2 * 1024**3
MANIFEST_RESERVE_BYTES = 256 * 1024


class ArtifactLimitError(RuntimeError):
    """Stop recording at the artifact cap while retaining all existing evidence."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic(path: Path, data: bytes, *, replace: bool = False) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # An exclusive hard link publishes the complete file without a
            # check-then-replace race against existing evidence.
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def source_fingerprint() -> dict[str, str]:
    paths = sorted((ROOT / "src/pv_sim").rglob("*.py"))
    paths += [ROOT / "uv.lock", ROOT / "pyproject.toml", ROOT / "configs/tolerances.toml"]
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in paths}


def runtime_metadata() -> dict[str, Any]:
    versions = {}
    for name in ("mujoco", "numpy", "pydantic", "Pillow", "pv-investigation-sim"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    git = {}
    for key, arguments in (
        ("revision", ["rev-parse", "HEAD"]),
        ("dirty_diff", ["diff", "--binary", "HEAD"]),
        ("status", ["status", "--porcelain"]),
    ):
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=ROOT, capture_output=True, timeout=5, check=False
            )
            git[key] = (
                hashlib.sha256(result.stdout).hexdigest()
                if key == "dirty_diff"
                else result.stdout.decode("utf-8", errors="replace").strip()
            )
            git[f"{key}_exit_code"] = result.returncode
        except (OSError, subprocess.TimeoutExpired):
            git[key] = "unavailable"
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "libraries": versions,
        "renderer": "mujoco_classic",
        "mujoco_gl": os.environ.get("MUJOCO_GL", "default"),
        "git": git,
        "command": {"argv": sys.argv, "cwd": str(Path.cwd()), "started_utc": _utc()},
    }


class Recorder:
    def __init__(
        self,
        output: Path,
        private_root: Path = Path("private_eval"),
        *,
        source_manifest: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.output = Path(output).resolve()
        self.run_id = self.output.name
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", self.run_id):
            raise ValueError("output basename must be a bounded run identifier")
        self.private_dir = Path(private_root).resolve() / self.run_id
        if self.output in self.private_dir.parents or self.private_dir in self.output.parents:
            raise ValueError("public and private run directories must be separate")
        if self.output == self.private_dir:
            raise ValueError("public and private run directories must be separate")
        if self.output.exists() or self.private_dir.exists():
            raise FileExistsError("run output or its private companion already exists")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.private_dir.parent.mkdir(parents=True, exist_ok=True)
        self.output.mkdir()
        self.private_dir.mkdir()
        self.public_dir = self.output / "public"
        self.public_dir.mkdir()
        (self.public_dir / "frames").mkdir()
        self.manifest_path = self.private_dir / "manifest.json"
        self._streams: dict[Path, IO[str]] = {}
        self._sequence = 0
        self._tick = 0
        self._started = False
        self._finished = False
        self._frame_hashes: dict[str, str] = {}
        self._written_bytes = 0
        self._manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "incomplete": True,
            "status": "not_started",
            "created_utc": _utc(),
            "public_relative_path": os.path.relpath(self.output, self.private_dir),
            "metadata": json.loads(canonical_json(metadata or {})),
            "artifact_cap_bytes": MAX_RUN_BYTES,
        }
        if source_manifest is not None:
            self._manifest["replay_source"] = {
                "manifest": str(source_manifest.resolve()),
                "sha256": sha256_file(source_manifest),
                "policy_requeried": False,
            }
        self._write_manifest()

    def _write_manifest(self) -> None:
        raw = (canonical_json(self._manifest) + "\n").encode()
        self._write_bytes(self.manifest_path, raw, replace=True, control=True)
        self._write_bytes(
            self.private_dir / "manifest.sha256",
            (hashlib.sha256(raw).hexdigest() + "\n").encode(),
            replace=True,
            control=True,
        )

    def _check_capacity(self, growth: int, *, control: bool = False) -> None:
        limit = MAX_RUN_BYTES if control else MAX_RUN_BYTES - MANIFEST_RESERVE_BYTES
        if self._written_bytes + growth > limit:
            raise ArtifactLimitError(
                "2 GiB per-run artifact cap reached; existing evidence retained"
            )

    def _write_bytes(
        self, path: Path, data: bytes, *, replace: bool = False, control: bool = False
    ) -> None:
        previous = path.stat().st_size if replace and path.exists() else 0
        growth = len(data) - previous
        self._check_capacity(growth, control=control)
        _atomic(path, data, replace=replace)
        self._written_bytes += growth

    def start(self, config: Config, seed: int, task: PublicTask) -> None:
        if self._started or self._finished:
            raise RuntimeError("recorder may start only once")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        self._config = config
        self._task = PublicTask.model_validate_json(task.model_dump_json())
        self._write_bytes(self.public_dir / "task.json", (task.model_dump_json() + "\n").encode())
        self._write_bytes(
            self.private_dir / "config.json", (config.canonical_json() + "\n").encode()
        )
        self._manifest.update(
            status="running",
            seed=seed,
            seed_streams=seed_streams(seed),
            seed_namespace=SEED_NAMESPACE,
            bit_generator=BIT_GENERATOR,
            episode_id=task.episode_id,
            config_sha256=config.sha256(),
            config_version=config.schema_version,
            dt_s=config.simulation.dt_s,
            source_fingerprint=source_fingerprint(),
            runtime=runtime_metadata(),
            initial_state=None,
            evidence_level="M1 trusted-policy/local synthetic simulator",
            image_storage="public-relative PNG files; wire payloads restored during replay",
        )
        if config.m2 is not None:
            self._manifest.update(
                capture_namespace=CAPTURE_NAMESPACE,
                evidence_level="M2 trusted-policy/local synthetic fixture",
            )
        initial = (canonical_json(self._manifest) + "\n").encode()
        self._write_bytes(self.private_dir / "manifest.initial.json", initial)
        self._manifest["initial_manifest_sha256"] = hashlib.sha256(initial).hexdigest()
        self._started = True
        self._write_manifest()

    def _check_open(self) -> None:
        if not self._started or self._finished:
            raise RuntimeError("recorder must be running")

    def _event(
        self,
        filename: str,
        kind: str,
        payload: Any,
        tick: int,
        *,
        private: bool = False,
        action_id: int | None = None,
    ) -> None:
        self._check_open()
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < self._tick:
            raise ValueError("event ticks must be nonnegative and monotonic")
        event = {
            "sequence": self._sequence,
            "tick": tick,
            "event_type": kind,
            "schema_version": "1.0",
            "config_version": self._config.schema_version,
            "action_id": action_id,
            "payload": payload,
        }
        raw = canonical_json(event) + "\n"
        written_bytes = len(raw.encode("utf-8"))
        self._check_capacity(written_bytes)
        path = (self.private_dir if private else self.public_dir) / filename
        if path not in self._streams:
            self._streams[path] = path.open("x", encoding="utf-8")
        self._streams[path].write(raw)
        self._streams[path].flush()
        self._written_bytes += written_bytes
        self._sequence += 1
        self._tick = tick

    def action(self, action: Any, tick: int) -> None:
        """Record every authoritative step attempt, including invalid JSON values.

        raw_json is a *string* inside valid outer JSON. Its parser preserves NaN
        and infinity only to reproduce deliberate invalid-input rejections; such
        values never become accepted public actions or numeric measurements.
        """
        value = action.model_dump(mode="json") if isinstance(action, Record) else action
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=True)
        action_id = value.get("action_id") if isinstance(value, dict) else None
        if isinstance(action_id, bool) or not isinstance(action_id, int) or action_id < 1:
            action_id = None
        self._event("actions.jsonl", "action", {"raw_json": raw}, tick, action_id=action_id)

    def observation(self, observation: Observation, tick: int | None = None) -> None:
        self._check_open()
        observation = Observation.model_validate_json(observation.model_dump_json())
        if observation.episode_id != self._task.episode_id:
            raise ValueError("observation belongs to a different episode")
        delivered_tick = round(observation.t_deliver_s / self._config.simulation.dt_s)
        if not math.isclose(
            delivered_tick * self._config.simulation.dt_s,
            observation.t_deliver_s,
            rel_tol=0,
            abs_tol=1e-10,
        ):
            raise ValueError("observation delivery is not tick aligned")
        tick = max(self._tick, delivered_tick) if tick is None else tick
        if tick < delivered_tick:
            raise ValueError("observation cannot be recorded before delivery")
        payload = observation.model_dump(mode="json")
        for frame in payload["rgb"]:
            encoded = frame.pop("png_base64")
            if encoded is None:
                frame.update(png_file=None, png_sha256=None)
                continue
            raw = base64.b64decode(encoded, validate=True)
            digest = hashlib.sha256(raw).hexdigest()
            identifier = frame["frame_id"]
            if identifier in self._frame_hashes and self._frame_hashes[identifier] != digest:
                raise ValueError("frame identifier reused with different pixels")
            if identifier not in self._frame_hashes:
                self._write_bytes(self.public_dir / "frames" / f"{identifier}.png", raw)
                self._frame_hashes[identifier] = digest
            frame.update(png_file=f"frames/{identifier}.png", png_sha256=digest)
        self._event("observations.jsonl", "observation", payload, tick)
        for feedback in observation.feedback:
            self._event(
                "feedback.jsonl",
                "feedback",
                feedback.model_dump(mode="json"),
                tick,
                action_id=feedback.action_id,
            )

    def decision(self, decision: Decision, latency_s: float, failure: str | None = None) -> None:
        validated = Decision.model_validate_json(decision.model_dump_json())
        if not math.isfinite(latency_s) or latency_s < 0:
            raise ValueError("wall-clock latency must be finite and nonnegative")
        if failure not in (None, "invalid_input", "invalid_output", "latency_overrun"):
            raise ValueError("failure must be a declared public policy-runner category")
        self._event(
            "decisions.jsonl",
            "decision",
            {
                "decision": validated.model_dump(mode="json"),
                "wall_clock_latency_s": latency_s,
                "failure": failure,
            },
            self._tick,
            action_id=validated.action.action_id,
        )

    def truth(self, payload: dict[str, Any]) -> None:
        tick = payload.get("tick")
        self._event("truth.jsonl", "truth", payload, tick, private=True)
        if self._manifest["initial_state"] is None:
            self._manifest["initial_state"] = json.loads(canonical_json(payload))
            self._write_manifest()

    def actuation(
        self, payload: dict[str, Any], tick: int, *, action_id: int | None = None
    ) -> None:
        """Evaluator-only issuance/application/fault events, separate from public feedback."""
        self._event(
            "actuation.jsonl", "actuation", payload, tick, private=True, action_id=action_id
        )

    def finish(self, metrics: dict[str, Any]) -> None:
        self._check_open()
        encoded_metrics = (canonical_json(metrics) + "\n").encode()
        for stream in self._streams.values():
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        self._write_bytes(self.private_dir / "metrics.json", encoded_metrics)
        # Include evidence written by the CLI/replay driver in the final guard.
        self._written_bytes = sum(
            path.stat().st_size
            for directory in (self.output, self.private_dir)
            for path in directory.rglob("*")
            if path.is_file()
        )
        self._check_capacity(0)
        self._manifest.update(
            incomplete=False,
            status="complete",
            completed_utc=_utc(),
            final_tick=self._tick,
            event_count=self._sequence,
            frame_count=len(self._frame_hashes),
            artifacts=self._artifacts(),
        )
        self._write_manifest()
        self._finished = True

    def _artifacts(self) -> list[dict[str, Any]]:
        artifacts = []
        for scope, directory in (("public", self.output), ("private", self.private_dir)):
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.name not in ("manifest.json", "manifest.sha256"):
                    artifacts.append(
                        {
                            "scope": scope,
                            "path": str(path.relative_to(directory)),
                            "sha256": sha256_file(path),
                            "bytes": path.stat().st_size,
                        }
                    )
        return artifacts

    def abort(self, error_type: str, message: str = "") -> None:
        """Preserve interrupted evidence and a bounded private failure explanation."""
        if self._finished:
            raise RuntimeError("cannot change a finalized recording")
        self.close()
        self._manifest.update(
            incomplete=True,
            status="failed",
            failed_utc=_utc(),
            final_tick=self._tick,
            failure={"type": error_type[:128], "message": message[:1000]},
            artifacts=self._artifacts(),
        )
        self._write_manifest()
        self._finished = True

    def close(self) -> None:
        """Release streams while retaining incomplete status after interruption."""
        for stream in self._streams.values():
            if not stream.closed:
                stream.flush()
                stream.close()
