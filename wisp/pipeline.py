"""The shared detection loop: CSISource + RoomProfile -> stream of Alerts.

One code path so that live detection (scripts/run_live.py) and the evaluation harness
(S9) run the *exact same* pipeline — features -> anomaly model -> temporal state machine.
Keeping it here means "what you demo" and "what you measure" can never silently diverge.
"""

from __future__ import annotations

from typing import Iterator, Tuple

from .calibrate.profile import RoomProfile
from .detect.state_machine import Alert, DetectionStateMachine
from .features.extract import feature_stream
from .source.base import CSISource


def _state_machine(profile: RoomProfile) -> DetectionStateMachine:
    return DetectionStateMachine(
        still_threshold=profile.still_threshold,
        occupied_threshold=profile.occupied_threshold,
        sharp_threshold=profile.sharp_threshold,
        confirm_s=profile.confirm_s,
        slow_confirm_s=profile.slow_confirm_s,
        recent_activity_s=profile.recent_activity_s,
        debounce_s=profile.debounce_s,
    )


def run_detection(source: CSISource, profile: RoomProfile) -> Iterator[Tuple[float, Alert]]:
    """Yield (timestamp, Alert) for every confirmed collapse in the source stream."""
    sm = _state_machine(profile)
    for t, feat in feature_stream(source, profile.mask, profile.win_samples, profile.hop_samples):
        alert = sm.update(t, feat, is_anomaly=profile.model.is_anomaly(feat))
        if alert is not None:
            yield t, alert
