"""Unit tests for Auditor Agent Stage 1 Customer Feedback policy synthesis & Stage 3 OKF preservation."""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

auditor = importlib.import_module("auditor_agent.agent")


class _FakeQueryJob:
    def __init__(self, rows):
        self._rows = rows

    def result(self):
        return self._rows


class TestAuditorCustomerFeedback(unittest.TestCase):
    def test_stage1_cte_sql_and_empty_candidate_policies_triggers_secondary_bq_fallback(self) -> None:
        """When Stage 1 AI.GENERATE returns issues but omits candidate_policies, fallback synthesizes them."""
        executed_sqls: list[str] = []

        def fake_query(sql: str, location: str = "US"):
            executed_sqls.append(sql)
            if len(executed_sqls) == 1:
                return _FakeQueryJob([
                    {
                        "avg_rating": 2.1,
                        "low_ratings_count": 5,
                        "total_ratings": 6,
                        "feedback_summary": "Customer Marcus (Rating: 2/5): Refused emergency dispatch for fridge error 22E.",
                        "issues": [
                            "Agents refuse urgent technician dispatch for refrigerator cooling failures.",
                            "Customers face rigid 15% restocking fees on items that do not fit.",
                        ],
                        "candidate_policies": [],
                        "ai_status": "",
                    }
                ])
            return _FakeQueryJob([
                {
                    "candidate_policies": [
                        "Authorize priority same-day technician dispatch for active refrigerator cooling failures.",
                        "Waive the 15% restocking fee when customers exchange oversized appliances.",
                    ],
                    "ai_status": "",
                }
            ])

        fake_client = mock.MagicMock()
        fake_client.query.side_effect = fake_query

        with mock.patch.object(auditor.bigquery, "Client", return_value=fake_client):
            result = auditor.query_customer_feedback_analysis_bq("test-project")

        self.assertEqual(len(executed_sqls), 2)
        self.assertIn("GeneratedAnalysis AS (", executed_sqls[0])
        self.assertNotIn("UNNEST([AI.GENERATE", executed_sqls[0])
        self.assertIn("res.status AS ai_status", executed_sqls[0])
        self.assertEqual(len(result["detected_issues"]), 2)
        self.assertEqual(len(result["candidate_policies"]), 2)
        self.assertIn("priority same-day technician dispatch", result["candidate_policies"][0])

    def test_stage1_deterministic_fallback_when_secondary_bq_also_empty(self) -> None:
        """If both primary and secondary BQ AI.GENERATE return empty candidate_policies, derive from issues."""
        fake_client = mock.MagicMock()
        fake_client.query.side_effect = [
            _FakeQueryJob([
                {
                    "avg_rating": 2.0,
                    "low_ratings_count": 3,
                    "total_ratings": 3,
                    "feedback_summary": "Customer complained about warehouse refund delays.",
                    "issues": ["Refunds stall in warehouse quarantine for 15 days without updates."],
                    "candidate_policies": None,
                    "ai_status": "partial_schema_omission",
                }
            ]),
            _FakeQueryJob([{"candidate_policies": [], "ai_status": ""}]),
        ]

        with mock.patch.object(auditor.bigquery, "Client", return_value=fake_client):
            result = auditor.query_customer_feedback_analysis_bq("test-project")

        self.assertEqual(len(result["candidate_policies"]), 1)
        self.assertIn("warehouse quarantine", result["candidate_policies"][0])

    def test_stage2c_token_directives_fallback_from_recommendations(self) -> None:
        """When Stage 2c AI.GENERATE omits token_directives, derive them from token_recommendations."""
        executed_sqls: list[str] = []

        def fake_query(sql: str, location: str = "US"):
            executed_sqls.append(sql)
            return _FakeQueryJob([
                {
                    "total_calls": 42,
                    "avg_prompt_tokens": 1200.0,
                    "avg_completion_tokens": 250.0,
                    "avg_latency_ms": 1800.0,
                    "p95_latency_ms": 3400,
                    "token_recommendations": [
                        "Eliminate repetitive greeting preambles after turn 1.",
                        "Use concise 3-bullet troubleshooting steps.",
                    ],
                    "token_directives": [],
                    "estimated_savings_percent": "32%",
                    "ai_status": "",
                }
            ])

        fake_client = mock.MagicMock()
        fake_client.query.side_effect = fake_query

        result = auditor._query_telemetry_token_efficiency_bq(fake_client, "test-project")
        self.assertIn("GeneratedTokenOpt AS (", executed_sqls[0])
        self.assertNotIn("UNNEST([AI.GENERATE", executed_sqls[0])
        self.assertEqual(len(result["token_directives"]), 2)
        self.assertEqual(result["token_directives"][0], "Eliminate repetitive greeting preambles after turn 1.")

    def test_purge_legacy_hardcoded_rules_preserves_customer_feedback_rules(self) -> None:
        """purge_legacy_hardcoded_rules must NEVER delete rules explicitly tagged [Based on: Customer Feedback]."""
        doc = """---
type: Operational Rule
title: Mixed Rules
---

# Policy
1. [Based on: Customer Feedback] Immediately dispatch a technician for refrigerator error 22E complaints without multi-turn hoops.
2. [Based on: Agent Metrics] Check refrigerator error 22E static template.
3. [Based on: Customer Feedback] Waive the 15% restocking fee for doorway fit exchanges.
4. [Based on: Agent Metrics] Keep refund status lookups concise and accurate.

# Token Optimization Directive
- [Based on: Customer Feedback] Avoid redundant diagnostic preambles when customers report shipping transit bolts.
- [Based on: Agent Metrics] Omit pleasantry preambles after turn 1.
"""
        cleaned = auditor.purge_legacy_hardcoded_rules(doc)

        # Customer Feedback rules matching legacy keywords MUST survive
        self.assertIn("[Based on: Customer Feedback] Immediately dispatch a technician for refrigerator error 22E", cleaned)
        self.assertIn("[Based on: Customer Feedback] Waive the 15% restocking fee", cleaned)
        self.assertIn("[Based on: Customer Feedback] Avoid redundant diagnostic preambles when customers report shipping transit bolts.", cleaned)

        # Legacy Agent Metrics rules matching legacy patterns are still purged
        self.assertNotIn("Check refrigerator error 22E static template.", cleaned)
        self.assertNotIn("Omit pleasantry preambles after turn 1.", cleaned)

        # Non-legacy Agent Metrics rules are retained
        self.assertIn("[Based on: Agent Metrics] Keep refund status lookups concise and accurate.", cleaned)

    def test_merge_preserves_customer_feedback_over_overlapping_agent_metrics(self) -> None:
        """Customer Feedback rules must survive merge even when an existing Agent Metrics rule covers the same topic."""
        existing_doc = """---
type: Operational Rule
title: Existing Rules
status: stable
generated: { by: auditor_agent/gemini-3.8-flash, at: 2026-01-01T00:00:00Z }
verified: { by: process:auditor-agent, at: 2026-01-01T00:00:00Z }
---

# Definition
Existing baseline.

# Policy
1. [Based on: Agent Metrics] Proactively waive restocking fees and expedite returns for damaged freight appliances.

# Token Optimization Directive
- [Based on: Agent Metrics] Keep responses under three concise bullet points.
"""
        analysis = {
            "detected_issues": ["Customers frustrated by restocking fees on damaged freight appliances."],
            "candidate_policies": [
                "Proactively waive restocking fees and expedite returns for damaged freight appliances.",
                "Offer immediate carrier escalation when high-value TV deliveries are missing.",
            ],
        }
        token_opt = {
            "candidate_policies": [
                "Offer immediate carrier escalation when high-value TV deliveries are missing.",
                "Retry failed order lookup tool calls once before escalating to human support.",
            ],
            "quality_policies": [],
            "error_guardrails": [],
            "token_directives": ["Avoid repeating policy disclaimers in follow-up turns."],
            "estimated_savings_percent": "30%",
        }

        updated, new_policies, new_directives = auditor.merge_and_append_new_rules(
            existing_doc, analysis, token_opt
        )

        # Both Customer Feedback policies must be added (not dropped by overlapping Agent Metrics rule)
        cf_added = [p for p in new_policies if p.startswith("[Based on: Customer Feedback]")]
        am_added = [p for p in new_policies if p.startswith("[Based on: Agent Metrics]")]
        self.assertEqual(len(cf_added), 2)
        # Duplicate Agent Metrics rule for TV deliveries should be deduplicated in favor of Customer Feedback,
        # while the distinct Agent Metrics rule (retry tool calls) survives
        self.assertEqual(len(am_added), 1)
        self.assertIn("Retry failed order lookup tool calls", am_added[0])

        # Customer Feedback rules appear ahead of newly added Agent Metrics rules
        self.assertTrue(new_policies[0].startswith("[Based on: Customer Feedback]"))
        self.assertTrue(new_policies[1].startswith("[Based on: Customer Feedback]"))
        self.assertTrue(new_policies[2].startswith("[Based on: Agent Metrics]"))

        self.assertIn("[Based on: Customer Feedback] Proactively waive restocking fees", updated)
        self.assertIn("[Based on: Customer Feedback] Offer immediate carrier escalation", updated)
        self.assertIn("[Based on: Agent Metrics] Retry failed order lookup tool calls", updated)
        # Customer Feedback rules must appear BEFORE Agent Metrics rules in # Policy
        self.assertLess(
            updated.index("[Based on: Customer Feedback] Proactively waive restocking fees"),
            updated.index("[Based on: Agent Metrics] Proactively waive restocking fees"),
        )
        self.assertEqual(len(new_directives), 1)

    def test_stage1_query_computes_overall_stats_from_all_customer_ratings(self) -> None:
        """Stage 1 SQL computes avg_rating/total_ratings across all demo.customer_ratings rows."""
        executed_sqls: list[str] = []

        def fake_query(sql: str, location: str = "US"):
            executed_sqls.append(sql)
            return _FakeQueryJob([
                {
                    "avg_rating": 3.4,
                    "low_ratings_count": 4,
                    "total_ratings": 11,
                    "feedback_summary": "Customer Levon (Rating: 2/5): Bureaucratic runaround.",
                    "issues": ["Bureaucratic runaround on fee waivers."],
                    "candidate_policies": ["Waive restocking fees immediately on defective units."],
                    "ai_status": "",
                }
            ])

        fake_client = mock.MagicMock()
        fake_client.query.side_effect = fake_query

        with mock.patch.object(auditor.bigquery, "Client", return_value=fake_client):
            result = auditor.query_customer_feedback_analysis_bq("test-project")

        self.assertIn("AllRatingsStats AS (", executed_sqls[0])
        self.assertEqual(result["total_rated_sessions"], 11)
        self.assertEqual(result["low_ratings_count"], 4)
        self.assertEqual(result["average_rating"], 3.4)

    def test_conversational_fallback_includes_customer_ratings_for_decision_quality_questions(self) -> None:
        """Open-ended decision quality & improvement questions must include demo.customer_ratings."""
        plan = auditor._build_adaptive_conversational_fallback_sql(
            "What is the quality of the decisions that the customer support agent takes? What can be done better?",
            project_id="test-project",
        )
        self.assertIn("test-project.demo.customer_ratings", plan["tables_referenced"])
        self.assertIn("CustomerRatingsContext", plan["sql"])

        infra_plan = auditor._build_adaptive_conversational_fallback_sql(
            "What is the p95 latency and token usage?",
            project_id="test-project",
        )
        self.assertNotIn("test-project.demo.customer_ratings", infra_plan["tables_referenced"])

    def test_generate_initial_okf_rules_prioritizes_customer_feedback_before_agent_metrics(self) -> None:
        """Initial OKF document lists Customer Feedback policies before Agent Metrics policies and deduplicates AM duplicates."""
        analysis = {
            "detected_issues": ["Long delays on refund approvals."],
            "candidate_policies": [
                "Issue immediate refund credit once warehouse delivery scan is confirmed.",
            ],
        }
        token_opt = {
            "candidate_policies": [
                "Issue immediate refund credit once warehouse delivery scan is confirmed.",
                "Consolidate tool calls to avoid multi-second latency spikes.",
            ],
            "quality_policies": [],
            "error_guardrails": [],
            "token_directives": ["Keep confirmation messages to two sentences."],
            "estimated_savings_percent": "34%",
        }

        doc = auditor.generate_initial_okf_rules(analysis, token_opt)
        cf_idx = doc.index("[Based on: Customer Feedback] Issue immediate refund credit")
        am_idx = doc.index("[Based on: Agent Metrics] Consolidate tool calls")
        self.assertLess(cf_idx, am_idx)
        self.assertNotIn("[Based on: Agent Metrics] Issue immediate refund credit", doc)


if __name__ == "__main__":
    unittest.main()
