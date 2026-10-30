"""Seed derivation/replay checks without running development pilot episodes."""

import numpy as np
import pytest

from pv_sim.scenarios import (
    BIT_GENERATOR,
    CAPTURE_NAMESPACE,
    SEED_NAMESPACE,
    STREAM_NAMES,
    rng_for_capture,
    rng_for_stream,
    seed_streams,
)


def test_versioned_known_seed_vector():
    assert SEED_NAMESPACE == "pv-sim/seed-streams/v1"
    seeds = seed_streams(20261016)
    assert seeds["geometry"] == int(
        "761f1f59f1be60ee658f7d08d7e8489b8f7ab4f080120018ed9c7478069ed746", 16
    )
    assert tuple(seeds) == (
        "geometry",
        "source",
        "material",
        "actuator",
        "numeric",
        "encoder",
        "rgb",
        "policy",
    )
    assert len(set(seeds.values())) == 8
    assert all(type(value) is int and 0 <= value < 2**256 for value in seeds.values())
    assert seeds == seed_streams(20261016, episode_index=0)
    assert all(seeds[name] != seed_streams(20261017)[name] for name in seeds)
    assert all(seeds[name] != seed_streams(20261016, episode_index=1)[name] for name in seeds)


def test_pcg64_pinned_and_named_draws_independent():
    assert BIT_GENERATOR == "PCG64"
    seeds = seed_streams(20261016)
    source = rng_for_stream(20261016, "source")
    assert type(source.bit_generator) is np.random.PCG64
    expected = np.random.Generator(np.random.PCG64(seeds["source"])).integers(0, 2**31, size=20)
    numeric = rng_for_stream(20261016, "numeric")
    numeric.standard_normal(10000)  # Extra scalar draws cannot advance another stream.
    np.testing.assert_array_equal(source.integers(0, 2**31, size=20), expected)
    # Construction order never changes a stream's initial state.
    for name in reversed(STREAM_NAMES):
        a = rng_for_stream(20261016, name, episode_index=3)
        b = rng_for_stream(20261016, name, episode_index=3)
        np.testing.assert_array_equal(a.integers(0, 2**31, size=20), b.integers(0, 2**31, size=20))


@pytest.mark.parametrize(
    "seed,episode", [(-1, 0), (0, -1), (True, 0), (0, False), (1.0, 0), (0, 1.0)]
)
def test_bad_seed_arguments_rejected(seed, episode):
    with pytest.raises(ValueError):
        seed_streams(seed, episode)


def test_unknown_stream_rejected_and_large_seed_supported():
    with pytest.raises(ValueError, match="unknown"):
        rng_for_stream(20261016, "unrecorded")
    assert seed_streams(2**128) == seed_streams(2**128)


def test_versioned_capture_known_vector_and_call_order_independence():
    assert CAPTURE_NAMESPACE == "pv-sim/capture-streams/v1"
    key = (20261016, "numeric", "voltage_v", 123, "gaussian_noise")
    expected = np.array([2084622086, 2015570660, 385145125, 223458245, 491015868])
    assert type(rng_for_capture(*key).bit_generator) is np.random.PCG64
    np.testing.assert_array_equal(rng_for_capture(*key).integers(0, 2**31, size=5), expected)
    for tick in (122, 900, 0, 124, 123):
        rng_for_capture(20261016, "numeric", "current_a", tick, "gaussian_noise").normal(size=7)
        rng_for_capture(20261016, "rgb", "rgb", tick, "delivery_jitter").random(size=4)
    np.testing.assert_array_equal(rng_for_capture(*key).integers(0, 2**31, size=5), expected)
    variants = (
        (20261017, "numeric", "voltage_v", 123, "gaussian_noise"),
        (20261016, "encoder", "voltage_v", 123, "gaussian_noise"),
        (20261016, "numeric", "current_a", 123, "gaussian_noise"),
        (20261016, "numeric", "voltage_v", 124, "gaussian_noise"),
        (20261016, "numeric", "voltage_v", 123, "dropout"),
    )
    for variant in variants:
        assert not np.array_equal(rng_for_capture(*variant).integers(0, 2**31, size=5), expected)
    assert not np.array_equal(
        rng_for_capture(*key, episode_index=1).integers(0, 2**31, size=5), expected
    )


@pytest.mark.parametrize(
    "channel,tick,purpose",
    [
        ("", 0, "noise"),
        ("voltage", True, "noise"),
        ("voltage", -1, "noise"),
        ("voltage", 0.5, "noise"),
        ("voltage", 0, ""),
        (1, 0, "noise"),
    ],
)
def test_invalid_capture_key_is_rejected(channel, tick, purpose):
    with pytest.raises(ValueError):
        rng_for_capture(1, "numeric", channel, tick, purpose)
