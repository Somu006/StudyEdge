"""
test_timestream.py — Smoke tests for Timestream integration
Run from the backend/ directory:
    python test_timestream.py
"""

import os
import sys
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from timestream import timestream

MACHINE_ID = "TEST-MACHINE-01"
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


# ─── Test 1: is_ready ────────────────────────────────────────────
def test_is_ready():
    ok = timestream.is_ready is True
    return ok, "client initialised and tables exist" if ok else "is_ready is False — check credentials"


# ─── Test 2: write_sensor_reading ────────────────────────────────
def test_write():
    ok = timestream.write_sensor_reading(
        machine_id=MACHINE_ID,
        volt=171.5,
        rotate=452.0,
        pressure=98.7,
        vibration=37.4,
        is_anomaly=False,
        rul=290.1,
        health_pct=83.2,
        temperature=41.0,
    )
    return ok, "record written" if ok else "write returned False"


# ─── Test 3: query_recent ────────────────────────────────────────
def test_query_recent():
    # Give Timestream a moment to make the record queryable
    time.sleep(5)
    rows = timestream.query_recent(MACHINE_ID, minutes=5)
    ok = isinstance(rows, list) and len(rows) >= 1
    detail = f"{len(rows)} record(s) returned" if ok else f"expected ≥1, got {len(rows)}"
    return ok, detail


# ─── Test 4: write anomaly + query_anomalies ─────────────────────
def test_anomaly_roundtrip():
    wrote = timestream.write_sensor_reading(
        machine_id=MACHINE_ID,
        volt=285.0,
        rotate=75.0,
        pressure=195.0,
        vibration=98.0,
        is_anomaly=True,
        rul=12.3,
        health_pct=4.1,
        temperature=95.0,
    )
    if not wrote:
        return False, "anomaly write failed"

    time.sleep(5)
    rows = timestream.query_anomalies(MACHINE_ID, hours=1)
    ok = isinstance(rows, list) and len(rows) >= 1
    detail = f"{len(rows)} anomaly record(s) found" if ok else f"expected ≥1, got {len(rows)}"
    return ok, detail


# ─── Run all tests ───────────────────────────────────────────────
print()
print("=" * 54)
print("  MachineWhisperer — Timestream Integration Tests")
print("=" * 54)

if not timestream.is_ready:
    print(f"\n  {FAIL}  Timestream client failed to initialise.")
    print("       Check AWS credentials in backend/.env\n")
    sys.exit(1)

print(f"\n  Region   : {os.environ.get('AWS_REGION', 'us-east-1')}")
print(f"  Database : machinewhisperer_db")
print(f"  Table    : sensor_readings")
print(f"  Machine  : {MACHINE_ID}\n")

run_test("is_ready                    ", test_is_ready)
run_test("write_sensor_reading        ", test_write)
run_test("query_recent (last 5 min)   ", test_query_recent)
run_test("anomaly write + query_anomalies", test_anomaly_roundtrip)

passed = sum(results)
total  = len(results)
print()
print(f"  {passed}/{total} tests passed")
print("=" * 54)

if passed == total:
    print()
    print("  All tests passed! Next steps:")
    print("  1. Start the full system:  run_all.bat")
    print("  2. Recent readings:        GET http://localhost:8000/api/timestream/recent/Screw-Compressor-01?minutes=60")
    print("  3. Anomaly history:        GET http://localhost:8000/api/timestream/anomalies/Screw-Compressor-01?hours=24")
    print("  4. Trigger a fault in the Simulator UI and watch anomaly records appear.")
    print()
else:
    print()
    print("  Some tests failed. Check AWS credentials and Timestream permissions.")
    print("  Required IAM actions: timestream:CreateDatabase, timestream:CreateTable,")
    print("                        timestream:WriteRecords, timestream:Select")
    print()
    sys.exit(1)
