"""ReplaySource — replays a recorded raw-CSI log file through the same interface.

Reads a file written by ingest.logger and yields the same ``(timestamp, amplitude)``
tuples the live stream would. Deterministic: identical input → identical output, so it
powers the evaluation harness (S9) and doubles as a safe demo fallback.
"""

from __future__ import annotations

from typing import Iterator, Tuple

import numpy as np

from .base import CSISource


class ReplaySource(CSISource):
    """Replays a recorded CSI log as if it were live."""

    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        raise NotImplementedError("ReplaySource.stream — reads a logged file, yields packets.")
