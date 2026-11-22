"""Unit tests for native BigQuery ratings persistence in customer_agent/agent.py."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from customer_agent import agent as customer_agent_mod


AGENT_PY_PATH = REPO_ROOT / "customer_agent" / "agent.py"


class TestNormalizeBqDatetime:
    def test_none_returns_naive_utc_datetime_string(self):
        result = customer_agent_mod._normalize_bq_datetime(None)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result), result
        assert "Z" not in result and "+" not in result and "T" not in result

    def test_iso_with_z_suffix(self):
        result = customer_agent_mod._normalize_bq_datetime("2026-11-22T08:15:30Z")
        assert result == "2026-11-22 08:15:30"

    def test_iso_with_utc_offset(self):
        result = customer_agent_mod._normalize_bq_datetime("2026-11-22T08:15:30.123456+00:00")
        assert result == "2026-11-22 08:15:30"

    def test_iso_with_non_utc_negative_offset_converts_to_utc(self):
        result = customer_agent_mod._normalize_bq_datetime("2026-11-22T03:15:30-05:00")
        assert result == "2026-11-22 08:15:30"

    def test_iso_with_non_utc_positive_offset_converts_to_utc(self):
        result = customer_agent_mod._normalize_bq_datetime("2026-11-22T10:15:30+02:00")
        assert result == "2026-11-22 08:15:30"

    def test_already_naive_datetime_string_preserved(self):
        assert (
            customer_agent_mod._normalize_bq_datetime("2026-11-22 08:15:30")
            == "2026-11-22 08:15:30"
        )
        assert (
            customer_agent_mod._normalize_bq_datetime("2026-11-22T08:15:30")
            == "2026-11-22 08:15:30"
        )


class TestEnsureBigQueryRatingsTable:
    def test_creates_dataset_us_and_table_with_datetime_schema(self):
        mock_client = MagicMock()
        with patch.object(customer_agent_mod.bigquery, "Client", return_value=mock_client) as mock_cls:
            customer_agent_mod._BQ_TABLE_VERIFIED = False
            customer_agent_mod.ensure_bigquery_ratings_table(project_id="experthub-test")

        mock_cls.assert_called_once_with(project="experthub-test")
        mock_client.create_dataset.assert_called_once()
        dataset_arg = mock_client.create_dataset.call_args.args[0]
        assert mock_client.create_dataset.call_args.kwargs.get("exists_ok") is True
        assert dataset_arg.dataset_id == "demo"
        assert dataset_arg.location == "US"

        mock_client.create_table.assert_called_once()
        table_arg = mock_client.create_table.call_args.args[0]
        assert mock_client.create_table.call_args.kwargs.get("exists_ok") is True
        assert table_arg.table_id == "customer_ratings"

        schema_map = {f.name: (f.field_type, f.mode) for f in table_arg.schema}
        assert schema_map == {
            "customer_id": ("INTEGER", "NULLABLE"),
            "customer_name": ("STRING", "NULLABLE"),
            "description": ("STRING", "NULLABLE"),
            "rating": ("INTEGER", "NULLABLE"),
            "timestamp": ("DATETIME", "NULLABLE"),
        }
        assert customer_agent_mod._BQ_TABLE_VERIFIED is True

    def test_handles_offline_exception_gracefully(self):
        with patch.object(
            customer_agent_mod.bigquery,
            "Client",
            side_effect=RuntimeError("offline credentials unavailable"),
        ):
            customer_agent_mod._BQ_TABLE_VERIFIED = False
            # Should not raise
            customer_agent_mod.ensure_bigquery_ratings_table(project_id="experthub-test")
            assert customer_agent_mod._BQ_TABLE_VERIFIED is False


class TestWriteCustomerRatingToBigQuery:
    def test_inserts_row_with_naive_utc_datetime_and_returns_success(self):
        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []

        with patch.object(customer_agent_mod.bigquery, "Client", return_value=mock_client):
            customer_agent_mod._BQ_TABLE_VERIFIED = True
            res = customer_agent_mod.write_customer_rating_to_bigquery(
                customer_id=123456,
                customer_name="Aria Montgomery",
                rating=4,
                description="Fast resolution with clear instructions.",
                timestamp="2026-11-22T03:15:30-05:00",
                project_id="experthub-510907",
            )

        assert res["status"] == "success"
        assert res["destination"] == "bigquery"
        assert res["table"] == "experthub-510907.demo.customer_ratings"

        mock_client.insert_rows_json.assert_called_once()
        table_ref, rows = mock_client.insert_rows_json.call_args.args
        assert table_ref == "experthub-510907.demo.customer_ratings"
        assert len(rows) == 1
        row = rows[0]
        assert row == {
            "customer_id": 123456,
            "customer_name": "Aria Montgomery",
            "description": "Fast resolution with clear instructions.",
            "rating": 4,
            "timestamp": "2026-11-22 08:15:30",
        }
        assert "Z" not in row["timestamp"] and "+" not in row["timestamp"]

    def test_clamps_rating_to_1_through_5(self):
        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []

        with patch.object(customer_agent_mod.bigquery, "Client", return_value=mock_client):
            customer_agent_mod._BQ_TABLE_VERIFIED = True
            res_high = customer_agent_mod.write_customer_rating_to_bigquery(
                customer_id=1,
                customer_name="High",
                rating=9,
                description="Too high",
                timestamp="2026-11-22T08:00:00Z",
                project_id="experthub-510907",
            )
            res_low = customer_agent_mod.write_customer_rating_to_bigquery(
                customer_id=2,
                customer_name="Low",
                rating=0,
                description="Too low",
                timestamp="2026-11-22T08:00:00Z",
                project_id="experthub-510907",
            )

        assert res_high["status"] == "success"
        assert res_high["row"]["rating"] == 5
        assert res_low["status"] == "success"
        assert res_low["row"]["rating"] == 1

    def test_handles_bigquery_insert_errors(self):
        mock_client = MagicMock()
        bq_errors = [{"index": 0, "errors": [{"reason": "invalid", "message": "bad row"}]}]
        mock_client.insert_rows_json.return_value = bq_errors

        with patch.object(customer_agent_mod.bigquery, "Client", return_value=mock_client):
            customer_agent_mod._BQ_TABLE_VERIFIED = True
            res = customer_agent_mod.write_customer_rating_to_bigquery(
                customer_id=123456,
                customer_name="Aria Montgomery",
                rating=3,
                description="Average support.",
                timestamp="2026-11-22T08:15:30Z",
                project_id="experthub-510907",
            )

        assert res["status"] == "error"
        assert res["destination"] == "bigquery"
        assert res["table"] == "experthub-510907.demo.customer_ratings"
        assert res["errors"] == bq_errors

    def test_handles_bigquery_client_exception(self):
        with patch.object(
            customer_agent_mod.bigquery,
            "Client",
            side_effect=RuntimeError("BQ network error"),
        ):
            customer_agent_mod._BQ_TABLE_VERIFIED = True
            res = customer_agent_mod.write_customer_rating_to_bigquery(
                customer_id=123456,
                customer_name="Aria Montgomery",
                rating=5,
                description="Great support.",
                timestamp="2026-11-22T08:15:30Z",
                project_id="experthub-510907",
            )

        assert res["status"] == "error"
        assert "BQ network error" in res["error"]


class TestNoAlloyDbOrPg8000References:
    def test_agent_py_has_zero_alloydb_or_pg8000_references(self):
        source = AGENT_PY_PATH.read_text(encoding="utf-8")
        lower_source = source.lower()
        assert "alloydb" not in lower_source
        assert "pg8000" not in lower_source

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "alloydb" not in alias.name.lower()
                    assert "pg8000" not in alias.name.lower()
            elif isinstance(node, ast.ImportFrom):
                mod_name = (node.module or "").lower()
                assert "alloydb" not in mod_name
                assert "pg8000" not in mod_name

    def test_root_agent_registers_bigquery_tool(self):
        assert customer_agent_mod.write_customer_rating_to_bigquery in customer_agent_mod.root_agent.tools
        assert "alloydb" not in customer_agent_mod.root_agent.description.lower()
        assert "bigquery" in customer_agent_mod.root_agent.description.lower()
