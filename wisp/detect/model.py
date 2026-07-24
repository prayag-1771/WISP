"""S5 — anomaly model. IsolationForest: fastest anomaly detector to get running.

Trains on the room's normal feature vectors and scores live windows for how anomalous
they are. Autoencoder / supervised baseline / model registry are all deferred.
"""

from __future__ import annotations

import numpy as np


class AnomalyModel:
    """Wraps sklearn IsolationForest over the S3 feature vectors."""

    def fit(self, features: np.ndarray) -> None:
        raise NotImplementedError("AnomalyModel.fit — train on normal features.")

    def score(self, features: np.ndarray) -> float:
        """Return an anomaly score for one feature vector (higher = more anomalous)."""
        raise NotImplementedError("AnomalyModel.score")
