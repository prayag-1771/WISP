# Handoff — where wisp stands and what's next

Snapshot for whoever picks this up next. Everything below is on `main`.

## TL;DR

The **data + feature + detection layers are implemented and import cleanly**. What's
left is the glue that makes it *run end-to-end and print the interface*: calibration,
the evaluation harness, and the three CLI scripts. All contracts are fixed, so the
remaining work is filling in known interfaces — not design.

## Status by module

| Module | S | Status | Notes |
| --- | --- | --- | --- |
| `wisp/source/base.py` | S1.6 | ✅ done | `CSISource.stream() -> (timestamp, amplitude[])` |
| `wisp/source/synthetic.py` | S1.6 | ✅ done | Labeled fake room. `SyntheticSource.demo()` (1 sudden + 1 slow fall) and `.normal_only()` (calibration). Ground truth in `.events`. |
| `wisp/ingest/parser.py` | S1 | ✅ done | Parses the trailing `[I Q I Q ...]` block → amplitude. **Verify against a real ESP32 line** once hardware streams. |
| `wisp/ingest/logger.py` | S1.5 | ✅ done | `RawLogger(path)` CSV writer, context manager. |
| `wisp/source/replay.py` | S1.6 | ✅ done | Reads a `RawLogger` CSV back through the same interface. |
| `wisp/preprocess/clean.py` | S2 | ✅ done | `subcarrier_mask(amps2d)` + `clean(amp, mask)` (Hampel). |
| `wisp/features/extract.py` | S3 | ✅ done | `extract(window)` → `{motion_intensity, transient_sharpness}`; `feature_stream(source, mask, win, hop)`. Stillness *duration* is accumulated in the state machine (it's temporal). |
| `wisp/detect/model.py` | S5 | ✅ done | `AnomalyModel` (IsolationForest). `fit / score / is_anomaly`, CPU, seconds. |
| `wisp/detect/rules.py` | S5.2 | ✅ done | `classify(trigger_sharpness, sharp_threshold)` → sudden vs slow. |
| `wisp/detect/state_machine.py` | S6 | ✅ done | `DetectionStateMachine` — disturbance → stillness ≥ T → `Alert`. Handles both fall types, debounce, audit log. |
| `wisp/config.py` | S2.7 | ✅ done | `config.load()` reads `config/pipeline.yaml`. |
| `wisp/calibrate/profile.py` | S4 | ⛔ TODO | Still a stub. See below. |
| `wisp/evaluate/harness.py` | S9 | ⛔ TODO | Still a stub. The deliverable. See below. |
| `scripts/calibrate.py` | — | ⛔ TODO | Wire `RoomProfile.fit` + save. |
| `scripts/run_live.py` | — | ⛔ TODO | The one-line console. Wire the loop. |
| `scripts/evaluate.py` | — | ⛔ TODO | Wire the harness + print metrics. |
| `tests/test_features.py` | S3.7 | ⚠️ xfail | Rewrite the 3 xfails to assert on `extract()` (sine → motion, step → sharpness) + add a state-machine test. |
| `wisp/source/serial_source.py` | S1.6 | ⛔ TODO (post-hardware) | Write LAST, after Milestone 1. Read serial → `parser.parse_csi_line` → yield. |
| `wisp/source/csi_bench_source.py` | — | ⛔ TODO (optional) | Adapter to replay the CSI-Bench fall `.h5` clips through the same interface for real-CSI validation. |

## The data contracts (so the remaining glue is mechanical)

- **Source** → `stream()` yields `(t: float, amp: np.ndarray[n_subcarriers])`.
- **Mask** → `subcarrier_mask(amps2d)` returns a bool keep-mask; pass it to `clean` and `feature_stream`.
- **Features** → `feature_stream(source, mask, win_samples, hop_samples)` yields `(t, {motion_intensity, transient_sharpness})`.
- **Model** → `AnomalyModel.fit(X)` on stacked feature vectors; `is_anomaly(feat_dict)` at run time.
- **State machine** → `update(t, feat_dict, is_anomaly)` → `Alert | None`.

## Next steps, in order (one commit each)

1. **`calibrate/profile.py` (S4).** Implement `RoomProfile`:
   - `fit(normal_source, rate, win_s, hop_s)`: materialize the normal recording, compute
     `subcarrier_mask`, run `feature_stream`, `AnomalyModel().fit(...)`, and derive
     thresholds from the *room's own* percentiles:
     `still_threshold` (low pct of motion), `occupied_threshold` (mid pct),
     `sharp_threshold` (~99.5th pct of transient_sharpness).
   - Store `mask, model, thresholds, rate, win_s, hop_s`. `save/load` via `pickle`
     (already git-ignored as `*.pkl`).
2. **`scripts/calibrate.py`.** CLI: build `SyntheticSource.normal_only()` (or a replay
   file), `RoomProfile.fit(...)`, `.save(out)`.
3. **`scripts/run_live.py`.** The interface. Loop `feature_stream` → `model.is_anomaly`
   → `state_machine.update` → on `Alert`, print
   `[HH:MM:SS] ALERT — {kind} (confidence {c}, stillness={s}s)` and append to an event log.
4. **`evaluate/harness.py` (S9).** `evaluate(source, events, profile)`: run the same loop,
   collect alerts, then compute **recall** (fall events with an alert after onset),
   **false alarms** (alerts not matching any event) → per day/week from `total_duration`,
   and **latency** (alert_t − onset). Return a dict.
5. **`scripts/evaluate.py`.** CLI: `SyntheticSource.demo()` → profile → harness → print
   the gate table.
6. **`tests/`.** Replace the 3 `xfail`s with real asserts on `extract`; add
   `tests/test_state_machine.py` (sudden path, slow path, empty-room-never-fires).
7. **Later, post-Milestone-1:** `serial_source.py`, and confirm `parser.py` against a real line.
8. **Optional:** `csi_bench_source.py` for real-CSI validation (needs `h5py`; add to requirements).

## How to run (once steps 1–5 are done)

```
pip install -r requirements.txt
python scripts/calibrate.py            # fits + saves a room profile from synthetic normal
python scripts/run_live.py             # prints the one-line alert console on synthetic demo
python scripts/evaluate.py             # prints recall / false-alarms-per-week / latency
pytest -q
```

## Design reminders (don't undo these)

- **Everything hides behind `CSISource`** — never let a downstream module import serial
  or a file path directly. Synthetic → replay → serial are interchangeable.
- **The state machine is the false-alarm killer.** Do not "simplify" it to single-window
  thresholding — that's what fails the gate.
- **No GPU / no CSI-Bench for the shipping detector.** IsolationForest trains on *this
  room's* normal in seconds. CSI-Bench is only for the optional supervised benchmark.
- The gate is a *room* number (false alarms/week over weeks), not a dataset accuracy.
