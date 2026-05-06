"""
s3_reporter.py — Amazon S3 work order report storage for MachineWhisperer
Bucket  : machinewhisperer-reports-{account_id}
Prefix  : reports/{machine_id}/{YYYY-MM-DD}/{work_order_id}.json|pdf
"""

import io
import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# ── optional reportlab ────────────────────────────────────────────
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class S3Reporter:
    def __init__(self):
        self._client     = None
        self.bucket_name = None
        self._ready      = False
        self._init()

    # ─── Internal setup ───────────────────────────────────────────

    def _creds(self) -> dict:
        kwargs = {
            "region_name":           os.environ.get("AWS_REGION", "us-east-1"),
            "aws_access_key_id":     os.environ.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        }
        token = os.environ.get("AWS_SESSION_TOKEN")
        if token:
            kwargs["aws_session_token"] = token
        return kwargs

    def _get_account_id(self) -> str:
        try:
            sts = boto3.client("sts", **self._creds())
            return sts.get_caller_identity()["Account"]
        except Exception:
            return "prod"

    def _ensure_bucket(self, bucket: str, region: str):
        try:
            if region == "us-east-1":
                self._client.create_bucket(Bucket=bucket)
            else:
                self._client.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )
            print(f"[S3] Created bucket: {bucket}", flush=True)

            # Enable versioning
            self._client.put_bucket_versioning(
                Bucket=bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )

            # Block all public access
            self._client.put_public_access_block(
                Bucket=bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls":       True,
                    "IgnorePublicAcls":      True,
                    "BlockPublicPolicy":     True,
                    "RestrictPublicBuckets": True,
                },
            )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                pass  # already exists — fine
            else:
                raise

    def _init(self):
        try:
            region = os.environ.get("AWS_REGION", "us-east-1")
            self._client = boto3.client("s3", **self._creds())

            account_id       = self._get_account_id()
            self.bucket_name = f"machinewhisperer-reports-{account_id}"

            self._ensure_bucket(self.bucket_name, region)

            self._ready = True
            print(f"[S3] Ready. Bucket: {self.bucket_name}", flush=True)
        except Exception as e:
            print(
                f"[S3] Init failed (app will continue without S3): {e}",
                flush=True,
            )
            self._ready = False

    # ─── Public property ──────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ─── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _date_prefix(created_at_str: str) -> str:
        """Extract YYYY-MM-DD from created_at string, fallback to today."""
        try:
            return str(created_at_str)[:10]
        except Exception:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ─── Upload methods ───────────────────────────────────────────

    def upload_json_report(self, work_order_dict: dict) -> str | None:
        """Serialize work order to JSON and upload to S3. Returns S3 key."""
        if not self._ready:
            return None
        try:
            wo        = dict(work_order_dict)
            machine   = wo.get("machine_id", "unknown")
            wo_id     = str(wo.get("id", "0"))
            date_pfx  = self._date_prefix(wo.get("created_at", ""))

            # Enrich with report metadata
            wo["report_generated_at"] = datetime.now(timezone.utc).isoformat()
            wo["report_version"]      = "1.0"
            wo["app"]                 = "MachineWhisperer"

            key  = f"reports/{machine}/{date_pfx}/{wo_id}.json"
            body = json.dumps(wo, indent=2, default=str).encode("utf-8")

            self._client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType="application/json",
                Metadata={
                    "machine_id": machine,
                    "severity":   str(wo.get("severity", "")),
                    "fault_type": str(wo.get("fault_type", "")),
                },
            )
            return key
        except Exception as e:
            print(f"[S3] upload_json_report error: {e}", flush=True)
            return None

    def upload_pdf_report(self, work_order_dict: dict) -> str | None:
        """Generate a PDF report and upload to S3. Returns S3 key."""
        if not self._ready:
            return None
        if not REPORTLAB_AVAILABLE:
            print("[S3] reportlab not installed — skipping PDF generation.", flush=True)
            return None
        try:
            wo       = work_order_dict
            machine  = str(wo.get("machine_id", "unknown"))
            wo_id    = str(wo.get("id", "0"))
            date_pfx = self._date_prefix(wo.get("created_at", ""))

            buf    = io.BytesIO()
            doc    = SimpleDocTemplate(
                buf, pagesize=A4,
                leftMargin=2*cm, rightMargin=2*cm,
                topMargin=2*cm, bottomMargin=2*cm,
            )
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                "MWTitle",
                parent=styles["Title"],
                fontSize=18,
                textColor=colors.HexColor("#1a1a2e"),
                spaceAfter=6,
            )
            heading_style = ParagraphStyle(
                "MWHeading",
                parent=styles["Heading2"],
                fontSize=12,
                textColor=colors.HexColor("#C8956C"),
                spaceBefore=14,
                spaceAfter=4,
            )
            body_style = ParagraphStyle(
                "MWBody",
                parent=styles["Normal"],
                fontSize=10,
                leading=14,
                textColor=colors.HexColor("#2C2416"),
            )
            footer_style = ParagraphStyle(
                "MWFooter",
                parent=styles["Normal"],
                fontSize=8,
                textColor=colors.grey,
                alignment=1,  # centre
            )

            severity_colors = {
                "P1": colors.HexColor("#DC2626"),
                "P2": colors.HexColor("#C9622F"),
                "P3": colors.HexColor("#2D6A4F"),
            }
            sev       = str(wo.get("severity", "P2"))
            sev_color = severity_colors.get(sev, colors.HexColor("#C8956C"))

            story = [
                Paragraph("MachineWhisperer — Maintenance Report", title_style),
                HRFlowable(width="100%", thickness=2, color=colors.HexColor("#C8956C")),
                Spacer(1, 0.4*cm),

                Paragraph("WORK ORDER DETAILS", heading_style),
                Table(
                    [
                        ["Work Order ID",  str(wo.get("id", "—"))],
                        ["Machine ID",     machine],
                        ["Generated At",   str(wo.get("created_at", "—"))],
                        ["Severity",       sev],
                        ["Fault Type",     str(wo.get("fault_type", "—"))],
                    ],
                    colWidths=[4*cm, 13*cm],
                    style=TableStyle([
                        ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
                        ("FONTNAME",    (0, 0), (0, -1),  "Helvetica-Bold"),
                        ("FONTSIZE",    (0, 0), (-1, -1), 10),
                        ("TEXTCOLOR",   (1, 3), (1, 3),   sev_color),
                        ("FONTNAME",    (1, 3), (1, 3),   "Helvetica-Bold"),
                        ("ROWBACKGROUNDS", (0, 0), (-1, -1),
                         [colors.HexColor("#FAF8F4"), colors.white]),
                        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#E8DDD0")),
                        ("TOPPADDING",  (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ]),
                ),
                Spacer(1, 0.3*cm),

                Paragraph("RECOMMENDED ACTION", heading_style),
                Paragraph(
                    str(wo.get("recommended_action", "—")).replace("\n", "<br/>"),
                    body_style,
                ),
                Spacer(1, 0.3*cm),

                Paragraph("TECHNICAL EXPLANATION", heading_style),
                Paragraph(
                    str(wo.get("explanation", "—")).replace("\n", "<br/>"),
                    body_style,
                ),
                Spacer(1, 0.6*cm),

                HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E8DDD0")),
                Spacer(1, 0.2*cm),
                Paragraph(
                    "Generated by MachineWhisperer | Cognizant Technoverse 2026",
                    footer_style,
                ),
            ]

            doc.build(story)
            buf.seek(0)

            key = f"reports/{machine}/{date_pfx}/{wo_id}.pdf"
            self._client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=buf.read(),
                ContentType="application/pdf",
                Metadata={
                    "machine_id": machine,
                    "severity":   sev,
                    "fault_type": str(wo.get("fault_type", "")),
                },
            )
            return key
        except Exception as e:
            print(f"[S3] upload_pdf_report error: {e}", flush=True)
            return None

    # ─── URL + listing methods ────────────────────────────────────

    def generate_presigned_url(self, s3_key: str, expiry_seconds: int = 3600) -> str | None:
        """Generate a presigned GET URL for an S3 object."""
        if not self._ready:
            return None
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiry_seconds,
            )
            return url
        except Exception as e:
            print(f"[S3] generate_presigned_url error: {e}", flush=True)
            return None

    def list_reports(self, machine_id: str, limit: int = 20) -> list:
        """List the most recent N report objects for a machine."""
        if not self._ready:
            return []
        try:
            prefix   = f"reports/{machine_id}/"
            paginator = self._client.get_paginator("list_objects_v2")
            objects  = []
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    objects.append({
                        "key":           obj["Key"],
                        "size":          obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    })
            objects.sort(key=lambda x: x["last_modified"], reverse=True)
            return objects[:limit]
        except Exception as e:
            print(f"[S3] list_reports error: {e}", flush=True)
            return []

    def get_report_stats(self) -> dict:
        """Return aggregate stats across all reports in the bucket."""
        base = {"total_reports": 0, "total_size_mb": 0.0, "bucket": self.bucket_name}
        if not self._ready:
            return base
        try:
            paginator   = self._client.get_paginator("list_objects_v2")
            total_count = 0
            total_bytes = 0
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix="reports/"):
                for obj in page.get("Contents", []):
                    total_count += 1
                    total_bytes += obj["Size"]
            return {
                "total_reports": total_count,
                "total_size_mb": round(total_bytes / (1024 * 1024), 2),
                "bucket":        self.bucket_name,
            }
        except Exception as e:
            print(f"[S3] get_report_stats error: {e}", flush=True)
            return base


# ─── Singleton ────────────────────────────────────────────────────
s3 = S3Reporter()
