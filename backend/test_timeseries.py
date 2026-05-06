"""
test_timeseries.py — Smoke tests for DynamoDB time-series integration
Run from the backend/ directory:
    python test_timeseries.py
"""

import os
import sys
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from dynamo import dynamo

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
    ok = dynamo._ready is True
    return ok, "DynamoDB client ready" if ok else "not ready — check credentials"


# ─── Test 2: write normal reading ────────────────────────────────
def test_write_normal():
    ok = dynamo.write_sensor_reading(
        machine_id=MACHINE_ID,
        volt=171.2,
        rotate=451.0,
        pressure=99.1,
        vibration=37.8,
        is_anomaly=False,
        rul=288.5,
        health_pct=82.4,
        temperature=40.5,
    )
    return ok, "normal record written" if ok else "write returned False"


# ─── Test 3: write anomaly reading ───────────────────────────────
def test_write_anomaly():
    ok = dynamo.write_sensor_reading(
        machine_id=MACHINE_ID,
        volt=284.0,
        rotate=78.0,
        pressure=198.0,
        vibration=85.0,
        is_anomaly=True,
        rul=9.1,
        health_pct=3.2,
        temperature=94.0,
    )
    return ok, "anomaly record written" if ok else "write returned False"


# ─── Test 4: query_recent ────────────────────────────────────────
def test_query_recent():
    # Small pause so writes are visible to the query
    time.sleep(2)
    rows = dynamo.query_recent(MACHINE_ID, minutes=5)
    ok = isinstance(rows, list) and len(rows) >= 1
    detail = f"{len(rows)} record(s) returned" if ok else f"expected ≥1, got {len(rows)}"
    return ok, detail


# ─── Test 5: query_anomalies ─────────────────────────────────────
def test_query_anomalies():
    rows = dynamo.query_anomalies(MACHINE_ID, hours=1)
    ok = isinstance(rows, list) and len(rows) >= 1
    detail = f"{len(rows)} anomaly record(s) found" if ok else f"expected ≥1, got {len(rows)}"
    return ok, detail


# ─── Test 6: get_sensor_stats ────────────────────────────────────
def test_get_sensor_stats():
    stats = dynamo.get_sensor_stats(MACHINE_ID, minutes=5)
    ok = (
        isinstance(stats, dict)
        and stats.get("total_readings", 0) >= 1
        and "avg_volt" in stats
        and "max_vibration" in stats
    )
    if ok:
        detail = (
            f"readings={stats['total_readings']}, "
            f"anomalies={stats['anomaly_count']}, "
            f"avg_volt={stats['avg_volt']}, "
            f"max_vib={stats['max_vibration']}"
        )
    else:
        detail = f"unexpected result: {stats}"
    return ok, detail


# ─── Run all tests ───────────────────────────────────────────────
print()
print("=" * 56)
print("  MachineWhisperer — DynamoDB Time-Series Tests")
print("=" * 56)

if not dynamo._ready:
    print(f"\n  {FAIL}  DynamoDB client failed to initialise.")
    print("       Check AWS credentials in backend/.env\n")
    sys.exit(1)

print(f"\n  Region  : {os.environ.get('AWS_REGION', 'us-east-1')}")
print(f"  Table   : mw_sensor_timeseries")
print(f"  Machine : {MACHINE_ID}\n")

run_test("is_ready                        ", test_is_ready)
run_test("write_sensor_reading (normal)   ", test_write_normal)
run_test("write_sensor_reading (anomaly)  ", test_write_anomaly)
run_test("query_recent (last 5 min)       ", test_query_recent)
run_test("query_anomalies (last 1 hour)   ", test_query_anomalies)
run_test("get_sensor_stats (last 5 min)   ", test_get_sensor_stats)

passed = sum(results)
total  = len(results)
print()
print(f"  {passed}/{total} tests passed")
print("=" * 56)

if passed == total:
    print()
    print("  All tests passed! Live endpoints:")
    print("  GET http://localhost:8000/api/timeseries/recent/Screw-Compressor-01?minutes=60")
    print("  GET http://localhost:8000/api/timeseries/anomalies/Screw-Compressor-01?hours=24")
    print("  GET http://localhost:8000/api/timeseries/stats/Screw-Compressor-01?minutes=60")
    print()
else:
    print()
    print("  Some tests failed. Check credentials and IAM permissions.")
    print("  Required: dynamodb:CreateTable, dynamodb:PutItem,")
    print("            dynamodb:Query, dynamodb:UpdateTimeToLive")
    print()
    sys.exit(1)
