"""SyntheticSource — a fake room you can build the entire pipeline against NOW.

Generates CSISource-compatible ``(timestamp, amplitude)`` packets that simulate a real
room's CSI amplitude: a static per-subcarrier baseline, dead null/guard subcarriers,
sensor noise, and — crucially — the *event signatures* the detector must key on:

    empty       low-variance baseline (nobody moving)
    walk        sustained broadband amplitude fluctuation
    sit         low, steady motion
    sudden_fall brief motion -> sharp high-amplitude transient -> abrupt stillness
    slow_fall   motion that gradually declines -> prolonged stillness

An optional periodic component ("fan") can be overlaid on the whole recording so you can
later test notch suppression. Because the source also records the ground-truth onset of
every staged fall, the evaluation harness (S9) has labels to score against — today, with
zero hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Tuple

import numpy as np

from .base import CSISource

# Labels the synthetic room can emit. Falls are the two we score recall on.
NORMAL_LABELS = ("empty", "walk", "sit")
FALL_LABELS = ("sudden_fall", "slow_fall")


@dataclass
class Event:
    """Ground truth for one staged fall: when it began and what kind it was."""

    onset: float          # seconds — when the collapse actually starts
    end: float            # seconds — end of the segment
    label: str            # "sudden_fall" | "slow_fall"


class SyntheticSource(CSISource):
    """Simulated CSI stream. Build against this before the ESP32s exist.

    Parameters
    ----------
    segments : list of (label, duration_seconds)
        The room's scripted timeline, e.g. ``[("empty", 5), ("walk", 10), ("sudden_fall", 15)]``.
    sample_rate_hz : float
        Packets per second (matches the real target of ~100 Hz).
    n_subcarriers : int
        Raw subcarrier count before masking (ESP32 HT20 ≈ 64; ~52 survive masking).
    fan : bool
        If True, overlay a steady periodic component on the whole recording.
    seed : int
        RNG seed — the source is fully deterministic for a given seed.
    """

    def __init__(
        self,
        segments: List[Tuple[str, float]],
        sample_rate_hz: float = 100.0,
        n_subcarriers: int = 64,
        fan: bool = False,
        fan_hz: float = 5.0,
        seed: int = 0,
    ) -> None:
        self.segments = segments
        self.sample_rate_hz = float(sample_rate_hz)
        self.dt = 1.0 / self.sample_rate_hz
        self.n_subcarriers = int(n_subcarriers)
        self.fan = fan
        self.fan_hz = fan_hz
        self.rng = np.random.default_rng(seed)

        # A static room fingerprint: per-subcarrier baseline amplitude + motion sensitivity.
        # Null/guard subcarriers (band edges + DC) are "dead" — near-zero, no signal.
        self.dead = np.zeros(self.n_subcarriers, dtype=bool)
        edge = max(2, self.n_subcarriers // 16)
        self.dead[:edge] = True
        self.dead[-edge:] = True
        self.dead[self.n_subcarriers // 2] = True  # DC
        self.active = ~self.dead

        na = int(self.active.sum())
        self.base = np.zeros(self.n_subcarriers)
        self.base[self.active] = self.rng.uniform(15.0, 40.0, na)
        self.gain = np.zeros(self.n_subcarriers)
        self.gain[self.active] = self.rng.uniform(3.0, 8.0, na)
        self.fan_mask = np.zeros(self.n_subcarriers)
        self.fan_mask[self.active] = self.rng.uniform(0.5, 1.5, na)

        self.noise_sd = 0.5
        self.events: List[Event] = []
        self._build_timeline()

    # ------------------------------------------------------------------ timeline
    def _build_timeline(self) -> None:
        """Precompute segment boundaries and record ground-truth fall onsets."""
        self._starts: List[float] = []
        t = 0.0
        for label, dur in self.segments:
            self._starts.append(t)
            if label == "sudden_fall":
                self.events.append(Event(onset=t + 1.5, end=t + dur, label=label))
            elif label == "slow_fall":
                self.events.append(Event(onset=t, end=t + dur, label=label))
            t += dur
        self.total_duration = t

    def _segment_at(self, t: float) -> Tuple[str, float]:
        """Return (label, local_time_within_segment) for global time t."""
        for (label, dur), start in zip(self.segments, self._starts):
            if start <= t < start + dur:
                return label, t - start
        return "empty", 0.0

    # ------------------------------------------------------------ motion envelope
    def _motion(self, label: str, tau: float) -> Tuple[float, float]:
        """Return (motion_level, transient_add) for a label at local time tau.

        motion_level scales the random cross-subcarrier fluctuation (=> variance).
        transient_add is a deterministic amplitude bump modelling a body hitting the
        floor (=> a sharp first-difference the detector reads as a sudden collapse).
        """
        if label == "empty":
            return 0.02, 0.0
        if label == "walk":
            return 0.45 + 0.15 * np.sin(2 * np.pi * 0.3 * tau), 0.0
        if label == "sit":
            return 0.12, 0.0
        if label == "sudden_fall":
            impact_at, impact_dur = 1.5, 0.2
            if tau < impact_at:
                return 0.35, 0.0                      # moving beforehand
            if tau < impact_at + impact_dur:
                shape = 1.0 - abs((tau - impact_at) / impact_dur - 0.5) * 2.0
                return 1.6, 18.0 * shape              # sharp transient
            return 0.02, 0.0                          # abrupt stillness afterwards
        if label == "slow_fall":
            decline = 5.0
            if tau < decline:
                return 0.35 * (1.0 - tau / decline) + 0.02, 0.0  # gradual sag
            return 0.02, 0.0                          # prolonged stillness
        return 0.02, 0.0

    # ------------------------------------------------------------------- stream
    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        n = int(round(self.total_duration * self.sample_rate_hz))
        na = int(self.active.sum())
        for i in range(n):
            t = i * self.dt
            label, tau = self._segment_at(t)
            m, transient = self._motion(label, tau)

            amp = np.zeros(self.n_subcarriers)
            amp[self.active] = self.base[self.active]
            amp[self.active] += m * self.gain[self.active] * self.rng.standard_normal(na)
            amp[self.active] += transient
            if self.fan:
                amp[self.active] += 2.0 * np.sin(2 * np.pi * self.fan_hz * t) * self.fan_mask[self.active]
            amp += self.noise_sd * self.rng.standard_normal(self.n_subcarriers)
            np.clip(amp, 0.0, None, out=amp)          # amplitudes are non-negative
            yield t, amp

    # --------------------------------------------------------------- factories
    @classmethod
    def normal_only(cls, minutes: float = 3.0, **kw) -> "SyntheticSource":
        """A calibration recording: only normal room life, no falls."""
        block = [("empty", 20.0), ("walk", 30.0), ("sit", 20.0), ("walk", 20.0)]
        reps = max(1, int(round(minutes * 60.0 / sum(d for _, d in block))))
        return cls(block * reps, **kw)

    @classmethod
    def demo(cls, **kw) -> "SyntheticSource":
        """A short labeled test timeline: normal life + one sudden + one slow fall."""
        segments = [
            ("empty", 10.0),
            ("walk", 20.0),
            ("sit", 10.0),
            ("sudden_fall", 25.0),   # impact then long stillness
            ("walk", 15.0),
            ("slow_fall", 40.0),     # gradual sag then long stillness
            ("empty", 5.0),
        ]
        return cls(segments, **kw)
