"""S6 — temporal logic. THE false-alarm killer. DO NOT SKIP.

Single-window thresholding is exactly what produces false-alarm spam that fails the
gate. This requires a PATTERN OVER TIME: disturbance -> stillness persists >= T seconds
-> CONFIRMED, with debounce/hysteresis. Keeps an audit log of every state transition.
Severity tiers and per-home sensitivity are deferred, but the audit log stays.
"""

from __future__ import annotations


class DetectionStateMachine:
    """disturbance -> stillness persists >= T -> CONFIRMED, with debounce."""

    def update(self, timestamp: float, features: dict, label: str | None):
        """Advance the state machine one step. Returns a confirmed alert or None."""
        raise NotImplementedError("DetectionStateMachine.update — the false-alarm killer.")
