"""Private deterministic named streams and capture-indexed M2 randomness.

No scenario fault corpus is generated here. Seeds belong only in private replay
manifests. Sensor draws are indexed by channel/capture tick/purpose, so extra
actions or captures never advance a later capture's random state.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

SEED_NAMESPACE = "pv-sim/seed-streams/v1"
CAPTURE_NAMESPACE = "pv-sim/capture-streams/v1"
BIT_GENERATOR = "PCG64"
STREAM_NAMES = ("geometry", "source", "material", "actuator", "numeric", "encoder", "rgb", "policy")


def _nonnegative_integer(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def seed_streams(seed: int, episode_index: int = 0) -> dict[str, int]:
    """SHA-256 of UTF-8 compact JSON [namespace,root,episode,name], big-endian.

    The complete 256-bit digest is the nonnegative PCG64 seed. Naming each stream
    independently avoids order-dependent SeedSequence spawning. JSON integers
    remain integers in Python replay artifacts; do not round them through floats.
    """
    _nonnegative_integer(seed, "seed")
    _nonnegative_integer(episode_index, "episode_index")
    result = {}
    for name in STREAM_NAMES:
        payload = json.dumps(
            [SEED_NAMESPACE, seed, episode_index, name], ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        result[name] = int.from_bytes(hashlib.sha256(payload).digest(), "big")
    return result


def rng_for_stream(seed: int, stream_name: str, episode_index: int = 0) -> np.random.Generator:
    """Construct a fresh explicitly pinned PCG64 generator for one private stream."""
    if stream_name not in STREAM_NAMES:
        raise ValueError("unknown private seed stream")
    return np.random.Generator(np.random.PCG64(seed_streams(seed, episode_index)[stream_name]))


def rng_for_capture(
    seed: int,
    stream_name: str,
    channel: str,
    capture_tick: int,
    purpose: str,
    episode_index: int = 0,
) -> np.random.Generator:
    """Fresh PCG64 from a versioned, unambiguous capture key; never a shared cursor.

    Hash UTF-8 compact JSON [capture_namespace, named_stream_seed, channel,
    capture_tick, purpose] and interpret the entire digest as a big-endian seed.
    Named stream derivation and episode indexing retain their M1 convention.
    Transport and Gaussian noise use distinct purposes within the same stream.
    """
    if stream_name not in STREAM_NAMES:
        raise ValueError("unknown private seed stream")
    _nonnegative_integer(capture_tick, "capture_tick")
    if type(channel) is not str or not channel or type(purpose) is not str or not purpose:
        raise ValueError("capture channel and purpose must be nonempty strings")
    stream_seed = seed_streams(seed, episode_index)[stream_name]
    payload = json.dumps(
        [CAPTURE_NAMESPACE, stream_seed, channel, capture_tick, purpose],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    capture_seed = int.from_bytes(hashlib.sha256(payload).digest(), "big")
    return np.random.Generator(np.random.PCG64(capture_seed))
