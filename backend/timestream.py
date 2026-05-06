"""
timestream.py — Amazon Timestream integration for MachineWhisperer
Database : machinewhisperer_db
Table    : sensor_readings
"""

import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

DB_NAME    = "machinewhisperer_db"
TABLE_NAME = "sensor_readings"


class Timestream:
    def __init__(self):
        self._write_client = None
        self._query_client = None
        self._ready = False
        self._init()

    # ─── Internal setup ───────────────────────────────────────────

    def _credentials(self) -> dict:
        kwargs = {
            "region_name": os.environ.get("AWS_REGION", "us-east-1"),
            "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        }
        token = os.environ.get("AWS_SESSION_TOKEN")
        if token:
            kwargs["aws_session_token"] = token
        return kwargs

    def _ensure_database(self):
        try:
            self._write_client.create_database(DatabaseName=DB_NAME)
            print(f"[Timestream] Created database: {DB_NAME}", flush=True)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ConflictException":
                pass  # already exists
            else:
                raise

    def _ensure_table(self):
        try:
            self._write_client.create_table(
                DatabaseName=DB_NAME,
                TableName=TABLE_NAME,
                RetentionProperties={
                    "MemoryStoreRetentionPeriodInHours": 24,
                    "MagneticStoreRetentionPeriodInDays": 365,
                },
            )
            print(f"[Timestream] Created table: {TABLE_NAME}", flush=True)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ConflictException":
                pass  # already exists
            else:
                raise

    def _init(self):
        try:
            creds = self._credentials()
            self._write_client = boto3.client("timestream-write", **creds)
            self._query_client = boto3.client("timestream-query", **creds)
            self._ensure_database()
            self._ensure_table()
            self._ready = True
            print(
                f"[Timestream] Ready. DB={DB_NAME}, Table={TABLE_NAME}",
                flush=True,
            )
        except Exception as e:
            print(
                f"[Timestream] Init failed (app will continue without Timestream): {e}",
                flush=True,
            )
            self._ready = False

    # ─── Public property ──────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ─── Write ────────────────────────────────────────────────────

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
        """Write one multi-measure record to Timestream. Returns True on success."""
        if not self._ready:
            return False
        try:
            current_time_ms = str(int(time.time() * 1000))

            record = {
                "MeasureName": "sensor_data",
                "MeasureValueType": "MULTI",
                "Time": current_time_ms,
                "TimeUnit": "MILLISECONDS",
                "MeasureValues": [
                    {"Name": "volt",        "Value": str(round(float(volt), 4)),        "Type": "DOUBLE"},
                    {"Name": "rotate",      "Value": str(round(float(rotate), 4)),      "Type": "DOUBLE"},
                    {"Name": "pressure",    "Value": str(round(float(pressure), 4)),    "Type": "DOUBLE"},
                    {"Name": "vibration",   "Value": str(round(float(vibration), 4)),   "Type": "DOUBLE"},
                    {"Name": "rul",         "Value": str(round(float(rul), 4)),         "Type": "DOUBLE"},
                    {"Name": "health_pct",  "Value": str(round(float(health_pct), 4)),  "Type": "DOUBLE"},
                    {"Name": "temperature", "Value": str(round(float(temperature), 4)), "Type": "DOUBLE"},
                    {"Name": "is_anomaly",  "Value": str(is_anomaly),                   "Type": "VARCHAR"},
                ],
            }

            common = {
                "Dimensions": [{"Name": "machine_id", "Value": machine_id}],
            }

            self._write_client.write_records(
                DatabaseName=DB_NAME,
                TableName=TABLE_NAME,
                CommonAttributes=common,
                Records=[record],
            )
            return True

        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "RejectedRecordsException":
                rejected = e.response.get("RejectedRecords", [])
                print(f"[Timestream] RejectedRecords: {rejected}", flush=True)
            else:
                print(f"[Timestream] write_sensor_reading ClientError: {e}", flush=True)
            return False
        except Exception as e:
            print(f"[Timestream] write_sensor_reading error: {e}", flush=True)
            return False

    # ─── Query helpers ────────────────────────────────────────────

    def _run_query(self, sql: str) -> list:
        """Execute a Timestream SQL query and return a list of row dicts."""
        rows = []
        try:
            paginator = self._query_client.get_paginator("query")
            pages = paginator.paginate(QueryString=sql)
            for page in pages:
                col_info = page["ColumnInfo"]
                for row in page["Rows"]:
                    record = {}
                    for i, datum in enumerate(row["Data"]):
                        col_name = col_info[i]["Name"]
                        record[col_name] = datum.get("ScalarValue", None)
                    rows.append(record)
        except ClientError as e:
            print(f"[Timestream] query ClientError: {e}", flush=True)
        except Exception as e:
            print(f"[Timestream] query error: {e}", flush=True)
        return rows

    def query_recent(self, machine_id: str, minutes: int = 60) -> list:
        """Return sensor readings for a machine from the last N minutes."""
        if not self._ready:
            return []
        sql = (
            f'SELECT * FROM "{DB_NAME}"."{TABLE_NAME}" '
            f"WHERE machine_id = '{machine_id}' "
            f"AND time > ago({minutes}m) "
            f"ORDER BY time DESC"
        )
        return self._run_query(sql)

    def query_anomalies(self, machine_id: str, hours: int = 24) -> list:
        """Return anomaly readings for a machine from the last N hours."""
        if not self._ready:
            return []
        sql = (
            f'SELECT * FROM "{DB_NAME}"."{TABLE_NAME}" '
            f"WHERE machine_id = '{machine_id}' "
            f"AND is_anomaly = 'True' "
            f"AND time > ago({hours}h) "
            f"ORDER BY time DESC"
        )
        return self._run_query(sql)


# ─── Singleton ────────────────────────────────────────────────────
timestream = Timestream()
