import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def send_anomaly_email(machine_id: str, fault_type: str, severity: str,
                       explanation: str, recommended_action: str,
                       volt: float, rotate: float, pressure: float,
                       vibration: float, auto_fixed: bool = False):
    """
    Send email notification when an anomaly is detected.
    Credentials are read from environment variables only.
    """
    sender = os.environ.get("EMAIL_SENDER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", "")
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))

    if not sender or not password or not recipient:
        print("[EMAIL] Skipped: credentials not configured in .env", flush=True)
        return False

    # Build email
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "AUTO-FIXED" if auto_fixed else "REQUIRES ATTENTION"

    subject = f"[{severity}] {fault_type} - {machine_id} ({status})"

    body = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MACHINEWHISPERER - ANOMALY ALERT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Machine:    {machine_id}
Time:       {timestamp}
Fault:      {fault_type}
Severity:   {severity}
Status:     {status}

━━━ SENSOR READINGS ━━━
  Voltage:    {volt:.1f} V
  Rotation:   {rotate:.0f} RPM
  Pressure:   {pressure:.1f} psi
  Vibration:  {vibration:.1f} mm/s

━━━ AI ANALYSIS ━━━
{explanation}

━━━ RECOMMENDED ACTION ━━━
{recommended_action}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is an automated alert from MachineWhisperer.
Do not reply to this email.
"""

    try:
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print(f"[EMAIL] Alert sent to {recipient}", flush=True)
        return True

    except Exception as e:
        print(f"[EMAIL] Failed to send: {e}", flush=True)
        return False
