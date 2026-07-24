"""SyntheticSource — a fake room you can build the entire pipeline against NOW.

Generates CSISource-compatible ``(timestamp, amplitude)`` packets simulating an empty
room's baseline noise, plus optional scripted events (walk, sudden fall, slow collapse,
periodic fan/HVAC). This is what lets you develop, test, and demo with zero hardware.
"""

from __future__ import annotations

from typing import Iterator, Tuple

import numpy as np

from .base import CSISource


class SyntheticSource(CSISource):
    """Simulated CSI stream. Build against this before the ESP32s exist."""

    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        raise NotImplementedError("SyntheticSource.stream — you'll write this first.")
