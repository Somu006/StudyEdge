"""
test_dynamo.py — Smoke tests for DynamoDB integration
Run from the backend/ directory:
    python test_dynamo.py
"""

import os
import sys

# Load .env so credentials are available before importing dynamo
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from dynamo import dynamo

MACHINE_ID = "test-machine-001"
PASS = "✅"
FAIL = "❌"

results = []


def run_test(name: str, fn):
    try:
        ok, detail = fn()
        symbol = PASS if ok else FAIL
        print(f"  {symbol}  {name}{(' — ' + detail) if detail else ''}")
        results.append(ok)
    except Exception as e:
        print(f"  {FAIL}  {name} — Exception: {e}")
        results.append(False)


# ─── Test 1: upsert_machine_state ────────────────────────────────
def test_upsert():
    ok = dynamo.upsert_machine_state(
        machine_id=MACHINE_ID,
        volt=172.3,
        rotate=448.0,
        pressure=99.5,
        vibration=38.2,
        is_anomaly=False,
        rul=285.4,
        health_pct=81.6,
        temperature=42.0,
    )
    return ok, "wrote sensor state" if ok else "write returned False"


# ─── Test 2: save_alert ──────────────────────────────────────────
def test_save_alert():
    alert_id = dynamo.save_alert(
        machine_id=MACHINE_ID,
        fault_type="Overvoltage",
        severity="P2",
        recommended_action="Reduce supply voltage to 170V",
        explanation="Voltage exceeded safe threshold by 65V.",
        volt=235.0,
        rotate=448.0,
        pressure=99.5,
        vibration=38.2,
        auto_fixed=True,
        rul=285.4,
    )
    ok = alert_id is not None
    return ok, f"alert_id={alert_id}" if ok else "returned None"


# ─── Test 3: get_machine_state ───────────────────────────────────
def test_get_machine_state():
    state = dynamo.get_machine_state(MACHINE_ID)
    ok = state is not None and state.get("machine_id") == MACHINE_ID
    detail = f"volt={state.get('volt')}, health={state.get('health_pct')}%" if ok else "returned None or wrong machine_id"
    return ok, detail


# ─── Test 4: get_alerts ──────────────────────────────────────────
def test_get_alerts():
    alerts = dynamo.get_alerts(MACHINE_ID, limit=5)
    ok = isinstance(alerts, list) and len(alerts) >= 1
    detail = f"{len(alerts)} alert(s) returned" if ok else f"expected ≥1, got {len(alerts)}"
    return ok, detail


# ─── Test 5: get_all_machine_states ──────────────────────────────
def test_get_all_machine_states():
    machines = dynamo.get_all_machine_states()
    ok = isinstance(machines, list) and any(m.get("machine_id") == MACHINE_ID for m in machines)
    detail = f"{len(machines)} machine(s) in table" if ok else f"test machine not found in scan ({len(machines)} records)"
    return ok, detail


# ─── Run all tests ───────────────────────────────────────────────
print()
print("=" * 52)
print("  MachineWhisperer — DynamoDB Integration Tests")
print("=" * 52)

if not dynamo._ready:
    print(f"\n  {FAIL}  DynamoDB client failed to initialise.")
    print("       Check AWS credentials in backend/.env\n")
    sys.exit(1)

print(f"\n  Region : {os.environ.get('AWS_REGION', 'us-east-1')}")
print(f"  Tables : mw_machine_state, mw_alerts")
print(f"  Machine: {MACHINE_ID}\n")

run_test("upsert_machine_state", test_upsert)
run_test("save_alert          ", test_save_alert)
run_test("get_machine_state   ", test_get_machine_state)
run_test("get_alerts          ", test_get_alerts)
run_test("get_all_machine_states", test_get_all_machine_states)

passed = sum(results)
total = len(results)
print()
print(f"  {passed}/{total} tests passed")
print("=" * 52)

if passed == total:
    print()
    print("  All tests passed! Next steps:")
    print("  1. Start the full system:  run_all.bat")
    print("  2. Live state endpoint:    GET http://localhost:8000/api/dynamo/state/Screw-Compressor-01")
    print("  3. Alerts endpoint:        GET http://localhost:8000/api/dynamo/alerts/Screw-Compressor-01")
    print("  4. All machines:           GET http://localhost:8000/api/dynamo/all-machines")
    print("  5. Trigger a fault in the Simulator UI and watch mw_alerts populate.")
    print()
else:
    print()
    print("  Some tests failed. Check AWS credentials and DynamoDB permissions.")
    print("  Required IAM actions: dynamodb:CreateTable, dynamodb:PutItem,")
    print("                        dynamodb:GetItem, dynamodb:Query, dynamodb:Scan")
    print()
    sys.exit(1)
