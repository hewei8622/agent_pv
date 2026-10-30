"""Synthetic detector tests only; these images are not render evidence."""

import numpy as np
import pytest
from fiducials import fiducial_centroid


def shaded_disk(colour, offset=0):
    image = np.empty((64, 64, 3), dtype=np.uint8)
    image[:] = (3, 13, 35)  # Board chromaticity must not enter the sphere mask.
    yy, xx = np.indices((64, 64))
    disk = (xx - 32 - offset) ** 2 + (yy - 32) ** 2 <= 9**2
    image[disk] = 1
    # Asymmetric brightness must not move the measured silhouette centre.
    intensity = np.where(yy < 32, 200, 20)
    image[:, :, colour][disk] = intensity[disk]
    return image


@pytest.mark.parametrize("colour", [0, 1, 2])
def test_shading_does_not_shift_centroid(colour):
    assert fiducial_centroid(shaded_disk(colour), colour) == (32.0, 32.0)


@pytest.mark.parametrize("colour", [0, 1, 2])
def test_displaced_marker_still_fails_two_pixel_projection_limit(colour):
    x, _ = fiducial_centroid(shaded_disk(colour, offset=4), colour)
    assert abs(x - 32) > 2
