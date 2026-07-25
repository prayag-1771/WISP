"""S6 tests — the temporal logic that decides confirmed collapses vs noise.

These pin the three behaviours the gate depends on:
  - a sharp disturbance followed by persistent stillness -> sudden collapse
  - occupancy followed by prolonged stillness (no sharp) -> slow collapse
  - an empty (never-occupied) room -> NOTHING, no matter how long it stays still
"""

from wisp.detect.state_machine import DetectionStateMachine


def _sm():
    return DetectionStateMachine(
        still_threshold=1.0,
        occupied_threshold=3.0,
        sharp_threshold=5.0,
        confirm_s=3.0,
        slow_confirm_s=6.0,
        recent_activity_s=10.0,
        debounce_s=2.0,
    )


def _run(sm, samples):
    """samples: list of (t, motion_intensity, transient_sharpness) -> list of alerts."""
    alerts = []
    for t, m, s in samples:
        a = sm.update(t, {"motion_intensity": m, "transient_sharpness": s})
        if a is not None:
            alerts.append(a)
    return alerts


def test_sudden_collapse_confirmed():
    sm = _sm()
    samples = [(0.0, 5, 0), (0.5, 5, 0), (1.0, 5, 10)]           # active + sharp impact
    samples += [(1.5 + 0.5 * i, 0, 0) for i in range(8)]          # stillness 1.5 .. 5.0 s
    alerts = _run(sm, samples)
    assert len(alerts) == 1
    assert alerts[0].kind == "sudden_collapse"


def test_slow_collapse_confirmed():
    sm = _sm()
    samples = [(0.0, 5, 0), (0.5, 5, 0), (1.0, 5, 0), (1.5, 5, 0), (2.0, 5, 0)]  # occupied
    samples += [(2.5 + 0.5 * i, 0, 0) for i in range(15)]         # stillness through 9.5 s
    alerts = _run(sm, samples)
    assert len(alerts) == 1
    assert alerts[0].kind == "slow_collapse"


def test_empty_room_never_fires():
    sm = _sm()
    samples = [(0.5 * i, 0, 0) for i in range(60)]                # 30 s of pure stillness
    assert _run(sm, samples) == []
