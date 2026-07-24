# wisp

Phase 0 MVP: a program that watches a room via Wi-Fi CSI (from 2 ESP32s) and prints
an alert when someone collapses — plus an evaluation harness that measures whether
those alerts can be trusted.

## The one question this answers

Can 2 ESP32s catch staged collapses in one real room **without spamming false alarms?**

The deliverable is not an app. It is a **number**: false alarms per week, alongside
proof that staged falls are caught.

## The gate (pass/fail)

Over weeks in one real occupied room:

- **PASS** if it catches (nearly) every staged sudden collapse and slow collapse,
  **and** produces fewer than ~1 false alarm per week under real living conditions.
- **FAIL** → you learned it cheaply (~$15, a few weeks) before raising money.

## The one interface everything hides behind

Every module is built against `wisp.source.base.CSISource`, whose `.stream()` yields
`(timestamp: float, amplitude: np.ndarray)` tuples. The same brain runs on:

- `synthetic.py` — fake room, build against this **now**
- `replay.py`    — recorded log files (deterministic; demo fallback)
- `serial_source.py` — **live** ESP32 serial, written **last**

Hardware is a plug-in, not a dependency.

## Layout (maps 1:1 to the MVP doc S-sections)

```
wisp/
├── config/pipeline.yaml          # all params, versioned (S2.7)
├── wisp/
│   ├── source/                   # S1.6 — the interface everything hides behind
│   │   ├── base.py               #   CSISource: .stream() -> (timestamp, amplitude[])
│   │   ├── synthetic.py          #   fake room — build against this NOW
│   │   ├── replay.py             #   read logged files
│   │   └── serial_source.py      #   LIVE — write this LAST
│   ├── ingest/                   # S1
│   │   ├── parser.py             #   CSI_DATA line -> amplitude array
│   │   └── logger.py             #   raw logger to disk (S1.5)
│   ├── preprocess/clean.py       # S2
│   ├── features/extract.py       # S3 — motion, sharpness, stillness
│   ├── calibrate/profile.py      # S4 — RoomProfile: mask, thresholds, model
│   ├── detect/
│   │   ├── model.py              # S5 — IsolationForest
│   │   ├── rules.py              # S5.2 — sudden vs slow
│   │   └── state_machine.py      # S6 — the false-alarm killer, do NOT skip
│   └── evaluate/harness.py       # S9 — recall, false-alarms/day, latency
├── scripts/
│   ├── calibrate.py              # fit a room profile from a recording
│   ├── run_live.py               # detection loop -> one-line debug console
│   └── evaluate.py               # replay + metrics
└── tests/test_features.py        # S3.7 — features on a known sine/step
```

## Build order (all of 1–6 with zero hardware)

1. `source/base.py` + `source/synthetic.py` — data to work with immediately
2. `ingest/parser.py` + `logger.py`
3. `preprocess` + `features` + the unit tests
4. `calibrate`
5. `detect` (model → rules → state machine)
6. `evaluate/harness.py`
7. Last, when hardware is up: `source/serial_source.py`

## Setup

```
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

## The MVP interface

A one-line printout is the whole UI until the gate passes:

```
[10:15:22] ALERT — sudden collapse (confidence 0.91, stillness=24s)
```

...plus the logged event file. Build no more UI than that.
