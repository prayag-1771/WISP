"""The MVP interface: detection loop -> one-line debug console + logged event file.

Usage:
    python scripts/run_live.py [--profile room_profile.pkl] [--replay FILE] [--rate HZ]

Picks a CSISource (synthetic demo / replay), runs preprocess -> features -> detect ->
state machine, and prints ONE line per confirmed alert:

    [00:00:41] ALERT - sudden collapse (confidence 0.91, stillness=8.0s)

If no profile exists yet it auto-calibrates on synthetic normal, so this runs out of the
box with zero hardware. Every alert is also appended to events.log. Build no more UI
than this until the gate passes.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.calibrate.profile import RoomProfile   # noqa: E402
from wisp.pipeline import run_detection           # noqa: E402
from wisp.source.replay import ReplaySource       # noqa: E402
from wisp.source.synthetic import SyntheticSource  # noqa: E402


def _clock(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="room_profile.pkl")
    ap.add_argument("--replay", help="run on a RawLogger CSV instead of the synthetic demo")
    ap.add_argument("--rate", type=float, default=100.0)
    args = ap.parse_args()

    if os.path.exists(args.profile):
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

    source = ReplaySource(args.replay) if args.replay else SyntheticSource.demo(sample_rate_hz=args.rate)
    label = args.replay if args.replay else "synthetic demo room"
    print(f"\nWatching {label} ... (Ctrl-C to stop)\n" + "-" * 60)

    n = 0
    with open("events.log", "a", encoding="utf-8") as log:
        for t, alert in run_detection(source, profile):
            kind = alert.kind.replace("_", " ")
            line = f"[{_clock(t)}] ALERT - {kind} (confidence {alert.confidence}, stillness={alert.stillness_s}s)"
            print(line)
            log.write(line + "\n")
            n += 1

    print("-" * 60)
    print(f"stream ended — {n} alert(s). (logged to events.log)")


if __name__ == "__main__":
    main()
