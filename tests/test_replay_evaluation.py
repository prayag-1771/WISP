"""Recording -> replay -> gate numbers, the path the deliverable actually travels.

`scripts/record.py` writes a log, `scripts/evaluate.py --replay` scores it. The join between
them is `ReplaySource.total_duration`: the harness divides false alarms by it to produce
false-alarms-per-week, so a source that does not report a duration silently reports the gate
number as infinity.
"""

import numpy as np
import pytest

from wisp.calibrate.profile import RoomProfile
from wisp.evaluate.harness import Metrics, evaluate
from wisp.ingest.logger import RawLogger
from wisp.source.replay import ReplaySource
from wisp.source.synthetic import SyntheticSource


def _record(path, source):
    with RawLogger(str(path)) as log:
        for t, amp in source.stream():
            log.log(t, amp)
    return str(path)


def test_replay_reports_the_recording_duration(tmp_path):
    # explicit segments, not normal_only(): that helper rounds up to whole 90 s blocks, and
    # this test is about the duration being read back exactly as recorded
    src30 = SyntheticSource([("empty", 10.0), ("walk", 20.0)], sample_rate_hz=20.0)
    src = ReplaySource(_record(tmp_path / "normal.csv", src30))

    # 30 s at 20 Hz, measured first packet to last
    assert src.total_duration == pytest.approx(30.0, abs=0.2)
    # cached, and reading it does not consume the stream
    assert src.total_duration == src.total_duration
    assert len(list(src.stream())) == pytest.approx(600, abs=2)


def test_duration_of_an_empty_or_comment_only_log_is_zero(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("# wisp raw CSI log\n", encoding="utf-8")
    assert ReplaySource(str(path)).total_duration == 0.0


def test_false_alarms_per_week_is_finite_for_a_recording(tmp_path):
    """The whole point: an unlabelled recording of ordinary life yields a real gate number
    rather than a division by zero."""
    path = _record(tmp_path / "normal.csv",
                   SyntheticSource.normal_only(minutes=1.0, sample_rate_hz=20.0))
    profile = RoomProfile.fit(
        SyntheticSource.normal_only(minutes=1.0, sample_rate_hz=20.0), sample_rate_hz=20.0)

    src = ReplaySource(path)
    metrics = evaluate(src, [], profile, duration_s=src.total_duration)

    assert metrics.duration_s > 0
    assert np.isfinite(metrics.false_alarms_per_week)
    assert metrics.n_events == 0


def test_report_says_n_a_instead_of_nan_when_nothing_was_staged():
    m = Metrics(n_events=0, n_detected=0, false_alarms=3, duration_s=3600.0,
                latencies=[], kind_correct=0)
    report = m.report()

    assert "nan" not in report.lower()
    assert "n/a" in report
    assert "per week" in report
