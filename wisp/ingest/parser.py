"""S1 — parse a raw CSI_DATA serial line into a per-subcarrier amplitude array.

The ESP-IDF CSI firmware prints CSV-ish lines that end in a bracketed list of
interleaved I/Q integers, e.g.::

    CSI_DATA,STA,aa:bb:cc:dd:ee:ff,-40,11,...,[12 -8 5 3 -2 9 ...]

This turns one such line into a 1-D amplitude array (``sqrt(i^2 + q^2)`` per subcarrier).
Pure function, no hardware — so it is unit-testable against captured example lines.
The exact column layout varies by firmware; only the trailing ``[...]`` I/Q block is
parsed here, which is the part every ESP-IDF CSI variant emits.
"""

from __future__ import annotations

import numpy as np


def parse_csi_line(line: str) -> np.ndarray:
    """Parse one CSI_DATA line into a float amplitude array.

    Returns ``amplitude[subcarrier]`` = ``sqrt(I^2 + Q^2)`` for each subcarrier.
    Raises ``ValueError`` if the line has no ``[...]`` I/Q block or an odd count.
    """
    start = line.find("[")
    end = line.find("]", start + 1)
    if start == -1 or end == -1:
        raise ValueError(f"no CSI I/Q block found in line: {line[:60]!r}")

    raw = line[start + 1:end].replace(",", " ").split()
    iq = np.array(raw, dtype=np.float64)
    if iq.size % 2 != 0:
        raise ValueError(f"odd number of I/Q values ({iq.size}); expected interleaved pairs")

    i = iq[0::2]
    q = iq[1::2]
    return np.hypot(i, q)
