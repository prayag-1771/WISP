"""S3 — the only three features that matter for MVP.

- motion_intensity   : cross-subcarrier amplitude variance (the workhorse)
- transient_sharpness: max first-difference (catches sudden collapse)
- stillness_duration : seconds since motion last exceeded a floor (catches slow collapse)

Rich contextual features and the breathing band are deliberately skipped for MVP.
"""

from __future__ import annotations

import numpy as np


def extract(window: np.ndarray) -> dict:
    """Compute {motion_intensity, transient_sharpness, stillness_duration} for a window."""
    raise NotImplementedError("extract — motion, sharpness, stillness.")
