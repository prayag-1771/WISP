"""Record live CSI to a log file — the raw material for calibration, replay and the gate.

Every hour recorded early is irreplaceable: it is your dataset, the input the evaluation
harness replays, and the safety net if the hardware misbehaves during a demo. This is the
one command that turns a live board into a file the rest of the toolchain understands.

Usage:
    python scripts/record.py --port COM5 --seconds 600 --out data/normal_evening.csv
    python scripts/record.py --port /dev/ttyUSB0 --seconds 60 --out data/fall_01.csv \\
        --traffic-host 192.168.1.42            # generate the traffic too, in one process

Then:
    python scripts/calibrate.py --replay data/normal_evening.csv   # learn this room
    python scripts/evaluate.py  --replay data/fall_01.csv          # the gate numbers

Label recordings by filename as you go (normal / walk / fall_sudden / fall_slow / pet).
The harness reads a labels CSV; a directory of well-named files is what makes writing it
five minutes of work instead of an archaeology project.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.ingest.logger import RawLogger              # noqa: E402
from wisp.source.live_reader import LinkStats, LiveCSIReader  # noqa: E402
from wisp.source.traffic import UdpTrafficGenerator   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", required=True, help="COM5 / /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--out", required=True, help="output CSV (ReplaySource reads it back)")
    ap.add_argument("--seconds", type=float, default=60.0, help="0 = until Ctrl-C")
    ap.add_argument("--companion", default=None, help="legacy 2-board rig: TX port to hold open")
    ap.add_argument("--traffic-host", default=None,
                    help="also generate UDP traffic at this address (the board's IP)")
    ap.add_argument("--traffic-hz", type=float, default=50.0)
    ap.add_argument("--traffic-port", type=int, default=8888)
    ap.add_argument("--raw", action="store_true",
                    help="log amplitudes with NO AGC correction (archival capture)")
    args = ap.parse_args()

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    traffic = None
    if args.traffic_host:
        traffic = UdpTrafficGenerator(args.traffic_host, port=args.traffic_port,
                                      hz=args.traffic_hz).start()
        print(f"traffic: {args.traffic_hz:g} Hz -> {args.traffic_host}:{args.traffic_port}")

    stats = LinkStats()
    # --raw keeps the receiver's own gain in the file. The AGC high-pass is cheap to apply
    # later but impossible to undo, so an archival capture should keep what the radio saw.
    reader = LiveCSIReader(args.port, baud=args.baud, companion_port=args.companion,
                           agc_alpha=0.0 if args.raw else 0.03, stats=stats)

    limit = f"{args.seconds:g}s" if args.seconds > 0 else "until Ctrl-C"
    print(f"recording {limit} from {args.port} @ {args.baud} -> {args.out}")
    print("(the first packets can take a few seconds while the board associates)\n")

    t0 = time.time()
    last_report = t0
    try:
        with RawLogger(args.out) as log:
            for t, amp in reader.stream():
                log.log(t, amp)
                now = time.time()
                if now - last_report >= 2.0:
                    last_report = now
                    rate = stats.measured_rate_hz
                    rate_s = f"{rate:5.1f} Hz" if rate else "  ... Hz"
                    print(f"  {now - t0:6.1f}s  packets={stats.packets:>7}  {rate_s}"
                          f"  subcarriers={stats.width}  gaps={stats.gaps}")
                if args.seconds > 0 and now - t0 >= args.seconds:
                    break
    except KeyboardInterrupt:
        print("\nstopped by user")
    finally:
        if traffic is not None:
            traffic.stop()

    size_kb = os.path.getsize(args.out) / 1024 if os.path.exists(args.out) else 0
    print(f"\nwrote {stats.packets} packets to {args.out} ({size_kb:.0f} KB)")
    if stats.packets == 0:
        print("NOTHING was recorded. Run scripts/serial_check.py first — that tells you")
        print("whether CSI is reaching the port at all, which is a different problem.")
        sys.exit(1)
    rate = stats.measured_rate_hz
    print(f"measured rate: {rate:.1f} Hz" if rate else "measured rate: too few packets")
    if stats.gaps:
        print(f"WARNING: {stats.gaps} dropouts, longest {stats.longest_gap_s:.1f}s — the link "
              f"stalled during this recording, so treat quiet stretches with suspicion.")


if __name__ == "__main__":
    main()
