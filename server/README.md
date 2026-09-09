# server — SenseThrough live dashboard (demo layer)

A thin **presentation layer** over the tested `wisp` detection pipeline: a Flask bridge +
a self-contained dashboard that turns the one-line alert console into a live room monitor
with a **fall alert + escalation** UI, suitable for a screen-recorded demo.

It is intentionally **separate from the core**. The core stays console-first (see the main
README); this is the "make it visible for the pitch" layer and does not change any
detection logic — it consumes `wisp.pipeline.detection_telemetry`, the same path the
evaluation harness uses, so the demo can never diverge from what is measured.

## What it shows

- **MONITORING vs FALL ALERT** hero that flips the whole screen red on a confirmed collapse.
- An always-visible **source badge**: green **LIVE · ESP32** when a board is streaming, amber
  **FALLBACK · …** otherwise. The fallback is never silent — it is labelled on screen.
- A live **activity meter + sparkline**, current room state, and detector thresholds.
- **Placement separation** and a loud banner when it is below 2x — with the still and active
  levels overlapping, the room's own quiet looks like a collapse, so the operator has to be
  told that the alerts on screen cannot be trusted.
- A **Radio link** panel for a live board: board IP and link state, measured packet rate,
  CSI the board dropped, stream gaps, subcarrier count, RSSI, and what the traffic generator
  is achieving. A sensor quietly running at 4 Hz, or throwing away a third of its packets,
  looks perfectly healthy without these.
- A cancellable **escalation countdown** ("contacting emergency contact") that resolves to
  *notified* if nobody cancels, or back to monitoring if you press **I'm OK**.

## The source fallback chain

On startup the engine walks this chain and reports which rung it landed on:

1. **LIVE ESP32** — if a serial port (auto-detected via pyserial: `COM*` on Windows,
   `/dev/ttyUSB*`/`ttyACM*` elsewhere, or `--serial`) actually emits `CSI_DATA` within
   `--probe-s` seconds. Calibrates on the room's own live normal (`--calibrate-s`), sizing
   its windows from the **measured** packet rate rather than `--rate`.
2. **Real-data replay** — `--csi-bench PATH` (real captured CSI, needs the Kaggle subset) or
   `--replay file.csv` (a recorded `RawLogger` log).
3. **Synthetic demo room** — always available, self-contained, correct. The guaranteed floor.

## Run it (inside the WSL venv, from the repo root)

> The pipeline runs on Windows Python or in WSL Ubuntu. If Windows Smart App Control blocks
> the scipy/sklearn native DLLs, use WSL — and keep a process alive inside it
> (`wsl -d Ubuntu -- sleep infinity`), because when WSL idles out it takes the USB
> attachment with it. Open http://localhost:8000 in any browser.

```bash
source ~/wisp-venv/bin/activate

# Guaranteed software demo (no hardware) — amber FALLBACK badge:
python server/app.py --no-serial --room "Washroom 3B"

# Auto: use the ESP32 if it's streaming, else fall back automatically:
python server/app.py --room "Washroom 3B"

# THE SINGLE-BOARD SENSOR — one ESP32, no companion. The server also starts the UDP
# traffic generator that sets the sample rate, aimed at the IP the board announces on
# its own serial line, so this is the whole setup:
python server/app.py --serial /dev/ttyUSB0 --baud 921600 --room "Bedroom"

# Legacy 2-board rig: the second board is the transmitter, so no generator is needed:
python server/app.py --serial /dev/ttyUSB0 --companion /dev/ttyUSB1 --baud 115200 --rate 12

# Real captured CSI (after downloading the CSI-Bench fall subset, see below):
python server/app.py --no-serial --csi-bench /path/to/FallDetection --room "Washroom 3B"
```

### Single-board flags

| Flag | Default | What it does |
| --- | --- | --- |
| `--serial` | autodetect | the board's port |
| `--baud` | 921600 | must match the firmware console baud |
| `--traffic-hz` | 50 | UDP datagrams/s to the board = the CSI sample rate you get |
| `--traffic-host` | auto | board IP; discovered from its `CSI_INFO` line if omitted |
| `--traffic-port` | 8888 | must match `CONFIG_WISP_UDP_PORT` |
| `--no-traffic` | — | do not generate traffic (sniffer mode, or you run `scripts/traffic.py` yourself) |
| `--gap-reset-s` | 3 | a CSI dropout longer than this resets detection, so a dead link is never counted as a still room |
| `--no-auto-rate` | — | size windows from `--rate` instead of the measured rate (not recommended) |
| `--companion` | none | legacy 2-board rig: TX port to hold open |

Other useful flags: `--speed` (fallback playback speed; live is always real-time),
`--escalate-s` (countdown length), `--no-loop` (play the fallback once), `--port`,
`--contact "Daughter — Priya"`, `--calibrate-s`, `--min-active-s`, `--smooth`.

> Full single-board bring-up, placement and troubleshooting:
> [`docs/SINGLE_ESP32.md`](../docs/SINGLE_ESP32.md).

## HTTP API (for an external dashboard too)

CORS is enabled, so a dashboard you host elsewhere can poll the same endpoints.

| Method | Path | Purpose |
| --- | --- | --- |
| GET  | `/`        | the dashboard HTML |
| GET  | `/status`  | JSON snapshot (poll ~2 Hz): mode, source label, room state, alert phase, countdown |
| POST | `/cancel`  | "I'm OK" — cancel an in-progress escalation |
| POST | `/reset`   | clear alert/resolved state |
| GET  | `/healthz` | liveness |

## Enabling real CSI-Bench data (optional)

The code path is ready (`--csi-bench`), but the dataset needs your Kaggle credentials:

1. Kaggle → Account → **Create New API Token** → download `kaggle.json`.
2. In WSL: `mkdir -p ~/.kaggle && cp /mnt/c/…/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json`
3. `kaggle datasets download -d guozhenjennzhu/csi-bench -p ~/csi-bench --unzip`
4. Point the server at the fall subset directory: `--csi-bench ~/csi-bench/…/FallDetection`
   (first run `CSIBenchSource(path).list_datasets()` to confirm the in-file layout).

This is a *real-CSI code sanity check*, not the Phase-0 gate (which is a weeks-long
false-alarms/week number in one real room). See `wisp/source/csi_bench_source.py`.
