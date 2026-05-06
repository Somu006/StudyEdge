#!/bin/bash
# =============================================================
#  health_check.sh — MachineWhisperer service health check
#  Usage: bash health_check.sh
# =============================================================

PROJECT_DIR="/home/ubuntu/AI-Compressor-Predictive-Maintenance"
VENV="$PROJECT_DIR/venv/bin"
ENV_FILE="$PROJECT_DIR/backend/.env"

PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "54.89.167.234")

PASS=0
FAIL=0

ok()   { echo "  ✅  $1"; PASS=$((PASS+1)); }
fail() { echo "  ❌  $1"; FAIL=$((FAIL+1)); }

echo ""
echo "============================================================="
echo "  MachineWhisperer — Health Check"
echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================="
echo ""

# ── 1. Port checks ────────────────────────────────────────────────
echo "  [ PORTS ]"

check_port() {
    local label=$1
    local port=$2
    local path=${3:-"/"}
    if curl -sf --max-time 5 "http://localhost:$port$path" > /dev/null 2>&1; then
        ok "$label — http://localhost:$port$path"
    else
        fail "$label — port $port not responding"
    fi
}

check_port "Backend  (FastAPI)"  8000 "/"
check_port "Frontend (serve)"    3000 "/"
check_port "Simulator"           9000 "/api/state"
echo ""

# ── 2. systemd service status ─────────────────────────────────────
echo "  [ SYSTEMD SERVICES ]"

check_svc() {
    local name=$1
    local label=$2
    if systemctl is-active --quiet "$name" 2>/dev/null; then
        ok "$label — active (running)"
    else
        fail "$label — not active"
    fi
}

check_svc "machinewhisperer-backend"   "machinewhisperer-backend  "
check_svc "machinewhisperer-frontend"  "machinewhisperer-frontend "
check_svc "machinewhisperer-simulator" "machinewhisperer-simulator"
echo ""

# ── 3. AWS DynamoDB ───────────────────────────────────────────────
echo "  [ AWS DYNAMODB ]"

DYNAMO_RESULT=$("$VENV/python" - <<'PYEOF' 2>&1
import os, sys
# Load .env manually (dotenv may not be in path)
env_file = "/home/ubuntu/AI-Compressor-Predictive-Maintenance/backend/.env"
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

import boto3
from botocore.exceptions import ClientError

try:
    client = boto3.client(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
    )
    tables = client.list_tables()["TableNames"]
    expected = ["mw_machine_state", "mw_alerts", "mw_sensor_timeseries"]
    found    = [t for t in expected if t in tables]
    missing  = [t for t in expected if t not in tables]
    if missing:
        print(f"PARTIAL:{','.join(found)}|MISSING:{','.join(missing)}")
    else:
        print(f"OK:{','.join(found)}")
except Exception as e:
    print(f"ERROR:{e}")
PYEOF
)

if echo "$DYNAMO_RESULT" | grep -q "^OK:"; then
    tables=$(echo "$DYNAMO_RESULT" | sed 's/^OK://')
    ok "DynamoDB — 3 tables found: $tables"
elif echo "$DYNAMO_RESULT" | grep -q "^PARTIAL:"; then
    fail "DynamoDB — $DYNAMO_RESULT"
else
    fail "DynamoDB — ${DYNAMO_RESULT#ERROR:}"
fi
echo ""

# ── 4. Amazon SNS ─────────────────────────────────────────────────
echo "  [ AMAZON SNS ]"

SNS_RESULT=$("$VENV/python" - <<'PYEOF' 2>&1
import os
env_file = "/home/ubuntu/AI-Compressor-Predictive-Maintenance/backend/.env"
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

import boto3
try:
    client = boto3.client(
        "sns",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
    )
    topics = client.list_topics()["Topics"]
    match  = [t["TopicArn"] for t in topics if "machinewhisperer-alerts" in t["TopicArn"]]
    if match:
        print(f"OK:{match[0]}")
    else:
        print("MISSING:machinewhisperer-alerts topic not found")
except Exception as e:
    print(f"ERROR:{e}")
PYEOF
)

if echo "$SNS_RESULT" | grep -q "^OK:"; then
    arn=$(echo "$SNS_RESULT" | sed 's/^OK://')
    ok "SNS — topic found: $arn"
else
    fail "SNS — ${SNS_RESULT#*:}"
fi
echo ""

# ── 5. Amazon S3 ──────────────────────────────────────────────────
echo "  [ AMAZON S3 ]"

S3_RESULT=$("$VENV/python" - <<'PYEOF' 2>&1
import os
env_file = "/home/ubuntu/AI-Compressor-Predictive-Maintenance/backend/.env"
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

import boto3
try:
    sts    = boto3.client(
        "sts",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
    )
    acct   = sts.get_caller_identity()["Account"]
    bucket = f"machinewhisperer-reports-{acct}"
    s3     = boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
    )
    s3.head_bucket(Bucket=bucket)
    print(f"OK:{bucket}")
except Exception as e:
    print(f"ERROR:{e}")
PYEOF
)

if echo "$S3_RESULT" | grep -q "^OK:"; then
    bucket=$(echo "$S3_RESULT" | sed 's/^OK://')
    ok "S3 — bucket accessible: $bucket"
else
    fail "S3 — ${S3_RESULT#ERROR:}"
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────
TOTAL=$((PASS+FAIL))
echo "============================================================="
echo "  Results: $PASS/$TOTAL checks passed"
if [ "$FAIL" -eq 0 ]; then
    echo "  ✅  All systems operational"
else
    echo "  ⚠️   $FAIL check(s) failed — see above"
fi
echo "============================================================="
echo ""
echo "  Frontend:  http://$PUBLIC_IP:3000"
echo "  API:       http://$PUBLIC_IP:8000"
echo "  API Docs:  http://$PUBLIC_IP:8000/docs"
echo "  Simulator: http://$PUBLIC_IP:9000"
echo ""
