"""Replay a labeled recording through the pipeline and print the gate metrics.

Usage:
    python scripts/evaluate.py                                  # synthetic demo timeline
    python scripts/evaluate.py --replay data/normal_night.csv    # false alarms on real data
    python scripts/evaluate.py --replay data/falls.csv --labels data/falls_labels.csv

With no args it evaluates the synthetic demo timeline (1 sudden + 1 slow fall amid normal
life), auto-calibrating a profile if none exists. That prints the Phase 0 gate numbers with
zero hardware.

With ``--replay`` it runs a **real recording** made by ``scripts/record.py`` through the
identical pipeline. This is the deliverable path:

- **Without ``--labels``** — hours of ordinary life with no staged falls. Every alert is by
  definition a false alarm, so this is the measurement that decides the gate:
  false-alarms-per-week. Recall is not meaningful and is reported as n/a.
- **With ``--labels``** — a CSV of ``onset,end,label`` (labels: ``sudden_fall`` /
  ``slow_fall``) marking staged collapses, so recall, kind accuracy and latency are
  reported too.

The profile must come from the SAME room and placement — calibrate on a separate
normal-only recording first:

    python scripts/calibrate.py --replay data/normal_evening.csv --rate 33
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.calibrate.profile import RoomProfile     # noqa: E402
from wisp.evaluate.harness import evaluate, load_events  # noqa: E402
from wisp.source.replay import ReplaySource         # noqa: E402
from wisp.source.synthetic import SyntheticSource   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="room_profile.pkl")
    ap.add_argument("--rate", type=float, default=100.0)
    ap.add_argument("--replay", help="a recording from scripts/record.py (RawLogger CSV)")
    ap.add_argument("--labels", help="ground-truth CSV: onset,end,label")
    args = ap.parse_args()

    if args.labels and not args.replay:
        ap.error("--labels describes a recording; pass --replay too")

    if os.path.exists(args.profile):
        profile = RoomProfile.load(args.profile)
    elif args.replay:
        # Calibrating on the recording we are about to score would leak: the thresholds
        # would be fitted to the very data whose false alarms we are counting, and the
        # number would flatter itself. Make the operator produce a profile from separate
        # normal-only data instead.
        print(f"No profile at {args.profile}. Calibrate on a SEPARATE normal-only recording"
              f" from the same placement first:\n"
              f"    python scripts/calibrate.py --replay <normal.csv> --rate {args.rate:g}"
              f" {args.profile}")
        sys.exit(2)
    else:
        print("No profile found — auto-calibrating on synthetic normal ...")
        profile = RoomProfile.fit(
            SyntheticSource.normal_only(minutes=3.0, sample_rate_hz=args.rate),
            sample_rate_hz=args.rate,
        )
        profile.save(args.profile)

    if args.replay:
        source = ReplaySource(args.replay)
        events = load_events(args.labels) if args.labels else []
        duration = source.total_duration
        if duration <= 0:
            print(f"{args.replay} has no usable timestamps — nothing to evaluate.")
            sys.exit(1)
        print(f"replaying {args.replay}: {duration:.0f}s"
              + (f", {len(events)} labelled event(s)" if events
                 else " (no labels — measuring false alarms only)"))
        metrics = evaluate(source, events, profile, duration_s=duration)
        print(metrics.report())
        if not events:
            print("\nNote: recall is n/a — this recording has no staged collapses. The number"
                  "\nthat matters here is false-alarms-per-week, above.")
        return

    demo = SyntheticSource.demo(sample_rate_hz=args.rate)
    metrics = evaluate(demo, demo.events, profile)
    print(metrics.report())


if __name__ == "__main__":
    main()
