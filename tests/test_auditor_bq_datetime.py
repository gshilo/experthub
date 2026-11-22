"""Unit tests verifying BigQuery DATETIME handling for demo.customer_ratings in auditor_agent."""

from __future__ import annotations

import datetime
import importlib
import os
import sys
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


class TestAuditorBQDatetime(unittest.TestCase):
    """Tests that demo.customer_ratings uses DATETIME / DATETIME_TRUNC while agent_events keeps TIMESTAMP_TRUNC."""

    def test_schema_guide_documents_customer_ratings_timestamp_as_datetime(self) -> None:
        guide = auditor._get_telemetry_and_ai_schema_guide("test-proj")
        # Section 3 describes demo.customer_ratings
        self.assertIn("`test-proj.demo.customer_ratings`", guide)
        ratings_section = guide.split("`test-proj.demo.customer_ratings`", 1)[1].split(
            "Available BigQuery AI Functions", 1
        )[0]
        self.assertIn("`timestamp` DATETIME", ratings_section)
        self.assertNotIn("`timestamp` TIMESTAMP", ratings_section)
        self.assertIn("DATETIME_TRUNC(timestamp, HOUR)", ratings_section)

        # Section 1 still documents agent_events.timestamp as TIMESTAMP
        events_section = guide.split("`test-proj.agent_telemetry.agent_events`", 1)[1].split(
            "2. `test-proj.agent_telemetry`", 1
        )[0]
        self.assertIn("`timestamp` TIMESTAMP", events_section)

    def test_generate_dynamic_analysis_query_prompt_mentions_datetime_trunc(self) -> None:
        captured_prompts = []

        class _FakeModels:
            def generate_content(self, *, model, contents):
                captured_prompts.append(contents)
                resp = mock.MagicMock()
                resp.text = (
                    '{"is_time_series": true, "time_bucket": "HOUR", "chart_type": "line", '
                    '"title": "CSAT Over Time", "target_sentiment": "all", '
                    '"tables_referenced": ["test-proj.demo.customer_ratings"], '
                    '"ai_functions": ["AI.CLASSIFY"], '
                    '"sql": "SELECT DATETIME_TRUNC(timestamp, HOUR) AS time_bucket FROM `test-proj.demo.customer_ratings`"}'
                )
                return resp

        fake_client = mock.MagicMock()
        fake_client.models = _FakeModels()

        genai_mod = types.ModuleType("google.genai")
        genai_mod.Client = lambda: fake_client

        with mock.patch.dict(sys.modules, {"google.genai": genai_mod}):
            if hasattr(sys.modules["google"], "genai"):
                orig_genai = sys.modules["google"].genai
            else:
                orig_genai = None
            sys.modules["google"].genai = genai_mod
            try:
                result = auditor.generate_dynamic_analysis_query(
                    "Show customer satisfaction over time", project_id="test-proj"
                )
            finally:
                if orig_genai is None:
                    delattr(sys.modules["google"], "genai")
                else:
                    sys.modules["google"].genai = orig_genai

        self.assertIsNotNone(result)
        self.assertEqual(len(captured_prompts), 1)
        prompt = captured_prompts[0]
        self.assertIn("DATETIME_TRUNC(timestamp, HOUR)", prompt)
        self.assertIn("demo.customer_ratings", prompt)
        self.assertIn("TIMESTAMP_TRUNC(timestamp, HOUR)", prompt)
        self.assertIn("agent_telemetry.agent_events", prompt)

    def _run_dynamic_query_capturing_sql(self, question: str, dynamic_gen=None) -> str:
        captured_sql = []

        fake_job = mock.MagicMock()
        fake_job.result.return_value = [
            {
                "time_bucket": datetime.datetime(2026, 11, 22, 8, 0, 0),
                "total_interactions": 5,
                "positive_count": 3,
                "neutral_count": 1,
                "negative_count": 1,
                "positive_pct": 60.0,
                "neutral_pct": 20.0,
                "negative_pct": 20.0,
                "avg_csat": 4.2,
            }
        ]

        fake_client = mock.MagicMock()

        def _fake_query(sql, location=None):
            captured_sql.append(sql)
            return fake_job

        fake_client.query.side_effect = _fake_query

        with (
            mock.patch.object(auditor, "generate_dynamic_analysis_query", return_value=dynamic_gen),
            mock.patch.object(auditor.bigquery, "Client", return_value=fake_client),
        ):
            res = auditor._process_chart_analysis_query(question, project_id="test-proj")

        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(len(captured_sql), 1)
        return captured_sql[0]

    def test_deterministic_customer_ratings_time_series_uses_datetime_trunc(self) -> None:
        sql = self._run_dynamic_query_capturing_sql("Show customer satisfaction trend over time")
        self.assertIn("`test-proj.demo.customer_ratings`", sql)
        self.assertIn("DATETIME_TRUNC(timestamp, HOUR)", sql)
        self.assertNotIn("TIMESTAMP_TRUNC", sql)

    def test_deterministic_agent_events_time_series_keeps_timestamp_trunc(self) -> None:
        sql = self._run_dynamic_query_capturing_sql(
            "Show sentiment trend over time by chat message turn"
        )
        self.assertIn("`test-proj.agent_telemetry.agent_events`", sql)
        self.assertIn("TIMESTAMP_TRUNC(timestamp, HOUR)", sql)
        self.assertNotIn("DATETIME_TRUNC", sql)

    def test_dynamic_gen_customer_ratings_normalizes_to_datetime_trunc_hour(self) -> None:
        for bad_sql in [
            "SELECT DATETIME_TRUNC(timestamp, DAY) AS time_bucket FROM `test-proj.demo.customer_ratings`",
            "SELECT DATE_TRUNC(timestamp, DAY) AS time_bucket FROM `test-proj.demo.customer_ratings`",
            "SELECT TIMESTAMP_TRUNC(timestamp, DAY) AS time_bucket FROM `test-proj.demo.customer_ratings`",
            "SELECT TIMESTAMP_TRUNC(timestamp, HOUR) AS time_bucket FROM `test-proj.demo.customer_ratings`",
        ]:
            dynamic_gen = {
                "is_time_series": True,
                "time_bucket": "HOUR",
                "chart_type": "line",
                "title": "CSAT Over Time",
                "tables_referenced": ["test-proj.demo.customer_ratings"],
                "ai_functions": ["AI.CLASSIFY"],
                "sql": bad_sql,
            }
            sql = self._run_dynamic_query_capturing_sql("ratings over time", dynamic_gen=dynamic_gen)
            self.assertIn("DATETIME_TRUNC(timestamp, HOUR)", sql, msg=f"Failed for input: {bad_sql}")
            self.assertNotIn("TIMESTAMP_TRUNC", sql, msg=f"Failed for input: {bad_sql}")

    def test_dynamic_gen_agent_events_keeps_timestamp_trunc_hour(self) -> None:
        dynamic_gen = {
            "is_time_series": True,
            "time_bucket": "HOUR",
            "chart_type": "line",
            "title": "Turn Sentiment Over Time",
            "tables_referenced": ["test-proj.agent_telemetry.agent_events"],
            "ai_functions": ["AI.CLASSIFY"],
            "sql": "SELECT TIMESTAMP_TRUNC(timestamp, DAY) AS time_bucket FROM `test-proj.agent_telemetry.agent_events`",
        }
        sql = self._run_dynamic_query_capturing_sql("chat turns over time", dynamic_gen=dynamic_gen)
        self.assertIn("TIMESTAMP_TRUNC(timestamp, HOUR)", sql)
        self.assertNotIn("DATETIME_TRUNC", sql)


if __name__ == "__main__":
    unittest.main()
