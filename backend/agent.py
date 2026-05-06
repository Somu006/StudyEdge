import os
import json
import httpx
import boto3
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END

# ─── AWS Bedrock Configuration (from environment variables) ───
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_SESSION_TOKEN = os.environ.get("AWS_SESSION_TOKEN", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# Machine Simulator URL
SIMULATOR_URL = "http://localhost:9000/api/params"

# Normal operating parameters for the compressor
NORMAL_PARAMS = {
    "volt": 170.0,
    "rotate": 450.0,
    "pressure": 100.0,
    "vibration": 40.0,
}


def _get_bedrock_client():
    """Create a Bedrock Runtime client using AWS credentials from env."""
    kwargs = {
        "service_name": "bedrock-runtime",
        "region_name": AWS_REGION,
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
    }
    # Add session token if present (required for temporary credentials from AWS Academy/Labs)
    if AWS_SESSION_TOKEN:
        kwargs["aws_session_token"] = AWS_SESSION_TOKEN
    return boto3.client(**kwargs)


def _invoke_bedrock(prompt: str, system: str = "") -> str:
    """Call AWS Bedrock and return text response."""
    client = _get_bedrock_client()
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    kwargs = {
        "modelId": BEDROCK_MODEL_ID,
        "messages": messages,
        "inferenceConfig": {"temperature": 0.3, "maxTokens": 2048},
    }
    if system:
        kwargs["system"] = [{"text": system}]
    response = client.converse(**kwargs)
    return response["output"]["message"]["content"][0]["text"]


def _parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def _send_params_to_simulator(params: dict) -> bool:
    """Send corrected parameters to the machine simulator. Returns True if successful."""
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.post(SIMULATOR_URL, json=params)
            return resp.status_code == 200
    except Exception as e:
        print(f"[AGENT] Failed to send params to simulator: {e}", flush=True)
        return False


# ─── Agent State ───
class AgentState(TypedDict):
    machine_id: str
    vibration: float
    volt: float
    pressure: float
    rotate: float
    rul: float
    fault_type: str
    severity: str
    can_auto_fix: bool
    auto_fix_applied: bool
    corrected_params: dict
    recommended_action: str
    explanation: str
    manual_workflow: str


# ═══════════════════════════════════════════════════════════════════
# NODE 1: Analyze sensor data → classify fault
# ═══════════════════════════════════════════════════════════════════
def analyze_sensor_data(state: AgentState):
    print(f"[AGENT] Step 1: Analyzing fault for {state['machine_id']}...", flush=True)

    prompt = f"""You are an industrial compressor diagnostic AI. Analyze these sensor readings:

Machine: {state['machine_id']}
- Voltage: {state['volt']} V (normal: ~170V)
- Rotation: {state['rotate']} RPM (normal: ~450 RPM)
- Pressure: {state['pressure']} psi (normal: ~100 psi)
- Vibration: {state['vibration']} mm/s (normal: ~40 mm/s)
- Predicted RUL: {state['rul']} hours

Classify the fault and determine:
1. fault_type: What is wrong (e.g., "Overvoltage", "Bearing Failure", "Pressure Leak", "Motor Overload")
2. severity: P1 (Critical - shutdown risk), P2 (Warning - degraded), P3 (Advisory - monitor)
3. can_auto_fix: true if the problem can be solved by adjusting voltage/rotation/pressure/vibration parameters back to safe values. false if it requires physical human intervention (like replacing a bearing, fixing a leak, replacing a part).

Return ONLY a JSON object with keys: "fault_type", "severity", "can_auto_fix" (boolean). No other text."""

    try:
        response = _invoke_bedrock(prompt)
        res = _parse_json_response(response)
        return {
            "fault_type": res.get("fault_type", "System Anomaly"),
            "severity": res.get("severity", "P2"),
            "can_auto_fix": res.get("can_auto_fix", False),
        }
    except Exception as e:
        print(f"[AGENT] Analysis Error: {e}", flush=True)
        # Default: try auto-fix for parameter-based issues
        can_fix = (state["volt"] > 250 or state["volt"] < 120 or
                   state["rotate"] > 1500 or state["rotate"] < 100 or
                   state["pressure"] > 180)
        return {"fault_type": "Parameter Anomaly", "severity": "P2", "can_auto_fix": can_fix}


# ═══════════════════════════════════════════════════════════════════
# NODE 2: Auto-Fix → Send corrected params to simulator
# ═══════════════════════════════════════════════════════════════════
def auto_fix_machine(state: AgentState):
    print(f"[AGENT] Step 2a: Attempting AUTO-FIX...", flush=True)

    prompt = f"""You are a compressor control system AI. The machine has a "{state['fault_type']}" fault.

Current readings:
- Voltage: {state['volt']} V
- Rotation: {state['rotate']} RPM
- Pressure: {state['pressure']} psi
- Vibration: {state['vibration']} mm/s

Normal safe operating values:
- Voltage: 170 V
- Rotation: 450 RPM
- Pressure: 100 psi
- Vibration: 40 mm/s

Determine the corrected parameter values to bring the machine back to safe operation.
You can adjust: volt, rotate, pressure, vibration.

Also provide a brief explanation of what you're doing.

Return ONLY a JSON object with keys:
- "volt": corrected voltage (number)
- "rotate": corrected rotation (number)
- "pressure": corrected pressure (number)
- "vibration": corrected vibration (number)
- "explanation": what the auto-fix is doing (string)

No other text."""

    try:
        response = _invoke_bedrock(prompt)
        res = _parse_json_response(response)

        corrected = {
            "volt": float(res.get("volt", NORMAL_PARAMS["volt"])),
            "rotate": float(res.get("rotate", NORMAL_PARAMS["rotate"])),
            "pressure": float(res.get("pressure", NORMAL_PARAMS["pressure"])),
            "vibration": float(res.get("vibration", NORMAL_PARAMS["vibration"])),
        }

        # Send to simulator
        success = _send_params_to_simulator(corrected)

        if success:
            print(f"[AGENT] AUTO-FIX APPLIED: {corrected}", flush=True)

        return {
            "auto_fix_applied": success,
            "corrected_params": corrected,
            "recommended_action": f"Auto-fix applied: Parameters adjusted to safe values.",
            "explanation": res.get("explanation", "Parameters were outside safe range and have been corrected automatically."),
            "manual_workflow": "",
        }
    except Exception as e:
        print(f"[AGENT] Auto-fix error: {e}. Falling back to safe defaults.", flush=True)
        # Fallback: just reset to normal
        success = _send_params_to_simulator(NORMAL_PARAMS)
        return {
            "auto_fix_applied": success,
            "corrected_params": NORMAL_PARAMS,
            "recommended_action": "Auto-fix applied: Reset to default safe parameters.",
            "explanation": f"Detected {state['fault_type']}. Parameters reset to factory defaults.",
            "manual_workflow": "",
        }


# ═══════════════════════════════════════════════════════════════════
# NODE 3: Generate Manual Workflow → For problems AI can't fix
# ═══════════════════════════════════════════════════════════════════
def generate_manual_workflow(state: AgentState):
    print(f"[AGENT] Step 2b: Generating MANUAL WORKFLOW (requires human)...", flush=True)

    prompt = f"""You are a senior maintenance engineer AI for an industrial screw air compressor.

The machine has a "{state['fault_type']}" fault (Severity: {state['severity']}) that CANNOT be fixed by adjusting parameters alone. It requires physical human intervention.

Current readings:
- Voltage: {state['volt']} V (normal: ~170V)
- Rotation: {state['rotate']} RPM (normal: ~450 RPM)
- Pressure: {state['pressure']} psi (normal: ~100 psi)
- Vibration: {state['vibration']} mm/s (normal: ~40 mm/s)
- RUL: {state['rul']} hours

Generate a complete step-by-step maintenance workflow that a technician can follow to resolve this issue.

Return ONLY a JSON object with these keys:
- "recommended_action": One-line summary of what needs to be done
- "explanation": Technical root cause (2-3 sentences)
- "manual_workflow": A detailed step-by-step workflow as a single string with numbered steps. Include: safety precautions, tools needed, step-by-step procedure, verification steps, and estimated time.

No other text."""

    try:
        response = _invoke_bedrock(prompt)
        res = _parse_json_response(response)

        # Also try to bring machine to a safe idle state
        safe_idle = {"volt": 150.0, "rotate": 200.0, "pressure": 50.0, "vibration": 40.0}
        _send_params_to_simulator(safe_idle)
        print("[AGENT] Machine set to SAFE IDLE for maintenance.", flush=True)

        return {
            "auto_fix_applied": False,
            "corrected_params": safe_idle,
            "recommended_action": res.get("recommended_action", "Schedule immediate maintenance."),
            "explanation": res.get("explanation", "Physical intervention required."),
            "manual_workflow": res.get("manual_workflow", "1. Shut down machine.\n2. Inspect components.\n3. Replace faulty parts.\n4. Test and restart."),
        }
    except Exception as e:
        print(f"[AGENT] Manual workflow error: {e}", flush=True)
        return {
            "auto_fix_applied": False,
            "corrected_params": {},
            "recommended_action": "Shut down machine and call maintenance team.",
            "explanation": f"Critical fault: {state['fault_type']}. Requires physical inspection.",
            "manual_workflow": "1. SAFETY: Lock out/tag out the machine.\n2. Shut down power supply.\n3. Inspect the compressor for the reported fault.\n4. Contact maintenance supervisor.\n5. Do not restart until cleared by qualified technician.",
        }


# ═══════════════════════════════════════════════════════════════════
# ROUTING: Decide auto-fix vs manual workflow
# ═══════════════════════════════════════════════════════════════════
def route_after_analysis(state: AgentState) -> str:
    """Route to auto-fix or manual workflow based on analysis."""
    if state.get("can_auto_fix", False):
        return "auto_fix"
    else:
        return "manual_workflow"


# ═══════════════════════════════════════════════════════════════════
# BUILD THE LANGGRAPH WORKFLOW
# ═══════════════════════════════════════════════════════════════════
#
#   START → analyze → [can_auto_fix?]
#                         ├── Yes → auto_fix → END
#                         └── No  → manual_workflow → END
#
workflow = StateGraph(AgentState)
workflow.add_node("analyze", analyze_sensor_data)
workflow.add_node("auto_fix", auto_fix_machine)
workflow.add_node("manual_workflow", generate_manual_workflow)

workflow.add_edge(START, "analyze")
workflow.add_conditional_edges("analyze", route_after_analysis, {
    "auto_fix": "auto_fix",
    "manual_workflow": "manual_workflow",
})
workflow.add_edge("auto_fix", END)
workflow.add_edge("manual_workflow", END)

agent_app = workflow.compile()


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════
def process_anomaly(machine_id: str, vib: float, volt: float, press: float, rotate: float, rul: float = 0.0):
    """
    Called by backend when anomaly is detected.
    The agent will:
      1. Analyze the fault
      2. If auto-fixable: adjust machine parameters automatically
      3. If not: generate a manual workflow for the technician
    Returns the full state dict with work order info.
    """
    initial_state = {
        "machine_id": machine_id,
        "vibration": vib,
        "volt": volt,
        "pressure": press,
        "rotate": rotate,
        "rul": rul,
        "fault_type": "",
        "severity": "",
        "can_auto_fix": False,
        "auto_fix_applied": False,
        "corrected_params": {},
        "recommended_action": "",
        "explanation": "",
        "manual_workflow": "",
    }
    result = agent_app.invoke(initial_state)
    print(f"[AGENT] Done. Auto-fixed: {result.get('auto_fix_applied')}. Fault: {result.get('fault_type')}", flush=True)
    return result


def process_chat_query(question: str, machine_id: str, vib: float, volt: float, press: float, rotate: float, rul: float):
    """Called by /api/chat. Returns AI response string only. No credentials exposed."""
    system_prompt = f"""You are MachineWhisperer AI — a specialized predictive maintenance assistant for an Industrial Oil-Injected Rotary Screw Air Compressor (Machine ID: {machine_id}).

MACHINE SPECIFICATIONS:
- Type: Single-stage oil-injected rotary screw compressor
- Motor: 37 kW, 3-phase AC induction motor
- Rated Speed: 1460 RPM (direct drive)
- Discharge Pressure: 7-13 bar (100-190 psi)
- Expected Lifespan: 10-20 years (80,000-160,000 operating hours)
- Cooling: Air-cooled aftercooler with fan
- Lubrication: Oil-injected (sealing, cooling, lubricating)

KEY COMPONENTS:
1. Air Inlet Filter — removes dust/particles
2. Suction Valve — load/unload control
3. Electric Motor — drives the twin screw rotors
4. Screw Compression Element — male rotor (4 lobes) + female rotor (6 grooves)
5. Oil Separator Vessel — separates oil from compressed air
6. Aftercooler — cools compressed air
7. Minimum Pressure Valve — maintains oil circulation pressure

CURRENT LIVE SENSOR READINGS:
- Voltage: {volt:.1f} V (Normal: ~170V)
- Rotation: {rotate:.0f} RPM (Normal: ~450 RPM)
- Pressure: {press:.1f} psi (Normal: ~100 psi)
- Vibration: {vib:.1f} mm/s (Normal: ~40 mm/s)
- Predicted Remaining Useful Life: {rul:.1f} cycles

NORMAL OPERATING RANGES:
- Voltage: 150-200V (danger below 120V or above 250V)
- Rotation: 300-600 RPM (danger below 100 or above 2000)
- Pressure: 80-120 psi (danger above 180 psi)
- Vibration: 20-50 mm/s (warning above 60, danger above 80)
- Temperature: 35-85°C (danger above 110°C)

COMMON FAILURE MODES:
- Bearing wear → increased vibration, noise
- Air/oil leak → pressure drop, oil consumption
- Motor overload → voltage spike, overheating
- Clogged filter → reduced flow, pressure drop
- Separator failure → oil in compressed air
- Belt/coupling wear → vibration, misalignment

YOUR ROLE:
- Analyze current sensor readings and identify potential issues
- Explain root causes in simple technical language
- Recommend specific maintenance actions with priority
- Predict when maintenance should be scheduled
- Answer questions about the compressor's operation and health
- If readings are normal, confirm the machine is healthy

Be concise, professional, and specific to THIS compressor. Use bullet points for recommendations. Always reference the actual sensor values in your analysis."""

    try:
        response = _invoke_bedrock(question, system=system_prompt)
        return response
    except Exception as e:
        return f"Error communicating with AWS Bedrock: {str(e)}"
