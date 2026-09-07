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


# --- one-board sensor: CSI dropouts ------------------------------------------------
# A single ESP32 rides on someone else's traffic, so the stream can simply stop for a
# while. Nothing arrives during a gap, so the machine sees a jump in timestamp — which,
# untreated, is indistinguishable from "the room went quiet and stayed quiet".


def _sm_gap(**kw):
    args = dict(
        still_threshold=1.0,
        occupied_threshold=3.0,
        sharp_threshold=5.0,
        confirm_s=3.0,
        slow_confirm_s=6.0,
        recent_activity_s=10.0,
        debounce_s=2.0,
        gap_reset_s=2.0,
    )
    args.update(kw)
    return DetectionStateMachine(**args)


def _stillness_spanning_a_dropout():
    """Someone is active, settles, and then the CSI link dies for 30 s. The dangerous part
    is that stillness was ALREADY accumulating when the stream stopped: on the first packet
    back, elapsed-time arithmetic credits the whole dead period as observed stillness."""
    samples = [(0.0, 5, 0), (0.5, 5, 0), (1.0, 5, 0)]     # occupied
    samples += [(1.5, 0, 0), (2.0, 0, 0)]                  # settling, stillness starts
    samples += [(32.0, 0, 0), (32.5, 0, 0)]                # link back, 30 s unobserved
    return samples


def test_data_gap_does_not_manufacture_a_slow_collapse():
    sm = _sm_gap()
    assert _run(sm, _stillness_spanning_a_dropout()) == []
    assert sm.gaps_seen == 1


def test_gap_guard_off_reproduces_the_false_alarm():
    """The same input with gap_reset_s=0 (the pre-existing behaviour) DOES fire, on 30
    seconds of stillness nobody measured — the bug this guard exists to fix, pinned here so
    it cannot quietly come back."""
    sm = _sm_gap(gap_reset_s=0.0)
    alerts = _run(sm, _stillness_spanning_a_dropout())
    assert len(alerts) == 1
    assert alerts[0].kind == "slow_collapse"
    assert alerts[0].stillness_s > 25          # credited to a dead link, not to the room


def test_detection_still_works_after_a_gap():
    """The guard discards history, it does not disable the detector: a full pattern that
    happens entirely after the dropout must still confirm."""
    sm = _sm_gap()
    samples = [(0.0, 5, 0), (0.5, 5, 0)]                          # pre-gap activity
    samples += [(20.0, 5, 0), (20.5, 5, 0), (21.0, 5, 10)]        # post-gap: active + impact
    samples += [(21.5 + 0.5 * i, 0, 0) for i in range(10)]        # then stillness
    alerts = _run(sm, samples)
    assert len(alerts) == 1
    assert alerts[0].kind == "sudden_collapse"
    assert sm.gaps_seen == 1


def test_normal_sample_spacing_is_not_a_gap():
    sm = _sm_gap()
    samples = [(0.0, 5, 0), (0.5, 5, 0), (1.0, 5, 10)]
    samples += [(1.5 + 0.5 * i, 0, 0) for i in range(8)]
    assert len(_run(sm, samples)) == 1
    assert sm.gaps_seen == 0
