"""PNG wire-boundary regressions; synthetic fixtures are not render evidence."""

import base64
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from pv_sim.contracts import RGBSample

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CANARY = b"CANARY_PRIVATE:/private/review-fixture"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/m0_agent_rgb.png"


def chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def header(depth=8, colour=2, compression=0, filtering=0, interlace=0):
    return struct.pack(">IIBBBBB", 640, 480, depth, colour, compression, filtering, interlace)


def scanlines(depth=8):
    return (b"\0" + b"\x30" * (640 * 3 * (depth // 8))) * 480


def png(depth=8, compressed=None, end_data=b""):
    if compressed is None:
        compressed = zlib.compress(scanlines(depth))
    return SIGNATURE + b"".join(
        (chunk(b"IHDR", header(depth)), chunk(b"IDAT", compressed), chunk(b"IEND", end_data))
    )


def payload(task, raw):
    return dict(
        frame_id="png_boundary_fixture",
        camera_id="agent_rgb",
        width=640,
        height=480,
        encoding="png_rgb8",
        png_base64=base64.b64encode(raw).decode(),
        calibration_id="nominal_v1",
        k=task.nominal_calibration.k,
        exposure=dict(duration_s=0.01, approximation="midpoint_snapshot"),
        t_start_s=0.0,
        t_capture_s=0.005,
        t_end_s=0.01,
        t_deliver_s=0.11,
        validity="valid",
    )


def validate(task, raw):
    return RGBSample.model_validate_json(json.dumps(payload(task, raw)))


@pytest.mark.parametrize(
    "raw",
    [png(compressed=b"not a zlib stream"), png(depth=16), png(end_data=CANARY)],
    ids=["review-invalid-idat-correct-crc", "review-rgb16", "review-nonempty-iend"],
)
def test_reviewer_counterexamples_rejected(task, raw):
    with pytest.raises(ValidationError):
        validate(task, raw)


@pytest.mark.parametrize("control", ["synthetic", "captured", "split-idat", "adam7"])
def test_valid_rgb8_controls_preserve_pixels_and_payload(task, control):
    if control == "captured":
        raw = FIXTURE.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == (
            "feb98b0181b2a9826f9062675b0eced712055ed4e0b0466f2a8343a0ccb8fd90"
        )
    elif control == "split-idat":
        stream = zlib.compress(scanlines())
        raw = (
            SIGNATURE
            + chunk(b"IHDR", header())
            + b"".join(chunk(b"IDAT", part) for part in (b"", stream[:11], stream[11:]))
            + chunk(b"IEND", b"")
        )
    elif control == "adam7":
        # Independent fixed pass sizes for a 640x480 Adam7 RGB8 image.
        passes = [(80, 60), (80, 60), (160, 60), (160, 120), (320, 120), (320, 240), (640, 240)]
        pixels = b"".join((b"\0" + b"\x30" * (w * 3)) * h for w, h in passes)
        raw = SIGNATURE + chunk(b"IHDR", header(interlace=1))
        raw += chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    else:
        raw = png()
    model = validate(task, raw)
    assert base64.b64decode(model.png_base64) == raw
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        assert image.mode == "RGB" and image.size == (640, 480)
        if control != "captured":
            assert image.getextrema() == ((48, 48), (48, 48), (48, 48))


def malformed_structure(case):
    ihdr = chunk(b"IHDR", header())
    idat = chunk(b"IDAT", zlib.compress(scanlines()))
    iend = chunk(b"IEND", b"")
    bodies = {
        "short-ihdr": chunk(b"IHDR", header()[:-1]) + idat + iend,
        "long-ihdr": chunk(b"IHDR", header() + CANARY) + idat + iend,
        "duplicate-ihdr": ihdr + ihdr + idat + iend,
        "late-ihdr": idat + ihdr + iend,
        "missing-ihdr": idat + iend,
        "missing-idat": ihdr + iend,
        "missing-iend": ihdr + idat,
        "early-iend": ihdr + iend + idat,
        "duplicate-iend": ihdr + idat + iend + iend,
        "trailing-data": ihdr + idat + iend + CANARY,
        "short-chunk-framing": ihdr + idat + b"\0\0\0",
        "oversized-chunk": ihdr + struct.pack(">I", 0xFFFFFFFF) + b"IDAT" + iend,
        "iend-crc": ihdr + idat + iend[:-1] + bytes([iend[-1] ^ 1]),
        "idat-crc": ihdr + idat[:-1] + bytes([idat[-1] ^ 1]) + iend,
    }
    return SIGNATURE + bodies[case]


@pytest.mark.parametrize(
    "case",
    [
        "short-ihdr",
        "long-ihdr",
        "duplicate-ihdr",
        "late-ihdr",
        "missing-ihdr",
        "missing-idat",
        "missing-iend",
        "early-iend",
        "duplicate-iend",
        "trailing-data",
        "short-chunk-framing",
        "oversized-chunk",
        "iend-crc",
        "idat-crc",
    ],
)
def test_critical_chunk_structure_rejected(task, case):
    with pytest.raises(ValidationError):
        validate(task, malformed_structure(case))


@pytest.mark.parametrize(
    "fields", [{"colour": 6}, {"compression": 1}, {"filtering": 1}, {"interlace": 2}]
)
def test_nonconforming_ihdr_fields_rejected(task, fields):
    raw = SIGNATURE + chunk(b"IHDR", header(**fields))
    raw += chunk(b"IDAT", zlib.compress(scanlines())) + chunk(b"IEND", b"")
    with pytest.raises(ValidationError):
        validate(task, raw)


@pytest.mark.parametrize(
    "compressed",
    [
        zlib.compress(scanlines()) + CANARY,
        zlib.compress(scanlines()) + zlib.compress(CANARY),
        zlib.compress(scanlines())[:-4],
        zlib.compress(scanlines()[:-1]),
        zlib.compress(scanlines() + CANARY),
    ],
    ids=[
        "trailing-idat-data",
        "second-zlib-stream",
        "missing-zlib-trailer",
        "short-pixels",
        "extra-pixels",
    ],
)
def test_idat_stream_must_contain_only_complete_image(task, compressed):
    with pytest.raises(ValidationError):
        validate(task, png(compressed=compressed))


def test_original_payload_size_limit_retained(task):
    raw = payload(task, png())
    raw["png_base64"] = "A" * 2800001
    with pytest.raises(ValidationError):
        RGBSample.model_validate_json(json.dumps(raw))
