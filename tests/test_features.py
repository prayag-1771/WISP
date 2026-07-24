"""S3.7 — features on a known signal.

Once features/extract.py is implemented, these pin its behavior on inputs whose answer
you can work out by hand: a pure sine (known motion intensity), a step (known transient
sharpness), and a flat/quiet window (stillness accumulates). Currently xfail stubs.
"""

import pytest


@pytest.mark.xfail(reason="features.extract not implemented yet", strict=False)
def test_sine_has_expected_motion_intensity():
    from wisp.features.extract import extract  # noqa: F401
    raise NotImplementedError


@pytest.mark.xfail(reason="features.extract not implemented yet", strict=False)
def test_step_has_high_transient_sharpness():
    from wisp.features.extract import extract  # noqa: F401
    raise NotImplementedError


@pytest.mark.xfail(reason="features.extract not implemented yet", strict=False)
def test_flat_window_accumulates_stillness():
    from wisp.features.extract import extract  # noqa: F401
    raise NotImplementedError
