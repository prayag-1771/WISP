"""ReplaySource — replays a recorded raw-CSI log file through the same interface.

Reads a CSV file written by ingest.logger.RawLogger and yields the same
``(timestamp, amplitude)`` tuples the live stream would. Deterministic: identical input
→ identical output, so it powers the evaluation harness (S9) and doubles as a safe demo
fallback.
"""

from __future__ import annotations

from typing import Iterator, Optional, Tuple

import numpy as np

from .base import CSISource


class ReplaySource(CSISource):
    """Replays a recorded CSI log (RawLogger CSV) as if it were live."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._duration: Optional[float] = None

    @property
    def total_duration(self) -> float:
        """Length of the recording in seconds (first packet to last).

        The evaluation harness divides false alarms by this to produce the gate number, so
        a source without it silently reports false-alarms-per-week as infinity. Computed by
        scanning the timestamp column once and cached; the file is read again for the
        replay itself, which keeps this side-effect-free.
        """
        if self._duration is None:
            first = last = None
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip() or line.startswith("#"):
                        continue
                    t = float(line.split(",", 1)[0])
                    if first is None:
                        first = t
                    last = t
            self._duration = 0.0 if first is None or last is None else last - first
        return self._duration

    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split(",")
                t = float(parts[0])
                amp = np.array(parts[1:], dtype=np.float64)
                yield t, amp
