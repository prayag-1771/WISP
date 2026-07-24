"""S4 — one-room calibration. Thresholds come from the room's OWN percentile stats.

Fit a RoomProfile from several hours of that room's "normal": the subcarrier mask,
per-feature thresholds (from percentiles, not global constants), any periodic
fan/HVAC notch, and the trained anomaly model. One room, one profile, stored to disk.
Recalibration UI / drift detection / multi-room are all post-MVP.
"""

from __future__ import annotations


class RoomProfile:
    """Mask + thresholds + notch + model, all fit from one room's normal recording."""

    @classmethod
    def fit(cls, recording) -> "RoomProfile":
        """Fit a profile from a normal-room recording (a CSISource / replay file)."""
        raise NotImplementedError("RoomProfile.fit — learn this room's normal.")

    def save(self, path: str) -> None:
        raise NotImplementedError("RoomProfile.save")

    @classmethod
    def load(cls, path: str) -> "RoomProfile":
        raise NotImplementedError("RoomProfile.load")
