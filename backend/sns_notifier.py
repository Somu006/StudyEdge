"""
sns_notifier.py — Amazon SNS integration for MachineWhisperer
Topic: machinewhisperer-alerts
Supports email and SMS subscriptions.
"""

import os
import boto3
from botocore.exceptions import ClientError

TOPIC_NAME = "machinewhisperer-alerts"


class SNSNotifier:
    def __init__(self):
        self._client   = None
        self.topic_arn = None
        self._ready    = False
        self._init()

    # ─── Internal setup ───────────────────────────────────────────

    def _get_client(self):
        kwargs = {
            "region_name":            os.environ.get("AWS_REGION", "us-east-1"),
            "aws_access_key_id":      os.environ.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key":  os.environ.get("AWS_SECRET_ACCESS_KEY"),
        }
        token = os.environ.get("AWS_SESSION_TOKEN")
        if token:
            kwargs["aws_session_token"] = token
        return boto3.client("sns", **kwargs)

    def _get_or_create_topic(self) -> str:
        """
        create_topic() is idempotent — returns the existing ARN if the topic
        already exists, so we don't need a separate list_topics() call.
        """
        resp = self._client.create_topic(Name=TOPIC_NAME)
        return resp["TopicArn"]

    def _init(self):
        try:
            self._client   = self._get_client()
            self.topic_arn = self._get_or_create_topic()
            self._ready    = True
            print(f"[SNS] Ready. Topic ARN: {self.topic_arn}", flush=True)
        except Exception as e:
            print(
                f"[SNS] Init failed (app will continue without SNS): {e}",
                flush=True,
            )
            self._ready = False

    # ─── Public property ──────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ─── Subscription methods ─────────────────────────────────────

    def subscribe_email(self, email_address: str) -> str | None:
        """Subscribe an email address to the alert topic."""
        if not self._ready:
            return None
        try:
            resp = self._client.subscribe(
                TopicArn=self.topic_arn,
                Protocol="email",
                Endpoint=email_address,
                ReturnSubscriptionArn=True,
            )
            arn = resp.get("SubscriptionArn")
            print(f"[SNS] Email subscription requested: {email_address} → {arn}", flush=True)
            return arn
        except Exception as e:
            print(f"[SNS] subscribe_email error: {e}", flush=True)
            return None

    def subscribe_sms(self, phone_number: str) -> str | None:
        """
        Subscribe a phone number (E.164 format, e.g. '+919876543210') to the topic.
        Note: SMS is not available in all AWS regions. us-east-1 supports it.
        """
        if not self._ready:
            return None
        try:
            resp = self._client.subscribe(
                TopicArn=self.topic_arn,
                Protocol="sms",
                Endpoint=phone_number,
                ReturnSubscriptionArn=True,
            )
            arn = resp.get("SubscriptionArn")
            print(f"[SNS] SMS subscription added: {phone_number} → {arn}", flush=True)
            return arn
        except Exception as e:
            print(f"[SNS] subscribe_sms error: {e}", flush=True)
            return None

    # ─── Alert methods ────────────────────────────────────────────

    def send_alert(
        self,
        machine_id: str,
        fault_type: str,
        severity: str,
        recommended_action: str,
        explanation: str,
        volt: float,
        rotate: float,
        pressure: float,
        vibration: float,
        auto_fixed: bool,
        rul: float = 0.0,
    ) -> bool:
        """Publish an anomaly alert to the SNS topic."""
        if not self._ready:
            return False
        try:
            auto_fixed_str = "Yes ✅" if auto_fixed else "No ⚠️"
            rul_display    = f"{round(float(rul), 1)}"

            message = (
                "🚨 MACHINEWHISPERER ALERT 🚨\n"
                "─────────────────────────────\n"
                f"Machine   : {machine_id}\n"
                f"Fault     : {fault_type}\n"
                f"Severity  : {severity}\n"
                f"Auto-Fixed: {auto_fixed_str}\n"
                f"RUL       : {rul_display} years remaining\n"
                "\n"
                "SENSOR READINGS:\n"
                f"Voltage   : {round(float(volt), 1)} V\n"
                f"RPM       : {round(float(rotate), 0)}\n"
                f"Pressure  : {round(float(pressure), 1)} bar\n"
                f"Vibration : {round(float(vibration), 1)} mm/s\n"
                "\n"
                "ACTION REQUIRED:\n"
                f"{recommended_action}\n"
                "─────────────────────────────\n"
                "MachineWhisperer | Predictive Maintenance"
            )

            subject = f"🚨 [{severity}] {fault_type} — {machine_id}"
            # SNS subject max length is 100 chars
            subject = subject[:100]

            self._client.publish(
                TopicArn=self.topic_arn,
                Message=message,
                Subject=subject,
            )
            print(f"[SNS] Alert published for {machine_id} ({fault_type})", flush=True)
            return True
        except Exception as e:
            print(f"[SNS] send_alert error: {e}", flush=True)
            return False

    def send_recovery_alert(self, machine_id: str) -> bool:
        """Publish a recovery notification when the machine returns to normal."""
        if not self._ready:
            return False
        try:
            message = (
                f"✅ RECOVERY: {machine_id} has returned to normal operating parameters."
            )
            subject = f"✅ RECOVERY — {machine_id}"

            self._client.publish(
                TopicArn=self.topic_arn,
                Message=message,
                Subject=subject,
            )
            print(f"[SNS] Recovery alert published for {machine_id}", flush=True)
            return True
        except Exception as e:
            print(f"[SNS] send_recovery_alert error: {e}", flush=True)
            return False

    # ─── Subscription listing ─────────────────────────────────────

    def get_subscriptions(self) -> list:
        """Return all subscriptions on the topic as a list of dicts."""
        if not self._ready:
            return []
        try:
            subs  = []
            kwargs = {"TopicArn": self.topic_arn}
            while True:
                resp = self._client.list_subscriptions_by_topic(**kwargs)
                for s in resp.get("Subscriptions", []):
                    subs.append({
                        "Protocol":        s.get("Protocol"),
                        "Endpoint":        s.get("Endpoint"),
                        "SubscriptionArn": s.get("SubscriptionArn"),
                    })
                next_token = resp.get("NextToken")
                if not next_token:
                    break
                kwargs["NextToken"] = next_token
            return subs
        except Exception as e:
            print(f"[SNS] get_subscriptions error: {e}", flush=True)
            return []


# ─── Singleton ────────────────────────────────────────────────────
sns = SNSNotifier()
