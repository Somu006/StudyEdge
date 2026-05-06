"""
test_lambda.py — Integration tests for the deployed Lambda Function URL

Run from the backend/ directory:
    python test_lambda.py

Requires LAMBDA_URL to be set in backend/.env after running lambda_deploy.py.
"""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

LAMBDA_URL = os.environ.get("LAMBDA_URL", "").rstrip("/")
MACHINE_ID = "Screw-Compressor-01"
PASS = "✅"
FAIL = "❌"

results = []


def post(payload: dict) -> tuple[int, dict]:
    """POST to Lambda URL, return (status_code, parsed_body)."""
    resp = httpx.post(LAMBDA_URL, json=payload, timeout=120.0)
    # Lambda Function URL returns body as a JSON string inside the HTTP body
    raw = resp.json()
    # If the Lambda returned the HTTP envelope (statusCode + body), unwrap it
    if isinstance(raw, dict) and "statusCode" in raw and "body" in raw:
        status = raw["statusCode"]
        body   = json.loads(raw["body"]) if isinstance(raw["body"], str) else raw["body"]
    else:
        # Direct response (shouldn't happen with Function URL but handle gracefully)
        status = resp.status_code
        body   = raw
    return status, body


def run_test(name: str, fn):
    try:
        ok, detail = fn()
        symbol = PASS if ok else FAIL
        print(f"  {symbol}  {name}{(' — ' + detail) if detail else ''}")
        results.append(ok)
    except Exception as e:
        print(f"  {FAIL}  {name} — Exception: {e}")
        results.append(False)


# ─── Test 1: health_check ────────────────────────────────────────
def test_health_check():
    status, body = post({"action": "health_check"})
    ok = (
        status == 200
        and body.get("status") == "ok"
        and body.get("dynamo") is True
    )
    detail = (
        f"dynamo={body.get('dynamo')}, sns={body.get('sns')}, s3={body.get('s3')}"
        if ok else f"status={status}, body={str(body)[:120]}"
    )
    return ok, detail


# ─── Test 2: get_machine_state ───────────────────────────────────
def test_get_machine_state():
    status, body = post({"action": "get_machine_state", "machine_id": MACHINE_ID})
    ok = status == 200 and "machine_id" in body and "error" not in body
    detail = (
        f"volt={body.get('volt')}, health={body.get('health_pct')}%"
        if ok else f"status={status}, body={str(body)[:120]}"
    )
    return ok, detail


# ─── Test 3: get_stats ───────────────────────────────────────────
def test_get_stats():
    status, body = post({"action": "get_stats", "machine_id": MACHINE_ID, "minutes": 60})
    ok = status == 200 and "total_readings" in body
    detail = (
        f"readings={body.get('total_readings')}, avg_volt={body.get('avg_volt')}"
        if ok else f"status={status}, body={str(body)[:120]}"
    )
    return ok, detail


# ─── Test 4: get_alerts ──────────────────────────────────────────
def test_get_alerts():
    status, body = post({"action": "get_alerts", "machine_id": MACHINE_ID, "limit": 5})
    ok = status == 200 and "alerts" in body
    detail = (
        f"{body.get('count', 0)} alert(s)"
        if ok else f"status={status}, body={str(body)[:120]}"
    )
    return ok, detail


# ─── Test 5: chat_query ──────────────────────────────────────────
def test_chat_query():
    status, body = post({
        "action":     "chat_query",
        "question":   "What is the machine health?",
        "machine_id": MACHINE_ID,
        "volt":       170.0,
        "rotate":     450.0,
        "pressure":   100.0,
        "vibration":  40.0,
        "rul":        12.0,
    })
    response_text = body.get("response", "")
    ok = status == 200 and isinstance(response_text, str) and len(response_text) > 10
    detail = (
        (response_text[:80] + "...") if ok
        else f"status={status}, body={str(body)[:120]}"
    )
    return ok, detail


# ─── Test 6: analyze_anomaly ─────────────────────────────────────
def test_analyze_anomaly():
    status, body = post({
        "action":     "analyze_anomaly",
        "machine_id": MACHINE_ID,
        "volt":       280.0,
        "rotate":     80.0,
        "pressure":   200.0,
        "vibration":  95.0,
        "rul":        2.0,
    })
    ok = status == 200 and "fault_type" in body and "severity" in body
    detail = (
        f"fault={body.get('fault_type')}, severity={body.get('severity')}, "
        f"alert_saved={body.get('alert_saved')}, sms_sent={body.get('sms_sent')}"
        if ok else f"status={status}, body={str(body)[:120]}"
    )
    return ok, detail


# ─── Run all tests ───────────────────────────────────────────────
print()
print("=" * 60)
print("  MachineWhisperer — Lambda Function URL Tests")
print("=" * 60)

if not LAMBDA_URL:
    print(f"\n  {FAIL}  LAMBDA_URL not set in backend/.env")
    print("       Run:  python lambda_deploy.py")
    print("       Then add LAMBDA_URL=<url> to backend/.env\n")
    sys.exit(1)

print(f"\n  Endpoint : {LAMBDA_URL}")
print(f"  Machine  : {MACHINE_ID}\n")
print("  Note: analyze_anomaly calls Bedrock — may take 15-30 s\n")

run_test("health_check                      ", test_health_check)
run_test("get_machine_state                 ", test_get_machine_state)
run_test("get_stats (last 60 min)           ", test_get_stats)
run_test("get_alerts (limit 5)              ", test_get_alerts)
run_test("chat_query                        ", test_chat_query)
run_test("analyze_anomaly (high readings)   ", test_analyze_anomaly)

passed = sum(results)
total  = len(results)
print()
print(f"  {passed}/{total} tests passed")
print("=" * 60)

if passed == total:
    print()
    print("  All tests passed! Your Lambda agent is live 24/7.")
    print(f"  Endpoint: {LAMBDA_URL}")
    print()
    print("  Quick test:")
    print(f'  curl -X POST "{LAMBDA_URL}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f"    -d '{{\"action\":\"health_check\"}}'")
    print()
else:
    print()
    print("  Some tests failed. Troubleshooting:")
    print("  - Check CloudWatch Logs: AWS Console → Lambda → machinewhisperer-agent → Monitor")
    print("  - Verify LAMBDA_URL in .env ends with /")
    print("  - Ensure Lambda has internet access (VPC config) for Bedrock calls")
    print("  - get_machine_state may return 'Not found' if no live data yet — start the app first")
    print()
    sys.exit(1)
