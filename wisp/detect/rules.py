"""S5.2 — rule discriminators that name the anomaly.

- sudden fall : sharp transient -> stillness
- slow collapse: gradual decline -> prolonged stillness

Also notches out steady periodic sources (fan/HVAC) identified during calibration.
"""

from __future__ import annotations


def classify(features: dict, profile) -> str | None:
    """Return 'sudden', 'slow', or None given current features + room profile."""
    raise NotImplementedError("classify — sudden vs slow vs nothing.")
