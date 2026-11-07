"""Small statistics helpers shared by Monte Carlo and the domain models."""

from __future__ import annotations

import math


def percentile(values: list[float], q: float) -> float:
    """The q-th percentile (0-100) using linear interpolation.

    Sort the values and imagine them at positions 0..n-1. The q-th
    percentile sits at position (n - 1) * q / 100; if that falls between
    two values we interpolate. This matches numpy's default method.
    """
    if not values:
        raise ValueError("percentile of an empty list")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lower, upper = math.floor(pos), math.ceil(pos)
    if lower == upper:
        return float(ordered[lower])
    fraction = pos - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
