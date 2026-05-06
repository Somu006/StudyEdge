"""
lambda_deploy.py — Deploy MachineWhisperer Agent to AWS Lambda

Run from the backend/ directory:
    python lambda_deploy.py

Steps:
  1. pip install all requirements into lambda_build/
  2. Copy source files into lambda_build/
  3. Zip lambda_build/ into machinewhisperer_lambda.zip
  4. Upload zip to S3
  5. Create or update Lambda function
  6. Create public Function URL
  7. Print the live endpoint URL
"""

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime

import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── Config ────────────────────────────────────────────────────────
FUNCTION_NAME = "machinewhisperer-agent"
HANDLER       = "lambda_handler.handler"
RUNTIME       = "python3.11"
MEMORY_MB     = 512
TIMEOUT_SEC   = 300
REGION        = os.environ.get("AWS_REGION", "us-east-1")

# Only these source files are bundled (not the full project)
SOURCE_FILES = [
    "lambda_handler.py",
    "agent.py",
    "dynamo.py",
    "sns_notifier.py",
    "s3_reporter.py",
    "sensor_simulator.py",
    "notifier.py",
    "pure_lstm.py",
    "database.py",
    "models.py",
]

# Packages to install into the zip
REQUIREMENTS = [
    "boto3",
    "langchain-core",
    "langgraph",
    "sqlalchemy",
    "python-dotenv",
    "reportlab",
    "numpy",
    "pandas",
    "scikit-learn",
    "httpx",
]


# ── AWS client factory ────────────────────────────────────────────
def _aws_kwargs() -> dict:
    kwargs = {
        "region_name":           REGION,
        "aws_access_key_id":     os.environ.get("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
    }
    token = os.environ.get("AWS_SESSION_TOKEN")
    if token:
        kwargs["aws_session_token"] = token
    return kwargs


# ── IAM role resolution ───────────────────────────────────────────
def get_role_arn(iam_client) -> str:
    """
    Resolve IAM role ARN in priority order:
      1. AGENTCORE_ROLE_ARN or LAMBDA_ROLE_ARN in .env  (fastest — use LabRole)
      2. Existing role named machinewhisperer-lambda-role
      3. Create a new role (may fail in AWS Academy due to SCPs)
    """
    # Option 1: explicit env var (recommended for AWS Academy)
    role_from_env = (
        os.environ.get("AGENTCORE_ROLE_ARN") or
        os.environ.get("LAMBDA_ROLE_ARN")
    )
    if role_from_env:
        print(f"[Deploy] Using role from .env: {role_from_env}")
        return role_from_env

    # Option 2: existing role
    role_name = "machinewhisperer-lambda-role"
    try:
        resp = iam_client.get_role(RoleName=role_name)
        arn  = resp["Role"]["Arn"]
        print(f"[Deploy] Found existing role: {arn}")
        return arn
    except Exception:
        pass

    # Option 3: create new role
    print(f"[Deploy] Creating IAM role: {role_name}")
    trust = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect":    "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action":    "sts:AssumeRole",
        }],
    })
    resp     = iam_client.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=trust,
        Description="MachineWhisperer Lambda Execution Role",
    )
    role_arn = resp["Role"]["Arn"]

    for policy in [
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonS3FullAccess",
        "arn:aws:iam::aws:policy/AmazonSNSFullAccess",
        "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    ]:
        iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy)
        print(f"[Deploy]   Attached: {policy.split('/')[-1]}")

    print("[Deploy] Waiting 15 s for IAM role to propagate ...")
    time.sleep(15)
    return role_arn


# ── Build zip ─────────────────────────────────────────────────────
def build_zip(project_dir: str) -> str:
    """
    1. pip install REQUIREMENTS into lambda_build/
    2. Copy SOURCE_FILES into lambda_build/
    3. Zip lambda_build/ → machinewhisperer_lambda.zip
    4. Remove lambda_build/
    Returns path to the zip file.
    """
    build_dir = os.path.join(project_dir, "lambda_build")
    zip_path  = os.path.join(project_dir, "machinewhisperer_lambda.zip")

    # Clean previous build
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    # Install dependencies
    print("[Deploy] Installing Python dependencies into lambda_build/ ...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "--target", build_dir,
        "--quiet",
        "--upgrade",
        *REQUIREMENTS,
    ])
    print("[Deploy] Dependencies installed.")

    # Copy source files
    for fname in SOURCE_FILES:
        src = os.path.join(project_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, build_dir)
            print(f"[Deploy] Copied: {fname}")
        else:
            print(f"[Deploy] WARNING: {fname} not found — skipping")

    # Create zip
    print(f"[Deploy] Creating zip: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(build_dir):
            for file in files:
                full    = os.path.join(root, file)
                arcname = os.path.relpath(full, build_dir)
                zf.write(full, arcname)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"[Deploy] Zip ready: {size_mb:.1f} MB")

    # Cleanup build dir
    shutil.rmtree(build_dir)
    return zip_path


# ── Main deploy ───────────────────────────────────────────────────
def deploy():
    print()
    print("═" * 55)
    print("  MachineWhisperer — AWS Lambda Deployment")
    print("═" * 55)
    print()

    project_dir = os.path.dirname(os.path.abspath(__file__))
    kwargs      = _aws_kwargs()

    sts        = boto3.client("sts",    **kwargs)
    iam        = boto3.client("iam",    **kwargs)
    s3_cli     = boto3.client("s3",     **kwargs)
    lambda_cli = boto3.client("lambda", **kwargs)

    account_id  = sts.get_caller_identity()["Account"]
    bucket_name = f"machinewhisperer-reports-{account_id}"
    zip_key     = f"deployments/lambda-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"

    # ── Step 1: Build zip ─────────────────────────────────────────
    zip_path = build_zip(project_dir)

    # ── Step 2: Upload to S3 ──────────────────────────────────────
    print(f"[Deploy] Uploading to s3://{bucket_name}/{zip_key} ...")
    s3_cli.upload_file(zip_path, bucket_name, zip_key)
    print("[Deploy] Upload complete.")
    os.unlink(zip_path)

    # ── Step 3: IAM role ──────────────────────────────────────────
    role_arn = get_role_arn(iam)

    # ── Step 4: Environment variables ────────────────────────────
    env_vars = {
        "AWS_REGION":            REGION,
        "AWS_ACCESS_KEY_ID":     os.environ.get("AWS_ACCESS_KEY_ID",     ""),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        "AWS_SESSION_TOKEN":     os.environ.get("AWS_SESSION_TOKEN",     ""),
        "BEDROCK_MODEL_ID":      os.environ.get(
            "BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
        "EMAIL_SENDER":          os.environ.get("EMAIL_SENDER",    ""),
        "EMAIL_PASSWORD":        os.environ.get("EMAIL_PASSWORD",  ""),
        "EMAIL_RECIPIENT":       os.environ.get("EMAIL_RECIPIENT", ""),
        "EMAIL_SMTP_HOST":       os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com"),
        "EMAIL_SMTP_PORT":       os.environ.get("EMAIL_SMTP_PORT", "587"),
    }

    # ── Step 5: Create or update Lambda function ──────────────────
    try:
        lambda_cli.get_function(FunctionName=FUNCTION_NAME)
        # ── Update existing ───────────────────────────────────────
        print(f"[Deploy] Updating existing function: {FUNCTION_NAME}")
        lambda_cli.update_function_code(
            FunctionName=FUNCTION_NAME,
            S3Bucket=bucket_name,
            S3Key=zip_key,
        )
        # Wait for code update before touching config
        print("[Deploy] Waiting for code update to complete ...")
        waiter = lambda_cli.get_waiter("function_updated")
        waiter.wait(FunctionName=FUNCTION_NAME)
        lambda_cli.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Handler=HANDLER,
            Runtime=RUNTIME,
            Role=role_arn,
            Timeout=TIMEOUT_SEC,
            MemorySize=MEMORY_MB,
            Environment={"Variables": env_vars},
        )
        print("[Deploy] Function updated.")

    except lambda_cli.exceptions.ResourceNotFoundException:
        # ── Create new ────────────────────────────────────────────
        print(f"[Deploy] Creating new Lambda function: {FUNCTION_NAME}")
        lambda_cli.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime=RUNTIME,
            Role=role_arn,
            Handler=HANDLER,
            Code={"S3Bucket": bucket_name, "S3Key": zip_key},
            Timeout=TIMEOUT_SEC,
            MemorySize=MEMORY_MB,
            Environment={"Variables": env_vars},
            Description="MachineWhisperer Predictive Maintenance Agent",
        )
        print("[Deploy] Function created.")

    # ── Step 6: Wait for active ───────────────────────────────────
    print("[Deploy] Waiting for function to become active ...")
    waiter = lambda_cli.get_waiter("function_active")
    waiter.wait(FunctionName=FUNCTION_NAME)

    # ── Step 7: Function URL ──────────────────────────────────────
    try:
        url_resp     = lambda_cli.create_function_url_config(
            FunctionName=FUNCTION_NAME,
            AuthType="NONE",
        )
        function_url = url_resp["FunctionUrl"]
    except lambda_cli.exceptions.ResourceConflictException:
        url_resp     = lambda_cli.get_function_url_config(FunctionName=FUNCTION_NAME)
        function_url = url_resp["FunctionUrl"]

    # ── Step 8: Allow public invocation ──────────────────────────
    try:
        lambda_cli.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId="FunctionURLAllowPublicAccess",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
    except lambda_cli.exceptions.ResourceConflictException:
        pass  # permission already exists

    # ── Summary ───────────────────────────────────────────────────
    func_info  = lambda_cli.get_function(FunctionName=FUNCTION_NAME)
    func_arn   = func_info["Configuration"]["FunctionArn"]
    func_state = func_info["Configuration"]["State"]

    print()
    print("═" * 55)
    print("  ✅  DEPLOYMENT COMPLETE")
    print("═" * 55)
    print(f"  Function : {FUNCTION_NAME}")
    print(f"  ARN      : {func_arn}")
    print(f"  State    : {func_state}")
    print(f"  URL      : {function_url}")
    print(f"  Region   : {REGION}")
    print()
    print("  Quick test:")
    print(f'  curl -X POST "{function_url}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f"    -d '{{\"action\":\"health_check\"}}'")
    print()
    print("  Add to backend/.env:")
    print(f"  LAMBDA_URL={function_url}")
    print("═" * 55)
    print()


if __name__ == "__main__":
    deploy()
