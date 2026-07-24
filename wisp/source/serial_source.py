"""SerialSource — the ONLY file that touches hardware. Write this LAST.

Reads CSI_DATA lines from the RX ESP32 over pyserial, hands each line to ingest.parser,
and yields ``(timestamp, amplitude)`` like every other source. When this one small file
works, the entire already-tested brain runs on live data unchanged.
"""

from __future__ import annotations

from typing import Iterator, Tuple

import numpy as np

from .base import CSISource


class SerialSource(CSISource):
    """Live CSI stream from the RX ESP32 over a serial port."""

    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        raise NotImplementedError("SerialSource.stream — write LAST, when hardware streams.")
