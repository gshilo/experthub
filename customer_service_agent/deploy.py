#!/usr/bin/env python3
"""Deployment script for Customer Service Agent to Vertex AI Agent Engine."""

import argparse
import os
import subprocess
import sys
from typing import Optional


def get_default_project() -> str:
    env_proj = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if env_proj:
        return env_proj.strip()
    try:
        res = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=False,
        )
        proj = res.stdout.strip()
        if res.returncode == 0 and proj and proj != "(unset)":
            return proj
    except Exception:
        pass
    return ""


def parse_args():
    parser = argparse.ArgumentParser(description="Deploy Customer Service Agent to Vertex AI Agent Engine.")
    parser.add_argument(
        "--project",
        default=get_default_project(),
        help="Google Cloud project ID.",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("GCP_REGION", "us-central1"),
        help="Google Cloud region for Agent Engine.",
    )
    parser.add_argument(
        "--display_name",
        default="customer_service_agent",
        help="Display name for the agent in Agent Engine.",
    )
    parser.add_argument(
        "--agent_engine_id",
        default=os.environ.get("AGENT_ENGINE_ID"),
        help="Optional existing Agent Engine ID to update.",
    )
    parser.add_argument(
        "--otel_to_cloud",
        action="store_true",
        default=True,
        help="Enable OpenTelemetry and telemetry reporting to Google Cloud Agent Engine (default: True).",
    )
    parser.add_argument(
        "--no-otel_to_cloud",
        dest="otel_to_cloud",
        action="store_false",
        help="Disable OpenTelemetry reporting to Google Cloud Agent Engine.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and stage agent without executing remote deployment.",
    )
    return parser.parse_args()


def find_existing_agent_engine_id(project: str, region: str, display_name: str) -> Optional[str]:
    try:
        import vertexai
        from vertexai.preview import reasoning_engines
        vertexai.init(project=project, location=region)
        for re in reasoning_engines.ReasoningEngine.list():
            if re.display_name == display_name:
                return re.resource_name.split("/")[-1]
    except Exception:
        pass
    return None


def main():
    args = parse_args()
    if not args.project:
        print("Error: Google Cloud project ID is required. Pass --project or set GOOGLE_CLOUD_PROJECT.", file=sys.stderr)
        return 1
    print("=" * 70)
    print(" Deploying Customer Service Agent to Vertex AI Agent Engine")
    print(f" Project:      {args.project}")
    print(f" Region:       {args.region}")
    print(f" Display Name: {args.display_name}")

    engine_id = args.agent_engine_id
    if not engine_id and not args.dry_run:
        engine_id = find_existing_agent_engine_id(args.project, args.region, args.display_name)
    if engine_id:
        print(f" Engine ID:    {engine_id} (Updating existing instance)")
    print("=" * 70)

    agent_dir = os.path.dirname(os.path.abspath(__file__))

    # Synchronize plugins.yaml with target project
    plugins_yaml_path = os.path.join(agent_dir, "plugins.yaml")
    if os.path.exists(plugins_yaml_path):
        with open(plugins_yaml_path, "r", encoding="utf-8") as f:
            content = f.read()
        import re
        updated = re.sub(r"^(\s*project_id:\s*).*$", f"\\g<1>{args.project}", content, flags=re.MULTILINE)
        if updated != content:
            with open(plugins_yaml_path, "w", encoding="utf-8") as f:
                f.write(updated)

    # Check for required ADK binary
    adk_bin = os.path.join(agent_dir, "..", ".venv", "bin", "adk")
    if not os.path.exists(adk_bin):
        adk_bin = "adk"

    cmd = [
        adk_bin,
        "deploy",
        "agent_engine",
        f"--project={args.project}",
        f"--region={args.region}",
        f"--display_name={args.display_name}",
    ]
    if args.otel_to_cloud:
        cmd.append("--otel_to_cloud")
    if engine_id:
        cmd.append(f"--agent_engine_id={engine_id}")
    cmd.append(agent_dir)

    print(f"Executing command: {' '.join(cmd)}")
    if args.dry_run:
        print("[DRY-RUN] Staging validated. Skipping actual remote API call.")
        return 0

    try:
        result = subprocess.run(cmd, check=True)
        print("Customer Service Agent deployed successfully to Vertex AI Agent Engine.")
        return result.returncode
    except subprocess.CalledProcessError as e:
        print(f"Deployment failed with exit code {e.returncode}.", file=sys.stderr)
        print("Note: Ensure the active GCP account has 'roles/aiplatform.admin' and 'roles/storage.admin'.", file=sys.stderr)
        return e.returncode
    except FileNotFoundError:
        print(f"Error: ADK CLI '{adk_bin}' not found.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
