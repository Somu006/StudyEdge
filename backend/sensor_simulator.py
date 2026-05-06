import time
import random
import asyncio

class SensorSimulator:
    def __init__(self, machine_id="Machine-1"):
        self.machine_id = machine_id
        # Baseline normal values for PdM dataset
        self.volt_base = 170.0
        self.rotate_base = 450.0
        self.pressure_base = 100.0
        self.vibration_base = 40.0
        
        self.is_anomaly = False
        
    def trigger_anomaly(self):
        """Triggers an anomaly state."""
        self.is_anomaly = True
        print(f"[{self.machine_id}] Anomaly injected!")

    def generate_reading(self):
        # Add random noise
        volt = max(0, random.normalvariate(self.volt_base, 5.0))
        rotate = max(0, random.normalvariate(self.rotate_base, 20.0))
        press = max(0, random.normalvariate(self.pressure_base, 10.0))
        vib = max(0, random.normalvariate(self.vibration_base, 2.0))

        if self.is_anomaly:
            # Shift the mean for anomaly - MAKE IT MASSIVE for the LSTM
            volt += random.uniform(80.0, 150.0)    # Huge voltage spike
            rotate -= random.uniform(300.0, 400.0) # Rotation almost stops
            press += random.uniform(100.0, 200.0)  # Extreme pressure
            vib += random.uniform(50.0, 100.0)     # Massive vibration

        return {
            "machine_id": self.machine_id,
            "timestamp": time.time(),
            "volt": round(volt, 2),
            "rotate": round(rotate, 2),
            "pressure": round(press, 2),
            "vibration": round(vib, 2),
            "is_anomaly": self.is_anomaly
        }
