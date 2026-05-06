"""
lambda_handler.py — AWS Lambda entry point for MachineWhisperer Agent

Invoked via Lambda Function URL (public HTTPS POST):
  {"action": "health_check" | "analyze_anomaly" | "chat_query" |
             "get_machine_state" | "get_alerts" | "get_stats" |
             "get_recent_readings", ...params}

Returns standard Lambda Function URL HTTP response format:
  {"statusCode": 200, "headers": {...}, "body": "<json string>"}
"""

import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load .env at module level (no-op in real Lambda, useful for local testing)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── lazy service imports ──────────────────────────────────────────
# Imported at module level so Lambda reuses the initialised singletons
# across warm invocations (connection pooling, table references, etc.)
from agent import process_anomaly, process_chat_query
from dynamo import dynamo
from sns_notifier import sns
from s3_reporter import s3

# ── supported actions (used in error messages) ────────────────────
SUPPORTED_ACTIONS = [
    "health_check",
    "analyze_anomaly",
    "chat_query",
    "get_machine_state",
    "get_alerts",
    "get_stats",
    "get_recent_readings",
]


def _response(status_code: int, body: dict) -> dict:
    """Wrap a result dict in the Lambda Function URL HTTP envelope."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def _parse_event(event: dict) -> dict:
    """
    Lambda Function URL wraps the POST body as a JSON string in event["body"].
    Direct Lambda invocations pass params at the top level.
    """
    if "body" in event and isinstance(event["body"], str):
        try:
            return json.loads(event["body"])
        except json.JSONDecodeError:
            return {}
    return event


def handler(event: dict, context: dict) -> dict:
    """AWS Lambda / AgentCore entry point. Never raises — always returns a dict."""
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        params = _parse_event(event)
        action = params.get("action", "unknown")

        print(f"[Lambda] action={action} ts={timestamp}", flush=True)

        # ── health_check ─────────────────────────────────────────
        if action == "health_check":
            return _response(200, {
                "status":    "ok",
                "app":       "MachineWhisperer",
                "version":   "1.0",
                "dynamo":    dynamo._ready,
                "sns":       sns.is_ready,
                "s3":        s3.is_ready,
                "timestamp": timestamp,
            })

        # ── analyze_anomaly ──────────────────────────────────────
        elif action == "analyze_anomaly":
            machine_id = params.get("machine_id", "unknown")
            result = process_anomaly(
                machine_id = machine_id,
                vib        = float(params.get("vibration", 0.0)),
                volt       = float(params.get("volt",      0.0)),
                press      = float(params.get("pressure",  0.0)),
                rotate     = float(params.get("rotate",    0.0)),
                rul        = float(params.get("rul",       0.0)),
            )

            # Sanitise LangGraph state — keep only JSON-serialisable values
            clean = {k: v for k, v in result.items()
                     if isinstance(v, (str, int, float, bool, list, dict, type(None)))}

            # Persist alert to DynamoDB
            alert_saved = False
            try:
                aid = dynamo.save_alert(
                    machine_id        = clean.get("machine_id", machine_id),
                    fault_type        = clean.get("fault_type", "Unknown"),
                    severity          = clean.get("severity", "P2"),
                    recommended_action= clean.get("recommended_action", ""),
                    explanation       = clean.get("explanation", ""),
                    volt              = float(params.get("volt",      0.0)),
                    rotate            = float(params.get("rotate",    0.0)),
                    pressure          = float(params.get("pressure",  0.0)),
                    vibration         = float(params.get("vibration", 0.0)),
                    auto_fixed        = bool(clean.get("auto_fix_applied", False)),
                    rul               = float(params.get("rul", 0.0)),
                )
                alert_saved = aid is not None
            except Exception as e:
                print(f"[Lambda] dynamo.save_alert error: {e}", flush=True)

            # Publish SNS alert
            sms_sent = False
            try:
                sms_sent = sns.send_alert(
                    machine_id        = clean.get("machine_id", machine_id),
                    fault_type        = clean.get("fault_type", "Unknown"),
                    severity          = clean.get("severity", "P2"),
                    recommended_action= clean.get("recommended_action", ""),
                    explanation       = clean.get("explanation", ""),
                    volt              = float(params.get("volt",      0.0)),
                    rotate            = float(params.get("rotate",    0.0)),
                    pressure          = float(params.get("pressure",  0.0)),
                    vibration         = float(params.get("vibration", 0.0)),
                    auto_fixed        = bool(clean.get("auto_fix_applied", False)),
                    rul               = float(params.get("rul", 0.0)),
                )
            except Exception as e:
                print(f"[Lambda] sns.send_alert error: {e}", flush=True)

            clean["alert_saved"] = alert_saved
            clean["sms_sent"]    = sms_sent
            return _response(200, clean)

        # ── chat_query ───────────────────────────────────────────
        elif action == "chat_query":
            answer = process_chat_query(
                question   = params.get("question", ""),
                machine_id = params.get("machine_id", "unknown"),
                vib        = float(params.get("vibration", 0.0)),
                volt       = float(params.get("volt",      0.0)),
                press      = float(params.get("pressure",  0.0)),
                rotate     = float(params.get("rotate",    0.0)),
                rul        = float(params.get("rul",       0.0)),
            )
            return _response(200, {"response": answer})

        # ── get_machine_state ────────────────────────────────────
        elif action == "get_machine_state":
            machine_id = params.get("machine_id", "unknown")
            state = dynamo.get_machine_state(machine_id)
            if state is None:
                return _response(200, {"error": "Not found", "machine_id": machine_id})
            return _response(200, state)

        # ── get_alerts ───────────────────────────────────────────
        elif action == "get_alerts":
            machine_id = params.get("machine_id", "unknown")
            limit      = int(params.get("limit", 10))
            alerts     = dynamo.get_alerts(machine_id, limit=limit)
            return _response(200, {"alerts": alerts, "count": len(alerts)})

        # ── get_stats ────────────────────────────────────────────
        elif action == "get_stats":
            machine_id = params.get("machine_id", "unknown")
            minutes    = int(params.get("minutes", 60))
            stats      = dynamo.get_sensor_stats(machine_id, minutes=minutes)
            return _response(200, stats)

        # ── get_recent_readings ──────────────────────────────────
        elif action == "get_recent_readings":
            machine_id = params.get("machine_id", "unknown")
            minutes    = int(params.get("minutes", 30))
            readings   = dynamo.query_recent(machine_id, minutes=minutes)
            return _response(200, {"readings": readings, "count": len(readings)})

        # ── unknown ──────────────────────────────────────────────
        else:
            return _response(200, {
                "error":     "Unknown action",
                "action":    action,
                "supported": SUPPORTED_ACTIONS,
            })

    except Exception as e:
        print(f"[Lambda] UNHANDLED ERROR: {e}", flush=True)
        return _response(500, {"error": str(e)})
