import asyncio
import json
import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from machine_engine import MachineEngine

app = FastAPI(title="MachineSimulator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

machine = MachineEngine()
active_connections: list[WebSocket] = []
last_reading: dict = {}

class ParamUpdate(BaseModel):
    volt: Optional[float] = None
    rotate: Optional[float] = None
    pressure: Optional[float] = None
    vibration: Optional[float] = None

async def simulation_loop():
    global last_reading
    print("[MachineSimulator] Simulation loop started.", flush=True)
    while True:
        reading = machine.tick()
        last_reading = reading

        if active_connections:
            payload = json.dumps(reading)
            dead = []
            for ws in active_connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                active_connections.remove(ws)

        await asyncio.sleep(1.0)

@app.on_event("startup")
async def startup():
    asyncio.create_task(simulation_loop())
    print("[MachineSimulator] Server ready at http://localhost:9000", flush=True)
    print("[MachineSimulator] Backend (MachineWhisperer) will auto-connect to /api/state", flush=True)

@app.get("/api/state")
def get_state():
    return last_reading if last_reading else machine.get_state()

@app.post("/api/params")
def set_params(params: ParamUpdate):
    machine.set_params(
        voltage=params.volt,
        rotation=params.rotate,
        pressure=params.pressure,
        vibration=params.vibration
    )
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    if last_reading:
        await websocket.send_text(json.dumps(last_reading))
    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                machine.set_params(
                    voltage=msg.get("volt"),
                    rotation=msg.get("rotate"),
                    pressure=msg.get("pressure"),
                    vibration=msg.get("vibration"),
                )
            except Exception:
                pass
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    ui_path = os.path.join(BASE_DIR, "ui.html")
    with open(ui_path, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=9000, reload=False)
