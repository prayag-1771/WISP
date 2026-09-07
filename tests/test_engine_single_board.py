"""Engine behaviour specific to the one-board sensor, tested with no board.

The single-board rig differs from the two-board one in three ways that are easy to get
wrong and invisible until a demo: which source gets built, when the traffic generator runs
(it is the thing that sets the sample rate), and whether the operator is told that the
placement cannot support detection.
"""

import numpy as np
import pytest

from server import engine as eng
from server.engine import EngineOptions, MonitorEngine, _live_note, _live_reader, choose_source
from wisp.calibrate.profile import RoomProfile
from wisp.detect.model import AnomalyModel
from wisp.source.live_reader import LiveCSIReader


class _FakeTraffic:
    """Stands in for UdpTrafficGenerator so tests never open a socket."""

    instances = []

    def __init__(self, host, port=8888, hz=50.0, payload_bytes=32):
        self.host, self.port, self.hz = host, port, hz
        self.started = False
        self.stopped = False
        _FakeTraffic.instances.append(self)

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True

    @property
    def running(self):
        return self.started and not self.stopped

    def summary(self):
        return {"host": self.host, "port": self.port, "requested_hz": self.hz}


@pytest.fixture(autouse=True)
def _no_real_sockets(monkeypatch):
    _FakeTraffic.instances = []
    monkeypatch.setattr(eng, "UdpTrafficGenerator", _FakeTraffic)


def _profile(still=0.01, occupied=0.05):
    return RoomProfile(
        mask=np.array([True, True, True]),
        model=AnomalyModel(),
        sample_rate_hz=30.0,
        win_samples=30,
        hop_samples=6,
        still_threshold=still,
        occupied_threshold=occupied,
        sharp_threshold=1.0,
    )


# --- source selection -------------------------------------------------------------

def test_single_board_source_is_one_reader_with_no_companion():
    reader = _live_reader(EngineOptions(gap_reset_s=4.0), "COM5")
    assert isinstance(reader, LiveCSIReader)
    assert reader.companion_port is None
    assert reader.port == "COM5"
    assert reader.gap_s == 4.0


def test_labels_distinguish_single_board_from_the_legacy_two_board_rig():
    single = choose_source(EngineOptions(serial_port="COM5", traffic_hz=40))
    assert single.live and "single board" in single.label
    assert "traffic generator 40 Hz" in single.note

    dual = choose_source(EngineOptions(serial_port="COM5", companion_port="COM6"))
    assert "2-board" in dual.label
    # the companion IS the transmitter, so no generator is advertised
    assert "traffic generator" not in dual.note


def test_note_says_when_traffic_generation_is_off():
    assert "traffic generator off" in _live_note(EngineOptions(traffic_hz=0), "COM5")


def test_fallback_chain_still_reaches_synthetic():
    choice = choose_source(EngineOptions(probe_serial=False))
    assert choice.mode == "FALLBACK" and choice.kind == "synthetic"


# --- traffic generation -----------------------------------------------------------

def test_board_ip_from_the_firmware_starts_the_generator():
    """The board announces its own address; nobody should have to type it in."""
    e = MonitorEngine(EngineOptions(traffic_hz=25, traffic_port=9999))
    e._on_board_info({"_kind": "CSI_INFO", "mode": "sta", "ip": "192.168.1.42"})

    assert len(_FakeTraffic.instances) == 1
    gen = _FakeTraffic.instances[0]
    assert (gen.host, gen.port, gen.hz) == ("192.168.1.42", 9999, 25)
    assert gen.started


def test_placeholder_ip_is_ignored():
    e = MonitorEngine(EngineOptions(traffic_hz=25))
    e._on_board_info({"_kind": "CSI_STAT", "ip": "0.0.0.0"})
    assert _FakeTraffic.instances == []


def test_no_generator_on_the_two_board_rig_or_when_disabled():
    """The companion board is the transmitter there; generating traffic would only add
    packets nobody asked for."""
    MonitorEngine(EngineOptions(companion_port="COM6"))._on_board_info({"ip": "192.168.1.42"})
    MonitorEngine(EngineOptions(traffic_hz=0))._on_board_info({"ip": "192.168.1.42"})
    assert _FakeTraffic.instances == []


def test_generator_is_not_restarted_for_the_same_address():
    e = MonitorEngine(EngineOptions(traffic_hz=25))
    for _ in range(4):
        e._on_board_info({"ip": "192.168.1.42"})
    assert len(_FakeTraffic.instances) == 1


def test_generator_is_re_aimed_when_the_board_changes_address():
    """A board that reconnects can come back on a different DHCP lease; keeping the old
    target would silently stop the CSI."""
    e = MonitorEngine(EngineOptions(traffic_hz=25))
    e._on_board_info({"ip": "192.168.1.42"})
    e._on_board_info({"ip": "192.168.1.77"})

    assert [g.host for g in _FakeTraffic.instances] == ["192.168.1.42", "192.168.1.77"]
    assert _FakeTraffic.instances[0].stopped
    assert _FakeTraffic.instances[1].running


def test_stop_stops_the_generator():
    e = MonitorEngine(EngineOptions(traffic_hz=25))
    e._on_board_info({"ip": "192.168.1.42"})
    e.stop()
    assert _FakeTraffic.instances[0].stopped


# --- placement quality ------------------------------------------------------------

def test_snapshot_reports_placement_separation():
    """Separation is the number that decides whether a placement can work at all, so it
    travels with the thresholds instead of living in a log."""
    e = MonitorEngine(EngineOptions(probe_serial=False))
    e.profile = _profile(still=0.01, occupied=0.09)
    snap = e.snapshot()

    assert snap["thresholds"]["separation"] == 9.0
    assert snap["thresholds"]["placement_ok"] is True


def test_snapshot_flags_a_placement_that_cannot_work():
    e = MonitorEngine(EngineOptions(probe_serial=False))
    e.profile = _profile(still=0.047, occupied=0.0745)   # measured on a bad real placement
    snap = e.snapshot()

    assert snap["thresholds"]["separation"] == 1.6
    assert snap["thresholds"]["placement_ok"] is False


def test_link_telemetry_is_absent_for_non_live_sources():
    e = MonitorEngine(EngineOptions(probe_serial=False))
    e.choice = choose_source(e.opts)
    assert e.snapshot()["link"] is None


def test_link_telemetry_surfaces_the_radio_view_when_live():
    e = MonitorEngine(EngineOptions(serial_port="COM5", traffic_hz=0))
    e.choice = choose_source(e.opts)
    e.link.board_ip = "192.168.1.42"
    e.link.firmware_dropped = 7
    e.link.gaps = 2
    e.link.width = 62

    link = e.snapshot()["link"]
    assert link["board_ip"] == "192.168.1.42"
    assert link["firmware_dropped"] == 7     # CSI the board could not print in time
    assert link["gaps"] == 2
    assert link["subcarriers"] == 62
    assert link["two_board"] is False
