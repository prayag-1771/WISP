# wisp

**Phase 0 MVP.** A program that watches a room via Wi-Fi Channel State Information
(CSI) — sensed by **a single ESP32** — and prints an alert when someone collapses,
plus an evaluation harness that measures whether those alerts can be *trusted*.

This is not a product. It has no polish, no app, no cloud. Its only job is to answer
one question and produce one number.

---

## The one question

> Can one ESP32 catch staged collapses in one real room **without spamming false alarms?**

Everything in this repo exists to answer that. The deliverable is not software — it is
a **trustworthy false-alarm-per-week number**, alongside proof that staged falls are
caught.

## The gate (pass / fail)

Over weeks of continuous operation in one real, occupied room:

| Metric | Target |
| --- | --- |
| Recall on staged sudden + slow collapses | catch **(nearly) all** |
| **False alarms per week** under real living conditions (cooking, fan, normal movement) | **< ~1** |
| Detection latency | reported, informational |

- **PASS** → the core idea is real; proceed to build the product on top.
- **FAIL** → learned cheaply (~$15, a few weeks) *before* raising money or quitting
  anything. This is a good outcome, not a bad one — it beats any amount of market research.

The second number — false alarms per week — decides everything. A fall detector that
also fires when a fan spins or the cat walks by is worse than useless: people mute it,
and a muted safety device saves no one.

---

## One board is the sensor

CSI is measured on frames a radio **receives**, so the sensor needs a transmitter — but not
one of ours. Your router already fills the room with frames; the ESP32 listens to that
link, and a person moving through the path between them perturbs it measurably.

```
   [ROUTER]  · · · · · ·  person crosses here  · · · · · ·  [ESP32] --USB--> laptop
   the transmitter                                          the sensor      the detector
```

The board also binds a UDP port and throws away whatever arrives: each datagram is one
received frame, i.e. one CSI sample, so [`scripts/traffic.py`](scripts/traffic.py) turns the
sample rate into a number we choose rather than one the network happens to give us
(measured: **66 Hz**, versus ~12 Hz on the old two-board link).

Firmware is in [`firmware/single_esp32_csi/`](firmware/single_esp32_csi/) — STA mode (router
transmits), SoftAP mode (laptop transmits), or a passive sniffer. The full bring-up,
placement guide and troubleshooting is [`docs/SINGLE_ESP32.md`](docs/SINGLE_ESP32.md).

**Two boards still work** ([`docs/SENSETHROUGH.md`](docs/SENSETHROUGH.md)) — pass
`--companion <port>` — but they are no longer required, and the second board was the source
of most of the operational trouble.

## How it works (and what it does NOT need)

The shipping detector is an **Isolation Forest** — an *unsupervised anomaly detector*.
It trains on **one room's own "normal" in seconds, on CPU**. There are no epochs, no GPU,
no massive dataset.

- **No GPU is used for the MVP.** A GTX 1650 (or any card) sits idle the whole time.
  That is the point of the anomaly-detection approach, not a limitation.
- **No public dataset is required to ship.** [CSI-Bench][csi-bench] (461 hours, 35 users,
  26 environments) is a *multi-task benchmark corpus*, not training data for this MVP.
  You never download all of it.
- **The only scenario that touches a dataset or GPU** is the *optional* supervised
  benchmark (S5.4) — training a small 1D-CNN/LSTM on the fall subset to produce a
  "credibility number for investors." Even then: pull only the fall single-task subset
  (~6,700 samples, a few GB — not 461 hours), and a full run is well under an hour on a
  4GB card (batch 32–64; avoid transformers). This is explicitly **not** the shipping
  model.

## The core idea: one interface, hardware as a plug-in

The entire detection "brain" is built against a single interface —
[`CSISource`](wisp/source/base.py) — whose `.stream()` yields
`(timestamp: float, amplitude: np.ndarray)` tuples. Nothing downstream knows or cares
where the data comes from. The same brain runs on:

- **`SyntheticSource`** — a fake room. Build and test everything against this **now**,
  with zero hardware.
- **`ReplaySource`** — recorded log files. Deterministic; powers evaluation and doubles
  as a safe live-demo fallback.
- **`LiveCSIReader`** — the **live** ESP32 serial stream (`source/live_reader.py`).

**The payoff:** the whole pipeline was built before the hardware existed, and when the board
finally streamed, the only new code was the reader and the firmware. Everything downstream
already worked and was already tested. The hardware is a plug-in, not a dependency — the
same detector runs on one board, two boards, a recording, or a simulated room.

---

## Layout

Maps 1:1 to the MVP doc's S-sections.

```
WISP/                              ← git repo = project root
├── config/pipeline.yaml          # all params, versioned (S2.7)
├── wisp/                          # the Python package (import wisp)
│   ├── source/                   # S1.6 — the interface everything hides behind
│   │   ├── base.py               #   CSISource: .stream() -> (timestamp, amplitude[])
│   │   ├── synthetic.py          #   fake room — no hardware needed
│   │   ├── replay.py             #   read logged files
│   │   ├── live_reader.py        #   LIVE — the single-board serial reader
│   │   ├── traffic.py            #   UDP generator: sets the live sample rate
│   │   └── serial_source.py      #   the original minimal live reader
│   ├── ingest/                   # S1
│   │   ├── parser.py             #   CSI_DATA line -> amplitude array
│   │   └── logger.py             #   raw logger to disk (S1.5)
│   ├── preprocess/clean.py       # S2 — mask dead subcarriers, Hampel, band-pass, windows
│   ├── features/extract.py       # S3 — motion, sharpness, stillness
│   ├── calibrate/profile.py      # S4 — RoomProfile: mask, thresholds, model
│   ├── detect/
│   │   ├── model.py              # S5 — IsolationForest anomaly model
│   │   ├── rules.py              # S5.2 — sudden vs slow discriminators
│   │   └── state_machine.py      # S6 — temporal logic, THE false-alarm killer
│   └── evaluate/harness.py       # S9 — recall, false-alarms/week, latency  ← the deliverable
├── firmware/single_esp32_csi/    # THE BOARD — ESP-IDF CSI streamer (STA/SoftAP/sniffer)
├── scripts/
│   ├── serial_check.py           # is CSI flowing? the first thing to run
│   ├── traffic.py                # generate the traffic the board measures
│   ├── record.py                 # capture live CSI to a replayable log
│   ├── calibrate.py              # fit a room profile from a recording
│   ├── run_live.py               # detection loop -> one-line alert console (live or offline)
│   └── evaluate.py               # replay + metrics
├── server/                       # optional dashboard over the same pipeline
└── tests/                        # 49 tests, no hardware required
```

Everything above is implemented and tested; the pipeline runs end to end with or without
a board attached.

---

## Module reference

| Module | S-section | What it does |
| --- | --- | --- |
| `source/base.py` | S1.6 | Abstract `CSISource.stream()` → `(timestamp, amplitude[])`. The one contract everything hides behind. **Done.** |
| `source/synthetic.py` | S1.6 | Fake room. Emits **labeled** sequences: empty / walking / sudden collapse / slow collapse / optional periodic fan. |
| `source/replay.py` | S1.6 | Replays a recorded log through the identical interface. Deterministic. |
| `source/live_reader.py` | S1.6 | **The live single-board reader.** AGC high-pass, subcarrier width lock, gap counting, measured packet rate, and the board's own CSI_STAT diagnostics. Its decode path is a pure generator over text lines, so all of it is tested without hardware. |
| `source/traffic.py` | — | UDP generator aimed at the firmware's sink: makes the CSI sample rate a number you choose. |
| `source/serial_source.py` | S1.6 | The original minimal pyserial reader, kept for simple captures. |
| `ingest/parser.py` | S1 | Parse a `CSI_DATA` serial line → per-subcarrier amplitude array (`sqrt(i²+q²)`). Pure, unit-testable. |
| `ingest/logger.py` | S1.5 | Raw CSI logger to disk, continuous. **Do not skip** — every hour logged early is irreplaceable data and your demo safety net. |
| `preprocess/clean.py` | S2 | Drop null/guard + dead subcarriers, Hampel outlier rejection, band-pass. Amplitude only (phase skipped for MVP). Rolling short (~1s) + long (~3–5s) windows. |
| `features/extract.py` | S3 | Three features: **motion intensity** (cross-subcarrier variance), **transient sharpness** (max first-difference), **stillness duration** (counter). |
| `calibrate/profile.py` | S4 | `RoomProfile` fit from hours of one room's "normal": subcarrier mask, percentile thresholds, fan/HVAC notch, trained model. One room, one profile. |
| `detect/model.py` | S5 | IsolationForest over the feature vectors (fastest anomaly detector to get running; CPU, seconds). |
| `detect/rules.py` | S5.2 | Discriminators: transient→stillness = sudden fall; gradual decline→prolonged stillness = slow collapse. Notches periodic sources. |
| `detect/state_machine.py` | S6 | Temporal logic: requires a *pattern over time*, not one anomalous window. `disturbance → stillness ≥ T → CONFIRMED`, with debounce/hysteresis. Keeps an audit log of transitions. **The false-alarm killer — do not skip.** |
| `evaluate/harness.py` | S9 | Replays labeled recordings through the exact live pipeline; computes recall, false-alarms/week, latency. **The actual deliverable.** |

---

## Build order (all of 1–6 need zero hardware)

```
synthetic.py  ──►  parser/logger (S1)  ──►  clean (S2)  ──►  extract (S3)
                                                                  │
                                          ┌───────────────────────┘
                                          ▼
                          profile (S4) ──► model + rules + state_machine (S5, S6)
                                                                  │
                                                                  ▼
                                                         harness (S9) ← the deliverable
```

1. `source/base.py` + `source/synthetic.py` — data to work with immediately.
2. `ingest/parser.py` + `logger.py`.
3. `preprocess` + `features` + the unit tests (turn the 3 `xfail`s green — first real milestone).
4. `calibrate`.
5. `detect` (model → rules → state machine).
6. `evaluate/harness.py`.
7. **Last, when hardware is up:** `source/serial_source.py`.

### Independent tracks (what can be parallelized)

Each depends only on a *data shape*, not another module's internals, so all can proceed
at once given people to do them:

1. **Source/data** — synthetic, replay, logger
2. **Preprocess** — clean (testable on hand-made arrays)
3. **Features** — extract (testable on a pure sine / step, no source needed)
4. **Detection** — model, rules, state machine (feed it fake feature dicts)
5. **Evaluation** — harness (stub the detector)
6. **Hardware** — firmware (H3) → serial_source, parser (the long pole)

The three worth parallelizing early: **source/synthetic**, **features**, and **hardware**.

---

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on Unix
pip install -r requirements.txt
```

Run it end-to-end on the synthetic room (zero hardware):

```
python scripts/calibrate.py     # learn this room's normal -> room_profile.pkl
python scripts/run_live.py      # the one-line alert console
python scripts/evaluate.py      # the Phase-0 gate numbers (recall / false-alarms per week)
python scripts/plot_run.py      # SEE it: saves run.png (motion + sharpness + alerts)
pytest -q                       # 49 tests
```

### Live dashboard (optional demo layer)

For a screen-recordable pitch, `server/` adds a Flask bridge + a self-contained dashboard
(fall-alert + escalation UI) over the same pipeline. It is **additive and isolated** — the
core stays console-first (dashboard/UI is otherwise deferred, see the bottom of this file).
It auto-picks a source and always shows which one: **LIVE ESP32 → real-data replay →
synthetic demo**.

```
python server/app.py --no-serial     # guaranteed software demo -> http://localhost:8000
python server/app.py                 # use the ESP32 if it's streaming, else fall back
```

See [`server/README.md`](server/README.md) for the fallback chain, flags, and HTTP API.

### Live, on one ESP32

Flash [`firmware/single_esp32_csi/`](firmware/single_esp32_csi/), then work through these in
order — each step either passes or tells you exactly what is wrong:

```
python scripts/serial_check.py --port COM5 --baud 921600      # 1. is CSI flowing?
python scripts/traffic.py --host <board-ip> --hz 50           # 2. set the sample rate
python scripts/run_live.py --serial COM5 --baud 921600        # 3. calibrate + alert console
python server/app.py --serial COM5 --baud 921600              # 4. the dashboard
```

Step 3 prints the number that decides everything:

```
still->occupied separation: 9.2x  [EXCELLENT]      # >=2x usable, <2x reposition the board
```

Below 2x the still and active levels overlap, so the room's own quiet looks like a collapse
and **no threshold tuning helps** — the geometry has to change. Measured 1.6x on a bad
placement here, and it produced a confident false "slow collapse" within a minute.

> Full bring-up, placement guide, the numbers to watch and every failure mode we hit:
> **[`docs/SINGLE_ESP32.md`](docs/SINGLE_ESP32.md)**. For the two-board rig, see
> [`docs/SENSETHROUGH.md`](docs/SENSETHROUGH.md).

## The MVP interface

A one-line printout is the entire UI until the gate passes:

```
[10:15:22] ALERT — sudden collapse (confidence 0.91, stillness=24s)
[11:33:01] ALERT — slow collapse   (confidence 0.87, stillness=180s)
```

...plus the logged event file. Build no more UI than that.

---

## Evaluation protocol (S9)

- **Replay engine:** recorded CSI → the same pipeline. Deterministic; also the demo fallback.
- **Labeling:** a simple CSV convention (not a UI): `staged fall / walk / empty / sit / pet-or-visitor`.
- **Staged collapses:** documented, safe protocol — crash mat, healthy volunteer, consent
  even for self-testing.
- **The run:** weeks of continuous unsupervised operation in the real occupied room,
  auto-logging every alert for human review.

Two things not to cut, ever, even in MVP:

1. **`logger.py` raw logging** — trivial to build, irreplaceable proprietary data, and your
   live-demo safety net.
2. **`state_machine.py` temporal logic** — single-window thresholding is exactly what
   produces the false-alarm spam that fails the gate. This is where the metric is won.

---

## Hardware (Phase 0)

- **1 ESP32** (WROOM-32 or ESP-32S) and one **data** USB cable. A second board is optional.
- A **transmitter you already own**: the router, a phone hotspot, or the laptop itself.
- Compute node = the laptop the board is plugged into. No Raspberry Pi.
- Firmware: [`firmware/single_esp32_csi/`](firmware/single_esp32_csi/), ESP-IDF v4.3+.
  **Milestone 1** = `scripts/serial_check.py` reports CSI flowing at a stable width.
- Fixed rig: the board taped or bracketed so it cannot move for the whole test. Moving it
  changes the channel more than a person does. Geometry documented once (board-to-router
  distance, heights, room sketch, photo).

Measured on the first real bring-up: **62 subcarriers, stable width, 33 Hz self-ping /
66 Hz with the traffic generator, 0 dropped packets.**

## References

- [CSI-Bench][csi-bench] — real Wi-Fi sensing benchmark. Source of the *optional* fall
  single-task subset for the supervised credibility number (S5.4). Not used to ship.
- [ESP-Fi-HAR][esp-fi-har] — ESP32 CSI human-activity-recognition reference. Useful when
  writing the firmware, the real `CSI_DATA` line format for `parser.py`, and `serial_source.py`.

[csi-bench]: https://github.com/guozhen-jenn-zhu/CSI-Bench-Real-WiFi-Sensing-Benchmark
[esp-fi-har]: https://github.com/AutoSmartGroup/ESP-Fi-HAR

---

## Explicitly deferred (NOT in this MVP)

Alerting service, dashboard/UI (a bare debug console is enough), data & ops tooling,
deployment hardening, autoencoder, supervised models, breathing detection, multi-room,
drift / recalibration automation, cloud, escalation, consent pipeline, data flywheel.

All of it is post-gate. The coding here is days; the *measuring* is weeks.
