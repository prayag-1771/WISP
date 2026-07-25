"""S5 — anomaly model. IsolationForest: fastest anomaly detector to get running.

Trains on the room's normal feature vectors (motion_intensity, transient_sharpness) and
scores live windows for how anomalous they are. Trains in seconds on CPU — no GPU, no
epochs, no external dataset. Autoencoder / supervised baseline / model registry are all
deferred.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest


class AnomalyModel:
    """Wraps sklearn IsolationForest over the S3 feature vectors."""

    FEATURES = ("motion_intensity", "transient_sharpness")

    def __init__(self, n_estimators: int = 100, contamination: float = 0.01, random_state: int = 0) -> None:
        self._forest = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=random_state,
        )
        self._fitted = False

    @classmethod
    def to_vector(cls, features: dict) -> np.ndarray:
        """Feature dict -> ordered 1-D vector the model expects."""
        return np.array([features[k] for k in cls.FEATURES], dtype=np.float64)

    def fit(self, features: np.ndarray) -> None:
        """Train on normal feature vectors, shape (n_windows, n_features)."""
        self._forest.fit(features)
        self._fitted = True

    def score(self, features: dict) -> float:
        """Anomaly score for one feature dict (higher = more anomalous)."""
        vec = self.to_vector(features).reshape(1, -1)
        # score_samples: higher = more normal. Negate so higher = more anomalous.
        return float(-self._forest.score_samples(vec)[0])

    def is_anomaly(self, features: dict) -> bool:
        """True if the forest labels this window an outlier (predict == -1)."""
        vec = self.to_vector(features).reshape(1, -1)
        return bool(self._forest.predict(vec)[0] == -1)
