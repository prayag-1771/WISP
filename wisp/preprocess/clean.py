"""S2 — minimum-viable preprocessing (amplitude only; phase skipped for MVP).

Steps: drop null/guard + dead subcarriers (from an empty-room variance profile),
Hampel outlier rejection, band-pass the amplitude, and maintain rolling windows
(one short ~1 s for transients, one long ~3-5 s for stillness).
"""

from __future__ import annotations

import numpy as np


def clean(amplitude: np.ndarray) -> np.ndarray:
    """Clean one amplitude vector (mask dead subcarriers, reject outliers, band-pass)."""
    raise NotImplementedError("clean — drop dead subcarriers, Hampel, band-pass.")
