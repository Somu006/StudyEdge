"""
predictive_engine.py — Proactive Predictive Maintenance Engine

This module provides TRUE predictive capabilities:
1. Trend Analysis — detects degradation BEFORE thresholds are crossed
2. Health Alerts — warns at 70%, 50%, 30% health levels
3. Maintenance Scheduler — calculates next service date from RUL
4. Early Warning — detects slow drift toward failure

Unlike reactive anomaly detection (which fires AFTER failure),
this engine warns BEFORE problems occur.
"""

import time
from collections import deque
from datetime import datetime, timezone, timedelta


class PredictiveEngine:
    """
    Analyzes sensor trends and predicts upcoming failures.
    Runs every tick (1 second) alongside the main sensor loop.
    """

    def __init__(self):
        # Rolling windows for trend analysis
        self._short_window = deque(maxlen=60)    # last 60 seconds
        self._long_window  = deque(maxlen=300)   # last 5 minutes

        # Alert state tracking (avoid spamming)
        self._last_health_alert_level = None
        self._last_trend_alert_time   = 0
        self._last_maintenance_calc   = 0

        # Current predictions
        self.status          = "normal"       # normal | degrading | warning | critical
        self.trend_warnings  = []             # list of active trend warnings
        self.health_alert    = None           # current health alert level
        self.maintenance_due = None           # predicted maintenance date
        self.days_to_maintenance = None       # days until maintenance needed
        self.degradation_rate = 0.0           # health % lost per hour

    def tick(self, reading: dict) -> dict:
        """
        Called every second with the latest sensor reading.
        Returns a prediction dict to be merged into the reading for the frontend.
        """
        # Store in windows
        entry = {
            "ts":        time.time(),
            "volt":      reading.get("volt", 170.0),
            "rotate":    reading.get("rotate", 450.0),
            "pressure":  reading.get("pressure", 100.0),
            "vibration": reading.get("vibration", 40.0),
            "health_pct": reading.get("health_pct") or 100.0,
            "rul":       reading.get("rul", 0.0),
        }
        self._short_window.append(entry)
        self._long_window.append(entry)

        # Run analyses
        self._analyze_trends()
        self._check_health_levels(entry["health_pct"])
        self._calculate_maintenance(entry)
        self._determine_status(entry)

        # Return prediction data for the frontend
        return {
            "prediction_status":      self.status,
            "trend_warnings":         self.trend_warnings,
            "health_alert":           self.health_alert,
            "maintenance_due":        self.maintenance_due,
            "days_to_maintenance":    self.days_to_maintenance,
            "degradation_rate":       round(self.degradation_rate, 3),
        }

    def _analyze_trends(self):
        """
        Compare short window (1 min) vs long window (5 min).
        Detect if parameters are trending toward danger.
        """
        self.trend_warnings = []

        if len(self._short_window) < 30 or len(self._long_window) < 120:
            return  # not enough data yet

        short_list = list(self._short_window)
        long_list  = list(self._long_window)

        # Calculate averages
        short_avg = {
            "vibration": sum(r["vibration"] for r in short_list[-30:]) / 30,
            "volt":      sum(r["volt"]      for r in short_list[-30:]) / 30,
            "pressure":  sum(r["pressure"]  for r in short_list[-30:]) / 30,
            "rotate":    sum(r["rotate"]    for r in short_list[-30:]) / 30,
        }
        long_avg = {
            "vibration": sum(r["vibration"] for r in long_list) / len(long_list),
            "volt":      sum(r["volt"]      for r in long_list) / len(long_list),
            "pressure":  sum(r["pressure"]  for r in long_list) / len(long_list),
            "rotate":    sum(r["rotate"]    for r in long_list) / len(long_list),
        }

        # Vibration trending up (most critical for bearing failure)
        vib_increase = short_avg["vibration"] - long_avg["vibration"]
        if vib_increase > 5.0:  # 5 mm/s increase in short term
            self.trend_warnings.append({
                "parameter": "vibration",
                "message": f"Vibration trending up (+{vib_increase:.1f} mm/s vs 5-min avg)",
                "severity": "warning" if vib_increase > 10 else "advisory",
                "prediction": f"If trend continues, anomaly threshold in ~{max(1, int((70 - short_avg['vibration']) / (vib_increase / 30 * 60)))} min",
            })

        # Voltage drifting (power supply degradation)
        volt_drift = abs(short_avg["volt"] - 170.0)
        if volt_drift > 30.0:
            direction = "high" if short_avg["volt"] > 170 else "low"
            self.trend_warnings.append({
                "parameter": "voltage",
                "message": f"Voltage drifting {direction} ({short_avg['volt']:.0f}V vs 170V nominal)",
                "severity": "warning" if volt_drift > 50 else "advisory",
                "prediction": f"Motor stress increasing — monitor for overheating",
            })

        # Pressure instability
        press_std = (sum((r["pressure"] - short_avg["pressure"])**2 for r in short_list[-30:]) / 30) ** 0.5
        if press_std > 15.0:
            self.trend_warnings.append({
                "parameter": "pressure",
                "message": f"Pressure unstable (±{press_std:.1f} psi fluctuation)",
                "severity": "warning",
                "prediction": "Possible valve or seal degradation",
            })

        # RPM dropping (bearing drag or motor issue)
        rpm_drop = long_avg["rotate"] - short_avg["rotate"]
        if rpm_drop > 30.0 and short_avg["rotate"] < 420:
            self.trend_warnings.append({
                "parameter": "rotation",
                "message": f"RPM declining ({rpm_drop:.0f} RPM below 5-min avg)",
                "severity": "warning" if rpm_drop > 60 else "advisory",
                "prediction": "Possible bearing drag or increased mechanical load",
            })

    def _check_health_levels(self, health_pct: float):
        """
        Generate proactive alerts at health thresholds.
        These fire BEFORE any anomaly is detected.
        """
        if health_pct is None:
            self.health_alert = None
            return

        if health_pct <= 30:
            level = "critical"
            message = "CRITICAL: Machine health below 30% — failure imminent. Schedule emergency maintenance."
        elif health_pct <= 50:
            level = "warning"
            message = "WARNING: Machine health below 50% — degradation accelerating. Plan maintenance within 1 week."
        elif health_pct <= 70:
            level = "advisory"
            message = "ADVISORY: Machine health below 70% — early degradation detected. Schedule inspection."
        else:
            level = None
            message = None

        self.health_alert = {"level": level, "message": message, "health_pct": health_pct} if level else None

    def _calculate_maintenance(self, entry: dict):
        """
        Calculate next maintenance date based on RUL and degradation rate.
        Only recalculate every 30 seconds to avoid noise.
        """
        now = time.time()
        if now - self._last_maintenance_calc < 30:
            return
        self._last_maintenance_calc = now

        # Calculate degradation rate (health % lost per hour)
        if len(self._long_window) >= 60:
            long_list = list(self._long_window)
            oldest_health = long_list[0]["health_pct"]
            newest_health = long_list[-1]["health_pct"]
            time_span_hours = (long_list[-1]["ts"] - long_list[0]["ts"]) / 3600.0

            if time_span_hours > 0.01:  # at least 36 seconds of data
                self.degradation_rate = (oldest_health - newest_health) / time_span_hours
            else:
                self.degradation_rate = 0.0
        else:
            self.degradation_rate = 0.0

        # Predict maintenance date from RUL
        health = entry.get("health_pct") or 100.0
        rul_hours = entry.get("rul_hours", 0)

        if rul_hours and rul_hours > 0:
            # Use RUL directly for maintenance scheduling
            maintenance_hours = rul_hours * 0.7  # Schedule at 70% of remaining life
            self.days_to_maintenance = max(1, int(maintenance_hours / 24))
            self.maintenance_due = (
                datetime.now(timezone.utc) + timedelta(hours=maintenance_hours)
            ).strftime("%Y-%m-%d")
        elif self.degradation_rate > 0.1:
            # Fallback: extrapolate from degradation rate
            hours_to_30pct = max(0, (health - 30.0) / self.degradation_rate)
            self.days_to_maintenance = max(1, int(hours_to_30pct / 24))
            self.maintenance_due = (
                datetime.now(timezone.utc) + timedelta(hours=hours_to_30pct)
            ).strftime("%Y-%m-%d")
        else:
            # Healthy, no degradation detected
            self.days_to_maintenance = None
            self.maintenance_due = None

    def _determine_status(self, entry: dict):
        """
        Determine overall predictive status:
        - normal:    everything fine, no trends
        - degrading: trends detected but not critical
        - warning:   health below 70% or strong trends
        - critical:  health below 30% or imminent failure
        """
        health = entry.get("health_pct") or 100.0

        if health <= 30 or any(w["severity"] == "warning" for w in self.trend_warnings if "anomaly threshold" in w.get("prediction", "")):
            self.status = "critical"
        elif health <= 50 or len([w for w in self.trend_warnings if w["severity"] == "warning"]) >= 2:
            self.status = "warning"
        elif health <= 70 or len(self.trend_warnings) > 0:
            self.status = "degrading"
        else:
            self.status = "normal"

    def get_prediction_summary(self) -> dict:
        """Full prediction state for API endpoint."""
        return {
            "status":              self.status,
            "trend_warnings":      self.trend_warnings,
            "health_alert":        self.health_alert,
            "maintenance_due":     self.maintenance_due,
            "days_to_maintenance": self.days_to_maintenance,
            "degradation_rate_per_hour": round(self.degradation_rate, 3),
            "short_window_size":   len(self._short_window),
            "long_window_size":    len(self._long_window),
            "timestamp":           datetime.now(timezone.utc).isoformat(),
        }


# Singleton
predictor = PredictiveEngine()
