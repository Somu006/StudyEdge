import asyncio
import time
import uvicorn
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
import pickle
import numpy as np
import pandas as pd
from collections import deque
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env (AWS credentials stay server-side only)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Import our StackedPureLSTM bridge
from pure_lstm import StackedPureLSTM

from sensor_simulator import SensorSimulator
from database import engine, Base, get_db, SessionLocal
from models import WorkOrder, SensorLog
from agent import process_anomaly, process_chat_query, get_agent_activity
from notifier import send_anomaly_email
from dynamo import dynamo
from sns_notifier import sns
from s3_reporter import s3
from agentcore_handler import handler as agentcore_handler
from predictive_engine import predictor
from anomaly_detector import anomaly_detector

# Create DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="MachineWhisperer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

simulator = SensorSimulator("Pump-A1")
active_connections = []
anomaly_processed = False

# Load RUL Model and Scaler
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(BASE_DIR, "rul_model.pth")
scaler_path = os.path.join(BASE_DIR, "lstm_scaler.pkl")

rul_model = None
scaler = None
FEATURE_COLS = []

def load_resources():
    global rul_model, scaler, FEATURE_COLS
    try:
        if os.path.exists(model_path):
            with open(model_path, "rb") as f:
                checkpoint = pickle.load(f)
                rul_model = checkpoint['model_obj']
                FEATURE_COLS = checkpoint.get('feature_cols', [])
            print(f"RUL Model loaded from {model_path}", flush=True)
        
        if os.path.exists(scaler_path):
            with open(scaler_path, "rb") as f:
                scaler_data = pickle.load(f)
                scaler = scaler_data["scaler"]
            print("Scaler loaded.", flush=True)
    except Exception as e:
        print(f"Resource Load Error: {e}", flush=True)

load_resources()

# History buffer
history = deque(maxlen=24)
current_machine_state = {}

async def broadcast_sensor_data():
    global anomaly_processed
    print("LOG: Sensor Broadcast loop entering while True...")
    
    SIMULATOR_URL = "http://localhost:9000/api/state"
    
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # 1. Try to fetch from Machine Simulator Demo (Port 9000)
                reading = None
                try:
                    resp = await client.get(SIMULATOR_URL, timeout=2.0)
                    if resp.status_code == 200:
                        sim_data = resp.json()
                        reading = {
                            "machine_id": "Screw-Compressor-01",
                            "timestamp": sim_data.get("timestamp", datetime.now().timestamp()),
                            "volt": sim_data.get("volt", 0.0),
                            "rotate": sim_data.get("rotate", 0.0),
                            "pressure": sim_data.get("pressure", 0.0),
                            "vibration": sim_data.get("vibration", 0.0),
                            "is_anomaly": sim_data.get("is_anomaly", False)
                        }
                        print(f"[LIVE] Simulator -> V={reading['volt']:.1f} RPM={reading['rotate']:.0f} P={reading['pressure']:.1f} Vib={reading['vibration']:.1f}", flush=True)
                except Exception as e:
                    print(f"[WARN] Simulator not reachable: {e}", flush=True)

                # Fallback to internal simulator if demo is not running
                if not reading:
                    reading = simulator.generate_reading()
                
                history.append(reading)
                
                # Predict RUL
                if rul_model and scaler and len(history) >= 24:
                    try:
                        df = pd.DataFrame(list(history))
                        
                        # Calculate Rolling Features (Mean/Std) for the window
                        # Column order must match scaler: volt, volt_mean, volt_std, rotate, ...
                        cols_to_use = ["volt", "rotate", "pressure", "vibration"]
                        for col in cols_to_use:
                            df[f"{col}_mean"] = df[col].mean()
                            # Add epsilon to avoid std=0 when window is constant
                            std_val = df[col].std()
                            df[f"{col}_std"]  = max(float(std_val), 1e-6)
                        
                        # Exact column order matching the scaler
                        current_features = [
                            "volt", "volt_mean", "volt_std",
                            "rotate", "rotate_mean", "rotate_std",
                            "pressure", "pressure_mean", "pressure_std",
                            "vibration", "vibration_mean", "vibration_std"
                        ]
                        
                        # Ensure columns are in the exact order
                        X_input = df[current_features].values 
                        X_scaled = scaler.transform(X_input)
                        
                        # Predict (raw output is in dataset "cycles")
                        rul_raw = float(rul_model.forward(X_scaled))
                        rul_clipped = max(0.0, rul_raw)
                        
                        # Smoothing
                        global current_smooth_rul
                        if 'current_smooth_rul' not in globals():
                            current_smooth_rul = rul_clipped
                        
                        alpha = 0.3
                        current_smooth_rul = (alpha * rul_clipped) + ((1 - alpha) * current_smooth_rul)
                        
                        # ─── MAP TO COMPRESSOR LIFESPAN ───
                        # Model raw output range: ~0 (critical) to ~1300 (healthy)
                        # Calibrated from actual model output on normal readings (~1286)
                        
                        MAX_LIFE_YEARS = 18.0   # Brand new compressor max
                        MODEL_MAX      = 1300.0  # Observed healthy output ceiling
                        
                        # ML health factor (0 to 1)
                        ml_health = min(1.0, max(0.0, current_smooth_rul / MODEL_MAX))
                        
                        # Physics degradation factor based on how far from ideal
                        v   = reading.get("volt",      170)
                        r   = reading.get("rotate",    450)
                        p   = reading.get("pressure",  100)
                        vib = reading.get("vibration",  40)
                        
                        # Each parameter deviation reduces life
                        volt_penalty  = min(1.0, abs(v   - 170) / 130.0)   # 0 at 170V,   1 at 300V
                        rpm_penalty   = min(1.0, abs(r   - 450) / 1500.0)  # 0 at 450RPM, 1 at 1950+
                        press_penalty = min(1.0, abs(p   - 100) / 100.0)   # 0 at 100psi, 1 at 200+
                        vib_penalty   = min(1.0, max(0, vib - 40) / 60.0)  # 0 at 40mm/s, 1 at 100+
                        
                        # Combined physics factor (weighted)
                        physics_health = 1.0 - (
                            volt_penalty  * 0.20 +
                            rpm_penalty   * 0.20 +
                            press_penalty * 0.25 +
                            vib_penalty   * 0.35
                        )
                        physics_health = max(0.01, physics_health)
                        
                        # Final combined health
                        combined_health = ml_health * physics_health
                        rul_years_float = MAX_LIFE_YEARS * combined_health
                        
                        # Convert to hours → years / days / hours
                        rul_hours = rul_years_float * 8760.0
                        rul_hours = max(0.0, min(MAX_LIFE_YEARS * 8760.0, rul_hours))
                        
                        rul_years = int(rul_hours // 8760)
                        remaining = rul_hours % 8760
                        rul_days  = int(remaining // 24)
                        rul_hrs   = int(remaining % 24)
                        
                        # Health percentage
                        health_pct = round(combined_health * 100, 1)
                        
                        reading["rul"] = round(current_smooth_rul, 1)
                        reading["rul_hours"] = round(rul_hours, 0)
                        reading["rul_years"] = rul_years
                        reading["rul_days"] = rul_days
                        reading["rul_hrs"] = rul_hrs
                        reading["rul_display"] = f"{rul_years}y {rul_days}d {rul_hrs}h"
                        reading["health_pct"] = health_pct
                        
                    except Exception as e:
                        print(f"RUL ERR: {e}", flush=True)
                        reading["rul"] = 0.0
                        reading["rul_hours"] = 0
                        reading["rul_years"] = 0
                        reading["rul_days"] = 0
                        reading["rul_hrs"] = 0
                        reading["rul_display"] = "0y 0d 0h"
                        reading["health_pct"] = 0.0
                else:
                    reading["rul"] = 0.0
                    reading["rul_hours"] = 0
                    reading["rul_years"] = 0
                    reading["rul_days"]  = 0
                    reading["rul_hrs"]   = 0
                    reading["rul_display"]  = "Calculating..."
                    reading["health_pct"]   = None   # don't show bar until model is ready
                
                current_machine_state.update(reading)

                # ─── PREDICTIVE ENGINE ─────────────────────────────────
                # Run trend analysis, health alerts, maintenance scheduling
                # This is the TRUE predictive layer — warns BEFORE failure
                predictions = predictor.tick(reading)
                reading.update(predictions)

                # ─── ML ANOMALY DETECTION (Isolation Forest) ───────────
                # Real ML model that learns normal patterns and detects
                # subtle multi-variate anomalies BEFORE thresholds breach
                ml_result = anomaly_detector.score(reading)
                reading.update(ml_result)

                # Override is_anomaly with ML detection if model is trained
                if ml_result["model_trained"] and ml_result["ml_anomaly"] and not reading["is_anomaly"]:
                    reading["is_anomaly"] = True
                    reading["anomaly_source"] = "ml_model"
                    print(f"[ML] Anomaly detected by Isolation Forest (score={ml_result['anomaly_score']:.2f})", flush=True)
                elif reading["is_anomaly"]:
                    reading["anomaly_source"] = "threshold"

                # Proactive SNS alert on health degradation (before anomaly)
                if predictions.get("health_alert") and predictions["health_alert"]["level"] in ("warning", "critical"):
                    alert_level = predictions["health_alert"]["level"]
                    if not hasattr(predictor, '_last_sns_alert_time'):
                        predictor._last_sns_alert_time = 0
                    # Only send once per 5 minutes to avoid spam
                    if time.time() - predictor._last_sns_alert_time > 300:
                        predictor._last_sns_alert_time = time.time()
                        try:
                            sns.send_alert(
                                machine_id=reading["machine_id"],
                                fault_type=f"Predictive: Health {alert_level.upper()}",
                                severity="P2" if alert_level == "warning" else "P1",
                                recommended_action=predictions["health_alert"]["message"],
                                explanation=f"Health at {predictions['health_alert']['health_pct']}%. Degradation rate: {predictions['degradation_rate']:.2f}%/hr. Maintenance due: {predictions.get('maintenance_due', 'N/A')}",
                                volt=reading.get("volt", 0.0),
                                rotate=reading.get("rotate", 0.0),
                                pressure=reading.get("pressure", 0.0),
                                vibration=reading.get("vibration", 0.0),
                                auto_fixed=False,
                                rul=reading.get("rul", 0.0),
                            )
                            print(f"[PREDICTIVE] Proactive {alert_level} alert sent via SNS", flush=True)
                        except Exception as e:
                            print(f"[PREDICTIVE] SNS error: {e}", flush=True)

                # Persist latest state to DynamoDB
                dynamo.upsert_machine_state(
                    machine_id=reading["machine_id"],
                    volt=reading.get("volt", 0.0),
                    rotate=reading.get("rotate", 0.0),
                    pressure=reading.get("pressure", 0.0),
                    vibration=reading.get("vibration", 0.0),
                    is_anomaly=reading.get("is_anomaly", False),
                    rul=reading.get("rul", 0.0),
                    health_pct=reading.get("health_pct", 100.0),
                    temperature=reading.get("temperature", 0.0),
                )

                # Write time-series record to DynamoDB timeseries table
                dynamo.write_sensor_reading(
                    machine_id=reading["machine_id"],
                    volt=reading.get("volt", 0.0),
                    rotate=reading.get("rotate", 0.0),
                    pressure=reading.get("pressure", 0.0),
                    vibration=reading.get("vibration", 0.0),
                    is_anomaly=reading.get("is_anomaly", False),
                    rul=reading.get("rul", 0.0),
                    health_pct=reading.get("health_pct", 100.0),
                    temperature=reading.get("temperature", 0.0),
                )

                # Background Save to DB
                asyncio.create_task(save_to_db(reading))
                
                # Anomaly Agent - triggers work order generation
                if reading["is_anomaly"] and not anomaly_processed:
                    anomaly_processed = True
                    print("[ANOMALY] Detected! Invoking AI agent for work order...", flush=True)
                    asyncio.create_task(handle_anomaly(reading))
                elif not reading["is_anomaly"] and anomaly_processed:
                    # Auto-reset when anomaly clears so next anomaly triggers again
                    anomaly_processed = False
                
                # WS Broadcast
                if active_connections:
                    disconnected = []
                    for connection in active_connections:
                        try:
                            await connection.send_json(reading)
                        except:
                            disconnected.append(connection)
                    for conn in disconnected:
                        if conn in active_connections:
                            active_connections.remove(conn)
                            
            except Exception as e:
                print(f"CRITICAL LOOP ERROR: {e}")
                
            await asyncio.sleep(1.0)

async def save_to_db(reading):
    db = SessionLocal()
    try:
        new_log = SensorLog(
            machine_id=reading["machine_id"],
            vibration=int(reading["vibration"]),
            temperature=int(reading["volt"]),
            pressure=int(reading["pressure"]),
            current=int(reading["rotate"]),
            is_anomaly=str(reading["is_anomaly"])
        )
        db.add(new_log)
        db.commit()
    except:
        pass
    finally:
        db.close()

async def handle_anomaly(reading):
    print("[ANOMALY] Invoking AI agent workflow...", flush=True)
    try:
        result = await asyncio.to_thread(
            process_anomaly,
            machine_id=reading["machine_id"],
            vib=reading["vibration"],
            volt=reading.get("volt", 0.0),
            press=reading["pressure"],
            rotate=reading.get("rotate", 0.0),
            rul=reading.get("rul", 0.0)
        )
        
        # Build work order with auto-fix status and manual workflow
        auto_fixed = result.get("auto_fix_applied", False)
        manual_wf = result.get("manual_workflow", "")
        
        # Prefix the action with status
        action = result.get("recommended_action", "Inspect machine.")
        if auto_fixed:
            action = "[AUTO-FIXED] " + action
        elif manual_wf:
            action = "[REQUIRES HUMAN] " + action
        
        # Combine explanation with manual workflow if present
        explanation = result.get("explanation", "")
        if manual_wf:
            explanation = explanation + "\n\n--- MAINTENANCE WORKFLOW ---\n" + manual_wf
        
        db = SessionLocal()
        new_wo = WorkOrder(
            machine_id=result["machine_id"],
            fault_type=result.get("fault_type", "Unknown"),
            severity=result.get("severity", "P2"),
            recommended_action=action,
            explanation=explanation
        )
        db.add(new_wo)
        db.commit()
        # Capture values before closing session (SQLAlchemy detaches after close)
        wo_id         = new_wo.id
        wo_machine_id = new_wo.machine_id
        wo_fault_type = new_wo.fault_type
        wo_severity   = new_wo.severity
        wo_action     = new_wo.recommended_action
        wo_explanation= new_wo.explanation
        wo_created_at = str(new_wo.created_at)
        db.close()

        # Persist alert to DynamoDB
        dynamo.save_alert(
            machine_id=result["machine_id"],
            fault_type=result.get("fault_type", "Unknown"),
            severity=result.get("severity", "P2"),
            recommended_action=action,
            explanation=result.get("explanation", ""),
            volt=reading.get("volt", 0.0),
            rotate=reading.get("rotate", 0.0),
            pressure=reading.get("pressure", 0.0),
            vibration=reading.get("vibration", 0.0),
            auto_fixed=auto_fixed,
            rul=reading.get("rul", 0.0),
        )

        # Upload work order reports to S3 (JSON + PDF)
        try:
            wo_dict = {
                "id":                 str(wo_id),
                "machine_id":         wo_machine_id,
                "fault_type":         wo_fault_type,
                "severity":           wo_severity,
                "recommended_action": wo_action,
                "explanation":        wo_explanation,
                "created_at":         wo_created_at,
            }
            json_key = s3.upload_json_report(wo_dict)
            pdf_key  = s3.upload_pdf_report(wo_dict)
            if json_key:
                print(f"[S3] JSON report saved: {json_key}", flush=True)
            if pdf_key:
                print(f"[S3] PDF report saved: {pdf_key}", flush=True)
        except Exception as e:
            print(f"[S3] Upload error: {e}", flush=True)

        if auto_fixed:
            print("[ANOMALY] Agent AUTO-FIXED the problem. Work order saved.", flush=True)
        else:
            print("[ANOMALY] Agent generated MANUAL WORKFLOW. Work order saved.", flush=True)
        
        # Send email notification
        try:
            await asyncio.to_thread(
                send_anomaly_email,
                machine_id=result["machine_id"],
                fault_type=result.get("fault_type", "Unknown"),
                severity=result.get("severity", "P2"),
                explanation=result.get("explanation", ""),
                recommended_action=action,
                volt=reading.get("volt", 0.0),
                rotate=reading.get("rotate", 0.0),
                pressure=reading.get("pressure", 0.0),
                vibration=reading.get("vibration", 0.0),
                auto_fixed=auto_fixed,
            )
        except Exception as e:
            print(f"[EMAIL] Error: {e}", flush=True)

        # Send SNS alert (SMS + email to all subscribers)
        try:
            await asyncio.to_thread(
                sns.send_alert,
                machine_id=result["machine_id"],
                fault_type=result.get("fault_type", "Unknown"),
                severity=result.get("severity", "P2"),
                recommended_action=action,
                explanation=explanation,
                volt=reading.get("volt", 0.0),
                rotate=reading.get("rotate", 0.0),
                pressure=reading.get("pressure", 0.0),
                vibration=reading.get("vibration", 0.0),
                auto_fixed=auto_fixed,
                rul=reading.get("rul", 0.0),
            )
            print("[SNS] Alert published.", flush=True)
        except Exception as e:
            print(f"[SNS] Error: {e}", flush=True)
    except Exception as e:
        print(f"Agent error: {e}")

@app.on_event("startup")
async def startup_event():
    print("Startup Event Triggered")
    asyncio.create_task(broadcast_sensor_data())

@app.get("/")
def read_root():
    return {"message": "MachineWhisperer API Running"}

@app.get("/api/work-orders")
def get_work_orders(db: Session = Depends(get_db)):
    return db.query(WorkOrder).order_by(WorkOrder.created_at.desc()).all()

@app.post("/api/trigger-anomaly")
async def trigger_anomaly():
    global anomaly_processed
    anomaly_processed = False
    
    # Try to trigger anomaly on the machine simulator (port 9000)
    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:9000/api/params", json={
                "volt": 280.0,
                "rotate": 80.0,
                "pressure": 200.0,
                "vibration": 100.0
            }, timeout=2.0)
        print("[TRIGGER] Anomaly injected into Machine Simulator", flush=True)
    except Exception:
        # Fallback: trigger internal simulator
        simulator.trigger_anomaly()
        print("[TRIGGER] Anomaly injected into internal simulator", flush=True)
    
    return {"message": "Anomaly triggered!"}

@app.post("/api/reset-anomaly")
async def reset_anomaly(db: Session = Depends(get_db)):
    global anomaly_processed
    simulator.is_anomaly = False
    anomaly_processed = False
    db.query(WorkOrder).delete()
    db.commit()
    
    # Reset machine simulator to normal values
    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:9000/api/params", json={
                "volt": 170.0,
                "rotate": 450.0,
                "pressure": 100.0,
                "vibration": 40.0
            }, timeout=2.0)
        print("[RESET] Machine Simulator reset to normal", flush=True)
    except Exception:
        pass
    
    return {"message": "System reset."}

class EmailSubscribeRequest(BaseModel):
    email: str

class SMSSubscribeRequest(BaseModel):
    phone: str

@app.post("/api/sns/subscribe/email")
def sns_subscribe_email(req: EmailSubscribeRequest):
    sns.subscribe_email(req.email)
    return {"message": "Subscription request sent. Check your email to confirm.", "email": req.email}

@app.post("/api/sns/subscribe/sms")
def sns_subscribe_sms(req: SMSSubscribeRequest):
    sns.subscribe_sms(req.phone)
    return {"message": "SMS subscription added.", "phone": req.phone}

@app.get("/api/sns/subscriptions")
def sns_get_subscriptions():
    subs = sns.get_subscriptions()
    return {"subscriptions": subs, "count": len(subs)}


class ChatRequest(BaseModel):
    question: str

@app.post("/api/chat")
def chat_with_agent(req: ChatRequest):
    try:
        if not current_machine_state:
            return {"response": "No data yet."}
        answer = process_chat_query(
            question=req.question,
            machine_id=current_machine_state.get("machine_id", "Unknown"),
            vib=current_machine_state.get("vibration", 0.0),
            volt=current_machine_state.get("volt", 0.0),
            press=current_machine_state.get("pressure", 0.0),
            rotate=current_machine_state.get("rotate", 0.0),
            rul=current_machine_state.get("rul", 0.0)
        )
        return {"response": answer}
    except Exception as e:
        return {"response": f"Error: {str(e)}"}

@app.get("/api/s3/reports/{machine_id}")
def s3_list_reports(machine_id: str, limit: int = 20):
    reports = s3.list_reports(machine_id, limit=limit)
    return {"machine_id": machine_id, "reports": reports, "count": len(reports)}


@app.get("/api/s3/download/{machine_id}/{filename}")
def s3_download(machine_id: str, filename: str):
    # Reconstruct the key — walk back through dated prefixes via list
    reports = s3.list_reports(machine_id, limit=100)
    s3_key  = next((r["key"] for r in reports if r["key"].endswith(f"/{filename}")), None)
    if not s3_key:
        return {"error": f"File '{filename}' not found for machine '{machine_id}'"}
    url = s3.generate_presigned_url(s3_key)
    return {"url": url, "expires_in": "1 hour"}


@app.get("/api/s3/stats")
def s3_stats():
    return s3.get_report_stats()


@app.get("/api/s3/latest/{machine_id}")
def s3_latest(machine_id: str):
    reports = s3.list_reports(machine_id, limit=1)
    if not reports:
        return {"error": f"No reports found for machine '{machine_id}'"}
    latest  = reports[0]
    base    = latest["key"].rsplit(".", 1)[0]   # strip extension
    json_url = s3.generate_presigned_url(base + ".json")
    pdf_url  = s3.generate_presigned_url(base + ".pdf")
    return {"json_url": json_url, "pdf_url": pdf_url, "report": latest}


@app.get("/api/timeseries/recent/{machine_id}")
def timeseries_recent(machine_id: str, minutes: int = 60):
    return dynamo.query_recent(machine_id, minutes=minutes)


@app.get("/api/timeseries/anomalies/{machine_id}")
def timeseries_anomalies(machine_id: str, hours: int = 24):
    return dynamo.query_anomalies(machine_id, hours=hours)


@app.get("/api/timeseries/stats/{machine_id}")
def timeseries_stats(machine_id: str, minutes: int = 60):
    return dynamo.get_sensor_stats(machine_id, minutes=minutes)


@app.get("/api/timestream/recent/{machine_id}")
def timestream_recent(machine_id: str, minutes: int = 60):
    return timestream.query_recent(machine_id, minutes=minutes)


@app.get("/api/timestream/anomalies/{machine_id}")
def timestream_anomalies(machine_id: str, hours: int = 24):
    return timestream.query_anomalies(machine_id, hours=hours)


@app.get("/api/dynamo/state/{machine_id}")
def dynamo_get_state(machine_id: str):
    state = dynamo.get_machine_state(machine_id)
    if state is None:
        return {"error": f"No state found for machine '{machine_id}'"}
    return state


@app.get("/api/dynamo/alerts/{machine_id}")
def dynamo_get_alerts(machine_id: str, limit: int = 20):
    return dynamo.get_alerts(machine_id, limit=limit)


@app.get("/api/dynamo/all-machines")
def dynamo_all_machines():
    return dynamo.get_all_machine_states()


@app.get("/api/predictions")
def get_predictions():
    """Full predictive analytics — trend analysis, health alerts, maintenance schedule."""
    return predictor.get_prediction_summary()


@app.get("/api/predictions/maintenance")
def get_maintenance_schedule():
    """When is the next maintenance due based on RUL and degradation trends."""
    summary = predictor.get_prediction_summary()
    return {
        "machine_id": current_machine_state.get("machine_id", "unknown"),
        "maintenance_due": summary["maintenance_due"],
        "days_to_maintenance": summary["days_to_maintenance"],
        "degradation_rate_per_hour": summary["degradation_rate_per_hour"],
        "current_health_pct": current_machine_state.get("health_pct"),
        "recommendation": (
            "No maintenance needed — machine is healthy."
            if summary["status"] == "normal"
            else f"Schedule maintenance by {summary['maintenance_due']}. "
                 f"Health declining at {summary['degradation_rate_per_hour']}%/hr."
            if summary["maintenance_due"]
            else "Monitoring — insufficient data for prediction."
        ),
    }


@app.get("/api/anomaly-detection/status")
def get_anomaly_detection_status():
    """ML anomaly detection model status and latest scores."""
    latest = current_machine_state
    return {
        "model": "Isolation Forest",
        "trained": anomaly_detector.is_trained,
        "training_samples": len(anomaly_detector._buffer),
        "contamination": anomaly_detector.contamination,
        "latest_score": latest.get("anomaly_score", 0.0),
        "ml_anomaly": latest.get("ml_anomaly", False),
        "feature_contributions": latest.get("feature_contributions", {}),
        "description": "Unsupervised ML model that learns normal operating patterns and detects multi-variate anomalies before threshold breach.",
    }


@app.get("/api/model/metrics")
def get_model_metrics():
    """ML model performance metrics and architecture info."""
    return {
        "models": {
            "rul_prediction": {
                "type": "Stacked Pure LSTM (NumPy)",
                "architecture": "2-layer LSTM → Dense(1)",
                "input_features": 12,
                "sequence_length": 24,
                "training_dataset": "Microsoft Azure PdM (Predictive Maintenance)",
                "output": "Remaining Useful Life (cycles)",
                "normalization": "MinMaxScaler",
            },
            "anomaly_detection": {
                "type": "Isolation Forest (scikit-learn)",
                "n_estimators": 100,
                "contamination": 0.05,
                "training": "Online (adapts to rolling 300-sample window)",
                "features": ["volt", "rotate", "pressure", "vibration"],
                "trained": anomaly_detector.is_trained,
                "samples_seen": len(anomaly_detector._buffer),
            },
            "fault_diagnosis": {
                "type": "LangGraph Multi-Agent Workflow",
                "llm": "Claude Haiku 4.5 (AWS Bedrock)",
                "nodes": ["analyze_sensor_data", "auto_fix_machine", "generate_manual_workflow"],
                "routing": "Conditional (can_auto_fix → auto_fix | manual_workflow)",
                "capabilities": ["Fault classification", "Severity assessment", "Auto-remediation", "Workflow generation"],
            },
            "predictive_engine": {
                "type": "Statistical Trend Analysis",
                "methods": ["Rolling window comparison", "Degradation rate extrapolation", "Health threshold monitoring"],
                "windows": {"short": "60 seconds", "long": "5 minutes"},
            },
        },
        "agent_framework": {
            "orchestrator": "LangGraph (StateGraph)",
            "llm_provider": "AWS Bedrock",
            "model_id": os.environ.get("BEDROCK_MODEL_ID", "unknown"),
            "pattern": "Autonomous Multi-Agent with Conditional Routing",
            "autonomy_level": "Full — auto-diagnoses, auto-fixes, auto-alerts",
        },
    }


@app.get("/api/agent/activity")
def get_activity_log():
    """Real-time agent decision log — shows what the AI is thinking."""
    return {"activity": get_agent_activity(), "count": len(get_agent_activity())}


@app.get("/api/agent/workflow-status")
def get_workflow_status():
    """Returns the current state of the AI agent system."""
    latest = list(history)[-1] if len(history) > 0 else None
    return {
        "agent_model": os.environ.get("BEDROCK_MODEL_ID", "unknown"),
        "agent_type": "LangGraph Multi-Node Workflow",
        "nodes": ["analyze_sensor_data", "auto_fix_machine", "generate_manual_workflow"],
        "routing": "conditional (can_auto_fix → auto_fix | manual_workflow)",
        "total_anomalies_processed": len([a for a in get_agent_activity() if a["step"].startswith("🎯")]),
        "auto_fixes_applied": len([a for a in get_agent_activity() if "Auto-Fix Applied" in a["step"]]),
        "services": {
            "bedrock": "Claude Haiku 4.5",
            "dynamo": dynamo._ready,
            "sns": sns.is_ready,
            "s3": s3.is_ready,
        },
    }


@app.get("/api/lambda/status")
def lambda_status():
    lambda_url = os.environ.get("LAMBDA_URL", "")
    return {
        "deployed":      bool(lambda_url),
        "lambda_url":    lambda_url if lambda_url else "not deployed",
        "function_name": "machinewhisperer-agent",
        "services": {
            "dynamo": dynamo._ready,
            "sns":    sns.is_ready,
            "s3":     s3.is_ready,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/agentcore/status")
def agentcore_status():
    agentcore_url = os.environ.get("AGENTCORE_URL", "")
    return {
        "deployed":  bool(agentcore_url),
        "endpoint":  agentcore_url if agentcore_url else "not deployed",
        "services": {
            "dynamo": dynamo._ready,
            "sns":    sns.is_ready,
            "s3":     s3.is_ready,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.websocket("/ws/sensors")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
