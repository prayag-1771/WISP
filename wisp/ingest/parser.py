"""S1 — parse a raw CSI_DATA serial line into a per-subcarrier amplitude array.

The ESP-IDF CSI firmware prints lines like ``CSI_DATA,...,[i0 q0 i1 q1 ...]``. This
turns one such line into a 1-D amplitude array (sqrt(i^2 + q^2) per subcarrier).
Pure function, no hardware — so it's unit-testable against captured example lines.
"""

from __future__ import annotations

import numpy as np


def parse_csi_line(line: str) -> np.ndarray:
    """Parse one CSI_DATA line into a float amplitude array. Returns amplitude[subcarrier]."""
    raise NotImplementedError("parse_csi_line — CSI_DATA line -> amplitude array.")
