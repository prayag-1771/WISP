"""ReplaySource — replays a recorded raw-CSI log file through the same interface.

Reads a CSV file written by ingest.logger.RawLogger and yields the same
``(timestamp, amplitude)`` tuples the live stream would. Deterministic: identical input
→ identical output, so it powers the evaluation harness (S9) and doubles as a safe demo
fallback.
"""

from __future__ import annotations

from typing import Iterator, Tuple

import numpy as np

from .base import CSISource


class ReplaySource(CSISource):
    """Replays a recorded CSI log (RawLogger CSV) as if it were live."""

    def __init__(self, path: str) -> None:
        self.path = path

    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split(",")
                t = float(parts[0])
                amp = np.array(parts[1:], dtype=np.float64)
                yield t, amp
