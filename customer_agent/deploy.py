#!/usr/bin/env python3
"""Deployment script for Customer Simulator Agent to Vertex AI Agent Engine."""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional


def _ensure_venv() -> None:
    """Re-executes the script using the local .venv Python if google.adk or vertexai is missing."""
    try:
        import vertexai  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get("_EXPERTHUB_VENV_REEXEC") == "1":
        return

    repo_root = Path(__file__).resolve().parent.parent
    venv_python = repo_root / ".venv" / "bin" / "python3"
    if venv_python.is_file() and os.access(venv_python, os.X_OK):
        env = os.environ.copy()
        env["_EXPERTHUB_VENV_REEXEC"] = "1"
        os.execve(str(venv_python), [str(venv_python), *sys.argv], env)


_ensure_venv()


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
    parser = argparse.ArgumentParser(description="Deploy Customer Simulator Agent to Vertex AI Agent Engine.")
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
        default="customer_agent",
        help="Display name for the customer agent in Agent Engine.",
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


def _network_attachment_exists(project: str, region: str, attachment_name: str = "agent-engine-psc-na") -> bool:
    try:
        res = subprocess.run(
            [
                "gcloud",
                "compute",
                "network-attachments",
                "describe",
                attachment_name,
                f"--region={region}",
                f"--project={project}",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def find_existing_agent_engine_id(project: str, region: str, display_name: str) -> Optional[str]:
    try:
        import vertexai
        client = vertexai.Client(project=project, location=region)
        for re in client.agent_engines.list():
            if re.api_resource.display_name == display_name:
                return re.api_resource.name.split("/")[-1]
    except Exception:
        pass
    try:
        import vertexai
        from vertexai.preview import reasoning_engines
        vertexai.init(project=project, location=region)
        for re in reasoning_engines.ReasoningEngine.list():
            if re.display_name == display_name:
                return re.resource_name.split("/")[-1]
    except Exception:
        pass
    try:
        tok = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if tok:
            url = f"https://{region}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{region}/reasoningEngines"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for re_obj in data.get("reasoningEngines", []):
                    if re_obj.get("displayName") == display_name:
                        return re_obj.get("name", "").split("/")[-1]
    except Exception:
        pass
    return None


def main():
    args = parse_args()
    if not args.project:
        print("Error: Google Cloud project ID is required. Pass --project or set GOOGLE_CLOUD_PROJECT.", file=sys.stderr)
        return 1
    print("=" * 70)
    print(" Deploying Customer Simulator Agent to Vertex AI Agent Engine")
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

    # Synchronize .agent_engine_config.json target_project with args.project
    config_path = os.path.join(agent_dir, ".agent_engine_config.json")
    if os.path.exists(config_path) and not args.dry_run:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault(
                "env_vars",
                {
                    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
                    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
                },
            )
            if args.dry_run or _network_attachment_exists(args.project, args.region, "agent-engine-psc-na"):
                cfg["psc_interface_config"] = {
                    "network_attachment": "agent-engine-psc-na",
                    "dns_peering_configs": [
                        {
                            "domain": f"{args.region}.alloydb-psc.goog.",
                            "target_project": args.project,
                            "target_network": "default",
                        }
                    ],
                }
            else:
                print(
                    f"[INFO] Network attachment 'agent-engine-psc-na' not found in {args.project}/{args.region}; "
                    "omitting psc_interface_config from .agent_engine_config.json."
                )
                cfg.pop("psc_interface_config", None)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
                f.write("\n")
        except Exception as e:
            print(f"Warning: Could not update {config_path}: {e}", file=sys.stderr)

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
        print("Customer Simulator Agent deployed successfully to Vertex AI Agent Engine.")
        return result.returncode
    except subprocess.CalledProcessError as e:
        print(f"Deployment failed with exit code {e.returncode}.", file=sys.stderr)
        return e.returncode
    except FileNotFoundError:
        print(f"Error: ADK CLI '{adk_bin}' not found.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
