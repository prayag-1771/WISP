"""S5.2 — rule discriminators that name a confirmed collapse.

Once the temporal layer (S6) confirms "disturbance -> prolonged stillness", this decides
*which kind* of collapse it was:

- **sudden** — the triggering disturbance carried a sharp amplitude transient
  (a body hitting the floor): transient_sharpness above the room's normal ceiling.
- **slow**   — no sharp transient; motion simply declined and then stayed still
  (a gradual slump).

The steady-periodic (fan/HVAC) notch is handled upstream: because calibration records
the room *with* the fan running, its steady motion is part of "normal", so it never
raises an anomaly in the first place.
"""

from __future__ import annotations


def classify(trigger_sharpness: float, sharp_threshold: float) -> str:
    """Return 'sudden_collapse' or 'slow_collapse' for a confirmed event.

    Parameters
    ----------
    trigger_sharpness : float
        The peak transient_sharpness observed during the disturbance that preceded
        this stillness.
    sharp_threshold : float
        The room's normal sharpness ceiling (from calibration percentiles).
    """
    return "sudden_collapse" if trigger_sharpness >= sharp_threshold else "slow_collapse"
