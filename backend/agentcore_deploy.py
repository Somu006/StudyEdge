"""
agentcore_deploy.py — Deploy MachineWhisperer to AWS Lambda (AgentCore Runtime)

Run from the backend/ directory:
    python agentcore_deploy.py

What it does:
  1. Creates a deployment zip of the entire backend project
  2. Uploads zip to S3 (machinewhisperer-reports-{account_id})
  3. Creates or updates a Lambda function (AgentCore uses Lambda under the hood)
  4. Creates a public Function URL
  5. Prints the endpoint URL and a ready-to-use curl test command
"""

import json
import os
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── Config ────────────────────────────────────────────────────────
AGENT_NAME   = "machinewhisperer-agent"
HANDLER      = "agentcore_handler.handler"
RUNTIME      = "python3.11"
MEMORY_MB    = 512
TIMEOUT_SEC  = 300
REGION       = os.environ.get("AWS_REGION", "us-east-1")

EXCLUDE_PATTERNS = [
    ".git", "__pycache__", "*.pyc", "*.pyo",
    "*.db", "*.sqlite", "node_modules",
    ".env", "venv", ".venv", "env",
    "test_*.py", "*.log", "*.pth",
    "agentcore_deploy.py",          # don't include the deploy script itself
]


def should_exclude(path: str) -> bool:
    base = os.path.basename(path)
    for pattern in EXCLUDE_PATTERNS:
        if fnmatch(base, pattern):
            return True
        if pattern in path.replace("\\", "/"):
            return True
    return False


def create_zip(project_dir: str, zip_path: str) -> str:
    """Zip the backend project, excluding dev/build artefacts."""
    print(f"[Deploy] Creating deployment zip from {project_dir} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]
            for file in files:
                full_path = os.path.join(root, file)
                if not should_exclude(full_path):
                    arcname = os.path.relpath(full_path, project_dir)
                    zf.write(full_path, arcname)
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"[Deploy] Zip created: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


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


def get_or_create_role(iam_client, role_name: str) -> str:
    """Return ARN of existing role, or create a new one with required policies."""
    try:
        resp = iam_client.get_role(RoleName=role_name)
        arn  = resp["Role"]["Arn"]
        print(f"[Deploy] Using existing IAM role: {arn}")
        return arn
    except iam_client.exceptions.NoSuchEntityException:
        pass

    print(f"[Deploy] Creating IAM role: {role_name}")
    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect":    "Allow",
            "Principal": {"Service": ["lambda.amazonaws.com", "bedrock.amazonaws.com"]},
            "Action":    "sts:AssumeRole",
        }],
    })
    resp     = iam_client.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=trust_policy,
        Description="MachineWhisperer AgentCore Runtime Role",
    )
    role_arn = resp["Role"]["Arn"]

    policies = [
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonS3FullAccess",
        "arn:aws:iam::aws:policy/AmazonSNSFullAccess",
        "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    ]
    for policy in policies:
        iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy)
        print(f"[Deploy]   Attached: {policy.split('/')[-1]}")

    print("[Deploy] Waiting 15 s for IAM role to propagate ...")
    time.sleep(15)
    return role_arn


def deploy():
    print()
    print("═" * 55)
    print("  MachineWhisperer — AgentCore Deployment")
    print("═" * 55)
    print()

    kwargs     = _aws_kwargs()
    sts        = boto3.client("sts",    **kwargs)
    iam        = boto3.client("iam",    **kwargs)
    s3_cli     = boto3.client("s3",     **kwargs)
    lambda_cli = boto3.client("lambda", **kwargs)

    account_id  = sts.get_caller_identity()["Account"]
    bucket_name = f"machinewhisperer-reports-{account_id}"
    role_name   = "machinewhisperer-agentcore-role"
    zip_key     = f"deployments/machinewhisperer-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"

    # ── Step 1: Create zip ────────────────────────────────────────
    project_dir = os.path.dirname(os.path.abspath(__file__))
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        zip_path = tmp.name
    create_zip(project_dir, zip_path)

    # ── Step 2: Upload zip to S3 ──────────────────────────────────
    print(f"[Deploy] Uploading to s3://{bucket_name}/{zip_key} ...")
    s3_cli.upload_file(zip_path, bucket_name, zip_key)
    print(f"[Deploy] Upload complete.")

    # ── Step 3: IAM role ──────────────────────────────────────────
    role_arn = get_or_create_role(iam, role_name)

    # ── Step 4: Environment variables ────────────────────────────
    env_vars = {
        "AWS_REGION":       REGION,
        "BEDROCK_MODEL_ID": os.environ.get(
            "BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
        "EMAIL_SENDER":     os.environ.get("EMAIL_SENDER",    ""),
        "EMAIL_PASSWORD":   os.environ.get("EMAIL_PASSWORD",  ""),
        "EMAIL_RECIPIENT":  os.environ.get("EMAIL_RECIPIENT", ""),
    }

    # ── Step 5: Create or update Lambda function ──────────────────
    func_name = AGENT_NAME
    try:
        lambda_cli.get_function(FunctionName=func_name)
        print(f"[Deploy] Updating existing function: {func_name}")
        lambda_cli.update_function_code(
            FunctionName=func_name,
            S3Bucket=bucket_name,
            S3Key=zip_key,
        )
        # Wait for code update to finish before updating config
        waiter = lambda_cli.get_waiter("function_updated")
        waiter.wait(FunctionName=func_name)
        lambda_cli.update_function_configuration(
            FunctionName=func_name,
            Handler=HANDLER,
            Runtime=RUNTIME,
            Role=role_arn,
            Timeout=TIMEOUT_SEC,
            MemorySize=MEMORY_MB,
            Environment={"Variables": env_vars},
        )
        print(f"[Deploy] Function updated.")
    except lambda_cli.exceptions.ResourceNotFoundException:
        print(f"[Deploy] Creating new Lambda function: {func_name}")
        lambda_cli.create_function(
            FunctionName=func_name,
            Runtime=RUNTIME,
            Role=role_arn,
            Handler=HANDLER,
            Code={"S3Bucket": bucket_name, "S3Key": zip_key},
            Timeout=TIMEOUT_SEC,
            MemorySize=MEMORY_MB,
            Environment={"Variables": env_vars},
            Description="MachineWhisperer Predictive Maintenance Agent",
        )
        print(f"[Deploy] Function created.")

    # ── Step 6: Wait for active ───────────────────────────────────
    print("[Deploy] Waiting for function to become active ...")
    waiter = lambda_cli.get_waiter("function_active")
    waiter.wait(FunctionName=func_name)

    # ── Step 7: Get function ARN ──────────────────────────────────
    resp       = lambda_cli.get_function(FunctionName=func_name)
    func_arn   = resp["Configuration"]["FunctionArn"]
    func_state = resp["Configuration"]["State"]

    # ── Step 8: Create / get Function URL ────────────────────────
    try:
        url_resp     = lambda_cli.create_function_url_config(
            FunctionName=func_name,
            AuthType="NONE",
        )
        function_url = url_resp["FunctionUrl"]
    except lambda_cli.exceptions.ResourceConflictException:
        url_resp     = lambda_cli.get_function_url_config(FunctionName=func_name)
        function_url = url_resp["FunctionUrl"]

    # Allow public invocation
    try:
        lambda_cli.add_permission(
            FunctionName=func_name,
            StatementId="FunctionURLAllowPublicAccess",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
    except lambda_cli.exceptions.ResourceConflictException:
        pass  # permission already exists

    # ── Cleanup ───────────────────────────────────────────────────
    os.unlink(zip_path)

    # ── Summary ───────────────────────────────────────────────────
    print()
    print("═" * 55)
    print("  ✅  DEPLOYMENT COMPLETE")
    print("═" * 55)
    print(f"  Function Name : {func_name}")
    print(f"  Function ARN  : {func_arn}")
    print(f"  State         : {func_state}")
    print(f"  Runtime URL   : {function_url}")
    print(f"  Region        : {REGION}")
    print()
    print("  Test with:")
    print(f'  curl -X POST "{function_url}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f"    -d '{{\"action\":\"health_check\"}}'")
    print()
    print("  Add to backend/.env:")
    print(f"  AGENTCORE_URL={function_url}")
    print("═" * 55)
    print()


if __name__ == "__main__":
    deploy()
