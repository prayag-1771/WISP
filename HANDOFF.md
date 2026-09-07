# Handoff — where wisp stands and what's next

Snapshot for whoever picks this up next. Everything below is on `main`.

## TL;DR

The MVP runs end-to-end **on a single ESP32**, and also with zero hardware. Flash
`firmware/single_esp32_csi`, run `scripts/serial_check.py`, and the same pipeline that
scores recall 2/2 on the synthetic demo runs on live CSI.

Verified on hardware 2026-09-08: 62 subcarriers, stable width, 33 Hz self-ping / 66 Hz with
the traffic generator, 0 dropped packets.

**The open blocker is physical, not software:** the first live placement measured a
still→occupied separation of **1.6×** (2× is the minimum) and produced a false "slow
collapse" within a minute. The board and its transmitter have to be positioned so a person
crosses the path between them. After that: staged falls, real recordings, and — the actual
point — weeks of real-room measurement.

## Run it (single board)

```
python scripts/serial_check.py --port /dev/ttyUSB0 --baud 921600   # 1. is CSI flowing?
python scripts/traffic.py --host <board-ip> --hz 50                # 2. set the sample rate
python scripts/run_live.py --serial /dev/ttyUSB0 --baud 921600     # 3. calibrate + detect
python server/app.py --serial /dev/ttyUSB0 --baud 921600           # 4. dashboard
```

Step 3 prints `still->occupied separation: N x` — below 2× nothing downstream is meaningful.
Full guide: `docs/SINGLE_ESP32.md`.

## Run it (no hardware)

```
pip install -r requirements.txt
python scripts/evaluate.py      # auto-calibrates, prints the gate table (recall / FA-per-week)
python scripts/run_live.py      # prints the one-line alert console on the synthetic demo
python scripts/calibrate.py     # fits + saves a room_profile.pkl explicitly
pytest -q                       # 49 tests, none of which need hardware
```

Example output of `run_live.py`:

```
[00:00:50] ALERT - sudden collapse (confidence 0.75, stillness=8.0s)
[00:01:44] ALERT - slow collapse (confidence 1.0, stillness=20.0s)
```

## Status by module

| Module | S | Status |
| --- | --- | --- |
| `wisp/source/base.py` | S1.6 | ✅ `CSISource` interface |
| `wisp/source/synthetic.py` | S1.6 | ✅ labeled fake room (`demo()`, `normal_only()`) |
| `wisp/ingest/parser.py` | S1 | ✅ parses `[I Q ...]` → amplitude — **verified against real ESP32 lines** |
| `wisp/ingest/logger.py` | S1.5 | ✅ `RawLogger` CSV writer |
| `wisp/source/replay.py` | S1.6 | ✅ replays a RawLogger CSV |
| `wisp/preprocess/clean.py` | S2 | ✅ mask + Hampel |
| `wisp/features/extract.py` | S3 | ✅ motion, sharpness, `feature_stream` |
| `wisp/detect/model.py` | S5 | ✅ IsolationForest |
| `wisp/detect/rules.py` | S5.2 | ✅ sudden vs slow |
| `wisp/detect/state_machine.py` | S6 | ✅ temporal logic + audit log |
| `wisp/calibrate/profile.py` | S4 | ✅ `RoomProfile.fit/save/load` |
| `wisp/pipeline.py` | — | ✅ shared `run_detection` loop |
| `wisp/evaluate/harness.py` | S9 | ✅ recall / FA-per-week / latency |
| `scripts/{serial_check,traffic,record,calibrate,run_live,evaluate}.py` | — | ✅ wired, runnable |
| `wisp/source/csi_bench_source.py` | — | ✅ adapter to replay CSI-Bench `.h5` clips (needs `h5py`) |
| `wisp/source/serial_source.py` | S1.6 | ✅ original minimal pyserial reader (superseded live by `live_reader.py`) |
| `scripts/plot_run.py` | — | ✅ saves `run.png` — motion + sharpness + alerts |
| `wisp/source/live_reader.py` | S1.6 | ✅ live single-board reader — running on hardware |
| `wisp/source/traffic.py` | — | ✅ UDP generator (sets the live sample rate) |
| `firmware/single_esp32_csi/` | H3 | ✅ ESP-IDF CSI firmware — flashed and verified |
| `tests/` | — | ✅ 49 passing (adds live reader + single-board engine) |

## What's genuinely left

1. **A placement that works.** Move the ESP32 (and, if you can, its transmitter) so a person
   crosses the path between them. Re-run `scripts/run_live.py --serial ...` until separation
   is ≥ 2×, ideally ≥ 5×. Nothing else on this list matters until this passes.
2. **Record real normal + staged falls**, calibrate on the real normal
   (`scripts/calibrate.py --replay <log.csv>`), and re-run `evaluate.py` on real
   recordings with a labels CSV (`harness.load_events`).
3. **The gate:** weeks of continuous real-room operation, logging every alert for review.
4. *Optional, already wired:* validate on real CSI via CSI-Bench. Download the Fall
   single-task subset (Kaggle: `guozhenjennzhu/csi-bench`), then:
   ```python
   from wisp.source.csi_bench_source import CSIBenchSource
   src = CSIBenchSource("path/to/FallDetection")   # a file or a directory of .h5
   print(src.list_datasets())                       # confirm the in-file layout first
   for t, amp in src.stream():                       # same (t, amp) contract as everything else
       ...
   ```
   Note this is a real-CSI *code* sanity check, not the gate (see the module docstring).
   The supervised S5.4 benchmark (investor credibility number) is still separate — GPU,
   ~sub-hour, NOT the shipping model.

## Tuning knobs (all in one place)

`RoomProfile.fit(...)` percentiles set the thresholds from the room's own stats:
`still_pct=35, occupied_pct=65, sharp_pct=99.5`. Temporal timings
(`confirm_s, slow_confirm_s, recent_activity_s, debounce_s`) travel on the profile and
feed the state machine via `pipeline._state_machine`. If real rooms produce false
alarms, raise `slow_confirm_s` and the percentiles first — that trades a little latency
for the gate number, which is the right trade.

## Design reminders (don't undo these)

- **Everything hides behind `CSISource`.** Synthetic → replay → serial are interchangeable.
- **The state machine is the false-alarm killer.** Never collapse it to single-window
  thresholding — that's what fails the gate.
- **No GPU / no CSI-Bench for the shipping detector.** IsolationForest trains on *this
  room's* normal in seconds. The gate is a *room* number (false alarms/week), not a
  dataset accuracy.
