"""Unit tests for Auditor Agent GitHub SSH dynamic context synchronization."""

from __future__ import annotations

import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


def _ensure_google_stubs() -> None:
    """Installs lightweight google.* stubs when GCP/ADK packages are not installed in the test venv."""
    try:
        import google.adk.agents  # noqa: F401
        import google.cloud.secretmanager  # noqa: F401
        return
    except ImportError:
        pass

    google_mod = sys.modules.setdefault("google", types.ModuleType("google"))
    auth_mod = types.ModuleType("google.auth")
    auth_mod.default = lambda: (None, "test-project")
    google_mod.auth = auth_mod
    sys.modules["google.auth"] = auth_mod

    adk_mod = types.ModuleType("google.adk")
    adk_agents_mod = types.ModuleType("google.adk.agents")

    class _DummyAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    adk_agents_mod.Agent = _DummyAgent

    adk_apps_mod = types.ModuleType("google.adk.apps")

    class _DummyApp:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    adk_apps_mod.App = _DummyApp

    adk_mod.agents = adk_agents_mod
    adk_mod.apps = adk_apps_mod
    google_mod.adk = adk_mod
    sys.modules["google.adk"] = adk_mod
    sys.modules["google.adk.agents"] = adk_agents_mod
    sys.modules["google.adk.apps"] = adk_apps_mod

    cloud_mod = types.ModuleType("google.cloud")
    bq_mod = types.ModuleType("google.cloud.bigquery")
    bq_mod.Client = mock.MagicMock
    bq_mod.QueryJobConfig = mock.MagicMock

    sm_mod = types.ModuleType("google.cloud.secretmanager")
    sm_mod.SecretManagerServiceClient = mock.MagicMock

    cloud_mod.bigquery = bq_mod
    cloud_mod.secretmanager = sm_mod
    google_mod.cloud = cloud_mod
    sys.modules["google.cloud"] = cloud_mod
    sys.modules["google.cloud.bigquery"] = bq_mod
    sys.modules["google.cloud.secretmanager"] = sm_mod


_ensure_google_stubs()
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

auditor = importlib.import_module("auditor_agent.agent")

FAKE_DEPLOY_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)

EXISTING_OKF_MAIN = """---
type: Operational Rule
title: Existing Rules
description: Existing dynamic rules.
tags: [customer-service]
status: stable
generated: { by: auditor_agent/gemini-3.8-flash, at: 2026-01-01T00:00:00Z }
verified: { by: process:auditor-agent, at: 2026-01-01T00:00:00Z }
---

# Definition
Existing operational baseline.

# Policy
1. [Based on: Customer Feedback] Offer expedited warranty replacement for verified dead-on-arrival OLED displays.

# Token Optimization Directive
- [Based on: Agent Metrics] Keep tracking updates under two concise sentences.
"""

EXISTING_OKF_NEW_VERSION = """---
type: Operational Rule
title: Existing New Version Rules
description: Existing dynamic rules on new_version.
tags: [customer-service]
status: stable
generated: { by: auditor_agent/gemini-3.8-flash, at: 2026-01-02T00:00:00Z }
verified: { by: process:auditor-agent, at: 2026-01-02T00:00:00Z }
---

# Definition
Pending review rules on new_version.

# Policy
1. [Based on: Customer Feedback] Waive pickup fees for oversized refrigerator exchanges caused by shipping damage.

# Token Optimization Directive
- [Based on: Agent Metrics] Consolidate multi-item refund confirmations into a single bulleted summary.
"""


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test Runner"
    env["GIT_AUTHOR_EMAIL"] = "test@example.local"
    env["GIT_COMMITTER_NAME"] = "Test Runner"
    env["GIT_COMMITTER_EMAIL"] = "test@example.local"
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


class TestAuditorGitHubSync(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.mkdtemp(prefix="test_auditor_git_")
        self.bare_repo = os.path.join(self.workspace, "remote.git")
        os.makedirs(self.bare_repo)
        _git(self.bare_repo, "init", "--bare", "-b", "main")

        self.sample_analysis = {
            "average_rating": 3.4,
            "detected_issues": ["Delayed technician scheduling for induction cooktops"],
            "candidate_policies": [
                "Schedule priority technician visits within 24 hours for induction cooktop ignition failures."
            ],
            "executed_queries": [],
        }
        self.sample_token_opt = {
            "token_recommendations": ["Avoid repeating customer order numbers in every turn"],
            "token_directives": [
                "Reference the order number once per session and omit repetitive greeting templates."
            ],
            "estimated_savings_percent": "38%",
            "telemetry_issues": ["Redundant greeting overhead across turns"],
            "total_errors": 0,
            "suboptimal_issues": [],
            "error_guardrails": [],
            "quality_policies": [],
            "candidate_policies": [],
            "executed_queries": [],
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def _seed_remote(
        self,
        main_files: dict[str, str] | None = None,
        new_version_files: dict[str, str] | None = None,
    ) -> None:
        seed_dir = os.path.join(self.workspace, "seed")
        os.makedirs(seed_dir)
        _git(seed_dir, "init", "-b", "main")
        _git(seed_dir, "remote", "add", "origin", self.bare_repo)

        if main_files:
            for rel_path, content in main_files.items():
                full_path = os.path.join(seed_dir, rel_path)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
            _git(seed_dir, "add", ".")
            _git(seed_dir, "commit", "-m", "seed main")
            _git(seed_dir, "push", "-u", "origin", "main")

        if new_version_files:
            _git(seed_dir, "checkout", "-b", "new_version")
            for rel_path, content in new_version_files.items():
                full_path = os.path.join(seed_dir, rel_path)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
            _git(seed_dir, "add", ".")
            _git(seed_dir, "commit", "-m", "seed new_version")
            _git(seed_dir, "push", "-u", "origin", "new_version")

    def test_push_to_existing_new_version_merges_rules(self) -> None:
        self._seed_remote(
            main_files={"dynamic_context.md": EXISTING_OKF_MAIN},
            new_version_files={"dynamic_context.md": EXISTING_OKF_NEW_VERSION},
        )

        with mock.patch.object(auditor, "get_secret", return_value=FAKE_DEPLOY_KEY):
            ok, msg, content, branch = auditor.sync_okf_rules_to_github(
                self.sample_analysis,
                self.sample_token_opt,
                repo_url=self.bare_repo,
            )

        self.assertTrue(ok, msg)
        self.assertEqual(branch, "new_version")
        self.assertIn("new_version", msg)
        # Existing rule on new_version is retained and new rule is merged
        self.assertIn("Waive pickup fees for oversized refrigerator exchanges", content)
        self.assertIn("induction cooktop ignition failures", content)
        self.assertIn("Reference the order number once per session", content)

        # Verify remote new_version has merged content and main is untouched
        remote_nv = _git(self.bare_repo, "show", "refs/heads/new_version:dynamic_context.md").stdout
        remote_main = _git(self.bare_repo, "show", "refs/heads/main:dynamic_context.md").stdout
        self.assertIn("Waive pickup fees for oversized refrigerator exchanges", remote_nv)
        self.assertIn("induction cooktop ignition failures", remote_nv)
        self.assertNotIn("induction cooktop ignition failures", remote_main)

    def test_creates_new_version_from_main_when_missing(self) -> None:
        self._seed_remote(main_files={"dynamic_context.md": EXISTING_OKF_MAIN})

        with mock.patch.object(auditor, "get_secret", return_value=FAKE_DEPLOY_KEY):
            ok, msg, content, branch = auditor.sync_okf_rules_to_github(
                self.sample_analysis,
                self.sample_token_opt,
                repo_url=self.bare_repo,
            )

        self.assertTrue(ok, msg)
        self.assertEqual(branch, "new_version")
        # Inherits main's existing rule and appends the newly discovered rule
        self.assertIn("expedited warranty replacement for verified dead-on-arrival OLED displays", content)
        self.assertIn("induction cooktop ignition failures", content)

        # Remote new_version branch was created and main remains unchanged
        branches = _git(self.bare_repo, "branch").stdout
        self.assertIn("new_version", branches)
        remote_nv = _git(self.bare_repo, "show", "refs/heads/new_version:dynamic_context.md").stdout
        remote_main = _git(self.bare_repo, "show", "refs/heads/main:dynamic_context.md").stdout
        self.assertIn("induction cooktop ignition failures", remote_nv)
        self.assertNotIn("induction cooktop ignition failures", remote_main)

    def test_missing_or_placeholder_deploy_key_returns_error(self) -> None:
        for bad_key in ("", "PLACEHOLDER_DEPLOY_KEY", "YOUR_KEY_HERE", "not-a-pem-key"):
            with self.subTest(bad_key=bad_key):
                with mock.patch.object(auditor, "get_secret", return_value=bad_key):
                    with mock.patch.object(auditor.subprocess, "run") as mock_run:
                        ok, msg, content, branch = auditor.sync_okf_rules_to_github(
                            self.sample_analysis,
                            self.sample_token_opt,
                            repo_url=self.bare_repo,
                        )
                self.assertFalse(ok)
                self.assertEqual(branch, "new_version")
                self.assertIn("deploy key", msg.lower())
                self.assertIn("# Policy", content)
                mock_run.assert_not_called()

    def test_temp_key_file_permissions_and_cleanup_on_success(self) -> None:
        self._seed_remote(main_files={"dynamic_context.md": EXISTING_OKF_MAIN})

        created_dirs: list[str] = []
        observed_key_modes: list[int] = []
        observed_ssh_cmds: list[str] = []
        real_mkdtemp = tempfile.mkdtemp
        real_run = subprocess.run

        def tracking_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created_dirs.append(d)
            return d

        def tracking_run(cmd, *args, **kwargs):
            env = kwargs.get("env") or {}
            if "GIT_SSH_COMMAND" in env:
                observed_ssh_cmds.append(env["GIT_SSH_COMMAND"])
            for d in created_dirs:
                kp = os.path.join(d, "id_ed25519")
                if os.path.exists(kp):
                    observed_key_modes.append(stat.S_IMODE(os.stat(kp).st_mode))
            return real_run(cmd, *args, **kwargs)

        with mock.patch.object(auditor.tempfile, "mkdtemp", side_effect=tracking_mkdtemp), \
             mock.patch.object(auditor.subprocess, "run", side_effect=tracking_run), \
             mock.patch.object(auditor, "get_secret", return_value=FAKE_DEPLOY_KEY):
            ok, msg, _, _ = auditor.sync_okf_rules_to_github(
                self.sample_analysis,
                self.sample_token_opt,
                repo_url=self.bare_repo,
            )

        self.assertTrue(ok, msg)
        self.assertTrue(created_dirs)
        self.assertTrue(observed_key_modes)
        self.assertTrue(all(m == 0o600 for m in observed_key_modes), f"Unexpected key modes: {observed_key_modes}")
        self.assertTrue(any("StrictHostKeyChecking=accept-new" in c and "IdentitiesOnly=yes" in c for c in observed_ssh_cmds))
        for d in created_dirs:
            self.assertFalse(os.path.exists(d), f"Temp dir was not cleaned up: {d}")
            self.assertFalse(os.path.exists(os.path.join(d, "id_ed25519")))

    def test_temp_key_file_cleanup_on_failure(self) -> None:
        created_dirs: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created_dirs.append(d)
            return d

        failed_clone = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="git@github.com: Permission denied (publickey).",
        )

        with mock.patch.object(auditor.tempfile, "mkdtemp", side_effect=tracking_mkdtemp), \
             mock.patch.object(auditor.subprocess, "run", return_value=failed_clone), \
             mock.patch.object(auditor, "get_secret", return_value=FAKE_DEPLOY_KEY):
            ok, msg, _, branch = auditor.sync_okf_rules_to_github(
                self.sample_analysis,
                self.sample_token_opt,
            )

        self.assertFalse(ok)
        self.assertEqual(branch, "new_version")
        self.assertIn("Permission denied", msg)
        self.assertTrue(created_dirs)
        for d in created_dirs:
            self.assertFalse(os.path.exists(d), f"Temp dir leaked on failure: {d}")
            self.assertFalse(os.path.exists(os.path.join(d, "id_ed25519")))

    def test_run_audit_pipeline_returns_clean_github_report(self) -> None:
        with mock.patch.object(auditor, "query_customer_feedback_analysis_bq", return_value=self.sample_analysis), \
             mock.patch.object(auditor, "query_agent_telemetry_analysis_bq", return_value=self.sample_token_opt), \
             mock.patch.object(
                 auditor,
                 "sync_okf_rules_to_github",
                 return_value=(True, "Pushed to new_version (@ abc1234)", "# Policy\n1. Test", "new_version"),
             ):
            report = auditor.run_audit_pipeline()

        self.assertEqual(report["status"], "COMPLETED")
        self.assertTrue(report["github_commit_success"])
        self.assertEqual(report["github_commit_status"], "Pushed to new_version (@ abc1234)")
        self.assertEqual(report["target_branch"], "new_version")
        self.assertEqual(report["repo"], "gshilo/experthub_context")
        self.assertEqual(report["workflow_state"], "AWAITING_HUMAN_REVIEW")
        self.assertEqual(report["okf_file"], "dynamic_context.md")
        self.assertNotIn("target_bucket", report)
        self.assertNotIn("object_path", report)
        self.assertNotIn("storage_sync_status", report)
        self.assertNotIn("ACTIVE_IN_GCS", str(report))
        self.assertNotIn("gs://", str(report))


if __name__ == "__main__":
    unittest.main()
