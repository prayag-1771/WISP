"""Replay a labeled recording through the pipeline and print the gate metrics.

Usage:
    python scripts/evaluate.py [--profile room_profile.pkl] [--rate HZ]

With no args it evaluates on the synthetic demo timeline (1 sudden + 1 slow fall amid
normal life), auto-calibrating a profile if none exists. This prints the Phase 0 gate
numbers — recall and false-alarms-per-week — with zero hardware.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.calibrate.profile import RoomProfile   # noqa: E402
from wisp.evaluate.harness import evaluate         # noqa: E402
from wisp.source.synthetic import SyntheticSource  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="room_profile.pkl")
    ap.add_argument("--rate", type=float, default=100.0)
    args = ap.parse_args()

    if os.path.exists(args.profile):
        profile = RoomProfile.load(args.profile)
    else:
        print("No profile found — auto-calibrating on synthetic normal ...")
        profile = RoomProfile.fit(
            SyntheticSource.normal_only(minutes=3.0, sample_rate_hz=args.rate),
            sample_rate_hz=args.rate,
        )
        profile.save(args.profile)

    demo = SyntheticSource.demo(sample_rate_hz=args.rate)
    metrics = evaluate(demo, demo.events, profile)
    print(metrics.report())


if __name__ == "__main__":
    main()
