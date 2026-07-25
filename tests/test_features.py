"""S3.7 — features on known signals whose answers you can work out by hand."""

import numpy as np

from wisp.features.extract import extract


def test_flat_window_has_near_zero_features():
    """A perfectly still window: no variance, no first-difference."""
    w = np.full((50, 10), 5.0)
    f = extract(w)
    assert f["motion_intensity"] < 1e-9
    assert f["transient_sharpness"] < 1e-9


def test_sine_has_more_motion_than_flat():
    """A sine wiggling over time raises motion_intensity above a flat window."""
    t = np.linspace(0, 2 * np.pi, 50)
    sine = np.stack([np.sin(t)] * 10, axis=1)     # (50, 10)
    flat = np.full((50, 10), 1.0)
    assert extract(sine)["motion_intensity"] > extract(flat)["motion_intensity"]
    assert extract(sine)["motion_intensity"] > 0.1


def test_step_has_high_transient_sharpness():
    """A step jump of 9 gives sharpness ≈ 9; a gradual ramp of the same span is tiny."""
    step = np.ones((50, 10))
    step[25:] = 10.0
    ramp = np.linspace(1.0, 10.0, 50).reshape(-1, 1) * np.ones((1, 10))
    assert extract(step)["transient_sharpness"] > extract(ramp)["transient_sharpness"]
    assert extract(step)["transient_sharpness"] > 5.0
