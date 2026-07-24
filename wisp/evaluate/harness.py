"""S9 — THE ACTUAL DELIVERABLE. Runs the whole pipeline over labeled recordings.

Replays recorded CSI through the exact live pipeline (deterministic) and computes the
gate metrics:
  - recall on staged collapses  (target: catch essentially all)
  - FALSE ALARMS PER DAY/WEEK   (the number that decides everything)
  - detection latency
Labels come from a simple CSV convention (staged fall / walk / empty / sit / pet).
"""

from __future__ import annotations


def evaluate(recording, labels, profile) -> dict:
    """Replay a labeled recording through the pipeline; return {recall, false_alarms, latency}."""
    raise NotImplementedError("evaluate — recall, false-alarms/week, latency.")
