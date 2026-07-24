"""S1.6 — CSISource: the one interface the entire brain hides behind.

Every downstream module (ingest, preprocess, features, detect, evaluate) consumes
a CSISource and nothing else. That means synthetic data, replayed log files, and the
live ESP32 serial stream are interchangeable: the hardware becomes a plug-in, not a
dependency. Build and test everything against SyntheticSource now; write the live
SerialSource last, when the ESP32s are streaming.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Tuple

import numpy as np


class CSISource(ABC):
    """Abstract source of CSI amplitude samples.

    Concrete implementations: SyntheticSource, ReplaySource, SerialSource.
    """

    @abstractmethod
    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        """Yield ``(timestamp, amplitude)`` tuples, one per CSI packet.

        Parameters
        ----------
        (none)

        Yields
        ------
        timestamp : float
            Seconds. Monotonic within a stream. For live sources this is wall-clock
            arrival time; for replay it is the recorded packet time.
        amplitude : np.ndarray
            1-D float array of per-subcarrier amplitudes for this packet. Length is
            the raw subcarrier count (masking happens later, in preprocess). Dropped
            packets are NOT interpolated here — gaps show up as jumps in timestamp.
        """
        raise NotImplementedError
