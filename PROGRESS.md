# wisp — Project Progress

> Living document. Updated as work happens. **Last updated: 2026-09-08.**
> Nothing here is pushed to git without explicit approval.

---

## 1. What this project is

A Phase-0 MVP that watches a room via **Wi-Fi Channel State Information (CSI)** from a
single ESP32 and prints an alert when someone collapses — plus an evaluation harness that
measures whether those alerts can be **trusted**. The deliverable is not an app; it is a
number: **false alarms per week**, alongside proof that staged falls are caught.

**The gate (pass/fail):** over weeks in one real occupied room — catch (nearly) every
staged sudden + slow collapse, **and** produce **< ~1 false alarm/week**.

---

## 2. Where the project is right now

**Status: the software MVP is built and tested, AND a single ESP32 is streaming real CSI
into it end to end.**

- The full pipeline (source → clean → features → anomaly model → temporal state machine →
  evaluation) runs on a simulated room with zero hardware, and on a live board.
- **49 automated tests pass.**
- **Live, on real hardware (2026-09-08):** one ESP32-WROOM on ESP-IDF v4.3, STA mode against
  a phone hotspot. 62 subcarriers, stable width, **33 Hz** from the board's own gateway
  self-ping and **66 Hz** with the UDP traffic generator, **0 dropped packets**, 0 parse
  failures. `serial_check` → calibration → live detection → alert all ran on that stream.
- Detection on synthetic data: recall 2/2, kinds correct 2/2, 0 false alarms; 0 false alarms
  over 630 s + 180 s of unseen normal-room data.

**What is NOT done:**
- **A good placement.** The first live run measured a still→occupied separation of **1.6×**
  (below the 2× minimum) and produced a false "slow collapse" within a minute — exactly what
  that number predicts. The board and its transmitter need to be positioned so a person
  crosses the path between them. This is geometry, not code.
- Recording real room data, calibrating on it, and the weeks-long gate run.
- Optional: supervised CSI-Bench benchmark; real CSI-Bench validation.

> Honest note: the *detection quality* numbers are still from simulated data. Real hardware
> now proves the signal chain works; it does not yet prove the alerts can be trusted. The
> false-alarms-per-week gate is unrun.

## 3. Technologies & tools used

| Area | Tech |
| --- | --- |
| Language | Python 3 |
| Numerics | NumPy, SciPy (`scipy.ndimage` Hampel filter) |
| ML / anomaly detection | scikit-learn — **IsolationForest** (unsupervised, CPU, trains in seconds) |
| Serial I/O | pyserial (live ESP32 reader) |
| Config | PyYAML (`config/pipeline.yaml`) |
| Dataset adapter | h5py (CSI-Bench `.h5` replay) |
| Plotting | Matplotlib (`scripts/plot_run.py`) |
| Testing | pytest (49 tests) |
| Hardware | **1× ESP32** (WROOM-32), custom ESP-IDF v4.3 firmware (`firmware/single_esp32_csi`), laptop compute node. Transmitter = any router/hotspot. 2-board rig still supported. |
| Reference datasets | CSI-Bench (fall subset, Kaggle) — optional; ESP-Fi-HAR — firmware/format reference |
| Version control | Git + GitHub (`sudarsan2507-hue/WISP`) |

**Key design decision:** the shipping detector is **unsupervised** (IsolationForest on the
room's own normal). No GPU, no deep learning, no external dataset needed to ship. CSI-Bench
+ GPU are only for an *optional* supervised benchmark, never the product.

---

## 4. What's built — module by module

Everything hides behind one interface: `CSISource.stream() -> (timestamp, amplitude[])`.
Synthetic / replay / CSI-Bench / serial sources are interchangeable.

| Module | S-section | Purpose | Status |
| --- | --- | --- | --- |
| `wisp/source/base.py` | S1.6 | `CSISource` abstract interface | ✅ |
| `wisp/source/synthetic.py` | S1.6 | Room simulator with labeled falls (demo + normal-only) | ✅ |
| `wisp/source/replay.py` | S1.6 | Replay a recorded CSV log | ✅ |
| `wisp/source/csi_bench_source.py` | — | Replay CSI-Bench `.h5` clips | ✅ |
| `wisp/source/live_reader.py` | S1.6 | **Live single-board reader** — AGC high-pass, width lock, gap counting, measured rate, board diagnostics | ✅ running on hardware |
| `wisp/source/traffic.py` | — | UDP generator: makes the sample rate a number we choose | ✅ running on hardware |
| `firmware/single_esp32_csi/` | H3 | ESP-IDF CSI streamer: STA / SoftAP / sniffer, UDP sink, self-ping, CSI_STAT diagnostics | ✅ flashed + verified |
| `wisp/source/serial_source.py` | S1.6 | Original minimal pyserial reader | ✅ |
| `wisp/ingest/parser.py` | S1 | `CSI_DATA` line → amplitude array | ✅ |
| `wisp/ingest/logger.py` | S1.5 | Raw CSI logger to CSV | ✅ |
| `wisp/preprocess/clean.py` | S2 | Subcarrier mask + Hampel outlier rejection | ✅ |
| `wisp/features/extract.py` | S3 | Motion intensity, transient sharpness, `feature_stream` | ✅ |
| `wisp/calibrate/profile.py` | S4 | `RoomProfile.fit/save/load` (percentile thresholds) | ✅ |
| `wisp/detect/model.py` | S5 | IsolationForest anomaly model | ✅ |
| `wisp/detect/rules.py` | S5.2 | Sudden vs slow discriminator | ✅ |
| `wisp/detect/state_machine.py` | S6 | Temporal logic — the false-alarm killer | ✅ |
| `wisp/pipeline.py` | — | Shared `run_detection` loop | ✅ |
| `wisp/evaluate/harness.py` | S9 | Recall / false-alarms-per-week / latency | ✅ |
| `wisp/config.py` | S2.7 | Load `config/pipeline.yaml` | ✅ |

### Scripts (all runnable)
- `scripts/serial_check.py` — is CSI flowing, at what rate, with what width? Run it first.
- `scripts/traffic.py` — generate the traffic the board measures (sets the sample rate).
- `scripts/record.py` — capture live CSI to a replayable log.
- `scripts/calibrate.py` — fit + save a room profile.
- `scripts/run_live.py` — the one-line alert console, live (`--serial`) or offline.
- `scripts/evaluate.py` — print the gate numbers.
- `scripts/plot_run.py` — save `run.png` (see the signals + alerts).

### Dashboard (demo layer — `server/`)
A thin Flask bridge + self-contained dashboard for the pitch, **separate from the core**
(the core stays console-first). It consumes `wisp.pipeline.detection_telemetry` — the same
path the harness uses — so the demo can't diverge from what's measured. Adds no detection
logic; the only core change is a shared `detection_telemetry` generator (`run_detection` is
now a thin filter over it) + a read-only `DetectionStateMachine.state`.
- **Source fallback chain, always labelled on screen:** LIVE ESP32 (if CSI actually streams)
  → real-data replay (`--csi-bench` / `--replay`) → synthetic demo room.
- **Fall-alert + escalation UI:** MONITORING/ALERT hero, LIVE-vs-FALLBACK badge, live activity
  meter/sparkline, cancellable escalation countdown.
- Run: `python server/app.py --no-serial` (guaranteed software demo) — see `server/README.md`.
- Endpoints (CORS on): `GET /status`, `POST /cancel`, `POST /reset`, `GET /healthz`.
> Note: the main README lists dashboard/UI + escalation as *deferred, post-gate*. This layer
> is deliberately additive and isolated in `server/`, for the demo — the gate is still the
> false-alarms/week number, unchanged.

### Tests (49 passing)
features · state machine (incl. data-gap guard) · parser · logger↔replay · anomaly model ·
profile · harness · CSI-Bench adapter · live reader (AGC, width lock, gaps, diagnostics,
measured rate) · single-board engine (source selection, traffic generation, placement
quality, link telemetry).

---

## 5. How to run it

```
pip install -r requirements.txt
python scripts/calibrate.py     # learn this room's normal -> room_profile.pkl
python scripts/run_live.py      # one-line alert console
python scripts/evaluate.py      # the Phase-0 gate numbers
python scripts/plot_run.py      # saves run.png
pytest -q                       # 49 tests
```

**On the single ESP32** (full guide: `docs/SINGLE_ESP32.md`):

```
python scripts/serial_check.py --port /dev/ttyUSB0 --baud 921600   # is CSI flowing?
python scripts/traffic.py --host <board-ip> --hz 50                # set the sample rate
python scripts/run_live.py --serial /dev/ttyUSB0 --baud 921600     # calibrate + detect
python server/app.py --serial /dev/ttyUSB0 --baud 921600           # dashboard
```

---

## 6. Roadmap / next steps

1. ~~Hardware Milestone 1 — CSI streaming to serial.~~ **Done 2026-09-08.**
2. **Find a placement that works.** Move the ESP32 (and its transmitter) so a person crosses
   the path between them; re-run `scripts/run_live.py` until separation ≥ 2×, ideally ≥ 5×.
   Nothing downstream is meaningful until this passes.
3. **Stage falls** on that placement and confirm sudden + slow collapses are caught.
4. **Record real data** (`scripts/record.py`) — normal + staged falls, safe protocol.
5. **Calibrate on real normal**, re-run the harness on real recordings with a labels CSV.
6. **The gate** — weeks of continuous real-room operation, logging every alert for review.
7. *Optional:* CSI-Bench validation; supervised S5.4 benchmark.

## 7. Known caveats / open items

- All current results are on **simulated** data (see the honest note above).
- **Placement is the open blocker**, not code: separation must be ≥ 2× before any live alert
  means anything (measured 1.6× on the first attempt).
- The board depends on a transmitter nobody controls. If the router changes channel or
  reboots, the channel changes under the detector; `gap_reset_s` handles the dropout, but a
  recalibration is the honest response.
- **WSL drops the USB attachment whenever the distro idles out** — keep a process running
  inside WSL (`wsl -d Ubuntu -- sleep infinity`) or the board vanishes mid-run.
- One **orphaned Claude-attributed scaffold commit** (`ae0eaa9`) and some orphaned old-message
  commits linger on GitHub's server (not in history, not in the contributor list, reachable only
  by exact SHA). They GC on GitHub's schedule; a repo delete+recreate is the only guaranteed wipe.
- Per-packet Hampel filter is the slowest step for batch-processing long recordings (fine for live).

---

## 8. Change log

- **2026-09-08** — **Single-ESP32 support, verified on hardware.** Wrote the firmware
  (`firmware/single_esp32_csi`: STA/SoftAP/sniffer, UDP sink, gateway self-ping, CSI_STAT
  diagnostics, LLTF-only constant width). Added `live_reader.py` (AGC high-pass, width lock,
  gap counting, measured rate, board diagnostics) and `traffic.py` (UDP generator that sets
  the sample rate). Fixed a real detection bug: a CSI dropout used to be credited as
  stillness, manufacturing a "slow collapse" out of a dead link (`gap_reset_s`). Engine now
  sizes windows from the measured rate, starts the traffic generator from the IP the board
  announces, and reports link health + placement separation. New scripts: `traffic.py`,
  `record.py`; `run_live.py` gained a live `--serial` path; `serial_check.py` rewritten.
  Firmware bring-up fixed three bugs (netif ordering → no DHCP, missing PMF → association
  refused, console baud silently ignored without `ESP_CONSOLE_UART_CUSTOM`). Docs:
  `docs/SINGLE_ESP32.md`. Tests 20 → 49.
- **2026-07-25** — Added a demo dashboard layer (`server/`): Flask bridge + self-contained
  UI with a LIVE→real-data→synthetic **source fallback chain** (always labelled on screen)
  and a cancellable **escalation** flow. Centralised detection into one
  `pipeline.detection_telemetry` path (dashboard + `run_detection` both consume it) and added
  a read-only `DetectionStateMachine.state`. Core tests still 20/20 green.
- **2026-07-25** — Implemented full pipeline (source, ingest, preprocess, features, calibrate,
  detect, state machine, harness), wired 4 scripts, added CSI-Bench adapter + live SerialSource,
  grew tests to 20, produced a visual dashboard. Reworded commit messages to drop "synthetic"
  framing. 29 commits on `main`. This progress doc created.
