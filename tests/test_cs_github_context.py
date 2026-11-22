"""Unit tests for Customer Service Agent GitHub SSH dynamic context loading."""

from __future__ import annotations

import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock


def _ensure_google_stubs() -> None:
    """Install lightweight stubs for optional Google SDK packages if not installed locally."""
    try:
        import google.adk  # noqa: F401
        import google.cloud.secretmanager  # noqa: F401
        return
    except ImportError:
        pass

    def _pkg(name: str) -> types.ModuleType:
        if name in sys.modules:
            return sys.modules[name]
        mod = types.ModuleType(name)
        mod.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = mod
        if "." in name:
            parent_name, attr = name.rsplit(".", 1)
            parent = _pkg(parent_name)
            setattr(parent, attr, mod)
        return mod

    # google.auth
    g_auth = _pkg("google.auth")
    g_auth.default = lambda: (None, "test-project")  # type: ignore[attr-defined]

    # google.genai & google.genai.types
    g_genai = _pkg("google.genai")
    g_genai_types = _pkg("google.genai.types")

    class _DummyConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    g_genai_types.GenerateContentConfig = _DummyConfig  # type: ignore[attr-defined]
    g_genai_types.ThinkingConfig = _DummyConfig  # type: ignore[attr-defined]
    g_genai.types = g_genai_types  # type: ignore[attr-defined]

    # google.adk
    g_adk_agents = _pkg("google.adk.agents")
    g_adk_cb = _pkg("google.adk.agents.callback_context")
    g_adk_apps = _pkg("google.adk.apps")
    g_adk_bq_plugin = _pkg("google.adk.plugins.bigquery_agent_analytics_plugin")

    class _DummyAgent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _DummyApp:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _DummyCallbackContext:
        pass

    class _DummyBQConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _DummyBQPlugin:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    g_adk_agents.Agent = _DummyAgent  # type: ignore[attr-defined]
    g_adk_cb.CallbackContext = _DummyCallbackContext  # type: ignore[attr-defined]
    g_adk_apps.App = _DummyApp  # type: ignore[attr-defined]
    g_adk_bq_plugin.BigQueryLoggerConfig = _DummyBQConfig  # type: ignore[attr-defined]
    g_adk_bq_plugin.BigQueryAgentAnalyticsPlugin = _DummyBQPlugin  # type: ignore[attr-defined]

    # google.cloud.bigquery & google.cloud.secretmanager
    g_bq = _pkg("google.cloud.bigquery")

    class _DummyBQClient:
        def __init__(self, **kwargs):
            pass

        def get_dataset(self, ref):
            return ref

    g_bq.Client = _DummyBQClient  # type: ignore[attr-defined]
    g_bq.DatasetReference = lambda p, d: (p, d)  # type: ignore[attr-defined]
    g_bq.Dataset = lambda ref: types.SimpleNamespace(ref=ref)  # type: ignore[attr-defined]

    g_sm = _pkg("google.cloud.secretmanager")

    class _DummySMClient:
        def access_secret_version(self, request):
            raise RuntimeError("Mocked Secret Manager not configured")

    g_sm.SecretManagerServiceClient = _DummySMClient  # type: ignore[attr-defined]


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_ensure_google_stubs()

# Avoid real GCP API calls during module import
with mock.patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-project", "GEMINI_API_KEY": "test-key-123"}):
    cs_agent = importlib.import_module("customer_service_agent.agent")


FAKE_PRIVATE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def _run_git(args: list[str], cwd: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test Bot",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test Bot",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _create_bare_repo_with_branches(
    main_files: dict[str, str],
    new_version_files: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Creates a local bare git repo with 'main' and optional 'new_version' branches."""
    base_dir = tempfile.mkdtemp(prefix="test_cs_okf_repo_")
    bare_dir = os.path.join(base_dir, "remote.git")
    work_dir = os.path.join(base_dir, "work")
    os.makedirs(work_dir)

    _run_git(["init", "--bare", "--initial-branch=main", bare_dir], cwd=base_dir)
    _run_git(["init", "--initial-branch=main"], cwd=work_dir)
    _run_git(["remote", "add", "origin", bare_dir], cwd=work_dir)

    # Always commit a README so 'main' exists even when dynamic_context.md is absent
    with open(os.path.join(work_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Context repo\n")
    for fname, body in main_files.items():
        with open(os.path.join(work_dir, fname), "w", encoding="utf-8") as f:
            f.write(body)
    _run_git(["add", "."], cwd=work_dir)
    _run_git(["commit", "-m", "initial main commit"], cwd=work_dir)
    _run_git(["push", "-u", "origin", "main"], cwd=work_dir)

    if new_version_files is not None:
        _run_git(["checkout", "-b", "new_version"], cwd=work_dir)
        for fname, body in new_version_files.items():
            with open(os.path.join(work_dir, fname), "w", encoding="utf-8") as f:
                f.write(body)
        _run_git(["add", "."], cwd=work_dir)
        _run_git(["commit", "-m", "proposal on new_version"], cwd=work_dir)
        _run_git(["push", "-u", "origin", "new_version"], cwd=work_dir)

    return base_dir, bare_dir


class TestCustomerServiceGitHubContext(unittest.TestCase):
    def setUp(self) -> None:
        cs_agent._SECRET_CACHE.clear()
        with cs_agent._OKF_CACHE_LOCK:
            cs_agent._OKF_CACHE = ("", 0.0)
            cs_agent._OKF_CACHE_INITIALIZED = False
            cs_agent._OKF_CACHE_REFRESHING = False
        self._cleanup_dirs: list[str] = []

    def tearDown(self) -> None:
        for d in self._cleanup_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_gcs_or_pat_scaffolding_remains(self) -> None:
        """Verify GCS bucket and github-pat/PyGithub artifacts are removed."""
        self.assertFalse(hasattr(cs_agent, "OKF_BUCKET_NAME"))
        self.assertFalse(hasattr(cs_agent, "OKF_BUCKET_LOCATION"))
        self.assertFalse(hasattr(cs_agent, "ensure_okf_bucket"))
        self.assertFalse(hasattr(cs_agent, "SECRET_NAME"))
        self.assertEqual(cs_agent.DEPLOY_KEY_SECRET_NAME, "github-deploy-key")
        self.assertEqual(cs_agent.MAIN_BRANCH, "main")

    def test_reads_dynamic_context_strictly_from_main_ignoring_new_version(self) -> None:
        """Reads dynamic_context.md from 'main' and ignores unmerged changes on 'new_version'."""
        main_rules = "# OKF Rules (MAIN)\n- Rule 1: Waive restocking fee for verified defects.\n"
        new_version_rules = "# OKF Rules (NEW_VERSION)\n- Rule 99: Unreviewed draft rule.\n"
        base_dir, bare_dir = _create_bare_repo_with_branches(
            main_files={"dynamic_context.md": main_rules},
            new_version_files={"dynamic_context.md": new_version_rules},
        )
        self._cleanup_dirs.append(base_dir)

        content = cs_agent.fetch_okf_via_git_ssh(
            FAKE_PRIVATE_KEY,
            repo_name="gshilo/experthub_context",
            branch="main",
            repo_url=bare_dir,
        )
        self.assertEqual(content, main_rules)
        self.assertNotIn("Unreviewed draft rule", content)

    def test_fallback_to_dynamic_content_md_on_main(self) -> None:
        """Falls back to dynamic_content.md if dynamic_context.md is absent on main."""
        fallback_rules = "# Fallback OKF\n- Rule F1: Immediate RMA.\n"
        base_dir, bare_dir = _create_bare_repo_with_branches(
            main_files={"dynamic_content.md": fallback_rules},
        )
        self._cleanup_dirs.append(base_dir)

        content = cs_agent.fetch_okf_via_git_ssh(
            FAKE_PRIVATE_KEY,
            repo_url=bare_dir,
        )
        self.assertEqual(content, fallback_rules)

    def test_missing_dynamic_context_on_main_returns_empty_and_uses_baseline(self) -> None:
        """Returns '' gracefully when dynamic_context.md is missing on main (even if on new_version)."""
        base_dir, bare_dir = _create_bare_repo_with_branches(
            main_files={},
            new_version_files={"dynamic_context.md": "# Only on new_version\n"},
        )
        self._cleanup_dirs.append(base_dir)

        content = cs_agent.fetch_okf_via_git_ssh(
            FAKE_PRIVATE_KEY,
            repo_url=bare_dir,
        )
        self.assertEqual(content, "")

        with mock.patch.object(cs_agent, "_fetch_okf_from_remote", return_value=""):
            cs_agent.invalidate_okf_cache(refresh_immediately=False)
            instructions = cs_agent.dynamic_instruction_provider(None)
            self.assertIn("BASELINE DEMEANOR (NO OKF OVERRIDES ACTIVE)", instructions)
            self.assertNotIn("ACTIVE DYNAMIC OPEN KNOWLEDGE FORMAT (OKF) DIRECTIVES", instructions)

    def test_fetch_okf_from_remote_uses_secret_manager_deploy_key_and_main_branch(self) -> None:
        """_fetch_okf_from_remote fetches github-deploy-key from Secret Manager and clones main."""
        fake_response = types.SimpleNamespace(
            payload=types.SimpleNamespace(data=FAKE_PRIVATE_KEY.encode("utf-8"))
        )
        mock_sm_instance = mock.MagicMock()
        mock_sm_instance.access_secret_version.return_value = fake_response

        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env", {})
            # Populate dynamic_context.md inside the target clone dir
            repo_dir = cmd[-1]
            os.makedirs(repo_dir, exist_ok=True)
            with open(os.path.join(repo_dir, "dynamic_context.md"), "w", encoding="utf-8") as f:
                f.write("OKF from mocked SSH")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(
            cs_agent.secretmanager, "SecretManagerServiceClient", return_value=mock_sm_instance
        ), mock.patch.object(cs_agent.subprocess, "run", side_effect=fake_run):
            result = cs_agent._fetch_okf_from_remote()

        self.assertEqual(result, "OKF from mocked SSH")
        mock_sm_instance.access_secret_version.assert_called_once()
        req_name = mock_sm_instance.access_secret_version.call_args.kwargs["request"]["name"]
        self.assertTrue(req_name.endswith("/secrets/github-deploy-key/versions/latest"))

        cmd = captured["cmd"]
        self.assertEqual(
            cmd[:7],
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                "main",
                "--single-branch",
            ],
        )
        self.assertEqual(cmd[7], "git@github.com:gshilo/experthub_context.git")

        git_ssh_cmd = captured["env"]["GIT_SSH_COMMAND"]
        self.assertIn("-o IdentitiesOnly=yes", git_ssh_cmd)
        self.assertIn("-o StrictHostKeyChecking=accept-new", git_ssh_cmd)

    def test_cache_ttl_and_invalidate_okf_cache(self) -> None:
        """Verifies TTL caching, invalidate_okf_cache(), and force refresh."""
        calls = {"count": 0}

        def fake_fetch() -> str:
            calls["count"] += 1
            return f"Rules v{calls['count']}"

        with mock.patch.object(cs_agent, "_fetch_okf_from_remote", side_effect=fake_fetch):
            # Initial fetch populates cache
            self.assertEqual(cs_agent.fetch_okf_dynamic_context(), "Rules v1")
            self.assertEqual(calls["count"], 1)

            # Subsequent call within TTL returns cached value without re-fetching
            self.assertEqual(cs_agent.fetch_okf_dynamic_context(), "Rules v1")
            self.assertEqual(calls["count"], 1)

            # invalidate_okf_cache(refresh_immediately=True) refreshes immediately
            refreshed = cs_agent.invalidate_okf_cache(refresh_immediately=True)
            self.assertEqual(refreshed, "Rules v2")
            self.assertEqual(calls["count"], 2)

            # invalidate_okf_cache(refresh_immediately=False) clears cache; next call fetches
            self.assertEqual(cs_agent.invalidate_okf_cache(refresh_immediately=False), "")
            self.assertEqual(calls["count"], 2)
            self.assertEqual(cs_agent.fetch_okf_dynamic_context(), "Rules v3")
            self.assertEqual(calls["count"], 3)

            # Expire TTL -> stale-while-revalidate returns cached content immediately
            with cs_agent._OKF_CACHE_LOCK:
                cs_agent._OKF_CACHE = ("Rules v3", time.time() - cs_agent._OKF_CACHE_TTL - 5.0)
            stale_val = cs_agent.fetch_okf_dynamic_context()
            self.assertEqual(stale_val, "Rules v3")

            # Wait briefly for background refresh thread to complete
            deadline = time.time() + 2.0
            while time.time() < deadline:
                with cs_agent._OKF_CACHE_LOCK:
                    if not cs_agent._OKF_CACHE_REFRESHING and cs_agent._OKF_CACHE[0] == "Rules v4":
                        break
                time.sleep(0.02)
            self.assertEqual(cs_agent.fetch_okf_dynamic_context(), "Rules v4")

    def test_temp_key_file_permissions_and_cleanup_on_success(self) -> None:
        """Temp key file is created with 0o600 permissions and deleted after successful fetch."""
        observed: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            repo_dir = cmd[-1]
            temp_dir = os.path.dirname(repo_dir)
            key_path = os.path.join(temp_dir, "deploy_key")
            observed["temp_dir"] = temp_dir
            observed["key_path"] = key_path
            observed["key_exists_during_run"] = os.path.exists(key_path)
            observed["key_mode"] = stat.S_IMODE(os.stat(key_path).st_mode)
            os.makedirs(repo_dir, exist_ok=True)
            with open(os.path.join(repo_dir, "dynamic_context.md"), "w", encoding="utf-8") as f:
                f.write("OKF content")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(cs_agent.subprocess, "run", side_effect=fake_run):
            res = cs_agent.fetch_okf_via_git_ssh(FAKE_PRIVATE_KEY)

        self.assertEqual(res, "OKF content")
        self.assertTrue(observed["key_exists_during_run"])
        self.assertEqual(observed["key_mode"], 0o600)
        self.assertFalse(os.path.exists(str(observed["key_path"])))
        self.assertFalse(os.path.exists(str(observed["temp_dir"])))

    def test_temp_key_file_cleanup_on_failure(self) -> None:
        """Temp key file and temp dir are deleted even when subprocess.run raises an exception."""
        observed: dict[str, str] = {}

        def fake_run_fail(cmd, **kwargs):
            repo_dir = cmd[-1]
            temp_dir = os.path.dirname(repo_dir)
            observed["temp_dir"] = temp_dir
            observed["key_path"] = os.path.join(temp_dir, "deploy_key")
            self.assertTrue(os.path.exists(observed["key_path"]))
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=20)

        with mock.patch.object(cs_agent.subprocess, "run", side_effect=fake_run_fail):
            res = cs_agent.fetch_okf_via_git_ssh(FAKE_PRIVATE_KEY)

        self.assertEqual(res, "")
        self.assertFalse(os.path.exists(observed["key_path"]))
        self.assertFalse(os.path.exists(observed["temp_dir"]))


if __name__ == "__main__":
    unittest.main()
