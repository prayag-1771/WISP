"""S3 — the features that matter for MVP.

``extract`` turns one short window (shape ``(n_samples, n_subcarriers)``) into two
instantaneous, stateless numbers:

- **motion_intensity**  — mean over subcarriers of the temporal variance within the
  window. The workhorse: high while someone moves, near-zero when the room is still.
- **transient_sharpness** — the largest single-step change (max over time of the mean
  absolute first-difference across subcarriers). Spikes when a body hits the floor.

The third MVP signal — **stillness duration** — is inherently temporal (it only has
meaning *across* windows), so it is accumulated by the state machine (S6) from the
motion_intensity stream rather than computed here.

``feature_stream`` glues cleaning + rolling windows + extraction onto any CSISource,
yielding ``(timestamp, {motion_intensity, transient_sharpness})`` — the one path used
identically by calibration, live detection, and the evaluation harness.
"""

from __future__ import annotations

from collections import deque
from typing import Iterator, Tuple

import numpy as np

from ..preprocess.clean import clean


def extract(window: np.ndarray) -> dict:
    """Compute {motion_intensity, transient_sharpness} for a window of shape (T, K)."""
    if window.ndim != 2 or window.shape[0] < 2:
        raise ValueError("window must be 2-D with at least 2 time samples")

    motion_intensity = float(np.mean(np.var(window, axis=0)))
    diffs = np.abs(np.diff(window, axis=0))            # (T-1, K)
    transient_sharpness = float(np.max(np.mean(diffs, axis=1)))
    return {"motion_intensity": motion_intensity, "transient_sharpness": transient_sharpness}


def feature_stream(
    source,
    mask: np.ndarray,
    win_samples: int,
    hop_samples: int,
) -> Iterator[Tuple[float, dict]]:
    """Yield (timestamp, features) over a CSISource using rolling short windows.

    Each amplitude packet is cleaned + masked and pushed into a ring buffer; once the
    buffer is full, features are emitted every ``hop_samples`` packets.
    """
    buf: deque = deque(maxlen=win_samples)
    since_hop = 0
    for t, amp in source.stream():
        buf.append(clean(amp, mask))
        since_hop += 1
        if len(buf) == win_samples and since_hop >= hop_samples:
            since_hop = 0
            yield t, extract(np.asarray(buf))
