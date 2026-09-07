"""Traffic generator — give the single-board sensor something to measure.

One ESP32 computes CSI from frames it RECEIVES. On its own it receives whatever the
network happens to send it, which is neither steady nor fast enough to detect a fall. This
sends UDP datagrams at a rate you choose; each one arrives as a Wi-Fi frame, and each frame
is one CSI sample. The payload is discarded — the arrival IS the measurement.

The board prints its own address at boot (``CSI_INFO,...,ip=...``), and ``server/app.py``
starts this generator automatically from that line. Run it by hand when using
``scripts/run_live.py``, recording with ``scripts/record.py``, or checking a placement.

Usage:
    python scripts/traffic.py --host 192.168.1.42            # 50 Hz, the usual default
    python scripts/traffic.py --host 192.168.1.42 --hz 20    # slower link / 115200 baud
    python scripts/traffic.py --host 192.168.4.1             # SoftAP mode board address

Nothing needs to be listening on the other end: an unreachable UDP port still delivers the
frame to the board's radio, which is all we are after. Leave it running in its own terminal
for as long as you are monitoring.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.source.traffic import UdpTrafficGenerator  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True, help="the board's IP (see its CSI_INFO line)")
    ap.add_argument("--port", type=int, default=8888, help="must match CONFIG_WISP_UDP_PORT")
    ap.add_argument("--hz", type=float, default=50.0, help="datagrams/s = CSI samples/s")
    ap.add_argument("--bytes", dest="payload", type=int, default=32, help="datagram size")
    ap.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = forever)")
    args = ap.parse_args()

    gen = UdpTrafficGenerator(args.host, port=args.port, hz=args.hz, payload_bytes=args.payload)
    print(f"sending {args.hz:g} datagrams/s to {args.host}:{args.port}  (Ctrl-C to stop)")
    print("each datagram is one CSI sample at the board — leave this running while you monitor\n")
    gen.start()
    deadline = time.time() + args.seconds if args.seconds > 0 else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(2.0)
            s = gen.summary()
            # Report what was ACHIEVED, not what was asked for: if the OS timer or the
            # network cannot keep up, the real CSI rate follows this number.
            note = ""
            if s["errors"]:
                note = f"   [{s['errors']} send errors — last: {gen.last_error}]"
            print(f"  sent {s['sent']:>7}   achieved {s['achieved_hz']:>6.1f} Hz"
                  f"   (requested {s['requested_hz']:g}){note}")
    except KeyboardInterrupt:
        print("\nstopping ...")
    finally:
        gen.stop()
        s = gen.summary()
        print(f"sent {s['sent']} datagrams, {s['achieved_hz']:.1f} Hz average, {s['errors']} errors")


if __name__ == "__main__":
    main()
