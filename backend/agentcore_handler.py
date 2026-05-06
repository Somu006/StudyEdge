"""
agentcore_handler.py — AWS AgentCore / Lambda entry point for MachineWhisperer

Supported event["action"] values:
  analyze_anomaly   — run full LangGraph agent workflow
  chat_query        — answer a natural language question via Bedrock
  get_machine_state — fetch latest state from DynamoDB
  get_alerts        — fetch alert history from DynamoDB
  get_stats         — fetch time-series stats from DynamoDB
  health_check      — verify all services are ready
"""

import json
import os
from datetime import datetime, timezone

# ── lazy imports so cold-start errors are surfaced cleanly ────────
def _import_services():
    from agent import process_anomaly, process_chat_query
    from dynamo import dynamo
    from sns_notifier import sns
    from s3_reporter import s3
    return process_anomaly, process_chat_query, dynamo, sns, s3


def handler(event: dict, context: dict) -> dict:
    """
    AgentCore Runtime entry point.
    Always returns a dict — never raises.
    """
    action     = event.get("action", "unknown")
    machine_id = event.get("machine_id", "unknown")
    timestamp  = datetime.now(timezone.utc).isoformat()

    print(f"[AgentCore] action={action} machine={machine_id} ts={timestamp}", flush=True)

    try:
        process_anomaly, process_chat_query, dynamo, sns, s3 = _import_services()
    except Exception as e:
        return {"error": f"Service import failed: {e}", "action": action}

    # ── 1. analyze_anomaly ────────────────────────────────────────
    if action == "analyze_anomaly":
        try:
            result = process_anomaly(
                machine_id = event.get("machine_id", "unknown"),
                vib        = float(event.get("vibration", 0.0)),
                volt       = float(event.get("volt",      0.0)),
                press      = float(event.get("pressure",  0.0)),
                rotate     = float(event.get("rotate",    0.0)),
                rul        = float(event.get("rul",       0.0)),
            )
            # LangGraph state contains non-serialisable objects — sanitise
            return {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
        except Exception as e:
            return {"error": str(e), "action": action}

    # ── 2. chat_query ─────────────────────────────────────────────
    elif action == "chat_query":
        try:
            response = process_chat_query(
                question   = event.get("question", ""),
                machine_id = event.get("machine_id", "unknown"),
                vib        = float(event.get("vibration", 0.0)),
                volt       = float(event.get("volt",      0.0)),
                press      = float(event.get("pressure",  0.0)),
                rotate     = float(event.get("rotate",    0.0)),
                rul        = float(event.get("rul",       0.0)),
            )
            return {"response": response}
        except Exception as e:
            return {"error": str(e), "action": action}

    # ── 3. get_machine_state ──────────────────────────────────────
    elif action == "get_machine_state":
        try:
            state = dynamo.get_machine_state(event.get("machine_id", "unknown"))
            if state is None:
                return {"error": "Machine not found", "machine_id": machine_id}
            return state
        except Exception as e:
            return {"error": str(e), "action": action}

    # ── 4. get_alerts ─────────────────────────────────────────────
    elif action == "get_alerts":
        try:
            limit  = int(event.get("limit", 10))
            alerts = dynamo.get_alerts(event.get("machine_id", "unknown"), limit=limit)
            return {"alerts": alerts, "count": len(alerts)}
        except Exception as e:
            return {"error": str(e), "action": action}

    # ── 5. get_stats ──────────────────────────────────────────────
    elif action == "get_stats":
        try:
            minutes = int(event.get("minutes", 60))
            stats   = dynamo.get_sensor_stats(event.get("machine_id", "unknown"), minutes=minutes)
            return stats
        except Exception as e:
            return {"error": str(e), "action": action}

    # ── 6. health_check ───────────────────────────────────────────
    elif action == "health_check":
        return {
            "status":    "ok",
            "dynamo":    dynamo._ready,
            "sns":       sns.is_ready,
            "s3":        s3.is_ready,
            "timestamp": timestamp,
        }

    # ── unknown ───────────────────────────────────────────────────
    else:
        return {"error": "Unknown action", "action": action}
