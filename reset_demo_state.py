#!/usr/bin/env python3
"""
reset_demo_state.py

Resets the state of the system for a fresh demo run:
1. Truncates BigQuery tables:
   - demo.customer_ratings
   - agent_telemetry.agent_events
2. In git repository https://github.com/gshilo/experthub_context.git:
   - Deletes everything from branch `new_version`
   - Merges `new_version` into `main`
   - Pushes both branches to `origin` (leaving both clean/empty)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple


def _ensure_venv() -> None:
    """Re-executes the script using the local .venv Python if google-cloud-bigquery is missing."""
    try:
        import google.cloud.bigquery  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get("_EXPERTHUB_VENV_REEXEC") == "1":
        return

    script_dir = Path(__file__).resolve().parent
    venv_python = script_dir / ".venv" / "bin" / "python3"
    if venv_python.is_file() and os.access(venv_python, os.X_OK):
        env = os.environ.copy()
        env["_EXPERTHUB_VENV_REEXEC"] = "1"
        os.execve(str(venv_python), [str(venv_python), *sys.argv], env)


_ensure_venv()


def get_default_project() -> str:
    """Detects GCP project from env or gcloud config, defaulting to experthub-510907."""
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
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "experthub-510907"


def get_deploy_key(project_id: str, secret_id: str = "github-deploy-key") -> Optional[str]:
    """Retrieves deploy SSH key from Secret Manager or environment variables."""
    # 1. Environment variable fallback
    env_key = os.environ.get("GITHUB_DEPLOY_KEY") or os.environ.get("SSH_DEPLOY_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # 2. Secret Manager
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8").strip()
    except Exception as e:
        print(f"[WARN] Could not retrieve secret '{secret_id}' from Secret Manager: {e}", file=sys.stderr)

    # 3. gcloud CLI fallback
    try:
        res = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_id}", f"--project={project_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    return None


def _truncate_bigquery_via_cli(project_id: str, tables: list, dry_run: bool = False) -> bool:
    """Fallback to truncate BigQuery tables using the `bq` CLI."""
    if not shutil.which("bq"):
        print("[ERROR] Neither google-cloud-bigquery nor `bq` CLI is available.", file=sys.stderr)
        return False

    success = True
    for table_name in tables:
        full_table_id = f"{project_id}.{table_name}"
        bq_table_spec = f"{project_id}:{table_name}"
        try:
            show_res = subprocess.run(
                ["bq", "show", "--format=json", bq_table_spec],
                capture_output=True,
                text=True,
                check=False,
            )
            if show_res.returncode != 0:
                err = show_res.stderr.strip() or show_res.stdout.strip()
                raise RuntimeError(f"bq show failed: {err}")
            table_info = json.loads(show_res.stdout)
            current_rows = table_info.get("numRows", "unknown")
            print(f"[*] Table '{full_table_id}': current row count = {current_rows}")

            if dry_run:
                print(f"    [DRY-RUN] Would execute: TRUNCATE TABLE `{full_table_id}`")
                continue

            query = f"TRUNCATE TABLE `{full_table_id}`"
            q_res = subprocess.run(
                ["bq", f"--project_id={project_id}", "query", "--use_legacy_sql=false", query],
                capture_output=True,
                text=True,
                check=False,
            )
            if q_res.returncode != 0:
                err = q_res.stderr.strip() or q_res.stdout.strip()
                raise RuntimeError(f"bq query failed: {err}")

            print("    [OK] Truncated successfully via bq CLI.")
        except Exception as e:
            print(f"    [ERROR] Failed to truncate table '{full_table_id}': {e}", file=sys.stderr)
            success = False

    return success


def truncate_bigquery_tables(project_id: str, dry_run: bool = False) -> bool:
    """Truncates demo.customer_ratings and agent_telemetry.agent_events."""
    print("\n--- [1/2] BigQuery Table Truncation ---")
    tables = [
        "demo.customer_ratings",
        "agent_telemetry.agent_events",
    ]

    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project_id)
    except ImportError:
        print("[WARN] google-cloud-bigquery package not installed; falling back to `bq` CLI...", file=sys.stderr)
        return _truncate_bigquery_via_cli(project_id, tables, dry_run=dry_run)
    except Exception as e:
        print(f"[ERROR] Failed to initialize BigQuery client: {e}", file=sys.stderr)
        return False

    success = True
    for table_name in tables:
        full_table_id = f"{project_id}.{table_name}"
        try:
            table_ref = client.get_table(full_table_id)
            current_rows = table_ref.num_rows
            print(f"[*] Table '{full_table_id}': current row count = {current_rows}")

            if dry_run:
                print(f"    [DRY-RUN] Would execute: TRUNCATE TABLE `{full_table_id}`")
                continue

            query = f"TRUNCATE TABLE `{full_table_id}`"
            job = client.query(query)
            job.result()  # Wait for query to complete

            updated_table = client.get_table(full_table_id)
            print(f"    [OK] Truncated successfully. New row count = {updated_table.num_rows}")
        except Exception as e:
            print(f"    [ERROR] Failed to truncate table '{full_table_id}': {e}", file=sys.stderr)
            success = False

    return success


def run_git_command(cmd: list, cwd: str, env: dict, desc: str) -> subprocess.CompletedProcess:
    """Runs a git command with error handling."""
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        err_msg = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"Git failed during '{desc}': {err_msg}")
    return res


def reset_git_repository(
    project_id: str,
    repo_url_ssh: str = "git@github.com:gshilo/experthub_context.git",
    deploy_key_override: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """
    Deletes all files from branch new_version and merges it into main,
    then pushes both branches to origin.
    """
    print("\n--- [2/2] Git Repository State Reset ---")
    print(f"[*] Target repository: {repo_url_ssh}")

    deploy_key = deploy_key_override or get_deploy_key(project_id)
    if not deploy_key:
        print("[ERROR] Could not find SSH deploy key in Secret Manager ('github-deploy-key') or environment.", file=sys.stderr)
        return False

    # Setup temporary key file
    key_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
    try:
        key_file.write(deploy_key)
        if not deploy_key.endswith("\n"):
            key_file.write("\n")
        key_file.close()
        os.chmod(key_file.name, 0o600)

        git_env = os.environ.copy()
        git_env["GIT_SSH_COMMAND"] = (
            f"ssh -i {key_file.name} "
            "-o IdentitiesOnly=yes "
            "-o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null "
            "-o LogLevel=ERROR"
        )
        git_env["GIT_AUTHOR_NAME"] = "ExpertHub Reset Tool"
        git_env["GIT_AUTHOR_EMAIL"] = "reset-demo@experthub.local"
        git_env["GIT_COMMITTER_NAME"] = "ExpertHub Reset Tool"
        git_env["GIT_COMMITTER_EMAIL"] = "reset-demo@experthub.local"

        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"[*] Cloning repository into temporary directory...")
            run_git_command(
                ["git", "clone", repo_url_ssh, temp_dir],
                cwd=".",
                env=git_env,
                desc="git clone",
            )

            # Fetch all branches
            run_git_command(["git", "fetch", "origin"], cwd=temp_dir, env=git_env, desc="git fetch")

            # Check if remote new_version exists
            ls_remote = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", "new_version"],
                cwd=temp_dir,
                env=git_env,
                capture_output=True,
                text=True,
            )
            has_remote_nv = bool(ls_remote.stdout.strip())

            # Switch to new_version branch
            if has_remote_nv:
                print("[*] Checking out branch 'new_version' from origin/new_version...")
                run_git_command(
                    ["git", "checkout", "-B", "new_version", "origin/new_version"],
                    cwd=temp_dir,
                    env=git_env,
                    desc="checkout new_version",
                )
            else:
                print("[*] Remote 'new_version' does not exist yet. Creating branch 'new_version' from origin/main...")
                run_git_command(
                    ["git", "checkout", "-B", "new_version", "origin/main"],
                    cwd=temp_dir,
                    env=git_env,
                    desc="checkout new_version from main",
                )

            # Inspect files on new_version
            tracked_files = subprocess.run(
                ["git", "ls-files"],
                cwd=temp_dir,
                env=git_env,
                capture_output=True,
                text=True,
            ).stdout.strip().splitlines()

            print(f"[*] Tracked files currently on 'new_version': {len(tracked_files)}")
            for f in tracked_files:
                print(f"    - {f}")

            if dry_run:
                print("[DRY-RUN] Would remove all tracked files from 'new_version', commit, merge to 'main', and push both branches.")
                return True

            if tracked_files:
                # Remove all files
                print("[*] Removing all tracked files on 'new_version'...")
                run_git_command(["git", "rm", "-rf", "."], cwd=temp_dir, env=git_env, desc="git rm -rf .")
                run_git_command(
                    ["git", "commit", "-m", "reset: delete all files from new_version for fresh demo"],
                    cwd=temp_dir,
                    env=git_env,
                    desc="commit deletion on new_version",
                )
                print("    [OK] Committed deletion of all files on 'new_version'.")
            else:
                print("[*] Branch 'new_version' is already empty.")

            # Checkout main
            print("[*] Checking out branch 'main' from origin/main...")
            run_git_command(
                ["git", "checkout", "-B", "main", "origin/main"],
                cwd=temp_dir,
                env=git_env,
                desc="checkout main",
            )

            # Merge new_version into main
            print("[*] Merging 'new_version' into 'main'...")
            run_git_command(
                ["git", "merge", "new_version", "-m", "reset: merge empty new_version into main for fresh demo"],
                cwd=temp_dir,
                env=git_env,
                desc="merge new_version into main",
            )
            print("    [OK] Merged 'new_version' into 'main'.")

            # Push both branches to origin
            print("[*] Pushing 'main' to origin...")
            run_git_command(
                ["git", "push", "origin", "main"],
                cwd=temp_dir,
                env=git_env,
                desc="push origin main",
            )
            print("    [OK] Pushed 'main' to origin.")

            print("[*] Pushing 'new_version' to origin...")
            run_git_command(
                ["git", "push", "origin", "new_version"],
                cwd=temp_dir,
                env=git_env,
                desc="push origin new_version",
            )
            print("    [OK] Pushed 'new_version' to origin.")

            print("[OK] Git repository reset completed successfully.")
            return True

    except Exception as e:
        print(f"[ERROR] Git reset failed: {e}", file=sys.stderr)
        return False
    finally:
        if os.path.exists(key_file.name):
            try:
                os.remove(key_file.name)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="Reset ExpertHub demo state (Truncate BigQuery tables and/or empty Git repository context branches)."
    )
    parser.add_argument(
        "--project",
        default=get_default_project(),
        help="Google Cloud Project ID (default: detected or experthub-510907)",
    )
    parser.add_argument(
        "--key-file",
        help="Optional path to private SSH deploy key file. If omitted, fetched automatically from Secret Manager.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Bypass interactive confirmation prompt and proceed immediately.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all operations without modifying BigQuery or pushing Git commits.",
    )
    parser.add_argument(
        "--bq-only",
        "--only-bq",
        action="store_true",
        dest="bq_only",
        help="Reset ONLY BigQuery tables (demo.customer_ratings and agent_telemetry.agent_events).",
    )
    parser.add_argument(
        "--git-only",
        "--only-git",
        action="store_true",
        dest="git_only",
        help="Reset ONLY the Git repository context branches.",
    )

    args = parser.parse_args()

    # Determine scope: bq, git, or both
    if args.bq_only and args.git_only:
        reset_bq = True
        reset_git = True
    elif args.bq_only:
        reset_bq = True
        reset_git = False
    elif args.git_only:
        reset_bq = False
        reset_git = True
    else:
        # Default: reset both
        reset_bq = True
        reset_git = True

    print("=====================================================")
    print("        EXPERTHUB DEMO STATE RESET UTILITY           ")
    print("=====================================================")
    print(f"Project ID: {args.project}")
    print(f"Dry Run   : {args.dry_run}")
    print(f"Scope     : BigQuery={'YES' if reset_bq else 'SKIPPED'}, Git={'YES' if reset_git else 'SKIPPED'}")
    print("Actions to be performed:")
    if reset_bq:
        print("  - Truncate BigQuery: demo.customer_ratings")
        print("  - Truncate BigQuery: agent_telemetry.agent_events")
    if reset_git:
        print("  - GitHub Repo https://github.com/gshilo/experthub_context.git:")
        print("     - Delete all files from branch 'new_version' & commit")
        print("     - Merge 'new_version' into 'main'")
        print("     - Push both 'new_version' and 'main' to origin")
    print("=====================================================")

    # Interactive confirmation prompt
    if not args.yes and not args.dry_run:
        try:
            confirm = input("\nAre you sure you want to proceed with resetting the demo state? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print("[INFO] Reset aborted by user.")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            print("\n[INFO] Reset aborted.")
            sys.exit(0)

    deploy_key_override = None
    if args.key_file:
        with open(args.key_file, "r") as f:
            deploy_key_override = f.read().strip()

    bq_ok = True
    git_ok = True

    if reset_bq:
        bq_ok = truncate_bigquery_tables(args.project, dry_run=args.dry_run)
    else:
        print("\n--- [1/2] BigQuery Table Truncation: SKIPPED ---")

    if reset_git:
        git_ok = reset_git_repository(
            project_id=args.project,
            deploy_key_override=deploy_key_override,
            dry_run=args.dry_run,
        )
    else:
        print("\n--- [2/2] Git Repository State Reset: SKIPPED ---")

    print("\n=====================================================")
    if bq_ok and git_ok:
        status_msg = "DRY RUN COMPLETE - NO CHANGES MADE" if args.dry_run else "DEMO STATE RESET COMPLETED SUCCESSFULLY"
        print(f"  [SUCCESS] {status_msg}")
        if reset_bq:
            print("            BigQuery Truncation : SUCCESS")
        if reset_git:
            print("            Git Repository Reset: SUCCESS")
        print("=====================================================")
        sys.exit(0)
    else:
        print("  [FAILURE] One or more reset operations failed.")
        if reset_bq:
            print(f"            BigQuery Truncation : {'SUCCESS' if bq_ok else 'FAILED'}")
        if reset_git:
            print(f"            Git Repository Reset: {'SUCCESS' if git_ok else 'FAILED'}")
        print("=====================================================")
        sys.exit(1)


if __name__ == "__main__":
    main()

