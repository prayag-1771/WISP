"""S1.5 — raw CSI logger. DO NOT SKIP: every hour logged early is irreplaceable data.

Continuously writes each ``(timestamp, amplitude)`` packet to disk in a format
ReplaySource can read back deterministically. This is simultaneously your dataset,
your evaluation input, and your live-demo safety net.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np


class RawLogger:
    """Appends CSI packets to a log file on disk."""

    def log(self, timestamp: float, amplitude: np.ndarray) -> None:
        """Write one packet. Called for every packet as it streams by."""
        raise NotImplementedError("RawLogger.log — append one packet to disk.")
