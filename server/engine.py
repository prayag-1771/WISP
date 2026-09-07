"""server/engine.py — the live monitoring engine behind the dashboard.

Responsibilities (framework-agnostic; no Flask here, so it stays unit-testable):

1. **Source selection with a fallback chain** — the heart of the demo's honesty:
       LIVE ESP32 (CSI actually streaming)  ->  real-data replay (CSI-Bench / recording)
       ->  synthetic demo room
   Whichever is chosen is reported as ``mode`` = LIVE | FALLBACK plus a human label, so the
   UI can ALWAYS show which one is running. A fallback is never silent.

2. **One detection path** — runs ``wisp.pipeline.detection_telemetry`` (same code the gate
   harness uses) in a background thread and keeps a thread-safe snapshot of room state.

3. **Escalation** — on a confirmed collapse, a cancellable countdown runs; if nobody
   cancels it, it "notifies the emergency contact". All timing is computed from wall-clock
   in ``snapshot`` so any number of dashboard viewers agree.

The web layer (``server/app.py``) is a thin shell over this.
"""

from __future__ import annotations

import glob
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from wisp.calibrate.profile import RoomProfile
from wisp.pipeline import detection_telemetry
from wisp.source.base import CSISource
from wisp.source.live_reader import LinkStats, LiveCSIReader, measure_rate, open_runmode
from wisp.source.replay import ReplaySource
from wisp.source.synthetic import SyntheticSource
from wisp.source.traffic import UdpTrafficGenerator

# ------------------------------------------------------------------ config

_KIND_LABEL = {"sudden_collapse": "sudden collapse", "slow_collapse": "slow collapse"}
_STATE_LABEL = {
    "NORMAL": "normal",
    "DISTURBANCE": "disturbance",
    "STILL": "still",
    "CONFIRMED": "collapse confirmed",
}
_HISTORY = 160          # motion-history samples kept for the sparkline
_STALE_AFTER_S = 3.0    # no telemetry update for this long => feed considered stale
_ESCALATION_HOLD_S = 6.0  # keep "notified" on screen this long before re-arming (looping demo)


@dataclass
class EngineOptions:
    # source chain
    serial_port: Optional[str] = None     # explicit port; None => autodetect (unless probe_serial False)
    probe_serial: bool = True             # try live ESP32 first
    baud: int = 921600
    probe_s: float = 6.0                  # how long to wait for a CSI line before giving up
    csi_bench: Optional[str] = None       # path to CSI-Bench .h5 file/dir (real-data fallback)
    replay: Optional[str] = None          # path to a recorded RawLogger CSV (real-data fallback)
    companion_port: Optional[str] = None  # legacy 2-board rig: TX port to hold open (single-board leaves this None)
    # traffic generation (single board) — the board measures CSI on frames it RECEIVES, so
    # with one ESP32 the sample rate is set by whoever transmits. We transmit: UDP datagrams
    # at a chosen rate to the firmware's sink. Without this the rate is the router's whim.
    traffic_hz: float = 50.0              # 0 disables the generator
    traffic_port: int = 8888              # must match CONFIG_WISP_UDP_PORT
    traffic_host: Optional[str] = None    # None => auto-discover from the board's CSI_INFO line
    # calibration
    profile_path: str = "room_profile.pkl"
    calibrate_s: float = 20.0             # seconds of live "normal" to fit a live profile
    rate_hz: float = 50.0                 # synthetic sample rate / nominal live rate
    auto_rate: bool = True                # live: size windows from the MEASURED packet rate
    gap_reset_s: float = 3.0              # live: a CSI dropout longer than this resets detection
    smooth_windows: int = 9               # live: median-filter features over N windows (kills noise-driven false alarms)
    # absolute threshold overrides (live): pin the still/occupied/sharp lines to measured
    # values instead of calibration percentiles. Needed when the resting noise floor sits
    # ABOVE the percentile-derived still line, which otherwise latches "disturbance" forever.
    still_abs: Optional[float] = None
    occupied_abs: Optional[float] = None
    sharp_abs: Optional[float] = None
    confirm_s: float = 8.0                 # live: stillness needed to confirm a sudden collapse
    min_active_s: float = 3.0              # live: sustained activity required before a collapse counts (false-alarm killer)
    # playback + demo flavour
    speed: float = 3.0                    # fallback playback speed multiplier (live is real-time)
    loop: bool = True                     # loop finite fallback streams (unattended demo)
    escalate_s: float = 30.0              # countdown before auto-notifying the contact
    room: str = "Room 1"
    contact: str = "Emergency contact"


@dataclass
class _SourceChoice:
    source: CSISource
    mode: str        # "LIVE" | "FALLBACK"
    live: bool
    kind: str        # serial | csi_bench | replay | synthetic
    label: str       # human label for the badge
    note: str        # why this source / extra context
    sample_rate_hz: float


# ------------------------------------------------------------------ probing / selection

def _autodetect_ports() -> List[str]:
    """Serial devices an ESP32 plausibly shows up as, on any host.

    pyserial enumerates properly on Windows (where ports are COM3, COM7, ... with no path
    to glob); the /dev globs are the Linux/WSL fallback for when pyserial is missing.
    """
    try:
        from serial.tools import list_ports
        ports = [p.device for p in list_ports.comports()]
        if ports:
            return sorted(ports)
    except Exception:
        pass
    return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


def probe_serial(port: str, baud: int, probe_s: float, prefix: str = "CSI_DATA") -> bool:
    """Return True iff a ``CSI_DATA`` line arrives on ``port`` within ``probe_s`` seconds.

    Safe on machines with no hardware / no pyserial: any failure => False (=> fallback).
    """
    try:
        ser = open_runmode(port, baud, timeout=0.5)
        try:
            deadline = time.time() + probe_s
            while time.time() < deadline:
                raw = ser.readline().decode("ascii", errors="ignore").strip()
                if raw.startswith(prefix):
                    return True
        finally:
            ser.close()
    except Exception:
        return False
    return False


class _ListSource(CSISource):
    """Re-streams an already-collected list of (t, amp) records (used for live calibration)."""

    def __init__(self, records) -> None:
        self._records = records

    def stream(self):
        yield from self._records


class _GenSource(CSISource):
    """Wraps an already-open generator so detection continues the SAME serial read (one open)."""

    def __init__(self, gen) -> None:
        self._gen = gen

    def stream(self):
        yield from self._gen


def _live_reader(opts: EngineOptions, port: str) -> LiveCSIReader:
    """The live source for either rig: one board, or one board plus a held-open companion."""
    return LiveCSIReader(
        port,
        baud=opts.baud,
        companion_port=opts.companion_port,
        gap_s=max(1.0, opts.gap_reset_s),
    )


def _live_note(opts: EngineOptions, port: str) -> str:
    if opts.companion_port:
        return (f"live CSI from the ESP32 on {port} "
                f"(2-board rig, TX held open on {opts.companion_port})")
    who = "the router" if opts.traffic_host is None else opts.traffic_host
    traffic = (f"; traffic generator {opts.traffic_hz:g} Hz -> {who}:{opts.traffic_port}"
               if opts.traffic_hz > 0 else "; traffic generator off")
    return f"live CSI from the single ESP32 on {port}{traffic}"


def choose_source(opts: EngineOptions) -> _SourceChoice:
    """Walk the fallback chain and return the first source that is actually available."""
    # 1) LIVE ESP32 — one board is the whole sensor; a companion port is the legacy 2-board rig.
    if opts.probe_serial:
        # An explicit --serial port is TRUSTED (no probe): probing means an extra open, and
        # every open resets the board. Autodetected ports are still probed, to pick the one
        # actually streaming CSI rather than a Bluetooth or debug port that happens to exist.
        port = opts.serial_port
        if not port:
            port = next((p for p in _autodetect_ports()
                         if probe_serial(p, opts.baud, opts.probe_s)), None)
        if port:
            return _SourceChoice(
                source=_live_reader(opts, port),
                mode="LIVE", live=True, kind="serial",
                label=f"ESP32 · {port}" + (" (2-board)" if opts.companion_port else " (single board)"),
                note=_live_note(opts, port),
                sample_rate_hz=opts.rate_hz,
            )
        tried = ", ".join(_autodetect_ports()) or "no serial ports found"
        fallback_note = f"no live ESP32 CSI ({tried}) — running on fallback data"
    else:
        fallback_note = "live probe disabled — running on fallback data"

    # 2) real-data replay — CSI-Bench (real captured CSI) or a recorded CSV
    if opts.csi_bench:
        try:
            from wisp.source.csi_bench_source import CSIBenchSource
            return _SourceChoice(
                source=CSIBenchSource(opts.csi_bench, sample_rate_hz=opts.rate_hz),
                mode="FALLBACK", live=False, kind="csi_bench",
                label="CSI-Bench · real captured CSI",
                note=f"{fallback_note}; replaying CSI-Bench clips: {opts.csi_bench}",
                sample_rate_hz=opts.rate_hz,
            )
        except Exception as exc:  # pragma: no cover - depends on optional h5py/data
            fallback_note += f"; CSI-Bench unavailable ({exc})"
    if opts.replay:
        return _SourceChoice(
            source=ReplaySource(opts.replay),
            mode="FALLBACK", live=False, kind="replay",
            label="Recording · replayed CSI log",
            note=f"{fallback_note}; replaying recording: {opts.replay}",
            sample_rate_hz=opts.rate_hz,
        )

    # 3) synthetic demo room — always available, correct, self-contained
    return _SourceChoice(
        source=SyntheticSource.demo(sample_rate_hz=opts.rate_hz),
        mode="FALLBACK", live=False, kind="synthetic",
        label="Synthetic demo room",
        note=f"{fallback_note}; using the built-in synthetic room",
        sample_rate_hz=opts.rate_hz,
    )


# ------------------------------------------------------------------ calibration

def build_profile(opts: EngineOptions, choice: _SourceChoice) -> RoomProfile:
    """Load a saved profile if present, else fit one for a FALLBACK source."""
    import os

    if os.path.exists(opts.profile_path):
        return RoomProfile.load(opts.profile_path)

    # Fallback sources only — a live board calibrates inside _run_live, on the same open
    # stream it then detects on (one board reset, one continuous read).
    #
    # Fallback sources: calibrate on synthetic normal at the same rate (matches the
    # synthetic demo exactly; a reasonable default for replay code-path demos too).
    profile = RoomProfile.fit(
        SyntheticSource.normal_only(minutes=3.0, sample_rate_hz=opts.rate_hz),
        sample_rate_hz=opts.rate_hz,
    )
    return profile


# ------------------------------------------------------------------ the engine

class MonitorEngine:
    """Runs detection in a background thread and exposes a thread-safe snapshot."""

    def __init__(self, opts: Optional[EngineOptions] = None) -> None:
        self.opts = opts or EngineOptions()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.choice: Optional[_SourceChoice] = None
        self.profile: Optional[RoomProfile] = None
        self._calibrating = True
        # live link health, filled in by the reader as the stream is consumed
        self.link = LinkStats()
        self.traffic: Optional[UdpTrafficGenerator] = None
        self.rate_hz = self.opts.rate_hz        # replaced by the MEASURED rate once live

        self._started_at = 0.0
        self._last_update = 0.0
        self._packets = 0
        self._cur = {"t": 0.0, "state": "NORMAL", "motion": 0.0, "sharp": 0.0, "motion_norm": 0.0}
        self._history: deque = deque(maxlen=_HISTORY)
        self._stream_ended = False
        self._error: Optional[str] = None

        # alert / escalation state
        self._alert: Optional[dict] = None   # {kind_raw, kind, confidence, stillness_s, at_t, deadline}
        self._escalated_at: Optional[float] = None
        self._resolution: Optional[str] = None   # "cancelled" | "notified"
        self._last_resolved_at = 0.0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "MonitorEngine":
        # choose_source probes for a live board (fast once CSI is flowing); calibration is
        # deferred into the worker thread so the web server can come up immediately.
        self.choice = choose_source(self.opts)
        self._started_at = time.time()
        self._last_update = time.time()
        self._thread = threading.Thread(target=self._run, name="wisp-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self.traffic is not None:
            self.traffic.stop()

    # -- single-board traffic ----------------------------------------------
    def _on_board_info(self, info: Dict[str, str]) -> None:
        """Called for each CSI_INFO/CSI_STAT/CSI_LINK line the board prints.

        The board announces its own IP, which is exactly what the traffic generator needs
        to aim at — so plugging in one ESP32 and starting the server is the whole setup, no
        address to look up and type in.
        """
        ip = info.get("ip")
        if ip and ip != "0.0.0.0":
            self._start_traffic(ip)

    def _start_traffic(self, host: str) -> None:
        """Start (or re-aim) the UDP generator that sets the CSI sample rate.

        Skipped on the 2-board rig, where the companion board is the transmitter, and
        skipped when --traffic-hz is 0 (self-ping or sniffer mode carries the link instead).
        """
        if self.opts.traffic_hz <= 0 or self.opts.companion_port:
            return
        with self._lock:
            if self.traffic is not None:
                if self.traffic.host == host and self.traffic.running:
                    return
                self.traffic.stop()
            self.traffic = UdpTrafficGenerator(
                host, port=self.opts.traffic_port, hz=self.opts.traffic_hz).start()

    def _run(self) -> None:
        assert self.choice is not None
        try:
            if self.choice.live:
                self._run_live()
            else:
                self._run_fallback()
        except Exception as exc:  # keep the server alive; surface the error to the UI
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
                self._stream_ended = True

    def _run_live(self) -> None:
        """ONE continuous serial read, shared by calibration + detection, so the board is
        reset once and never mid-run. On the single-board sensor the first CSI arrives a few
        seconds after open, once the board has associated and traffic is flowing; on the
        legacy 2-board rig it takes ~15 s for both boards to boot and link up."""
        reader: LiveCSIReader = self.choice.source          # type: ignore[assignment]
        reader.stats = self.link
        reader.on_info = self._on_board_info                # discovers the IP -> starts traffic
        # A fixed traffic_host needs no discovery, so start generating immediately: with one
        # board, nothing transmits until we do, which means no CSI to calibrate on.
        if self.opts.traffic_host and not self.opts.companion_port:
            self._start_traffic(self.opts.traffic_host)
        gen = reader.stream()

        # calibrate on the room's own live normal (keep the room normal during this window)
        n = max(120, int(self.opts.calibrate_s * self.opts.rate_hz))
        cal = []
        for rec in gen:
            if self._stop.is_set():
                return
            cal.append(rec)
            with self._lock:
                self._last_update = time.time()
            if len(cal) >= n:
                break

        # Size the windows from the rate the link ACTUALLY delivered, not the configured
        # guess. With one board the rate is whatever the transmitter and the UART settled on
        # (~30 Hz on a self-ping, exactly --traffic-hz with the generator, ~10 Hz sniffing);
        # calling that 50 Hz would make every "1 second" window some other length, and every
        # timing in the state machine wrong with it.
        self.rate_hz = measure_rate(cal, default=self.opts.rate_hz) if self.opts.auto_rate \
            else self.opts.rate_hz

        # Conservative thresholds + timings for a noisy live signal: a wide dead-band (only
        # the bottom 25% of motion counts as "still", only the top 20% as "occupied", only
        # extreme spikes as an impact) plus long sustained-stillness confirmation, so ordinary
        # radio noise can't walk the state machine into a false collapse.
        self.profile = RoomProfile.fit(
            _ListSource(cal), sample_rate_hz=self.rate_hz,
            still_pct=25.0, occupied_pct=80.0, sharp_pct=97.0,
            still_abs=self.opts.still_abs, occupied_abs=self.opts.occupied_abs,
            sharp_abs=self.opts.sharp_abs,
            confirm_s=self.opts.confirm_s, slow_confirm_s=25.0,
            recent_activity_s=12.0, debounce_s=8.0,
            min_active_s=self.opts.min_active_s,
            gap_reset_s=self.opts.gap_reset_s,
        )
        self.profile.save(self.opts.profile_path)
        with self._lock:
            self._calibrating = False
            self._last_update = time.time()

        # detection continues the SAME open stream — no re-open, no extra reset. Median
        # smoothing rejects isolated noisy packets before they reach the state machine.
        for t, feat, state, alert in detection_telemetry(
                _GenSource(gen), self.profile, smooth_windows=self.opts.smooth_windows):
            if self._stop.is_set():
                break
            self._ingest(t, feat, state, alert)
        with self._lock:
            self._stream_ended = True

    def _run_fallback(self) -> None:
        self.profile = build_profile(self.opts, self.choice)
        with self._lock:
            self._calibrating = False
            self._last_update = time.time()
        first_pass = True
        while not self._stop.is_set() and (first_pass or self.opts.loop):
            first_pass = False
            source = self._fresh_source()  # a fresh source each pass (generators are one-shot)
            wall0 = time.time()
            for t, feat, state, alert in detection_telemetry(source, self.profile):
                if self._stop.is_set():
                    return
                if self.opts.speed > 0:
                    target = wall0 + t / self.opts.speed
                    gap = target - time.time()
                    if gap > 0:
                        time.sleep(min(gap, 0.25))  # cap so stop stays responsive
                self._ingest(t, feat, state, alert)
        with self._lock:
            self._stream_ended = True

    def _fresh_source(self) -> CSISource:
        """Re-create the chosen fallback source for another playback loop."""
        assert self.choice is not None
        c = self.choice
        if c.kind == "synthetic":
            return SyntheticSource.demo(sample_rate_hz=c.sample_rate_hz)
        if c.kind == "replay":
            return ReplaySource(self.opts.replay)  # type: ignore[arg-type]
        if c.kind == "csi_bench":
            from wisp.source.csi_bench_source import CSIBenchSource
            return CSIBenchSource(self.opts.csi_bench, sample_rate_hz=c.sample_rate_hz)  # type: ignore[arg-type]
        return c.source

    # -- ingest one window -------------------------------------------------
    def _ingest(self, t: float, feat: dict, state: str, alert) -> None:
        occ = self.profile.occupied_threshold or 1e-9
        still = self.profile.still_threshold
        # Display ceiling: spread the bar across the whole movement range (still -> clearly
        # active), NOT just the narrow still->occupied detection band. When that band is small
        # (noisy placement), normalizing by it alone snaps the meter 0<->100 with nothing in
        # between; scaling to ~5x the band above still puts the "occupied" line near a fifth of
        # the bar and lets real movement climb gradually toward full. The dashboard maps
        # motion_norm (0..1.6) onto 0..100%, so ceiling -> 1.6 = full bar.
        ceiling = still + max(occ - still, 1e-9) * 5.0
        span = max(ceiling - still, 1e-9)
        motion = float(feat["motion_intensity"])
        with self._lock:
            self._last_update = time.time()
            self._packets += 1
            self._cur = {
                "t": round(t, 2),
                "state": state,
                "motion": motion,
                "sharp": float(feat["transient_sharpness"]),
                "motion_norm": max(0.0, min(1.6 * (motion - still) / span, 1.6)),
            }
            self._history.append(round(self._cur["motion_norm"], 4))

            if alert is not None and self._alert is None and self._resolution is None:
                self._alert = {
                    "kind_raw": alert.kind,
                    "kind": _KIND_LABEL.get(alert.kind, alert.kind.replace("_", " ")),
                    "confidence": alert.confidence,
                    "stillness_s": alert.stillness_s,
                    "at_t": round(alert.timestamp, 1),
                    "deadline": time.time() + self.opts.escalate_s,
                }
                self._escalated_at = None

    # -- external commands -------------------------------------------------
    def cancel(self) -> bool:
        """Dashboard 'I'm OK' — cancel an in-progress alert/escalation."""
        with self._lock:
            if self._alert is not None:
                self._alert = None
                self._escalated_at = None
                self._resolution = "cancelled"
                self._last_resolved_at = time.time()
                return True
            return False

    def reset(self) -> None:
        """Clear any resolved/alert state so the monitor returns to a clean baseline."""
        with self._lock:
            self._alert = None
            self._escalated_at = None
            self._resolution = None

    # -- snapshot ----------------------------------------------------------
    def _advance_escalation(self) -> None:
        """Compute escalation phase from wall clock; auto-clear after the hold window."""
        now = time.time()
        if self._alert is not None:
            if self._escalated_at is None and now >= self._alert["deadline"]:
                self._escalated_at = now
                self._resolution = "notified"
        # auto-clear a resolved alert after the hold, so a looping demo can re-fire
        if self._resolution is not None:
            ref = self._escalated_at or self._last_resolved_at
            if self._resolution == "notified" and self._escalated_at is not None and now - self._escalated_at >= _ESCALATION_HOLD_S:
                self._alert = None
                self._escalated_at = None
                self._resolution = None
            elif self._resolution == "cancelled" and now - self._last_resolved_at >= 2.0:
                self._resolution = None

    def _link_snapshot(self) -> Optional[dict]:
        """The radio's own view of itself — only meaningful for a live board.

        A single-board sensor can look perfectly healthy on screen while quietly running at
        4 Hz through a router that is rate-limiting us, or dropping a third of its packets
        into a full UART. Both destroy detection and neither shows up as an error, so the
        numbers that reveal them belong on the dashboard, not in a log nobody reads.
        """
        c = self.choice
        if c is None or not c.live:
            return None
        st = self.link
        return {
            "board_ip": st.board_ip,
            "state": st.link_state,
            "rssi": st.rssi,
            "packets": st.packets,
            "measured_rate_hz": (round(st.measured_rate_hz, 1)
                                 if st.measured_rate_hz is not None else None),
            "firmware_rate_hz": st.firmware_rate_hz,
            "firmware_dropped": st.firmware_dropped,   # CSI the board could not print in time
            "gaps": st.gaps,
            "longest_gap_s": round(st.longest_gap_s, 1),
            "subcarriers": st.width,
            "malformed": st.malformed,
            "width_skipped": st.width_skipped,
            "two_board": bool(self.opts.companion_port),
            "traffic": None if self.traffic is None else self.traffic.summary(),
        }

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            self._advance_escalation()
            c = self.choice
            stale = (c is not None and c.live and not self._calibrating
                     and (now - self._last_update > _STALE_AFTER_S))

            if self._alert is not None:
                phase = "escalated" if self._escalated_at is not None else "active"
                countdown = max(0.0, self._alert["deadline"] - now)
                alert = {
                    "phase": phase,
                    "kind": self._alert["kind"],
                    "kind_raw": self._alert["kind_raw"],
                    "confidence": self._alert["confidence"],
                    "stillness_s": self._alert["stillness_s"],
                    "at_t": self._alert["at_t"],
                    "countdown_s": round(countdown, 1),
                    "resolution": self._resolution,
                }
            elif self._resolution == "cancelled":
                alert = {"phase": "cancelled", "resolution": "cancelled"}
            else:
                alert = {"phase": "none"}

            state = self._cur["state"]
            status_label = _STATE_LABEL.get(state, state.lower())

            return {
                "mode": None if c is None else c.mode,
                "live": bool(c and c.live),
                "source_kind": None if c is None else c.kind,
                "source_label": None if c is None else c.label,
                "note": None if c is None else c.note,
                "sample_rate_hz": round(self.rate_hz, 1) if (c and c.live) else (
                    None if c is None else c.sample_rate_hz),
                "link": self._link_snapshot(),
                "room": self.opts.room,
                "contact": self.opts.contact,
                "escalate_s": self.opts.escalate_s,
                "running": self._thread is not None and self._thread.is_alive(),
                "calibrating": self._calibrating,
                "stream_ended": self._stream_ended,
                "stale": stale,
                "error": self._error,
                "uptime_s": round(now - self._started_at, 1) if self._started_at else 0.0,
                "packets": self._packets,
                "thresholds": None if self.profile is None else {
                    "still": round(self.profile.still_threshold, 4),
                    "occupied": round(self.profile.occupied_threshold, 4),
                    "sharp": round(self.profile.sharp_threshold, 4),
                    # Separation is the one number that says whether this PLACEMENT can work.
                    # Below ~2x the still and active levels overlap, so the room's own quiet
                    # looks like a collapse and every alert is suspect. No threshold tuning
                    # fixes it — the geometry has to change — so it is reported next to the
                    # thresholds rather than buried in a log.
                    "separation": round(self.profile.occupied_threshold
                                        / max(self.profile.still_threshold, 1e-9), 1),
                    "placement_ok": (self.profile.occupied_threshold
                                     >= 2.0 * max(self.profile.still_threshold, 1e-9)),
                },
                "profile_summary": None if self.profile is None else self.profile.summary(),
                "monitor": {
                    "t": self._cur["t"],
                    "state": state,
                    "status_label": status_label,
                    "motion": round(self._cur["motion"], 4),
                    "motion_norm": round(self._cur["motion_norm"], 4),
                    "sharp": round(self._cur["sharp"], 4),
                    "history": list(self._history),
                },
                "alert": alert,
            }
