"""Colour-based silhouette measurement for the noise-free calibration fixture."""

import numpy as np


def fiducial_centroid(rgb, colour):
    values = rgb.astype(float)
    # Sphere material dominant/secondary ratio is 1/.03 = 33.3; the blue
    # board's largest dominant/next-largest ratio is .35/.13 = 2.69.
    # A ratio of 5 separates those materials without selecting only the
    # illuminated hemisphere. Exclude only zero signal, not dim surface pixels.
    mask = values[:, :, colour] > 0
    for other in set(range(3)) - {colour}:
        mask &= values[:, :, colour] > 5 * values[:, :, other]
    rows, columns = np.where(mask)
    assert len(rows) > 20, "insufficient fiducial pixels"
    return float(columns.mean()), float(rows.mean())
