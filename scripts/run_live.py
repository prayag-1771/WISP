"""The MVP interface: detection loop -> one-line debug console + logged event file.

Usage:
    python scripts/run_live.py                                  # synthetic demo, no hardware
    python scripts/run_live.py --replay data/evening.csv        # a recording
    python scripts/run_live.py --serial COM5                    # THE SINGLE ESP32, live
    python scripts/run_live.py --serial /dev/ttyUSB0 --traffic-host 192.168.1.42

Picks a CSISource (live board / replay / synthetic demo), runs preprocess -> features ->
detect -> state machine, and prints ONE line per confirmed alert:

    [00:00:41] ALERT - sudden collapse (confidence 0.91, stillness=8.0s)

With ``--serial`` this is the whole product on one board and no browser: it calibrates on
the room's own live normal, measures the real packet rate, and prints alerts. The dashboard
in ``server/`` is the same pipeline with a UI on top.

If no profile exists it auto-calibrates — on live normal when a board is attached, on
synthetic normal otherwise — so this runs out of the box either way. Every alert is also
appended to events.log.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.calibrate.profile import RoomProfile          # noqa: E402
from wisp.pipeline import detection_telemetry            # noqa: E402
from wisp.source.base import CSISource                   # noqa: E402
from wisp.source.live_reader import LinkStats, LiveCSIReader, measure_rate  # noqa: E402
from wisp.source.replay import ReplaySource              # noqa: E402
from wisp.source.synthetic import SyntheticSource        # noqa: E402
from wisp.source.traffic import UdpTrafficGenerator      # noqa: E402


class _ListSource(CSISource):
    def __init__(self, records):
        self._records = records

    def stream(self):
        yield from self._records


class _GenSource(CSISource):
    """Continue an ALREADY-OPEN stream: calibration and detection share one serial read, so
    the board is reset once at the start and never mid-run."""

    def __init__(self, gen):
        self._gen = gen

    def stream(self):
        yield from self._gen


def _clock(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _live_profile(args, gen, stats: LinkStats) -> RoomProfile:
    """Calibrate on the room's own live normal, off the open stream."""
    print(f"calibrating on {args.calibrate_s:g}s of live normal — behave normally, and move")
    print("around a little so the room shows both its still and its active levels ...")
    cal = []
    t0 = time.time()
    for rec in gen:
        cal.append(rec)
        if time.time() - t0 >= args.calibrate_s and len(cal) >= 120:
            break

    # The real rate, not the configured guess: with one board it is whatever the transmitter
    # and the UART settled on, and mis-sizing the windows mis-times everything downstream.
    rate = measure_rate(cal, default=args.rate)
    print(f"measured packet rate: {rate:.1f} Hz over {len(cal)} packets"
          f" (subcarriers={stats.width}, gaps={stats.gaps})")

    profile = RoomProfile.fit(
        _ListSource(cal), sample_rate_hz=rate,
        still_pct=25.0, occupied_pct=80.0, sharp_pct=97.0,
        confirm_s=args.confirm_s, slow_confirm_s=25.0,
        recent_activity_s=12.0, debounce_s=8.0,
        min_active_s=args.min_active_s, gap_reset_s=args.gap_reset_s,
    )
    sep = profile.occupied_threshold / max(profile.still_threshold, 1e-9)
    print(f"thresholds: still<{profile.still_threshold:.4f}  "
          f"occupied>{profile.occupied_threshold:.4f}  sharp>{profile.sharp_threshold:.4f}")
    # The single number that decides whether this placement can work at all. Everything
    # downstream is threshold tuning; none of it helps if moving and still look alike here.
    verdict = ("EXCELLENT" if sep >= 5 else "usable" if sep >= 2 else "TOO WEAK — reposition")
    print(f"still->occupied separation: {sep:.1f}x  [{verdict}]")
    if sep < 2:
        print("  A body has to cross the line between the transmitter and the board. Move the")
        print("  board so the person passes through that path, then run this again.")
    return profile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="room_profile.pkl")
    ap.add_argument("--serial", default=None, help="live ESP32 port (COM5 / /dev/ttyUSB0)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--companion", default=None, help="legacy 2-board rig: TX port to hold open")
    ap.add_argument("--replay", help="run on a RawLogger CSV instead of the synthetic demo")
    ap.add_argument("--rate", type=float, default=100.0, help="fallback rate if none measured")
    ap.add_argument("--calibrate-s", dest="calibrate_s", type=float, default=20.0)
    ap.add_argument("--confirm-s", dest="confirm_s", type=float, default=8.0)
    ap.add_argument("--min-active-s", dest="min_active_s", type=float, default=3.0)
    ap.add_argument("--gap-reset-s", dest="gap_reset_s", type=float, default=3.0)
    ap.add_argument("--smooth", type=int, default=1,
                    help="median-filter features over N windows (live: 9 is a good default)")
    ap.add_argument("--traffic-host", default=None, help="generate UDP traffic at the board")
    ap.add_argument("--traffic-hz", type=float, default=50.0)
    ap.add_argument("--traffic-port", type=int, default=8888)
    ap.add_argument("--recalibrate", action="store_true", help="ignore any saved profile")
    args = ap.parse_args()

    traffic = None
    if args.traffic_host:
        traffic = UdpTrafficGenerator(args.traffic_host, port=args.traffic_port,
                                      hz=args.traffic_hz).start()
        print(f"traffic: {args.traffic_hz:g} Hz -> {args.traffic_host}:{args.traffic_port}")

    stats = LinkStats()
    gen = None
    if args.serial:
        reader = LiveCSIReader(args.serial, baud=args.baud, companion_port=args.companion,
                               gap_s=max(1.0, args.gap_reset_s), stats=stats)
        gen = reader.stream()
        label = f"live ESP32 on {args.serial}"
        # A live board always calibrates on the room in front of it now. A profile from a
        # different placement (or a different day) describes a different radio channel, and
        # silently reusing one is the fastest way to a detector that cannot see anything.
        profile = _live_profile(args, gen, stats)
        profile.save(args.profile)
        source: CSISource = _GenSource(gen)
        smooth = args.smooth if args.smooth > 1 else 9   # live is noisy; smooth by default
    else:
        if os.path.exists(args.profile) and not args.recalibrate:
            profile = RoomProfile.load(args.profile)
            print(f"Loaded profile: {profile.summary()}")
        else:
            print("No profile found — auto-calibrating on synthetic normal ...")
            profile = RoomProfile.fit(
                SyntheticSource.normal_only(minutes=3.0, sample_rate_hz=args.rate),
                sample_rate_hz=args.rate,
            )
            profile.save(args.profile)
            print(f"Calibrated + saved -> {args.profile}: {profile.summary()}")
        source = ReplaySource(args.replay) if args.replay else \
            SyntheticSource.demo(sample_rate_hz=args.rate)
        label = args.replay if args.replay else "synthetic demo room"
        smooth = max(1, args.smooth)

    print(f"\nWatching {label} ... (Ctrl-C to stop)\n" + "-" * 60)

    n = 0
    last_note = time.time()
    try:
        with open("events.log", "a", encoding="utf-8") as log:
            for t, _feat, state, alert in detection_telemetry(source, profile,
                                                              smooth_windows=smooth):
                if alert is not None:
                    kind = alert.kind.replace("_", " ")
                    line = (f"[{_clock(t)}] ALERT - {kind} (confidence {alert.confidence}, "
                            f"stillness={alert.stillness_s}s)")
                    print(line)
                    log.write(line + "\n")
                    log.flush()
                    n += 1
                # A live console that prints nothing for minutes is indistinguishable from a
                # dead one, so say what the room looks like even when nothing is wrong.
                if args.serial and time.time() - last_note >= 15.0:
                    last_note = time.time()
                    rate = stats.measured_rate_hz
                    print(f"  [{_clock(t)}] {state.lower():<11} "
                          f"packets={stats.packets} rate={rate:.0f}Hz gaps={stats.gaps}"
                          if rate else f"  [{_clock(t)}] {state.lower()}")
    except KeyboardInterrupt:
        print("\nstopped by user")
    finally:
        if traffic is not None:
            traffic.stop()

    print("-" * 60)
    print(f"stream ended — {n} alert(s). (logged to events.log)")


if __name__ == "__main__":
    main()
