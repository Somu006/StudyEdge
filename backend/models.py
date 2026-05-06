from sqlalchemy import Column, Integer, String, DateTime
from database import Base
import datetime

class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String, index=True)
    fault_type = Column(String)
    severity = Column(String) # P1, P2, P3
    recommended_action = Column(String)
    explanation = Column(String)
    status = Column(String, default="Open")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class SensorLog(Base):
    __tablename__ = "sensor_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String, index=True)
    vibration = Column(Integer) # scaled or float 
    temperature = Column(Integer)
    pressure = Column(Integer)
    current = Column(Integer)
    is_anomaly = Column(String) # boolean stored as string or int
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
