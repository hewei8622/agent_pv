"""New real source-response images; no saved image or skip fallback."""

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from validate_source_response import main  # noqa: E402

pytestmark = pytest.mark.render


def test_actual_source_response_images_and_late_frame():
    output = os.environ.get(
        "PV_SOURCE_RESPONSE_EVIDENCE_DIR",
        str(ROOT / "runs" / ("source-render-test-" + uuid.uuid4().hex)),
    )
    assert main(["--render", "--output", output]) == 0
