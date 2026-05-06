"""
test_sns.py — Smoke tests for Amazon SNS integration
Run from the backend/ directory:
    python test_sns.py
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from sns_notifier import sns

MACHINE_ID  = "TEST-MACHINE-01"
TEST_EMAIL  = os.environ.get("EMAIL_RECIPIENT", "test@example.com")
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


# ─── Test 1: is_ready + topic ARN ────────────────────────────────
def test_is_ready():
    ok = sns.is_ready and sns.topic_arn is not None
    detail = f"ARN: {sns.topic_arn}" if ok else "not ready — check credentials"
    return ok, detail


# ─── Test 2: subscribe_email ─────────────────────────────────────
def test_subscribe_email():
    arn = sns.subscribe_email(TEST_EMAIL)
    ok  = arn is not None
    detail = f"subscription ARN: {arn}" if ok else "returned None"
    return ok, detail


# ─── Test 3: send_alert ──────────────────────────────────────────
def test_send_alert():
    ok = sns.send_alert(
        machine_id=MACHINE_ID,
        fault_type="Overvoltage",
        severity="P2",
        recommended_action="Reduce supply voltage to 170V immediately.",
        explanation="Voltage exceeded safe threshold by 114V. Risk of motor burnout.",
        volt=284.0,
        rotate=78.0,
        pressure=198.0,
        vibration=85.0,
        auto_fixed=False,
        rul=9.1,
    )
    return ok, "alert published to topic" if ok else "publish returned False"


# ─── Test 4: send_recovery_alert ─────────────────────────────────
def test_send_recovery():
    ok = sns.send_recovery_alert(MACHINE_ID)
    return ok, "recovery alert published" if ok else "publish returned False"


# ─── Test 5: get_subscriptions ───────────────────────────────────
def test_get_subscriptions():
    subs = sns.get_subscriptions()
    ok   = isinstance(subs, list)
    if ok and subs:
        detail = f"{len(subs)} subscription(s): " + ", ".join(
            f"{s['Protocol']}:{s['Endpoint']}" for s in subs
        )
    elif ok:
        detail = "0 subscriptions (topic is empty)"
    else:
        detail = "returned non-list"
    return ok, detail


# ─── Run all tests ───────────────────────────────────────────────
print()
print("=" * 56)
print("  MachineWhisperer — SNS Integration Tests")
print("=" * 56)

if not sns.is_ready:
    print(f"\n  {FAIL}  SNS client failed to initialise.")
    print("       Check AWS credentials in backend/.env\n")
    sys.exit(1)

print(f"\n  Region  : {os.environ.get('AWS_REGION', 'us-east-1')}")
print(f"  Topic   : machinewhisperer-alerts")
print(f"  Email   : {TEST_EMAIL}\n")

run_test("is_ready + topic ARN            ", test_is_ready)
run_test("subscribe_email                 ", test_subscribe_email)
run_test("send_alert (anomaly)            ", test_send_alert)
run_test("send_recovery_alert             ", test_send_recovery)
run_test("get_subscriptions               ", test_get_subscriptions)

passed = sum(results)
total  = len(results)
print()
print(f"  {passed}/{total} tests passed")
print("=" * 56)

if passed == total:
    print()
    print("  All tests passed! Next steps:")
    print(f"  1. Check {TEST_EMAIL} inbox — confirm the SNS subscription email.")
    print("  2. To add SMS:  POST http://localhost:8000/api/sns/subscribe/sms")
    print('     Body: {"phone": "+919876543210"}')
    print("  3. Trigger a fault in the Simulator UI — SNS alert fires automatically.")
    print("  4. View subscriptions: GET http://localhost:8000/api/sns/subscriptions")
    print()
else:
    print()
    print("  Some tests failed. Check credentials and IAM permissions.")
    print("  Required: sns:CreateTopic, sns:Subscribe, sns:Publish,")
    print("            sns:ListSubscriptionsByTopic")
    print()
    sys.exit(1)
