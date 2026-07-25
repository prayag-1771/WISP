"""Tests for the CSI-Bench adapter — verified against a synthetic .h5 we write here.

We can't ship the real dataset, but the adapter's job (discover a 2-D dataset, convert to
amplitude, stream rows through the CSISource contract) is fully testable on a fake file.
Skipped automatically if h5py isn't installed.
"""

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from wisp.source.csi_bench_source import CSIBenchSource


def _write_h5(path, data, key="csi"):
    with h5py.File(path, "w") as f:
        f.create_dataset(key, data=data)


def test_streams_real_valued_amplitude(tmp_path):
    fp = tmp_path / "session.h5"
    data = np.arange(30, dtype=np.float64).reshape(10, 3)   # 10 time steps, 3 subcarriers
    _write_h5(fp, data)

    src = CSIBenchSource(str(fp), sample_rate_hz=100.0)
    rows = list(src.stream())
    assert len(rows) == 10
    t0, amp0 = rows[0]
    assert t0 == 0.0
    assert np.allclose(amp0, [0, 1, 2])
    # timestamps advance by 1/rate
    assert np.isclose(rows[1][0] - rows[0][0], 0.01)


def test_complex_is_converted_to_magnitude(tmp_path):
    fp = tmp_path / "complex.h5"
    data = np.array([[3 + 4j, 0 + 0j], [6 + 8j, 5 + 12j]])   # magnitudes: [5,0],[10,13]
    _write_h5(fp, data)

    src = CSIBenchSource(str(fp), convert="auto")
    amps = [amp for _, amp in src.stream()]
    assert np.allclose(amps[0], [5.0, 0.0])
    assert np.allclose(amps[1], [10.0, 13.0])


def test_iq_interleaved_pairs(tmp_path):
    fp = tmp_path / "iq.h5"
    data = np.array([[3.0, 4.0, 6.0, 8.0]])                  # (I,Q)=(3,4),(6,8) -> 5,10
    _write_h5(fp, data)

    src = CSIBenchSource(str(fp), convert="iq")
    _, amp = next(iter(src.stream()))
    assert np.allclose(amp, [5.0, 10.0])


def test_list_datasets_reports_shape(tmp_path):
    fp = tmp_path / "inspect.h5"
    _write_h5(fp, np.zeros((5, 4)), key="grp/csi")
    listed = CSIBenchSource(str(fp)).list_datasets()
    assert ("grp/csi", (5, 4)) == (listed[0][0], listed[0][1])
