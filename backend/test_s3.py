"""
test_s3.py — Smoke tests for S3 report storage
Run from the backend/ directory:
    python test_s3.py
"""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from s3_reporter import s3

MACHINE_ID = "TEST-MACHINE-01"
PASS = "✅"
FAIL = "❌"

DUMMY_WO = {
    "id":                 "test-001",
    "machine_id":         MACHINE_ID,
    "fault_type":         "Overvoltage",
    "severity":           "P2",
    "recommended_action": "Reduce supply voltage to 170V immediately.",
    "explanation":        (
        "Voltage exceeded safe threshold by 114V. "
        "Risk of motor burnout and insulation damage. "
        "Immediate corrective action required."
    ),
    "created_at": datetime.now(timezone.utc).isoformat(),
}

results   = []
json_key  = None
pdf_key   = None


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
    ok = s3.is_ready and s3.bucket_name is not None
    return ok, f"bucket: {s3.bucket_name}" if ok else "not ready — check credentials"


# ─── Test 2: upload_json_report ──────────────────────────────────
def test_upload_json():
    global json_key
    json_key = s3.upload_json_report(DUMMY_WO)
    ok = json_key is not None
    return ok, f"key: {json_key}" if ok else "returned None"


# ─── Test 3: upload_pdf_report ───────────────────────────────────
def test_upload_pdf():
    global pdf_key
    pdf_key = s3.upload_pdf_report(DUMMY_WO)
    ok = pdf_key is not None
    return ok, f"key: {pdf_key}" if ok else "returned None (reportlab missing?)"


# ─── Test 4: generate_presigned_url ──────────────────────────────
def test_presigned_url():
    if not json_key:
        return False, "skipped — no JSON key from Test 2"
    url = s3.generate_presigned_url(json_key, expiry_seconds=3600)
    ok  = url is not None and url.startswith("https://")
    return ok, (url[:80] + "...") if ok else "returned None"


# ─── Test 5: list_reports ────────────────────────────────────────
def test_list_reports():
    reports = s3.list_reports(MACHINE_ID, limit=20)
    ok      = isinstance(reports, list) and len(reports) >= 1
    detail  = f"{len(reports)} file(s) found" if ok else f"expected ≥1, got {len(reports)}"
    return ok, detail


# ─── Test 6: get_report_stats ────────────────────────────────────
def test_report_stats():
    stats = s3.get_report_stats()
    ok    = isinstance(stats, dict) and stats.get("total_reports", 0) >= 1
    detail = (
        f"total={stats['total_reports']}, "
        f"size={stats['total_size_mb']} MB, "
        f"bucket={stats['bucket']}"
    ) if ok else f"unexpected: {stats}"
    return ok, detail


# ─── Run all tests ───────────────────────────────────────────────
print()
print("=" * 58)
print("  MachineWhisperer — S3 Report Storage Tests")
print("=" * 58)

if not s3.is_ready:
    print(f"\n  {FAIL}  S3 client failed to initialise.")
    print("       Check AWS credentials in backend/.env\n")
    sys.exit(1)

print(f"\n  Region : {os.environ.get('AWS_REGION', 'us-east-1')}")
print(f"  Bucket : {s3.bucket_name}")
print(f"  Machine: {MACHINE_ID}\n")

run_test("is_ready + bucket name          ", test_is_ready)
run_test("upload_json_report              ", test_upload_json)
run_test("upload_pdf_report               ", test_upload_pdf)
run_test("generate_presigned_url          ", test_presigned_url)
run_test("list_reports                    ", test_list_reports)
run_test("get_report_stats                ", test_report_stats)

passed = sum(results)
total  = len(results)
print()
print(f"  {passed}/{total} tests passed")
print("=" * 58)

if passed == total:
    print()
    print("  All tests passed! Live endpoints:")
    print(f"  GET http://localhost:8000/api/s3/reports/{MACHINE_ID}")
    print(f"  GET http://localhost:8000/api/s3/latest/{MACHINE_ID}")
    print(f"  GET http://localhost:8000/api/s3/stats")
    print(f"  GET http://localhost:8000/api/s3/download/{MACHINE_ID}/test-001.json")
    print()
else:
    print()
    print("  Some tests failed. Check credentials and IAM permissions.")
    print("  Required: s3:CreateBucket, s3:PutObject, s3:GetObject,")
    print("            s3:ListBucket, s3:PutBucketVersioning,")
    print("            s3:PutBucketPublicAccessBlock")
    print()
    sys.exit(1)
