"""CSIBenchSource — replay CSI-Bench .h5 clips through the CSISource interface.

CSI-Bench (https://github.com/guozhen-jenn-zhu/CSI-Bench-Real-WiFi-Sensing-Benchmark,
Kaggle: guozhenjennzhu/csi-bench) ships real Wi-Fi CSI as per-session HDF5 files under a
single-task tree, e.g. ``FallDetection/sub_User/user_U#/act_Activity/env_E#/device/session_*.h5``.
This adapter turns one such file (or a directory of them) into the same
``(timestamp, amplitude)`` stream the synthetic and serial sources produce, so the exact
same pipeline can chew on real captured CSI.

Honest scope — what this is and isn't for
------------------------------------------
- ✅ Confirm the pipeline (features -> model -> state machine) *runs on real CSI shapes*,
  and eyeball real falls vs real normal.
- ✅ Feed the OPTIONAL supervised benchmark (S5.4).
- ⚠️ It does NOT reproduce the Phase-0 gate. The gate is a *room* number
  (false-alarms/week over weeks of continuous living); CSI-Bench is segmented clips from
  many rooms/devices, and the unsupervised detector calibrates to one room's own normal.
  Treat this as a code/real-signal sanity check, not the gate.

HDF5 layout note
----------------
CSI-Bench's exact in-file dataset name/dtype is not published in the repo README, and it
differs across releases. This reader therefore *discovers* the CSI array (largest 2-D
numeric dataset) and converts it to amplitude, but you should confirm the layout against
a downloaded file with ``CSIBenchSource(path).list_datasets()`` and, if needed, pass an
explicit ``dataset`` key. If clips carry no timestamps, synthetic ones are generated from
``sample_rate_hz``.
"""

from __future__ import annotations

import glob
import os
from typing import Iterator, List, Optional, Tuple

import numpy as np

from .base import CSISource


class CSIBenchSource(CSISource):
    """Streams amplitude rows from a CSI-Bench .h5 file (or a directory of them).

    Parameters
    ----------
    path : str
        A ``.h5`` file, or a directory (all ``*.h5`` under it are streamed in sorted order).
    dataset : str, optional
        Explicit HDF5 dataset path. If omitted, the largest 2-D numeric dataset is used.
    sample_rate_hz : float
        Used to synthesize timestamps when the file has none.
    convert : {"auto", "complex", "iq", "raw"}
        How to turn stored values into amplitude:
          - ``auto``    : abs() if complex, else use values as-is (already amplitude/features)
          - ``complex`` : force np.abs on a complex array
          - ``iq``      : treat the last axis as interleaved [I,Q,I,Q,...] -> hypot pairs
          - ``raw``     : use values unchanged
    time_axis : int
        Which axis of the 2-D array indexes time (default 0). Set 1 if rows are subcarriers.
    """

    def __init__(
        self,
        path: str,
        dataset: Optional[str] = None,
        sample_rate_hz: float = 100.0,
        convert: str = "auto",
        time_axis: int = 0,
    ) -> None:
        self.path = path
        self.dataset = dataset
        self.sample_rate_hz = float(sample_rate_hz)
        self.dt = 1.0 / self.sample_rate_hz
        self.convert = convert
        self.time_axis = time_axis

    # ------------------------------------------------------------------ helpers
    def _files(self) -> List[str]:
        if os.path.isdir(self.path):
            return sorted(glob.glob(os.path.join(self.path, "**", "*.h5"), recursive=True))
        return [self.path]

    def list_datasets(self) -> List[Tuple[str, tuple, str]]:
        """Return [(dataset_path, shape, dtype)] for the first file — for inspection."""
        import h5py

        found: List[Tuple[str, tuple, str]] = []
        with h5py.File(self._files()[0], "r") as f:
            f.visititems(lambda name, obj: found.append((name, obj.shape, str(obj.dtype)))
                         if isinstance(obj, h5py.Dataset) else None)
        return found

    @staticmethod
    def _pick_dataset(f) -> str:
        """Choose the largest 2-D numeric dataset in an open h5py.File."""
        import h5py

        best, best_size = None, -1
        def visit(name, obj):
            nonlocal best, best_size
            if isinstance(obj, h5py.Dataset) and obj.ndim == 2 and np.issubdtype(obj.dtype, np.number):
                if obj.size > best_size:
                    best, best_size = name, obj.size
        f.visititems(visit)
        if best is None:
            raise ValueError("no 2-D numeric dataset found; pass an explicit `dataset=`")
        return best

    def _to_amplitude(self, arr: np.ndarray) -> np.ndarray:
        """(n_time, k) numeric array -> (n_time, n_subcarriers) amplitude."""
        if self.convert == "raw":
            return arr.astype(np.float64)
        if self.convert == "complex" or (self.convert == "auto" and np.iscomplexobj(arr)):
            return np.abs(arr).astype(np.float64)
        if self.convert == "iq":
            if arr.shape[1] % 2 != 0:
                raise ValueError("`iq` convert needs an even number of columns")
            return np.hypot(arr[:, 0::2], arr[:, 1::2]).astype(np.float64)
        return arr.astype(np.float64)  # auto + real -> already amplitude/features

    # ------------------------------------------------------------------- stream
    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        import h5py

        t = 0.0
        for fp in self._files():
            with h5py.File(fp, "r") as f:
                key = self.dataset or self._pick_dataset(f)
                arr = np.asarray(f[key])
            if arr.ndim != 2:
                raise ValueError(f"{key} in {fp} is not 2-D (shape {arr.shape})")
            if self.time_axis == 1:
                arr = arr.T
            amp = self._to_amplitude(arr)
            for row in amp:
                yield t, row
                t += self.dt
