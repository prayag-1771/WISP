"""LiveCSIReader — the live serial reader for the ONE-BOARD sensor.

A single ESP32 running ``firmware/single_esp32_csi`` measures CSI on frames it receives
from a transmitter that is not ours (the router, the laptop, or any AP on the air), so the
Python side reads exactly one port. The two-board rig is still supported by holding the
transmitter port open (``companion_port``) — see ``docs/SENSETHROUGH.md`` — but nothing
here requires it.

Four things this does beyond "read lines and parse them", each one a lesson from real
hardware:

1. **AGC high-pass.** Raw ESP32 amplitude rides on the receiver's automatic gain control:
   the whole packet scales up and down for reasons unrelated to the room, which downstream
   reads as large fake motion. Dividing by a *slow* EMA of the packet mean cancels that
   drift while preserving the fast changes a moving body causes. (Dividing by the packet's
   own mean, the obvious version, also cancels the real signal.)
2. **Width lock.** ESP32 CSI packets can arrive with different subcarrier counts. The
   fixed-width room mask raises ``IndexError`` on the first odd one and kills the detection
   loop, so we lock onto the dominant width from the first packets and skip the rest.
   LLTF-only firmware makes the width constant and this a no-op — which is why it is the
   firmware default.
3. **Diagnostics from the board.** The firmware prints ``CSI_STAT`` (measured rate, dropped
   packets, RSSI, link state) and ``CSI_INFO`` (mode, IP). Those are surfaced on ``stats``
   so the dashboard can show the radio's own view, and so the server can auto-aim its
   traffic generator at the board's IP without being told it.
4. **Gap counting.** A single-board link depends on someone else's traffic; when it pauses,
   CSI stops. Gaps are counted here and, more importantly, are what
   ``DetectionStateMachine(gap_reset_s=...)`` watches — a dropout must never accumulate as
   "the room went still".

``csi_records`` is the whole decode path as a pure generator over lines of text, so all of
the above is unit-testable with no serial port and no board.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

import numpy as np

from ..ingest.parser import parse_csi_line
from .base import CSISource

_DEFAULT_PREFIX = "CSI_DATA"
_INFO_PREFIXES = ("CSI_INFO", "CSI_STAT", "CSI_LINK")


@dataclass
class LinkStats:
    """Live view of the radio link, updated as the stream is consumed."""

    packets: int = 0                    # CSI packets yielded
    malformed: int = 0                  # lines that looked like CSI but would not parse
    width_skipped: int = 0              # packets dropped for having the wrong subcarrier count
    gaps: int = 0                       # inter-packet intervals longer than gap_s
    longest_gap_s: float = 0.0
    width: Optional[int] = None         # locked subcarrier count
    board_ip: Optional[str] = None      # from CSI_INFO — where to aim the traffic generator
    link_state: Optional[str] = None    # from CSI_LINK / CSI_STAT
    firmware_rate_hz: Optional[float] = None   # the board's own measurement
    firmware_dropped: Optional[int] = None     # CSI the board could not print in time
    rssi: Optional[int] = None
    first_t: Optional[float] = None
    last_t: Optional[float] = None
    intervals: List[float] = field(default_factory=list)   # recent inter-packet gaps

    @property
    def measured_rate_hz(self) -> Optional[float]:
        """Packet rate measured from arrival times — the median interval, so a dropout or a
        burst cannot drag it around the way a mean would.

        This is the number the pipeline should size its windows with. A configured
        ``--rate`` is a guess; on a single-board link the real rate is whatever the
        transmitter and the UART agreed on, and using the guess instead makes every "1
        second" window some other length.
        """
        if len(self.intervals) < 5:
            return None
        med = float(np.median(self.intervals))
        return (1.0 / med) if med > 1e-9 else None


def parse_info_line(line: str) -> Dict[str, str]:
    """Parse a firmware ``CSI_INFO`` / ``CSI_STAT`` / ``CSI_LINK`` line into a dict.

    Format is ``PREFIX,key=value,key=value`` — bare tokens are ignored, so a line that
    changes shape in a later firmware revision degrades to "fewer keys", never an error.
    """
    out: Dict[str, str] = {}
    parts = line.split(",")
    out["_kind"] = parts[0].strip()
    for tok in parts[1:]:
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k.strip()] = v.strip()
    return out


def csi_records(
    lines: Iterable[str],
    stats: Optional[LinkStats] = None,
    prefix: str = _DEFAULT_PREFIX,
    agc_alpha: float = 0.03,
    width_lock_packets: int = 40,
    gap_s: float = 2.0,
    clock: Callable[[], float] = time.time,
    on_info: Optional[Callable[[Dict[str, str]], None]] = None,
) -> Iterator[Tuple[float, np.ndarray]]:
    """Decode an iterable of serial lines into ``(timestamp, amplitude)`` records.

    Pure with respect to hardware: feed it a list of strings in a test, a serial port in
    production. ``stats`` (if given) is updated in place as the stream is consumed, which is
    how the engine reports the link without a second read path.

    ``agc_alpha`` is the EMA weight of the AGC high-pass; 0 disables the correction.
    ``width_lock_packets`` packets are buffered to find the dominant subcarrier width, then
    replayed. Timestamps come from ``clock`` and are relative to the first packet.
    """
    st = stats if stats is not None else LinkStats()
    t0: Optional[float] = None
    baseline: Optional[float] = None
    buf: List[Tuple[float, np.ndarray]] = []

    def _record(rec: Tuple[float, np.ndarray]) -> Tuple[float, np.ndarray]:
        t = rec[0]
        if st.last_t is not None:
            dt = t - st.last_t
            st.intervals.append(dt)
            if len(st.intervals) > 400:
                del st.intervals[:-400]
            if dt > gap_s:
                st.gaps += 1
                st.longest_gap_s = max(st.longest_gap_s, dt)
        else:
            st.first_t = t
        st.last_t = t
        st.packets += 1
        return rec

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(prefix):
            # Not CSI: the board's own diagnostics are worth keeping, boot chatter is not.
            if line.startswith(_INFO_PREFIXES):
                info = parse_info_line(line)
                if "ip" in info and info["ip"] not in ("", "0.0.0.0"):
                    st.board_ip = info["ip"]
                if "state" in info:
                    st.link_state = info["state"]
                if "link" in info:
                    st.link_state = info["link"]
                if "rate_hz" in info:
                    try:
                        st.firmware_rate_hz = float(info["rate_hz"])
                    except ValueError:
                        pass
                if "dropped" in info:
                    try:
                        st.firmware_dropped = int(info["dropped"])
                    except ValueError:
                        pass
                if "rssi" in info:
                    try:
                        st.rssi = int(info["rssi"])
                    except ValueError:
                        pass
                if on_info is not None:
                    on_info(info)
            continue

        try:
            amp = parse_csi_line(line)
        except ValueError:
            st.malformed += 1        # partial line from a mid-packet open, or line noise
            continue

        now = clock()
        if t0 is None:
            t0 = now
        t = now - t0

        if agc_alpha > 0:
            pm = float(amp.mean())
            if pm > 1e-6:
                baseline = pm if baseline is None else (1.0 - agc_alpha) * baseline + agc_alpha * pm
                amp = amp / baseline

        if st.width is None:
            buf.append((t, amp))
            if len(buf) >= max(1, width_lock_packets):
                st.width = Counter(a.size for _, a in buf).most_common(1)[0][0]
                for rec in buf:
                    if rec[1].size == st.width:
                        yield _record(rec)
                    else:
                        st.width_skipped += 1
                buf = []
            continue

        if amp.size != st.width:
            st.width_skipped += 1
            continue
        yield _record((t, amp))


def measure_rate(records: Iterable[Tuple[float, np.ndarray]], default: float = 20.0) -> float:
    """Packet rate implied by a batch of records (median interval). Falls back to ``default``
    when there is too little to measure — never returns 0, which would make window sizing
    divide by zero downstream."""
    times = [t for t, _ in records]
    if len(times) < 6:
        return default
    diffs = np.diff(np.asarray(times, dtype=float))
    diffs = diffs[diffs > 1e-9]
    if diffs.size == 0:
        return default
    med = float(np.median(diffs))
    return (1.0 / med) if med > 1e-9 else default


def open_runmode(port: str, baud: int, timeout: float = 0.1):
    """Open a serial port WITHOUT knocking the ESP32 into download mode or holding it in
    reset: on these dev boards RTS drives EN and DTR drives GPIO0, so an ordinary open can
    reset the chip or leave it stuck in the bootloader (which looks exactly like "no CSI").
    Both lines are set low before and after ``open()``. The board still resets once."""
    import serial  # pyserial — lazy, so wisp imports fine with no hardware installed

    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = timeout
    s.dtr = False
    s.rts = False
    s.open()
    s.dtr = False
    s.rts = False
    return s


class LiveCSIReader(CSISource):
    """Live CSI from one ESP32 over serial (the single-board sensor).

    Parameters
    ----------
    port : str
        The board's serial device — ``COM5`` / ``/dev/ttyUSB0``.
    baud : int
        Must match the firmware console baud (921600 by default).
    companion_port : str, optional
        Legacy two-board rig only: a second port to hold open so that board keeps
        transmitting. Leave ``None`` for the single-board sensor.
    stats : LinkStats, optional
        Pass one in to watch the link while the stream is consumed elsewhere.
    on_info : callable, optional
        Called with each parsed ``CSI_INFO``/``CSI_STAT``/``CSI_LINK`` dict — the server
        uses it to discover the board's IP and start the traffic generator.
    """

    def __init__(
        self,
        port: str,
        baud: int = 921600,
        companion_port: Optional[str] = None,
        prefix: str = _DEFAULT_PREFIX,
        agc_alpha: float = 0.03,
        width_lock_packets: int = 40,
        gap_s: float = 2.0,
        stats: Optional[LinkStats] = None,
        on_info: Optional[Callable[[Dict[str, str]], None]] = None,
    ) -> None:
        self.port = port
        self.baud = baud
        self.companion_port = companion_port
        self.prefix = prefix
        self.agc_alpha = agc_alpha
        self.width_lock_packets = width_lock_packets
        self.gap_s = gap_s
        self.stats = stats if stats is not None else LinkStats()
        self.on_info = on_info

    def _lines(self, ser) -> Iterator[str]:
        while True:
            yield ser.readline().decode("ascii", errors="ignore")

    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        companion = open_runmode(self.companion_port, self.baud) if self.companion_port else None
        ser = open_runmode(self.port, self.baud)
        try:
            yield from csi_records(
                self._lines(ser),
                stats=self.stats,
                prefix=self.prefix,
                agc_alpha=self.agc_alpha,
                width_lock_packets=self.width_lock_packets,
                gap_s=self.gap_s,
                on_info=self.on_info,
            )
        finally:
            ser.close()
            if companion is not None:
                companion.close()
