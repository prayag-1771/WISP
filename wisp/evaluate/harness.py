"""S9 — THE ACTUAL DELIVERABLE. Runs the whole pipeline over labeled recordings.

Replays recorded/synthetic CSI through the exact live pipeline (`pipeline.run_detection`,
so it is deterministic) and computes the gate metrics:

  - recall on staged collapses  (target: catch essentially all)
  - FALSE ALARMS PER DAY/WEEK   (the number that decides everything)
  - detection latency
  - kind accuracy (did sudden/slow get labelled right)

Ground-truth events are the `Event` list a SyntheticSource exposes (or, for real
recordings, loaded from a labels CSV — see `load_events`).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import List, Optional

from ..calibrate.profile import RoomProfile
from ..pipeline import run_detection
from ..source.base import CSISource
from ..source.synthetic import Event

SECONDS_PER_DAY = 86400.0
SECONDS_PER_WEEK = 604800.0
KIND_OF = {"sudden_fall": "sudden_collapse", "slow_fall": "slow_collapse"}


@dataclass
class Metrics:
    n_events: int
    n_detected: int
    false_alarms: int
    duration_s: float
    latencies: List[float]
    kind_correct: int

    @property
    def recall(self) -> float:
        return self.n_detected / self.n_events if self.n_events else float("nan")

    @property
    def false_alarms_per_day(self) -> float:
        return self.false_alarms / self.duration_s * SECONDS_PER_DAY if self.duration_s else float("nan")

    @property
    def false_alarms_per_week(self) -> float:
        return self.false_alarms / self.duration_s * SECONDS_PER_WEEK if self.duration_s else float("nan")

    @property
    def mean_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else float("nan")

    def report(self) -> str:
        lines = [
            "=== wisp evaluation (Phase 0 gate) ===",
            f"recording duration     : {self.duration_s:.0f} s",
            f"staged collapses       : {self.n_events}",
            f"recall                 : {self.n_detected}/{self.n_events}  ({self.recall*100:.0f}%)",
            f"kind labelled correctly: {self.kind_correct}/{self.n_detected}",
            f"detection latency (avg): {self.mean_latency:.1f} s",
            f"FALSE ALARMS           : {self.false_alarms}",
            f"  -> per day           : {self.false_alarms_per_day:.2f}",
            f"  -> per week           : {self.false_alarms_per_week:.2f}   <-- the gate number",
        ]
        return "\n".join(lines)


def load_events(path: str) -> List[Event]:
    """Load ground-truth events from a labels CSV: columns onset,end,label."""
    events: List[Event] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            events.append(Event(onset=float(row["onset"]), end=float(row["end"]), label=row["label"]))
    return events


def evaluate(
    source: CSISource,
    events: List[Event],
    profile: RoomProfile,
    duration_s: Optional[float] = None,
    grace_s: float = 30.0,
) -> Metrics:
    """Replay a labeled recording through the pipeline and return the gate metrics.

    An alert is credited to an event if it lands between the event onset and
    ``end + grace_s`` (a collapse alert legitimately arrives some seconds after onset,
    once stillness has persisted). Any alert not matched to an event is a false alarm.
    """
    alerts = [alert for _, alert in run_detection(source, profile)]

    matched = [False] * len(events)
    latencies: List[float] = []
    kind_correct = 0
    false_alarms = 0

    for alert in alerts:
        hit = None
        for i, ev in enumerate(events):
            if not matched[i] and ev.onset <= alert.timestamp <= ev.end + grace_s:
                hit = i
                break
        if hit is None:
            false_alarms += 1
        else:
            matched[hit] = True
            latencies.append(alert.timestamp - events[hit].onset)
            if KIND_OF.get(events[hit].label) == alert.kind:
                kind_correct += 1

    if duration_s is None:
        duration_s = getattr(source, "total_duration", 0.0)

    return Metrics(
        n_events=len(events),
        n_detected=sum(matched),
        false_alarms=false_alarms,
        duration_s=float(duration_s),
        latencies=latencies,
        kind_correct=kind_correct,
    )
