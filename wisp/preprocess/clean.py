"""S2 — minimum-viable preprocessing (amplitude only; phase skipped for MVP).

Two pieces:

- ``subcarrier_mask`` learns, from an empty/normal recording's variance + mean profile,
  which subcarriers carry signal — dropping null/guard/dead ones.
- ``clean`` applies that mask and does a Hampel outlier rejection across the subcarrier
  axis (a spike on one subcarrier is replaced by the local median), which kills the
  impulsive glitches CSI hardware produces.

Temporal band-pass / detrending happens at the windowing stage in features.extract
(each window has its per-subcarrier mean removed), so a single amplitude vector here
needs no time context. Phase is deliberately ignored for MVP.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter


def subcarrier_mask(amps: np.ndarray, var_frac: float = 1e-3, mean_frac: float = 1e-2) -> np.ndarray:
    """Learn a boolean keep-mask from a recording ``amps`` of shape (n_packets, n_subcarriers).

    A subcarrier is kept if both its variance and its mean amplitude are a non-trivial
    fraction of the strongest subcarrier's — null/guard/dead carriers sit near zero and
    are dropped.
    """
    var = amps.var(axis=0)
    mean = np.abs(amps).mean(axis=0)
    keep = (var > var.max() * var_frac) & (mean > mean.max() * mean_frac)
    return keep


def clean(amplitude: np.ndarray, mask: np.ndarray, hampel_size: int = 5, n_sigma: float = 3.0) -> np.ndarray:
    """Mask dead subcarriers, then Hampel-reject outliers across the subcarrier axis."""
    x = amplitude[mask]
    med = median_filter(x, size=hampel_size, mode="nearest")
    mad = median_filter(np.abs(x - med), size=hampel_size, mode="nearest")
    thr = n_sigma * 1.4826 * mad
    return np.where(np.abs(x - med) > thr, med, x)
