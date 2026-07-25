"""Fit a room profile from a normal-room recording and save it to disk.

Usage:
    python scripts/calibrate.py [out_profile.pkl] [--replay FILE] [--rate HZ] [--minutes M]

With no --replay, calibrates on a synthetic "normal" room (empty/walk/sit, no falls) so
you can run the whole pipeline with zero hardware. With --replay, calibrates on a real
recording captured by RawLogger.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.calibrate.profile import RoomProfile   # noqa: E402
from wisp.source.replay import ReplaySource       # noqa: E402
from wisp.source.synthetic import SyntheticSource  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="room_profile.pkl", help="output profile path")
    ap.add_argument("--replay", help="calibrate on a RawLogger CSV instead of synthetic")
    ap.add_argument("--rate", type=float, default=100.0, help="sample rate (Hz)")
    ap.add_argument("--minutes", type=float, default=3.0, help="synthetic normal duration")
    args = ap.parse_args()

    if args.replay:
        source = ReplaySource(args.replay)
    else:
        source = SyntheticSource.normal_only(minutes=args.minutes, sample_rate_hz=args.rate)

    print(f"Calibrating on {'replay ' + args.replay if args.replay else 'synthetic normal'} ...")
    profile = RoomProfile.fit(source, sample_rate_hz=args.rate)
    profile.save(args.out)
    print(profile.summary())
    print(f"Saved profile -> {args.out}")


if __name__ == "__main__":
    main()
