"""
test_agentcore.py — Integration tests for the deployed AgentCore Lambda endpoint

Run from the backend/ directory:
    python test_agentcore.py

Requires AGENTCORE_URL to be set in backend/.env after deployment.
"""

import os
import sys
import json

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

AGENTCORE_URL = os.environ.get("AGENTCORE_URL", "").rstrip("/")
MACHINE_ID    = "Screw-Compressor-01"
PASS = "✅"
FAIL = "❌"

results = []


def post(payload: dict) -> dict:
    resp = httpx.post(AGENTCORE_URL, json=payload, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


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
    r  = post({"action": "health_check"})
    ok = r.get("status") == "ok" and r.get("dynamo") and r.get("sns") and r.get("s3")
    detail = (
        f"dynamo={r.get('dynamo')}, sns={r.get('sns')}, s3={r.get('s3')}"
        if ok else f"unexpected response: {r}"
    )
    return ok, detail


# ─── Test 2: get_machine_state ───────────────────────────────────
def test_get_machine_state():
    r  = post({"action": "get_machine_state", "machine_id": MACHINE_ID})
    ok = isinstance(r, dict) and "error" not in r
    detail = f"volt={r.get('volt')}, health={r.get('health_pct')}%" if ok else str(r)
    return ok, detail


# ─── Test 3: get_stats ───────────────────────────────────────────
def test_get_stats():
    r  = post({"action": "get_stats", "machine_id": MACHINE_ID, "minutes": 60})
    ok = isinstance(r, dict) and "total_readings" in r
    detail = (
        f"readings={r.get('total_readings')}, avg_volt={r.get('avg_volt')}"
        if ok else str(r)
    )
    return ok, detail


# ─── Test 4: get_alerts ──────────────────────────────────────────
def test_get_alerts():
    r     = post({"action": "get_alerts", "machine_id": MACHINE_ID, "limit": 5})
    ok    = isinstance(r, dict) and "alerts" in r
    detail = f"{r.get('count', 0)} alert(s) returned" if ok else str(r)
    return ok, detail


# ─── Test 5: chat_query ──────────────────────────────────────────
def test_chat_query():
    r  = post({
        "action":     "chat_query",
        "question":   f"What is the current health of {MACHINE_ID}?",
        "machine_id": MACHINE_ID,
        "volt":       170.0,
        "rotate":     450.0,
        "pressure":   100.0,
        "vibration":  40.0,
        "rul":        280.0,
    })
    ok     = isinstance(r, dict) and isinstance(r.get("response"), str) and len(r["response"]) > 10
    detail = (r["response"][:80] + "...") if ok else str(r)
    return ok, detail


# ─── Test 6: analyze_anomaly ─────────────────────────────────────
def test_analyze_anomaly():
    r  = post({
        "action":     "analyze_anomaly",
        "machine_id": "TEST-MACHINE-01",
        "volt":       285.0,
        "rotate":     75.0,
        "pressure":   195.0,
        "vibration":  88.0,
        "rul":        8.5,
    })
    ok = isinstance(r, dict) and "fault_type" in r and "severity" in r
    detail = (
        f"fault={r.get('fault_type')}, severity={r.get('severity')}, "
        f"auto_fix={r.get('auto_fix_applied')}"
        if ok else str(r)
    )
    return ok, detail


# ─── Run all tests ───────────────────────────────────────────────
print()
print("=" * 58)
print("  MachineWhisperer — AgentCore Endpoint Tests")
print("=" * 58)

if not AGENTCORE_URL:
    print(f"\n  {FAIL}  AGENTCORE_URL not set in backend/.env")
    print("       Run:  python agentcore_deploy.py")
    print("       Then add AGENTCORE_URL=<url> to backend/.env\n")
    sys.exit(1)

print(f"\n  Endpoint : {AGENTCORE_URL}")
print(f"  Machine  : {MACHINE_ID}\n")

run_test("health_check                    ", test_health_check)
run_test("get_machine_state               ", test_get_machine_state)
run_test("get_stats (last 60 min)         ", test_get_stats)
run_test("get_alerts (limit 5)            ", test_get_alerts)
run_test("chat_query                      ", test_chat_query)
run_test("analyze_anomaly (high readings) ", test_analyze_anomaly)

passed = sum(results)
total  = len(results)
print()
print(f"  {passed}/{total} tests passed")
print("=" * 58)

if passed == total:
    print()
    print("  All tests passed! Your AgentCore endpoint is live.")
    print(f"  Endpoint: {AGENTCORE_URL}")
    print()
    print("  Quick test:")
    print(f'  curl -X POST "{AGENTCORE_URL}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f"    -d '{{\"action\":\"health_check\"}}'")
    print()
else:
    print()
    print("  Some tests failed.")
    print("  - Verify the Lambda function is Active in AWS Console")
    print("  - Check CloudWatch logs for the function")
    print("  - Ensure AGENTCORE_URL ends with / or adjust the URL")
    print()
    sys.exit(1)
