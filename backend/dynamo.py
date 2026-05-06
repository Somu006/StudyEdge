"""
dynamo.py — DynamoDB integration for MachineWhisperer
Tables:
  mw_machine_state     PK: machine_id (S)
  mw_alerts            PK: machine_id (S), SK: alert_id (S)
  mw_sensor_timeseries PK: machine_id (S), SK: timestamp_ms (S)
"""

import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


def _to_decimal(value) -> Decimal:
    """Convert float/int to Decimal for DynamoDB storage."""
    return Decimal(str(round(float(value), 4)))


class DynamoDB:
    TABLE_MACHINE_STATE    = "mw_machine_state"
    TABLE_ALERTS           = "mw_alerts"
    TABLE_TIMESERIES       = "mw_sensor_timeseries"

    def __init__(self):
        self._resource = None
        self._client   = None
        self._machine_state_table = None
        self._alerts_table        = None
        self._timeseries_table    = None
        self._ready = False
        self._init()

    # ─── Internal setup ───────────────────────────────────────────

    def _get_resource(self):
        kwargs = {
            "region_name": os.environ.get("AWS_REGION", "us-east-1"),
            "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        }
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        if session_token:
            kwargs["aws_session_token"] = session_token
        return boto3.resource("dynamodb", **kwargs)

    def _get_client(self):
        kwargs = {
            "region_name": os.environ.get("AWS_REGION", "us-east-1"),
            "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        }
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        if session_token:
            kwargs["aws_session_token"] = session_token
        return boto3.client("dynamodb", **kwargs)

    def _ensure_table(self, resource, table_name: str, key_schema: list, attr_defs: list):
        """Create table if it doesn't exist; return the Table object."""
        try:
            table = resource.create_table(
                TableName=table_name,
                KeySchema=key_schema,
                AttributeDefinitions=attr_defs,
                BillingMode="PAY_PER_REQUEST",
            )
            table.wait_until_exists()
            print(f"[DynamoDB] Created table: {table_name}", flush=True)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceInUseException":
                # Table already exists — just get a reference
                table = resource.Table(table_name)
            else:
                raise
        return table

    def _init(self):
        try:
            resource = self._get_resource()
            self._client = self._get_client()

            self._machine_state_table = self._ensure_table(
                resource,
                self.TABLE_MACHINE_STATE,
                key_schema=[{"AttributeName": "machine_id", "KeyType": "HASH"}],
                attr_defs=[{"AttributeName": "machine_id", "AttributeType": "S"}],
            )

            self._alerts_table = self._ensure_table(
                resource,
                self.TABLE_ALERTS,
                key_schema=[
                    {"AttributeName": "machine_id", "KeyType": "HASH"},
                    {"AttributeName": "alert_id",   "KeyType": "RANGE"},
                ],
                attr_defs=[
                    {"AttributeName": "machine_id", "AttributeType": "S"},
                    {"AttributeName": "alert_id",   "AttributeType": "S"},
                ],
            )

            self._timeseries_table = self._ensure_table(
                resource,
                self.TABLE_TIMESERIES,
                key_schema=[
                    {"AttributeName": "machine_id",   "KeyType": "HASH"},
                    {"AttributeName": "timestamp_ms", "KeyType": "RANGE"},
                ],
                attr_defs=[
                    {"AttributeName": "machine_id",   "AttributeType": "S"},
                    {"AttributeName": "timestamp_ms", "AttributeType": "S"},
                ],
            )

            # Enable TTL on the timeseries table (safe to call even if already enabled)
            try:
                self._client.update_time_to_live(
                    TableName=self.TABLE_TIMESERIES,
                    TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
                )
                print("[DynamoDB] TTL enabled on mw_sensor_timeseries", flush=True)
            except Exception as e:
                print(f"[DynamoDB] TTL update skipped (may already be enabled): {e}", flush=True)

            self._ready = True
            print(
                "[DynamoDB] Ready. Tables: mw_machine_state, mw_alerts, mw_sensor_timeseries",
                flush=True,
            )

        except Exception as e:
            print(f"[DynamoDB] Init failed (app will continue without DynamoDB): {e}", flush=True)
            self._ready = False

    # ─── Public methods ───────────────────────────────────────────

    def upsert_machine_state(
        self,
        machine_id: str,
        volt: float,
        rotate: float,
        pressure: float,
        vibration: float,
        is_anomaly: bool,
        rul: float = 0.0,
        health_pct: float = 100.0,
        temperature: float = 0.0,
    ) -> bool:
        """Write (or overwrite) the latest sensor reading for a machine."""
        if not self._ready:
            return False
        try:
            self._machine_state_table.put_item(
                Item={
                    "machine_id": machine_id,
                    "volt": _to_decimal(volt),
                    "rotate": _to_decimal(rotate),
                    "pressure": _to_decimal(pressure),
                    "vibration": _to_decimal(vibration),
                    "is_anomaly": is_anomaly,
                    "rul": _to_decimal(rul),
                    "health_pct": _to_decimal(health_pct),
                    "temperature": _to_decimal(temperature),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return True
        except Exception as e:
            print(f"[DynamoDB] upsert_machine_state error: {e}", flush=True)
            return False

    def save_alert(
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
    ) -> str | None:
        """Save an anomaly alert. Returns the generated alert_id, or None on failure."""
        if not self._ready:
            return None
        try:
            alert_id = str(uuid.uuid4())
            self._alerts_table.put_item(
                Item={
                    "machine_id": machine_id,
                    "alert_id": alert_id,
                    "fault_type": fault_type,
                    "severity": severity,
                    "recommended_action": recommended_action,
                    "explanation": explanation,
                    "volt": _to_decimal(volt),
                    "rotate": _to_decimal(rotate),
                    "pressure": _to_decimal(pressure),
                    "vibration": _to_decimal(vibration),
                    "auto_fixed": auto_fixed,
                    "rul": _to_decimal(rul),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            return alert_id
        except Exception as e:
            print(f"[DynamoDB] save_alert error: {e}", flush=True)
            return None

    def get_machine_state(self, machine_id: str) -> dict | None:
        """Return the latest state dict for a machine, or None if not found."""
        if not self._ready:
            return None
        try:
            resp = self._machine_state_table.get_item(
                Key={"machine_id": machine_id}
            )
            item = resp.get("Item")
            return _deserialize(item) if item else None
        except Exception as e:
            print(f"[DynamoDB] get_machine_state error: {e}", flush=True)
            return None

    def get_alerts(self, machine_id: str, limit: int = 20) -> list:
        """Return up to `limit` alerts for a machine, newest first."""
        if not self._ready:
            return []
        try:
            resp = self._alerts_table.query(
                KeyConditionExpression=Key("machine_id").eq(machine_id),
                ScanIndexForward=False,   # descending by sort key
                Limit=limit,
            )
            return [_deserialize(item) for item in resp.get("Items", [])]
        except Exception as e:
            print(f"[DynamoDB] get_alerts error: {e}", flush=True)
            return []

    def get_all_machine_states(self) -> list:
        """Scan and return all machine state records."""
        if not self._ready:
            return []
        try:
            resp = self._machine_state_table.scan()
            return [_deserialize(item) for item in resp.get("Items", [])]
        except Exception as e:
            print(f"[DynamoDB] get_all_machine_states error: {e}", flush=True)
            return []

    # ─── Time-series methods ──────────────────────────────────────

    def write_sensor_reading(
        self,
        machine_id: str,
        volt: float,
        rotate: float,
        pressure: float,
        vibration: float,
        is_anomaly: bool,
        rul: float = 0.0,
        health_pct: float = 100.0,
        temperature: float = 0.0,
    ) -> bool:
        """Append a time-stamped sensor reading to mw_sensor_timeseries."""
        if not self._ready:
            return False
        try:
            timestamp_ms = str(int(time.time() * 1000))
            self._timeseries_table.put_item(
                Item={
                    "machine_id":    machine_id,
                    "timestamp_ms":  timestamp_ms,
                    "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                    "volt":          str(round(float(volt), 2)),
                    "rotate":        str(round(float(rotate), 2)),
                    "pressure":      str(round(float(pressure), 2)),
                    "vibration":     str(round(float(vibration), 2)),
                    "is_anomaly":    str(is_anomaly),
                    "rul":           str(round(float(rul), 2)),
                    "health_pct":    str(round(float(health_pct), 1)),
                    "temperature":   str(round(float(temperature), 1)),
                    "ttl":           int(time.time()) + 86400 * 7,  # auto-delete after 7 days
                }
            )
            return True
        except Exception as e:
            print(f"[DynamoDB] write_sensor_reading error: {e}", flush=True)
            return False

    def query_recent(self, machine_id: str, minutes: int = 60) -> list:
        """Return up to 500 readings for a machine from the last N minutes, newest first."""
        if not self._ready:
            return []
        try:
            cutoff_ms = str(int((time.time() - minutes * 60) * 1000))
            resp = self._timeseries_table.query(
                KeyConditionExpression=(
                    Key("machine_id").eq(machine_id) &
                    Key("timestamp_ms").gte(cutoff_ms)
                ),
                ScanIndexForward=False,
                Limit=500,
            )
            return resp.get("Items", [])
        except Exception as e:
            print(f"[DynamoDB] query_recent error: {e}", flush=True)
            return []

    def query_anomalies(self, machine_id: str, hours: int = 24) -> list:
        """Return anomaly readings for a machine from the last N hours, newest first."""
        if not self._ready:
            return []
        try:
            cutoff_ms = str(int((time.time() - hours * 3600) * 1000))
            resp = self._timeseries_table.query(
                KeyConditionExpression=(
                    Key("machine_id").eq(machine_id) &
                    Key("timestamp_ms").gte(cutoff_ms)
                ),
                ScanIndexForward=False,
                Limit=500,
            )
            items = resp.get("Items", [])
            return [item for item in items if item.get("is_anomaly") == "True"]
        except Exception as e:
            print(f"[DynamoDB] query_anomalies error: {e}", flush=True)
            return []

    def get_sensor_stats(self, machine_id: str, minutes: int = 60) -> dict:
        """Return aggregated stats for a machine over the last N minutes."""
        empty = {
            "machine_id":     machine_id,
            "period_minutes": minutes,
            "total_readings": 0,
            "anomaly_count":  0,
            "avg_volt":       0.0,
            "avg_rotate":     0.0,
            "avg_pressure":   0.0,
            "avg_vibration":  0.0,
            "avg_health_pct": 0.0,
            "max_vibration":  0.0,
            "min_volt":       0.0,
        }
        if not self._ready:
            return empty
        try:
            items = self.query_recent(machine_id, minutes=minutes)
            if not items:
                return empty

            def _f(item, key):
                try:
                    return float(item.get(key, 0))
                except (ValueError, TypeError):
                    return 0.0

            volts      = [_f(i, "volt")       for i in items]
            rotates    = [_f(i, "rotate")     for i in items]
            pressures  = [_f(i, "pressure")   for i in items]
            vibrations = [_f(i, "vibration")  for i in items]
            healths    = [_f(i, "health_pct") for i in items]
            n          = len(items)

            return {
                "machine_id":     machine_id,
                "period_minutes": minutes,
                "total_readings": n,
                "anomaly_count":  sum(1 for i in items if i.get("is_anomaly") == "True"),
                "avg_volt":       round(sum(volts)      / n, 2),
                "avg_rotate":     round(sum(rotates)    / n, 2),
                "avg_pressure":   round(sum(pressures)  / n, 2),
                "avg_vibration":  round(sum(vibrations) / n, 2),
                "avg_health_pct": round(sum(healths)    / n, 1),
                "max_vibration":  round(max(vibrations),    2),
                "min_volt":       round(min(volts),         2),
            }
        except Exception as e:
            print(f"[DynamoDB] get_sensor_stats error: {e}", flush=True)
            return empty


# ─── Helpers ──────────────────────────────────────────────────────

def _deserialize(item: dict) -> dict:
    """Recursively convert Decimal back to float for JSON serialisation."""
    out = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, dict):
            out[k] = _deserialize(v)
        elif isinstance(v, list):
            out[k] = [_deserialize(i) if isinstance(i, dict) else (float(i) if isinstance(i, Decimal) else i) for i in v]
        else:
            out[k] = v
    return out


# ─── Singleton ────────────────────────────────────────────────────
dynamo = DynamoDB()
