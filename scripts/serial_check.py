"""Serial sanity check — run this the MOMENT the ESP32 is flashed, before anything else.

It answers the questions that decide whether the live path can work, and it answers them in
about fifteen seconds instead of during a demo:

  1. Are CSI_DATA lines arriving on this port?      (flashed? associated? traffic?)
  2. Does wisp.ingest.parser understand them?       (line format matches?)
  3. Is the subcarrier count stable?                (the room mask needs a fixed width)
  4. What rate are we ACTUALLY getting?             (windows are sized from this)
  5. Is the board dropping CSI it could not print?  (UART too slow for the rate)

It only READS the port — no flashing, no writes. Prints a verdict, then exits non-zero if
the live path is not ready.

Usage:
    python scripts/serial_check.py --port COM5
    python scripts/serial_check.py --port /dev/ttyUSB0 --baud 921600 --seconds 20
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.ingest.parser import parse_csi_line       # noqa: E402
from wisp.source.live_reader import parse_info_line  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="COM5 (Windows) or /dev/ttyUSB0 (Linux/WSL)")
    ap.add_argument("--baud", type=int, default=921600,
                    help="must match the firmware console baud (sdkconfig.defaults)")
    ap.add_argument("--prefix", default="CSI_DATA")
    ap.add_argument("--seconds", type=float, default=15.0, help="how long to listen")
    args = ap.parse_args()

    try:
        import serial  # noqa: F401
    except Exception:
        print("pyserial not installed:  pip install pyserial")
        sys.exit(2)

    from wisp.source.live_reader import open_runmode
    try:
        ser = open_runmode(args.port, args.baud, timeout=0.5)
    except Exception as exc:
        print(f"could not open {args.port} @ {args.baud}: {exc}")
        print("  -> check the port name, that nothing else holds it open (a monitor, the")
        print("     server), and on WSL that the board is attached (usbipd attach --wsl).")
        sys.exit(2)

    print(f"listening on {args.port} @ {args.baud} for {args.seconds:.0f}s ...\n")
    lines = csi = parse_fail = garbled = 0
    widths: Counter = Counter()
    shown = 0
    arrivals = []
    board: dict = {}
    link_lines = []
    deadline = time.time() + args.seconds

    try:
        while time.time() < deadline:
            raw = ser.readline().decode("ascii", errors="replace").strip()
            if not raw:
                continue
            lines += 1
            # A wrong baud does not fail cleanly: it delivers plausible-looking bytes. Count
            # replacement characters so we can say "wrong baud" instead of "no CSI".
            if raw.count("�") > 2:
                garbled += 1
                continue
            if raw.startswith(("CSI_INFO", "CSI_STAT", "CSI_LINK")):
                info = parse_info_line(raw)
                board.update({k: v for k, v in info.items() if k != "_kind"})
                if len(link_lines) < 6:
                    link_lines.append(raw[:120])
                continue
            if not raw.startswith(args.prefix):
                continue
            csi += 1
            arrivals.append(time.time())
            try:
                amp = parse_csi_line(raw)
            except ValueError as exc:
                parse_fail += 1
                if parse_fail <= 3:
                    print(f"  [parse FAIL] {exc}\n     line: {raw[:90]}...")
                continue
            widths[amp.size] += 1
            if shown < 3:
                shown += 1
                print(f"  [ok] subcarriers={amp.size:>3}  amp[min/mean/max]="
                      f"{amp.min():.1f}/{amp.mean():.1f}/{amp.max():.1f}")
    finally:
        ser.close()

    print("\n" + "=" * 66)
    if link_lines:
        print("board says:")
        for l in link_lines:
            print("  " + l)
        print()
    print(f"lines: {lines}   CSI_DATA: {csi}   parse failures: {parse_fail}   garbled: {garbled}")

    if garbled > lines * 0.3:
        print("\nVERDICT: BAUD MISMATCH. Most lines decoded to nonsense.")
        print("  -> the firmware console baud is set by CONFIG_ESP_CONSOLE_UART_BAUDRATE in")
        print("     firmware/single_esp32_csi/sdkconfig.defaults. Try --baud 115200.")
        sys.exit(1)

    if csi == 0:
        print("\nVERDICT: NO CSI. Nothing with the CSI_DATA prefix arrived.")
        state = board.get("state") or board.get("link")
        if state in ("disconnected", "down", None):
            why = board.get("why")
            print(f"  -> the board is NOT linked{' (' + why + ')' if why else ''}.")
            print("     STA mode: check SSID/password and that the network is 2.4 GHz.")
            print("     SoftAP mode: nothing has joined the board's network yet.")
        else:
            print("  -> the board IS linked but nothing is transmitting TO it, so there are")
            print("     no frames to measure. Start the traffic generator:")
            ip = board.get("ip", "<board-ip>")
            print(f"       python scripts/traffic.py --host {ip} --hz 50")
        sys.exit(1)

    if not widths:
        print("\nVERDICT: CSI arrived but the parser could not decode any of it.")
        print("  -> capture one line and check the trailing [...] block in wisp/ingest/parser.py")
        sys.exit(1)

    # Rate measured from arrival times: this is the number the pipeline sizes windows with.
    rate = 0.0
    if len(arrivals) > 5:
        rate = (len(arrivals) - 1) / max(arrivals[-1] - arrivals[0], 1e-6)
    common, count = widths.most_common(1)[0]
    stable = len(widths) == 1

    print(f"subcarriers: {dict(widths)}  ({'STABLE' if stable else 'VARYING'})")
    print(f"measured rate: {rate:.1f} Hz")
    if "rate_hz" in board:
        print(f"board-reported rate: {board['rate_hz']} Hz   dropped: {board.get('dropped', '?')}")

    ok = True
    dropped = int(board.get("dropped", 0) or 0)
    if dropped > max(5, csi * 0.05):
        ok = False
        print(f"\nWARNING: the board dropped {dropped} CSI packets it could not print in time.")
        print("  The UART is the bottleneck, and drops make the sampling UNEVEN, which is")
        print("  worse for detection than a lower rate. Raise the console baud, or lower the")
        print("  traffic rate / CONFIG_WISP_PING_INTERVAL_MS until dropped stays near zero.")
    if not stable:
        print("\nNOTE: subcarrier width varies. The reader locks the dominant width and skips")
        print("  the rest, so this works, but LLTF-only firmware (the default) avoids it.")
    if rate < 8:
        ok = False
        print(f"\nWARNING: {rate:.1f} Hz is low. A fall lasts under a second; below ~10 Hz there")
        print("  are too few samples in a window for motion variance to mean much. Start or")
        print("  speed up the traffic generator.")

    print("\nVERDICT: CSI IS FLOWING and the parser understands it."
          + ("" if ok else " Fix the warnings above first."))
    ip = board.get("ip")
    print("\nNext:")
    if ip and ip != "0.0.0.0":
        print(f"  python scripts/traffic.py --host {ip} --hz 50      # in another terminal")
    print(f"  python scripts/run_live.py --serial {args.port} --baud {args.baud}")
    print(f"  python server/app.py --serial {args.port} --baud {args.baud} --room \"Room 1\"")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
