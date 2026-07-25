"""S1.5 — raw CSI logger. DO NOT SKIP: every hour logged early is irreplaceable data.

Continuously writes each ``(timestamp, amplitude)`` packet to disk in a plain CSV
format ReplaySource can read back deterministically:

    # wisp raw CSI log — columns: timestamp, amp_0, amp_1, ...
    0.000000,21.3,0.0,18.7,...
    0.010000,21.1,0.0,19.2,...

This is simultaneously your dataset, your evaluation input, and your live-demo safety net.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


class RawLogger:
    """Appends CSI packets to a CSV log file on disk. Usable as a context manager."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fh = open(path, "w", encoding="utf-8", newline="")
        self._fh.write("# wisp raw CSI log — columns: timestamp, amp_0, amp_1, ...\n")
        self._n: Optional[int] = None

    def log(self, timestamp: float, amplitude: np.ndarray) -> None:
        """Write one packet: the timestamp followed by every subcarrier amplitude."""
        if self._n is None:
            self._n = amplitude.size
        row = ",".join(f"{v:.4f}" for v in amplitude)
        self._fh.write(f"{timestamp:.6f},{row}\n")

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "RawLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
