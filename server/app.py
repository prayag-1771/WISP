"""server/app.py — the Flask bridge + dashboard host.

A thin shell over ``server.engine.MonitorEngine``:

    GET  /            -> the dashboard (self-contained HTML)
    GET  /status      -> JSON snapshot the dashboard polls (~2 Hz)
    POST /cancel      -> "I'm OK": cancel an in-progress escalation
    POST /reset       -> clear resolved/alert state
    GET  /healthz     -> liveness

The engine picks its source via the LIVE -> real-data -> synthetic fallback chain, so the
same server powers both the live-ESP32 demo and the guaranteed software fallback; the
dashboard always shows which one is running.

Run (from the repo root):
    python server/app.py --port 8000            # auto: live ESP32 if streaming, else fallback
    python server/app.py --no-serial            # force the software fallback
    python server/app.py --serial COM5          # the single-board sensor (or /dev/ttyUSB0)
    python server/app.py --csi-bench PATH       # real-data fallback from CSI-Bench .h5

Single board is the default shape: one ESP32 on one port. The server also starts the UDP
traffic generator that sets the CSI sample rate, aimed at the IP the board announces on its
own serial line — so "plug in the board and run this" is the whole setup. ``--companion``
switches back to the legacy 2-board rig, where the second board is the transmitter and no
generator is needed.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from flask import Flask, jsonify, send_from_directory  # noqa: E402
from flask_cors import CORS  # noqa: E402

from server.engine import EngineOptions, MonitorEngine  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
CORS(app)  # let an external dashboard poll /status too
engine: MonitorEngine  # set in main()


@app.route("/")
def index():
    return send_from_directory(_HERE, "dashboard.html")


@app.route("/status")
def status():
    return jsonify(engine.snapshot())


@app.route("/cancel", methods=["POST"])
def cancel():
    return jsonify({"cancelled": engine.cancel()})


@app.route("/reset", methods=["POST"])
def reset():
    engine.reset()
    return jsonify({"ok": True})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="wisp live monitor dashboard")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    # source chain
    p.add_argument("--serial", dest="serial_port", default=None,
                   help="serial port of the ESP32 (default: autodetect COM*/ttyUSB*)")
    p.add_argument("--companion", default=None,
                   help="legacy 2-board rig: TX ESP32 port to hold open (omit for single board)")
    p.add_argument("--no-serial", dest="probe_serial", action="store_false",
                   help="skip the live ESP32 probe and go straight to fallback")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--probe-s", type=float, default=6.0,
                   help="seconds to wait for a CSI line before falling back")
    p.add_argument("--csi-bench", default=None, help="CSI-Bench .h5 file/dir (real-data fallback)")
    p.add_argument("--replay", default=None, help="recorded RawLogger CSV (real-data fallback)")
    # calibration + playback
    p.add_argument("--profile", dest="profile_path", default="room_profile.pkl")
    p.add_argument("--calibrate-s", type=float, default=20.0,
                   help="seconds of live 'normal' to fit a room profile (live only)")
    p.add_argument("--rate", dest="rate_hz", type=float, default=50.0,
                   help="nominal sample rate; live runs MEASURE the real one and use that")
    p.add_argument("--no-auto-rate", dest="auto_rate", action="store_false",
                   help="trust --rate for window sizing instead of the measured packet rate")
    p.add_argument("--gap-reset-s", dest="gap_reset_s", type=float, default=3.0,
                   help="a CSI dropout longer than this resets detection (0 = off). "
                        "Stops a dead link being counted as a still room.")
    # single-board traffic generation
    p.add_argument("--traffic-hz", dest="traffic_hz", type=float, default=50.0,
                   help="UDP datagrams/s sent to the board = the CSI sample rate you get")
    p.add_argument("--traffic-host", dest="traffic_host", default=None,
                   help="board IP to aim traffic at (default: auto-discover from CSI_INFO)")
    p.add_argument("--traffic-port", dest="traffic_port", type=int, default=8888,
                   help="must match CONFIG_WISP_UDP_PORT in the firmware")
    p.add_argument("--no-traffic", dest="traffic_hz", action="store_const", const=0.0,
                   help="do not generate traffic (sniffer mode, self-ping only, or 2-board)")
    p.add_argument("--smooth", dest="smooth_windows", type=int, default=9,
                   help="median-filter features over N windows (live noise suppression; 1=off)")
    # absolute threshold overrides (live) — pin the lines to measured values, bypass percentiles
    p.add_argument("--still", dest="still_abs", type=float, default=None,
                   help="absolute stillness floor (override calibration percentile)")
    p.add_argument("--occupied", dest="occupied_abs", type=float, default=None,
                   help="absolute occupied level (override calibration percentile)")
    p.add_argument("--sharp", dest="sharp_abs", type=float, default=None,
                   help="absolute impact/sharpness ceiling (override calibration percentile)")
    p.add_argument("--confirm-s", dest="confirm_s", type=float, default=8.0,
                   help="stillness seconds needed to confirm a sudden collapse (live)")
    p.add_argument("--min-active-s", dest="min_active_s", type=float, default=3.0,
                   help="sustained activity required before a collapse counts (live false-alarm killer)")
    p.add_argument("--speed", type=float, default=3.0, help="fallback playback speed (live is real-time)")
    p.add_argument("--no-loop", dest="loop", action="store_false", help="don't loop finite fallback streams")
    p.add_argument("--escalate-s", type=float, default=30.0)
    p.add_argument("--room", default="Room 1")
    p.add_argument("--contact", default="Emergency contact")
    return p.parse_args(argv)


def main(argv=None) -> None:
    global engine
    a = _parse_args(argv)
    opts = EngineOptions(
        serial_port=a.serial_port, probe_serial=a.probe_serial, baud=a.baud, probe_s=a.probe_s,
        csi_bench=a.csi_bench, replay=a.replay, companion_port=a.companion,
        traffic_hz=a.traffic_hz, traffic_port=a.traffic_port, traffic_host=a.traffic_host,
        profile_path=a.profile_path, calibrate_s=a.calibrate_s, rate_hz=a.rate_hz,
        auto_rate=a.auto_rate, gap_reset_s=a.gap_reset_s,
        smooth_windows=a.smooth_windows,
        still_abs=a.still_abs, occupied_abs=a.occupied_abs, sharp_abs=a.sharp_abs,
        confirm_s=a.confirm_s, min_active_s=a.min_active_s,
        speed=a.speed, loop=a.loop, escalate_s=a.escalate_s, room=a.room, contact=a.contact,
    )
    engine = MonitorEngine(opts).start()
    c = engine.choice
    print("=" * 64)
    print(f"  wisp monitor  |  mode: {c.mode}  |  source: {c.label}")
    print(f"  {c.note}")
    if c.live and not a.companion:
        print("  single-board sensor: the transmitter is your router (or whatever the")
        print("  firmware is linked to) — keep the person BETWEEN it and the board.")
    print(f"  dashboard -> http://localhost:{a.port}    (Ctrl-C to stop)")
    print("=" * 64)
    # threaded=True so /status polling doesn't block; reloader off (background thread).
    app.run(host=a.host, port=a.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
