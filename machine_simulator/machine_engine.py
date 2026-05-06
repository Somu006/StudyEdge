import time
import random
import math


class MachineEngine:
    """
    Industrial Screw Air Compressor Simulation Engine
    
    Simulates a compressor with 4 sensor parameters matching the
    Microsoft PdM (Predictive Maintenance) dataset ranges:
      - Voltage:   ~170V (mean), range 100-300V
      - Rotation:  ~450 RPM (mean), range 0-3000 RPM
      - Pressure:  ~100 units (mean), range 0-250
      - Vibration: ~40 mm/s (mean), range 0-150
    
    Physics model:
      Voltage -> Motor torque -> Rotation
      Rotation -> Compression -> Pressure
      Pressure -> Back-load on motor
      All parameters -> Vibration
    
    The simulation uses real physical relationships but scaled to match
    the dataset ranges so the ML model (RUL prediction) works correctly.
    """

    def __init__(self):
        # -- Setpoints (what the user dials in via sliders) --
        self.voltage_setpoint: float = 170.0
        self.rotation_setpoint: float = 450.0
        self.pressure_setpoint: float = 100.0
        self.vibration_setpoint: float = 40.0

        # -- Actual physical state --
        self.actual_voltage: float = 170.0
        self.actual_rotation: float = 450.0
        self.actual_pressure: float = 100.0
        self.actual_vibration: float = 40.0

        # -- Operating limits --
        self.max_voltage: float = 300.0
        self.max_rotation: float = 3000.0
        self.max_pressure: float = 250.0
        self.max_vibration: float = 150.0

        # -- Internal state --
        self._last_tick: float = time.time()
        self.temperature: float = 35.0
        self.wear_factor: float = 0.0

    def set_params(self, voltage: float = None, rotation: float = None,
                   pressure: float = None, vibration: float = None):
        """Update setpoints from user input."""
        if voltage is not None:
            self.voltage_setpoint = max(0.0, min(float(voltage), self.max_voltage))
        if rotation is not None:
            self.rotation_setpoint = max(0.0, min(float(rotation), self.max_rotation))
        if pressure is not None:
            self.pressure_setpoint = max(0.0, min(float(pressure), self.max_pressure))
        if vibration is not None:
            self.vibration_setpoint = max(0.0, min(float(vibration), self.max_vibration))

    def tick(self) -> dict:
        """
        Advance simulation by one time step (~1 second).
        
        Physics approach:
        - Each actual value tracks toward its setpoint using first-order dynamics
        - Cross-coupling between parameters adds realism
        - Sensor noise simulates real measurement uncertainty
        """
        now = time.time()
        dt = now - self._last_tick
        dt = max(0.05, min(3.0, dt))
        self._last_tick = now

        # Sub-step for numerical stability
        steps = 10
        h = dt / steps

        for _ in range(steps):
            # ─── VOLTAGE ───────────────────────────────────────────────
            # Fast response (power electronics), tau ~ 0.3s
            tau_v = 0.3
            self.actual_voltage += (h / (tau_v + h)) * (self.voltage_setpoint - self.actual_voltage)

            # ─── ROTATION ──────────────────────────────────────────────
            # Motor speed controlled by VFD (Variable Frequency Drive)
            # Tracks setpoint, but affected by voltage and pressure load
            #
            # Physics: higher voltage = more torque available = can reach higher RPM
            # Higher pressure = more load = RPM drops slightly
            tau_r = 1.5  # Mechanical time constant (inertia), ~1.5s
            
            # Voltage effect: if voltage drops below rated, max achievable RPM drops
            voltage_factor = self.actual_voltage / 170.0  # 1.0 at rated voltage
            
            # Pressure load effect: higher pressure = harder to maintain speed
            # At 100 (normal), no effect. At 200, RPM drops ~10%
            load_factor = 1.0 - 0.1 * max(0.0, (self.actual_pressure - 100.0) / 100.0)
            
            # Target RPM considering physics
            effective_target = self.rotation_setpoint * min(voltage_factor, 1.2) * max(load_factor, 0.5)
            
            self.actual_rotation += (h / (tau_r + h)) * (effective_target - self.actual_rotation)
            self.actual_rotation = max(0.0, min(self.max_rotation, self.actual_rotation))

            # ─── PRESSURE ──────────────────────────────────────────────
            # Pressure builds from compression (proportional to RPM)
            # Suction valve modulates to hold setpoint
            # Natural leakage reduces pressure
            tau_p = 3.0  # Pressure time constant (tank filling), ~3s
            
            # Generation: proportional to RPM (more rotation = more compression)
            rpm_ratio = self.actual_rotation / 450.0  # 1.0 at normal RPM
            generation_target = self.pressure_setpoint * rpm_ratio
            
            # Suction valve modulation: holds pressure near setpoint
            if self.actual_pressure > self.pressure_setpoint * 1.02:
                # Unloading: valve closes, pressure drops toward setpoint
                pressure_target = self.pressure_setpoint
                tau_p = 2.0  # Faster correction
            elif self.actual_pressure < self.pressure_setpoint * 0.98:
                # Loading: valve open, pressure builds
                pressure_target = generation_target
                tau_p = 2.5
            else:
                # In band: maintain
                pressure_target = self.pressure_setpoint
                tau_p = 4.0
            
            # Leak effect (small continuous loss)
            leak = 0.001 * self.actual_pressure * h
            
            self.actual_pressure += (h / (tau_p + h)) * (pressure_target - self.actual_pressure) - leak
            self.actual_pressure = max(0.0, min(self.max_pressure, self.actual_pressure))

        # ─── VIBRATION ─────────────────────────────────────────────────
        # Vibration is an OUTPUT, not directly controllable.
        # It depends on: base condition (setpoint), RPM, pressure stability, wear
        #
        # The setpoint represents the machine's mechanical condition:
        #   Low setpoint (20) = well-balanced, new bearings
        #   High setpoint (80+) = worn bearings, misalignment
        
        # Base from mechanical condition
        base_vib = self.vibration_setpoint * 0.75
        
        # RPM contribution (centrifugal force ~ omega^2)
        # At 450 RPM (normal): adds ~3. At 1500 RPM: adds ~30
        rpm_vib = (self.actual_rotation / 450.0) ** 2 * 3.0
        
        # Pressure instability contribution
        pressure_error = abs(self.actual_pressure - self.pressure_setpoint)
        pressure_vib = (pressure_error / 50.0) * 5.0
        
        # Voltage instability
        voltage_error = abs(self.actual_voltage - self.voltage_setpoint)
        voltage_vib = (voltage_error / 50.0) * 3.0
        
        # Wear contribution (accumulates over time)
        wear_vib = self.wear_factor * 20.0
        
        self.actual_vibration = base_vib + rpm_vib + pressure_vib + voltage_vib + wear_vib
        self.actual_vibration = max(0.0, min(self.max_vibration, self.actual_vibration))

        # ─── TEMPERATURE ───────────────────────────────────────────────
        # Heat from compression and motor losses, cooling from aftercooler
        heat_in = (self.actual_rotation / 1000.0) * 3.0 + (self.actual_voltage / 200.0) * 2.0
        heat_out = (self.temperature - 25.0) * 0.08
        self.temperature += (heat_in - heat_out) * dt / 30.0
        self.temperature = max(25.0, min(130.0, self.temperature))

        # ─── WEAR ──────────────────────────────────────────────────────
        speed_stress = self.actual_rotation / 1500.0
        vib_stress = self.actual_vibration / 50.0
        self.wear_factor += speed_stress * vib_stress * 0.00002 * dt
        self.wear_factor = min(1.0, self.wear_factor)

        # ─── SENSOR OUTPUTS (with realistic measurement noise) ─────────
        out_volt = max(0.0, random.gauss(self.actual_voltage, 3.0))
        out_rotate = max(0.0, random.gauss(self.actual_rotation, 8.0))
        out_press = max(0.0, random.gauss(self.actual_pressure, 2.0))
        out_vib = max(0.0, random.gauss(self.actual_vibration, 1.0))

        # ─── ANOMALY DETECTION ─────────────────────────────────────────
        is_anomaly = (
            out_volt > 250.0 or
            out_volt < 100.0 or
            out_rotate < 100.0 or
            out_rotate > 2000.0 or
            out_press > 180.0 or
            out_vib > 70.0 or
            self.temperature > 110.0
        )

        return {
            "timestamp": round(now, 3),
            "volt": round(out_volt, 2),
            "rotate": round(out_rotate, 2),
            "pressure": round(out_press, 2),
            "vibration": round(out_vib, 2),
            "is_anomaly": is_anomaly,
            "temperature": round(self.temperature, 1),
            "wear": round(self.wear_factor * 100, 1),
        }

    def get_state(self) -> dict:
        """Return current state without advancing time."""
        return {
            "volt": round(self.actual_voltage, 2),
            "rotate": round(self.actual_rotation, 2),
            "pressure": round(self.actual_pressure, 2),
            "vibration": round(self.actual_vibration, 2),
            "temperature": round(self.temperature, 1),
            "wear": round(self.wear_factor * 100, 1),
        }

    def reset(self):
        """Reset to initial conditions."""
        self.actual_voltage = self.voltage_setpoint
        self.actual_rotation = self.rotation_setpoint
        self.actual_pressure = self.pressure_setpoint
        self.actual_vibration = self.vibration_setpoint
        self.temperature = 35.0
        self.wear_factor = 0.0
        self._last_tick = time.time()
