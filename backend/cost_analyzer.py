"""
cost_analyzer.py — Maintenance Cost Optimization Engine

Calculates the financial impact of maintenance decisions:
- Preventive maintenance cost vs corrective (after failure) cost
- ROI of predictive maintenance
- Optimal maintenance timing based on RUL and cost curves

This is what makes the project a BUSINESS case, not just a tech demo.
"""

from datetime import datetime, timezone


# ─── Cost Parameters (Industrial Screw Compressor) ────────────────
# Based on real industry data for 37kW rotary screw compressors

COSTS = {
    # Preventive maintenance costs (scheduled)
    "preventive": {
        "bearing_replacement":    8500,    # ₹ — planned bearing swap
        "oil_change":             3200,    # ₹ — routine oil service
        "filter_replacement":     2100,    # ₹ — air/oil filter
        "belt_alignment":         4500,    # ₹ — coupling/belt service
        "electrical_inspection":  3800,    # ₹ — motor winding check
        "full_overhaul":         45000,    # ₹ — complete service
    },
    # Corrective maintenance costs (after failure — much higher)
    "corrective": {
        "bearing_failure":       35000,    # ₹ — emergency bearing + motor damage
        "motor_burnout":         85000,    # ₹ — motor replacement
        "pressure_leak":         22000,    # ₹ — seal replacement + lost production
        "oil_system_failure":    28000,    # ₹ — separator + flush + refill
        "compressor_element":   120000,    # ₹ — screw element replacement
        "electrical_failure":    45000,    # ₹ — VFD/starter replacement
    },
    # Downtime cost
    "downtime_per_hour":         12000,    # ₹ — lost production per hour
    # Typical repair times
    "repair_hours": {
        "preventive":  4,     # hours — planned maintenance
        "corrective": 16,     # hours — emergency repair (includes diagnosis)
    },
}


class CostAnalyzer:
    """Calculates maintenance cost optimization and ROI."""

    def analyze(self, fault_type: str, severity: str, health_pct: float,
                rul_hours: float, auto_fixed: bool) -> dict:
        """
        Full cost-benefit analysis for a maintenance decision.
        
        Returns a dict with:
        - preventive_cost: cost if you do maintenance NOW
        - corrective_cost: cost if you wait until failure
        - savings: money saved by acting now
        - roi_percent: return on investment of predictive maintenance
        - recommendation: human-readable advice
        - optimal_window: best time to schedule maintenance
        """
        # Map fault type to cost category
        category = self._map_fault_to_category(fault_type)
        
        preventive_cost = COSTS["preventive"].get(category, 8500)
        corrective_cost = COSTS["corrective"].get(
            self._map_fault_to_corrective(fault_type), 35000
        )
        
        # Downtime costs
        preventive_downtime = COSTS["repair_hours"]["preventive"] * COSTS["downtime_per_hour"]
        corrective_downtime = COSTS["repair_hours"]["corrective"] * COSTS["downtime_per_hour"]
        
        total_preventive = preventive_cost + preventive_downtime
        total_corrective = corrective_cost + corrective_downtime
        
        savings = total_corrective - total_preventive
        roi_pct = round((savings / total_preventive) * 100, 1) if total_preventive > 0 else 0
        
        # Risk factor based on health
        failure_probability = self._calculate_failure_probability(health_pct, rul_hours)
        expected_loss = total_corrective * failure_probability
        
        # Optimal maintenance window
        if health_pct > 70:
            window = "Schedule within 30 days"
            urgency = "low"
        elif health_pct > 50:
            window = "Schedule within 7 days"
            urgency = "medium"
        elif health_pct > 30:
            window = "Schedule within 48 hours"
            urgency = "high"
        else:
            window = "IMMEDIATE — failure imminent"
            urgency = "critical"

        # Recommendation
        if auto_fixed:
            recommendation = (
                f"AI auto-fixed the issue. Monitor for recurrence. "
                f"Schedule preventive maintenance within 7 days to prevent repeat failure."
            )
        elif severity == "P1":
            recommendation = (
                f"CRITICAL: Immediate shutdown and repair required. "
                f"Corrective cost if delayed: ₹{total_corrective:,}. "
                f"Act now to save ₹{savings:,}."
            )
        else:
            recommendation = (
                f"Schedule preventive maintenance ({window}). "
                f"Cost now: ₹{total_preventive:,} vs failure cost: ₹{total_corrective:,}. "
                f"ROI of acting early: {roi_pct}%."
            )

        return {
            "preventive_cost":     total_preventive,
            "corrective_cost":     total_corrective,
            "savings":             savings,
            "roi_percent":         roi_pct,
            "failure_probability": round(failure_probability * 100, 1),
            "expected_loss":       round(expected_loss),
            "downtime_hours": {
                "preventive": COSTS["repair_hours"]["preventive"],
                "corrective": COSTS["repair_hours"]["corrective"],
            },
            "optimal_window":      window,
            "urgency":             urgency,
            "recommendation":      recommendation,
            "currency":            "INR",
        }

    def _map_fault_to_category(self, fault_type: str) -> str:
        ft = fault_type.lower()
        if "bearing" in ft or "vibration" in ft:
            return "bearing_replacement"
        elif "voltage" in ft or "motor" in ft or "overload" in ft:
            return "electrical_inspection"
        elif "pressure" in ft or "leak" in ft:
            return "belt_alignment"
        elif "oil" in ft:
            return "oil_change"
        else:
            return "full_overhaul"

    def _map_fault_to_corrective(self, fault_type: str) -> str:
        ft = fault_type.lower()
        if "bearing" in ft:
            return "bearing_failure"
        elif "motor" in ft or "overload" in ft:
            return "motor_burnout"
        elif "voltage" in ft or "electrical" in ft:
            return "electrical_failure"
        elif "pressure" in ft or "leak" in ft:
            return "pressure_leak"
        elif "oil" in ft:
            return "oil_system_failure"
        else:
            return "compressor_element"

    def _calculate_failure_probability(self, health_pct: float, rul_hours: float) -> float:
        """Estimate probability of failure in next 7 days based on health and RUL."""
        if health_pct <= 20:
            return 0.90
        elif health_pct <= 40:
            return 0.60
        elif health_pct <= 60:
            return 0.30
        elif health_pct <= 80:
            return 0.10
        else:
            return 0.02


# Singleton
cost_analyzer = CostAnalyzer()
