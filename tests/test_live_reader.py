"""The single-board live reader, tested with no board.

``csi_records`` is a pure generator over lines of text, so every behaviour that used to
need an ESP32 on a desk — AGC removal, width locking, gap counting, firmware diagnostics —
is checked here from string fixtures.
"""

import numpy as np
import pytest

from wisp.source.live_reader import (
    LinkStats,
    csi_records,
    measure_rate,
    parse_info_line,
)


def _line(iq, mac="ac:84:c6:11:22:33"):
    """One firmware-format CSI_DATA line carrying the given interleaved I/Q values."""
    body = " ".join(str(int(v)) for v in iq)
    return (f"CSI_DATA,SINGLE,{mac},-47,11,1,0,0,1,1,0,0,0,0,-93,0,6,0,1043216,0,42,0,"
            f"{len(iq)},[{body}]")


def _fake_clock(step=0.05, start=1000.0):
    """A clock that advances a fixed step per call (deterministic timestamps)."""
    t = [start - step]

    def clock():
        t[0] += step
        return t[0]

    return clock


def test_parses_firmware_lines_into_amplitudes():
    lines = [_line([3, 4] * 4) for _ in range(3)]
    recs = list(csi_records(lines, width_lock_packets=1, agc_alpha=0.0, clock=_fake_clock()))

    assert len(recs) == 3
    # amplitude = sqrt(3^2 + 4^2) = 5 on every subcarrier
    assert recs[0][1].shape == (4,)
    assert np.allclose(recs[0][1], 5.0)
    # first packet is t=0; timestamps are relative and increasing
    assert recs[0][0] == pytest.approx(0.0)
    assert recs[1][0] > recs[0][0]


def test_ignores_non_csi_chatter_and_counts_malformed():
    st = LinkStats()
    lines = [
        "I (523) wifi: mode : sta",              # boot chatter -> ignored silently
        "",
        _line([3, 4] * 4),
        "CSI_DATA,SINGLE,mac,-47,truncated line", # looks like CSI, has no [...] block
        _line([6, 8] * 4),
    ]
    recs = list(csi_records(lines, stats=st, width_lock_packets=1, agc_alpha=0.0,
                            clock=_fake_clock()))

    assert len(recs) == 2
    assert st.packets == 2
    assert st.malformed == 1


def test_agc_highpass_cancels_slow_gain_drift():
    """A packet-wide gain ramp is the receiver's AGC, not the room, and must not survive as
    motion. "Slow" is relative to the EMA time constant (~1/alpha packets): drift spread
    over hundreds of packets is what AGC actually looks like."""
    drifting = [_line([20 + 40 * n / 600.0, 0] * 8) for n in range(600)]
    st = LinkStats()
    recs = list(csi_records(drifting, stats=st, width_lock_packets=1, agc_alpha=0.03,
                            clock=_fake_clock()))

    means = np.array([r[1].mean() for r in recs])
    raw_spread = 60.0 / 20.0 - 1.0             # the gain tripled over the recording: 200%
    residual_spread = means[10:].max() / means[10:].min() - 1.0
    assert residual_spread < raw_spread / 10   # what survives is a tenth of that, or less
    assert means[10:].max() - means[10:].min() < 0.2


def test_agc_highpass_preserves_a_fast_change():
    """The flip side: a change fast enough to be a body moving must come through. The EMA
    cannot follow it, so it lands in the output where the detector can see it."""
    steady = [_line([30, 0] * 8)] * 40
    recs = list(csi_records(steady + [_line([30, 0] * 4 + [120, 0] * 4)],
                            width_lock_packets=1, agc_alpha=0.03, clock=_fake_clock()))

    before = recs[-2][1]
    after = recs[-1][1]
    assert before.max() / before.min() == pytest.approx(1.0, abs=0.01)   # flat while steady
    assert after.max() > 3.0 * after.min()                               # the change survives


def test_agc_disabled_leaves_amplitudes_raw():
    recs = list(csi_records([_line([30, 40] * 4)], width_lock_packets=1, agc_alpha=0.0,
                            clock=_fake_clock()))
    assert np.allclose(recs[0][1], 50.0)


def test_width_lock_replays_buffer_and_skips_odd_widths():
    """The fixed-width room mask raises IndexError on a wrong-width packet, so the reader
    must settle on the dominant width and drop the rest — not pass them through."""
    st = LinkStats()
    lines = ([_line([3, 4] * 8) for _ in range(6)]      # 8 subcarriers: the majority
             + [_line([3, 4] * 3)]                       # 3: an HT-LTF straggler
             + [_line([3, 4] * 8) for _ in range(3)])
    recs = list(csi_records(lines, stats=st, width_lock_packets=7, agc_alpha=0.0,
                            clock=_fake_clock()))

    assert st.width == 8
    assert {r[1].size for r in recs} == {8}
    assert len(recs) == 9
    assert st.width_skipped == 1


def test_counts_gaps_in_the_link():
    """A single-board link runs on someone else's traffic; when it pauses, CSI stops. The
    reader has to make those dropouts visible rather than smoothing over them."""
    st = LinkStats()
    times = [0.0, 0.05, 0.10, 5.10, 5.15]     # one 5-second dropout
    it = iter(times)
    recs = list(csi_records([_line([3, 4] * 4) for _ in times], stats=st,
                            width_lock_packets=1, agc_alpha=0.0, gap_s=2.0,
                            clock=lambda: next(it)))

    assert len(recs) == 5
    assert st.gaps == 1
    assert st.longest_gap_s == pytest.approx(5.0, abs=0.01)


def test_firmware_diagnostics_are_surfaced():
    st = LinkStats()
    seen = []
    lines = [
        "CSI_INFO,mode=sta,ip=192.168.1.42,udp_port=8888",
        "CSI_LINK,state=connected,bssid=ac:84:c6:11:22:33,channel=6,rssi=-47",
        "CSI_STAT,rate_hz=32.8,packets=164,dropped=3,link=up,rssi=-51,ip=192.168.1.42",
        _line([3, 4] * 4),
    ]
    recs = list(csi_records(lines, stats=st, width_lock_packets=1, agc_alpha=0.0,
                            clock=_fake_clock(), on_info=seen.append))

    assert len(recs) == 1
    assert st.board_ip == "192.168.1.42"        # this is what the traffic generator aims at
    assert st.firmware_rate_hz == pytest.approx(32.8)
    assert st.firmware_dropped == 3
    assert st.rssi == -51
    assert st.link_state == "up"
    assert len(seen) == 3


def test_info_line_survives_unexpected_shape():
    info = parse_info_line("CSI_INFO,hint=aim the generator here,ip=10.0.0.9,bare_token")
    assert info["_kind"] == "CSI_INFO"
    assert info["ip"] == "10.0.0.9"
    assert "bare_token" not in info


def test_measured_rate_is_robust_to_a_dropout():
    """The median interval is the point: one long gap must not halve the reported rate, or
    every window the pipeline sizes from it is wrong."""
    st = LinkStats()
    times = [i * 0.05 for i in range(40)] + [8.0, 8.05, 8.10, 8.15, 8.20]
    it = iter(times)
    list(csi_records([_line([3, 4] * 4) for _ in times], stats=st, width_lock_packets=1,
                     agc_alpha=0.0, clock=lambda: next(it)))

    assert st.measured_rate_hz == pytest.approx(20.0, rel=0.05)


def test_measure_rate_falls_back_instead_of_dividing_by_zero():
    assert measure_rate([], default=17.0) == 17.0
    assert measure_rate([(0.0, None), (0.0, None)], default=17.0) == 17.0
    recs = [(i * 0.1, None) for i in range(20)]
    assert measure_rate(recs) == pytest.approx(10.0, rel=1e-6)
