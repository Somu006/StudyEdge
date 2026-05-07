"""
anomaly_detector.py — ML-based Anomaly Detection using Isolation Forest

This replaces simple threshold-based detection with a real ML model that:
1. Learns what "normal" looks like from a rolling window
2. Detects anomalies BEFORE thresholds are crossed
3. Provides an anomaly SCORE (0-1) not just True/False
4. Explains WHICH parameters contributed most to the anomaly

This is TRUE predictive AI — it catches subtle multi-variate patterns
that simple if-statements miss.
"""

import numpy as np
from collections import deque
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


class AnomalyDetector:
    """
    Isolation Forest-based anomaly detector.
    
    How it works:
    - Trains on a rolling window of "normal" data (first 120 seconds)
    - After training, scores every new reading
    - Score < threshold = anomaly detected
    - Also provides feature importance (which sensor caused it)
    """

    def __init__(self, contamination: float = 0.10, window_size: int = 300):
        self.contamination = contamination
        self.window_size   = window_size
        self._buffer       = deque(maxlen=window_size)
        self._model        = None
        self._scaler       = StandardScaler()
        self._is_trained   = False
        self._train_threshold = 120  # train after 120 readings
        self._feature_names = ["volt", "rotate", "pressure", "vibration"]
        
        # Normal reference (for explainability)
        self._normal_mean = np.array([170.0, 450.0, 100.0, 40.0])
        self._normal_std  = np.array([10.0, 30.0, 15.0, 5.0])

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def _extract_features(self, reading: dict) -> np.ndarray:
        """Extract the 4 sensor features from a reading dict."""
        return np.array([
            reading.get("volt",      170.0),
            reading.get("rotate",    450.0),
            reading.get("pressure",  100.0),
            reading.get("vibration",  40.0),
        ])

    def _train(self):
        """Train the Isolation Forest on the buffered normal data."""
        if len(self._buffer) < self._train_threshold:
            return

        X = np.array(list(self._buffer))
        self._scaler.fit(X)
        X_scaled = self._scaler.transform(X)

        self._model = IsolationForest(
            contamination=self.contamination,
            n_estimators=100,
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(X_scaled)
        self._is_trained = True
        
        # Update normal reference from training data
        self._normal_mean = X.mean(axis=0)
        self._normal_std  = X.std(axis=0) + 1e-6
        
        print(f"[AnomalyDetector] Trained on {len(self._buffer)} samples. Ready for inference.", flush=True)

    def score(self, reading: dict) -> dict:
        """
        Score a reading for anomaly.
        
        Returns:
            {
                "ml_anomaly": bool,           # True if ML detects anomaly
                "anomaly_score": float,       # 0.0 (normal) to 1.0 (highly anomalous)
                "confidence": float,          # model confidence 0-1
                "feature_contributions": {    # which sensor caused it
                    "volt": float,
                    "rotate": float,
                    "pressure": float,
                    "vibration": float,
                },
                "model_trained": bool,
            }
        """
        features = self._extract_features(reading)
        self._buffer.append(features)

        # Not enough data yet — train first
        if not self._is_trained:
            if len(self._buffer) >= self._train_threshold:
                self._train()
            return {
                "ml_anomaly": False,
                "anomaly_score": 0.0,
                "confidence": 0.0,
                "feature_contributions": {n: 0.0 for n in self._feature_names},
                "model_trained": False,
            }

        # Retrain periodically (every 300 readings) to adapt
        if len(self._buffer) == self._buffer.maxlen and len(self._buffer) % 300 == 0:
            self._train()

        # Score the reading
        X = features.reshape(1, -1)
        X_scaled = self._scaler.transform(X)

        # Isolation Forest: decision_function returns negative for anomalies
        raw_score = self._model.decision_function(X_scaled)[0]
        prediction = self._model.predict(X_scaled)[0]  # 1 = normal, -1 = anomaly

        # Convert to 0-1 score (higher = more anomalous)
        # decision_function range is roughly [-0.5, 0.5], center at 0
        anomaly_score = max(0.0, min(1.0, 0.5 - raw_score))
        
        # Use score-based detection (more reliable than predict())
        is_anomaly = anomaly_score > 0.35

        # Feature contributions (how much each feature deviates from learned normal)
        deviations = np.abs(features - self._normal_mean) / self._normal_std
        total_dev  = deviations.sum() + 1e-6
        contributions = deviations / total_dev

        return {
            "ml_anomaly":    is_anomaly,
            "anomaly_score": round(float(anomaly_score), 3),
            "confidence":    round(min(1.0, len(self._buffer) / self._train_threshold), 2),
            "feature_contributions": {
                self._feature_names[i]: round(float(contributions[i]), 3)
                for i in range(4)
            },
            "model_trained": True,
        }


# Singleton
anomaly_detector = AnomalyDetector()
