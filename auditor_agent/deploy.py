#!/usr/bin/env python3
"""Deployment script for Auditor Agent to Vertex AI Agent Engine."""

import argparse
import os
import subprocess
import sys
from typing import Optional


def parse_args():
    parser = argparse.ArgumentParser(description="Deploy Auditor Agent to Vertex AI Agent Engine.")
    parser.add_argument(
        "--project",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT", "experthub-510907"),
        help="Google Cloud project ID.",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("GCP_REGION", "us-central1"),
        help="Google Cloud region for Agent Engine.",
    )
    parser.add_argument(
        "--display_name",
        default="auditor_agent",
        help="Display name for the auditor agent in Agent Engine.",
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
    print("=" * 70)
    print(" Deploying Auditor Agent to Vertex AI Agent Engine")
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

    config_path = os.path.join(agent_dir, ".agent_engine_config.json")
    import json
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "env_vars": {
                    "GOOGLE_GENAI_USE_VERTEXAI": "true",
                    "VERTEX_AI_LOCATION": "global",
                    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
                    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
                }
            },
            f,
            indent=2,
        )

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
        print("Auditor Agent deployed successfully to Vertex AI Agent Engine.")
        return result.returncode
    except subprocess.CalledProcessError as e:
        print(f"Deployment failed with exit code {e.returncode}.", file=sys.stderr)
        return e.returncode
    except FileNotFoundError:
        print(f"Error: ADK CLI '{adk_bin}' not found.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
