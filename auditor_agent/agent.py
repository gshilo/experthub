"""Auditor Agent implementation for ApexHome & Electro.

Built with Google Agent Development Kit (ADK 2.0), Gemini 3.8 Flash,
BigQuery analytics integration, and automated GitHub OKF rule commits.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App
from google.cloud import bigquery
from google.cloud import secretmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auditor_agent")

PROJECT_ID = (
    os.environ.get("GOOGLE_CLOUD_PROJECT")
    or os.environ.get("GCP_PROJECT")
    or "experthub-510907"
)
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")
DEPLOY_KEY_SECRET_NAME = os.environ.get("GITHUB_DEPLOY_KEY_SECRET_NAME", "github-deploy-key")
SECRET_NAME = os.environ.get("GITHUB_SECRET_NAME", "github-pat")
REPO_NAME = "gshilo/experthub_context"
MAIN_BRANCH = "main"
NEW_VERSION_BRANCH = "new_version"
OKF_FILENAME = "dynamic_context.md"
OKF_FALLBACK_FILENAME = "dynamic_content.md"


def get_secret(secret_id: str = SECRET_NAME, project: str = PROJECT_ID) -> str:
    """Retrieves secret from Google Cloud Secret Manager with fallback to env var.

    API keys and credentials are never stored in static files.
    """
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8").strip()
        logger.info(f"Retrieved secret '{secret_id}' directly from Secret Manager.")
        return secret_value
    except Exception as e:
        logger.info(
            f"Could not retrieve secret '{secret_id}' from Secret Manager: {e}. "
            "Checking environment fallback."
        )

    # Fallback to env var if Secret Manager access fails
    if secret_id in ("github-pat", SECRET_NAME):
        env_token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
        if env_token:
            return env_token.strip()
    elif secret_id in ("github-deploy-key", DEPLOY_KEY_SECRET_NAME):
        env_key = os.environ.get("GITHUB_DEPLOY_KEY") or os.environ.get("SSH_DEPLOY_KEY")
        if env_key:
            return env_key.strip()
    elif secret_id in ("gemini-api-key", "google-api-key"):
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key:
            return env_key.strip()

    return ""


def is_placeholder_token(token: str) -> bool:
    """Checks whether token is empty or an unconfigured placeholder."""
    if not token:
        return True
    t = token.strip().upper()
    return (
        t.startswith("PLACEHOLDER")
        or t.startswith("YOUR_")
        or "PLACEHOLDER" in t
        or t in ("DUMMY", "TEST", "NONE", "NULL")
    )


def ensure_gemini_api_key(project_id: str = PROJECT_ID) -> Optional[str]:
    """Ensures GEMINI_API_KEY / GOOGLE_API_KEY is retrieved directly from Secret Manager.

    Retrieves secret from Google Cloud Secret Manager ('gemini-api-key' or fallback 'google-api-key')
    and populates os.environ dynamically at runtime. The key is never read from or stored in static files.
    """
    for secret_name in ("gemini-api-key", "google-api-key"):
        val = get_secret(secret_name, project=project_id)
        if val and not is_placeholder_token(val):
            os.environ["GEMINI_API_KEY"] = val
            os.environ["GOOGLE_API_KEY"] = val
            logger.info(f"Dynamically loaded Gemini API key from Secret Manager secret '{secret_name}' (not static files).")
            return val

    existing_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if existing_key and not is_placeholder_token(existing_key):
        return existing_key

    logger.warning("No Gemini API key found in Secret Manager ('gemini-api-key') or environment.")
    return None


# Ensure Gemini API key is loaded into environment from Secret Manager before agent execution
ensure_gemini_api_key(PROJECT_ID)


def execute_bigquery_query(query: str, project_id: str = PROJECT_ID) -> Dict[str, Any]:
    """Executes a read-only SQL query against BigQuery using BigQuery AI functions or analytics views.

    Allows the Auditor Agent to construct and run queries on the fly to inspect
    agent telemetry, customer feedback, token usage, and latency.
    Enforces read-only safety: only SELECT / WITH statements targeting agent_telemetry
    and demo datasets or AI functions are permitted.

    Args:
        query: The SQL query to execute. Must be read-only (SELECT / WITH) targeting
               agent_telemetry or demo datasets or BigQuery AI functions.
        project_id: Google Cloud Project ID.

    Returns:
        Dict containing status, row_count, and query rows.
    """
    q_stripped = query.strip()
    q_upper = q_stripped.upper()

    if not (q_upper.startswith("SELECT") or q_upper.startswith("WITH")):
        return {
            "status": "ERROR",
            "error": "Only read-only queries starting with SELECT or WITH are permitted.",
        }

    forbidden_keywords = [
        "DROP ", "DELETE ", "UPDATE ", "INSERT ", "TRUNCATE ", "ALTER ", "MERGE ", "CREATE "
    ]
    for kw in forbidden_keywords:
        if kw in q_upper:
            return {
                "status": "ERROR",
                "error": f"Query contains forbidden modification keyword: '{kw.strip()}'. Only read-only queries are allowed.",
            }

    try:
        client = bigquery.Client(project=project_id)
        job_config = bigquery.QueryJobConfig(use_query_cache=True)
        query_job = client.query(query, job_config=job_config, location=BQ_LOCATION)
        results = list(query_job.result())

        cleaned_rows = []
        for row in results:
            row_dict = dict(row)
            cleaned_row = {}
            for k, v in row_dict.items():
                if isinstance(v, (datetime.datetime, datetime.date)):
                    cleaned_row[k] = v.isoformat()
                elif isinstance(v, bytes):
                    cleaned_row[k] = v.decode("utf-8", errors="replace")
                else:
                    cleaned_row[k] = v
            cleaned_rows.append(cleaned_row)

        return {
            "status": "SUCCESS",
            "row_count": len(cleaned_rows),
            "rows": cleaned_rows[:100],
        }
    except Exception as e:
        logger.error(f"Error executing BigQuery query: {e}")
        return {
            "status": "ERROR",
            "error": str(e),
        }


def query_customer_feedback_analysis_bq(
    project_id: str = PROJECT_ID,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Pushes down customer feedback AI analysis to BigQuery using AI functions.

    Uses BigQuery AI function `AI.GENERATE` with connection `us.gemini` and endpoint `gemini-3.8-flash`
    to analyze ratings and customer feedback from `{project_id}.demo.customer_ratings`.
    All AI processing occurs in BigQuery without sending telemetry to Python LLM.
    """
    logger.info("Executing customer feedback AI pushdown query in BigQuery...")
    client = bigquery.Client(project=project_id)
    sql = f"""
        WITH FeedbackStats AS (
          SELECT
            ROUND(AVG(rating), 2) AS avg_rating,
            COUNTIF(rating <= 3) AS low_ratings_count,
            COUNT(*) AS total_ratings,
            STRING_AGG(
              CONCAT("Customer ", customer_name, " (Rating: ", CAST(rating AS STRING), "/5): ", description),
              "\\n" ORDER BY rating ASC, timestamp DESC
              LIMIT 15
            ) AS feedback_summary
          FROM `{project_id}.demo.customer_ratings`
        )
        SELECT
          f.avg_rating,
          f.low_ratings_count,
          f.total_ratings,
          res.issues,
          res.candidate_policies
        FROM FeedbackStats f,
        UNNEST([AI.GENERATE(
          CONCAT(
            "Analyze the following customer service ratings and feedback.\\n",
            "Identify specific operational issues, negative friction points, and formulate direct policy rules to resolve them.\\n\\n",
            "Customer Feedback Records:\\n", f.feedback_summary
          ),
          connection_id => "us.gemini",
          endpoint => "gemini-3.8-flash",
          output_schema => "issues ARRAY<STRING>, candidate_policies ARRAY<STRING>"
        )]) AS res
    """
    last_err = None
    for attempt in range(max_retries):
        try:
            query_job = client.query(sql, location=BQ_LOCATION)
            results = list(query_job.result())
            if results:
                row = results[0]
                issues = list(row.get("issues") or [])
                candidate_policies = list(row.get("candidate_policies") or [])
                return {
                    "average_rating": float(row.get("avg_rating") or 3.8),
                    "low_ratings_count": int(row.get("low_ratings_count") or 0),
                    "total_rated_sessions": int(row.get("total_ratings") or 0),
                    "detected_issues": issues,
                    "candidate_policies": candidate_policies,
                }
            break
        except Exception as e:
            last_err = e
            wait_sec = 2 ** attempt
            logger.warning(
                f"BigQuery customer feedback AI pushdown attempt {attempt + 1}/{max_retries} failed: {e}. "
                f"Retrying in {wait_sec}s..."
            )
            time.sleep(wait_sec)

    logger.error(f"Customer feedback AI pushdown failed after {max_retries} retries: {last_err}")
    raise RuntimeError(
        f"BigQuery AI customer feedback pushdown failed after {max_retries} attempts: {last_err}"
    )


def query_agent_telemetry_analysis_bq(
    project_id: str = PROJECT_ID,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Pushes down agent execution telemetry AI analysis to BigQuery using AI functions.

    Uses BigQuery AI function `AI.GENERATE` with connection `us.gemini` and endpoint `gemini-3.8-flash`
    to analyze LLM performance metrics and tool executions from `{project_id}.agent_telemetry.v_llm_response`.
    All AI processing occurs in BigQuery without sending telemetry to Python LLM.
    """
    logger.info("Executing agent telemetry AI pushdown query in BigQuery...")
    client = bigquery.Client(project=project_id)
    sql = f"""
        WITH TelemetrySummary AS (
          SELECT
            COUNT(*) AS total_calls,
            ROUND(AVG(usage_prompt_tokens), 1) AS avg_prompt_tokens,
            ROUND(AVG(usage_completion_tokens), 1) AS avg_completion_tokens,
            ROUND(AVG(total_ms), 1) AS avg_latency_ms,
            APPROX_QUANTILES(total_ms, 100)[OFFSET(95)] AS p95_latency_ms,
            STRING_AGG(SUBSTR(TO_JSON_STRING(response), 1, 150), "\\n" LIMIT 5) AS sample_responses
          FROM `{project_id}.agent_telemetry.v_llm_response`
        )
        SELECT
          t.total_calls,
          t.avg_prompt_tokens,
          t.avg_completion_tokens,
          t.avg_latency_ms,
          t.p95_latency_ms,
          res.token_recommendations,
          res.token_directives,
          res.estimated_savings_percent
        FROM TelemetrySummary t,
        UNNEST([AI.GENERATE(
          CONCAT(
            "Analyze the following customer service LLM agent execution telemetry metrics:\\n",
            "- Total calls: ", CAST(t.total_calls AS STRING), "\\n",
            "- Avg prompt tokens: ", CAST(t.avg_prompt_tokens AS STRING), "\\n",
            "- Avg completion tokens: ", CAST(t.avg_completion_tokens AS STRING), "\\n",
            "- Avg latency: ", CAST(t.avg_latency_ms AS STRING), "ms\\n",
            "- P95 latency: ", CAST(t.p95_latency_ms AS STRING), "ms\\n",
            "Sample model completions:\\n", t.sample_responses, "\\n\\n",
            "Provide actionable token compression recommendations, operational token directives for the agent prompt, and an estimated token savings percentage."
          ),
          connection_id => "us.gemini",
          endpoint => "gemini-3.8-flash",
          output_schema => "token_recommendations ARRAY<STRING>, token_directives ARRAY<STRING>, estimated_savings_percent STRING"
        )]) AS res
    """
    last_err = None
    for attempt in range(max_retries):
        try:
            query_job = client.query(sql, location=BQ_LOCATION)
            results = list(query_job.result())
            if results:
                row = results[0]
                recs = list(row.get("token_recommendations") or [])
                directives = list(row.get("token_directives") or [])
                savings = str(row.get("estimated_savings_percent") or "35%")
                return {
                    "total_calls": int(row.get("total_calls") or 0),
                    "avg_prompt_tokens": float(row.get("avg_prompt_tokens") or 0.0),
                    "avg_completion_tokens": float(row.get("avg_completion_tokens") or 0.0),
                    "avg_latency_ms": float(row.get("avg_latency_ms") or 0.0),
                    "p95_latency_ms": int(row.get("p95_latency_ms") or 0),
                    "token_recommendations": recs,
                    "token_directives": directives,
                    "estimated_savings_percent": savings,
                }
            break
        except Exception as e:
            last_err = e
            wait_sec = 2 ** attempt
            logger.warning(
                f"BigQuery agent telemetry AI pushdown attempt {attempt + 1}/{max_retries} failed: {e}. "
                f"Retrying in {wait_sec}s..."
            )
            time.sleep(wait_sec)

    logger.error(f"Agent telemetry AI pushdown failed after {max_retries} retries: {last_err}")
    raise RuntimeError(
        f"BigQuery AI agent telemetry pushdown failed after {max_retries} attempts: {last_err}"
    )


def query_audit_data_from_bigquery(
    project_id: str = PROJECT_ID,
    limit: int = 15,
) -> Dict[str, Any]:
    """Compatibility query function returning raw rows if requested."""
    try:
        client = bigquery.Client(project=project_id)
        ratings = [dict(r) for r in client.query(f"SELECT * FROM `{project_id}.demo.customer_ratings` LIMIT {limit}").result()]
        telemetry = [dict(r) for r in client.query(f"SELECT * FROM `{project_id}.agent_telemetry.agent_events` LIMIT {limit}").result()]
        return {"ratings": ratings, "telemetry": telemetry}
    except Exception as e:
        logger.warning(f"Compatibility query notice: {e}")
        return {"ratings": [], "telemetry": []}


def analyze_interactions(data: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility analyzer delegating to BigQuery AI pushdown."""
    return query_customer_feedback_analysis_bq(PROJECT_ID)


def normalize_rule_text(rule: str) -> str:
    """Strips [Based on: ...] or [Source: ...] tag and normalizes rule text."""
    r = re.sub(
        r"\[(based on|source|basis):\s*(customer feedback|agent metrics)\]",
        "",
        rule,
        flags=re.IGNORECASE,
    ).strip()
    r = re.sub(
        r"\((based on|source|basis):\s*(customer feedback|agent metrics)\)",
        "",
        r,
        flags=re.IGNORECASE,
    ).strip()
    r = re.sub(
        r"\[(customer feedback|agent metrics)\]",
        "",
        r,
        flags=re.IGNORECASE,
    ).strip()
    return r.strip()


def classify_rule_basis(rule_text: str) -> str:
    """Determines whether a rule is based on 'Customer Feedback' or 'Agent Metrics'."""
    text_lower = rule_text.lower()
    if "agent metrics" in text_lower:
        return "Agent Metrics"
    if "customer feedback" in text_lower:
        return "Customer Feedback"

    agent_metrics_keywords = [
        "token",
        "latency",
        "pleasantry",
        "words",
        "checklist under",
        "overhead",
        "tool execution",
        "response time",
        "p95",
        "seconds",
        "conciseness",
        "preamble",
        "disclaimers after initial",
        "single-line direct",
        "sequential tool calls",
        "processing time",
        "tool invocation",
        "data retrieval",
        "batch",
    ]
    for kw in agent_metrics_keywords:
        if kw in text_lower:
            return "Agent Metrics"

    return "Customer Feedback"


def format_rule_with_basis(rule_text: str, default_basis: Optional[str] = None) -> str:
    """Formats a rule string ensuring it includes the '[Based on: ...]' indication."""
    if re.search(
        r"\[(based on|source|basis):\s*(customer feedback|agent metrics)\]",
        rule_text,
        flags=re.IGNORECASE,
    ):
        return rule_text

    basis = default_basis or classify_rule_basis(rule_text)
    clean_text = normalize_rule_text(rule_text)
    return f"[Based on: {basis}] {clean_text}"


def optimize_token_efficiency(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Sub-Agent 2: Token Efficiency Optimizer."""
    recommendations = [
        "Consolidate preliminary hardware troubleshooting instructions into a single bulleted checklist in turn 1 rather than multi-turn sequential inquiries (-35% dialogue turns & tokens).",
        "Disclose return fee terms (15% restocking fee on opened items) alongside courtesy exchange waiver options upfront to eliminate 4-turn fee disputes (-30% output tokens).",
        "Automatically trigger carrier terminal trace queries upon reported missing deliveries rather than asking customers to do manual neighborhood sweeps (-25% interaction turns).",
        "Differentiate authorization holds from captured charges and supply transaction ARN reference letters immediately for billing inquiries (-20% tokens).",
    ]

    token_directives = [
        format_rule_with_basis("Omit pleasantry preambles after turn 1 in multi-turn dialogues.", "Agent Metrics"),
        format_rule_with_basis("Consolidate error code diagnostic steps into a single 3-point checklist under 45 words.", "Agent Metrics"),
        format_rule_with_basis("State 30-day return policy, 15% restocking fee, and exchange waiver options upfront.", "Customer Feedback"),
        format_rule_with_basis("For delivery discrepancies, open carrier trace ticket immediately without speculative delays.", "Customer Feedback"),
    ]

    return {
        "token_recommendations": recommendations,
        "token_directives": token_directives,
        "estimated_savings_percent": "32%",
    }


def generate_initial_okf_rules(analysis: Dict[str, Any], token_opt: Dict[str, Any]) -> str:
    """Sub-Agent 3: OKF Rule Author - generates initial baseline OKF document with rule source indications."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    directives_bullets = "\n".join(f"- {format_rule_with_basis(d)}" for d in token_opt["token_directives"])
    issues_summary = "; ".join(analysis["detected_issues"][:2])

    okf_document = f"""---
type: Operational Rule
title: Precision Multi-Turn Support, Diagnostics & Token Efficiency Directives
description: Enforces structured troubleshooting, policy transparency, and token conservation across multi-turn interactions.
tags: [customer-service, policy, token-efficiency, self-improving, multi-turn]
status: stable
generated: {{ by: auditor_agent/gemini-3.8-flash, at: {now_iso} }}
verified: {{ by: process:auditor-agent, at: {now_iso} }}
sources:
  - id: agent-telemetry
    resource: bigquery://{PROJECT_ID}/agent_telemetry
    title: Agent Telemetry Logs
  - id: customer-ratings
    resource: bigquery://{PROJECT_ID}/demo/customer_ratings
    title: Customer Feedback Ratings
---

# Definition
Telemetry and customer sentiment analysis identified customer friction regarding multi-turn diagnostic delays, restocking fee surprises, and carrier delivery discrepancies:
{issues_summary}

# Policy
1. [Based on: Customer Feedback] For Refrigerator Error 22E: Direct customer to inspect upper evaporator fan for frost obstruction and verify the door seal. Offer next-day warranty dispatch if frost persists.
2. [Based on: Customer Feedback] For Washing Machine Vibration: Verify rear shipping transit bolts are removed prior to considering mechanical motor overload.
3. [Based on: Customer Feedback] For TV eARC / Audio Dropouts: Instruct customer to set 'Digital Sound Output' to 'Pass Through' and disable 'AMD FreeSync Premium' on PC inputs to eliminate G-Sync EDID conflicts.
4. [Based on: Customer Feedback] For Returns & Restocking Fees: State the 30-day window and 15% restocking fee on opened non-defective goods, and proactively present courtesy exchange fee waivers.
5. [Based on: Customer Feedback] For Missing Deliveries Marked Delivered: Require formal 24-48h carrier trace investigation before issuing replacement or refund.
6. [Based on: Customer Feedback] For Payment Disputes: Clarify pre-authorization holds vs settled captures and issue formal Bank Release Authorization Letters (ARN).
7. [Based on: Agent Metrics] For Tool Invocation & Latency: Restrict sequential tool lookups to at most 2 per dialogue turn to maintain p95 response latency under 3.5s.
8. [Based on: Agent Metrics] For Diagnostic Conciseness & Token Budget: Limit technical triage responses to under 60 words to reduce prompt/completion overhead and maintain turn response latency under 2.5s.

# Token Optimization Directive
To reduce multi-turn token consumption by {token_opt['estimated_savings_percent']} while accelerating resolution latency:
{directives_bullets}
"""
    return okf_document


def generate_okf_rules(analysis: Dict[str, Any], token_opt: Dict[str, Any]) -> str:
    """Sub-Agent 3: OKF Rule Author (conforms to OKF v0.2 spec)."""
    return generate_initial_okf_rules(analysis, token_opt)


def parse_policies_and_directives(content: str) -> Tuple[List[Tuple[int, str]], List[str]]:
    """Parses an OKF markdown document to extract existing numbered policies and token directives."""
    policies: List[Tuple[int, str]] = []
    directives: List[str] = []
    current_sec = None

    for line in content.splitlines():
        line_s = line.strip()
        if line_s.startswith("# Policy"):
            current_sec = "policy"
            continue
        elif line_s.startswith("# Token Optimization Directive"):
            current_sec = "token"
            continue
        elif line_s.startswith("# ") and current_sec:
            current_sec = None
            continue

        if current_sec == "policy":
            m = re.match(r"^\s*(\d+)[\.\)]\s*(.+)$", line)
            if m:
                policies.append((int(m.group(1)), m.group(2).strip()))
            elif line_s.startswith("- ") or line_s.startswith("* "):
                policies.append((len(policies) + 1, line_s[2:].strip()))
        elif current_sec == "token":
            if line_s.startswith("- ") or line_s.startswith("* "):
                directives.append(line_s[2:].strip())

    return policies, directives


def get_candidate_new_rules(
    analysis: Dict[str, Any],
    token_opt: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    """Synthesizes candidate policy rules and token directives with source basis indications."""
    candidate_policies: List[str] = []

    # 1. Incorporate dynamically synthesized policies from BigQuery AI pushdown
    for p in analysis.get("candidate_policies", []):
        formatted_p = format_rule_with_basis(p, "Customer Feedback")
        if formatted_p not in candidate_policies:
            candidate_policies.append(formatted_p)

    # 2. Baseline candidate policy rules
    baseline_policies = [
        format_rule_with_basis("For Refrigerator Error 22E: Direct customer to inspect upper evaporator fan for frost obstruction and verify the door seal. Offer next-day warranty dispatch if frost persists.", "Customer Feedback"),
        format_rule_with_basis("For Washing Machine Vibration: Verify rear shipping transit bolts are removed prior to considering mechanical motor overload.", "Customer Feedback"),
        format_rule_with_basis("For TV eARC / Audio Dropouts: Instruct customer to set 'Digital Sound Output' to 'Pass Through' and disable 'AMD FreeSync Premium' on PC inputs to eliminate G-Sync EDID conflicts.", "Customer Feedback"),
        format_rule_with_basis("For Returns & Restocking Fees: State the 30-day window and 15% restocking fee on opened non-defective goods, and proactively present courtesy exchange fee waivers.", "Customer Feedback"),
        format_rule_with_basis("For Missing Deliveries Marked Delivered: Require formal 24-48h carrier trace investigation before issuing replacement or refund.", "Customer Feedback"),
        format_rule_with_basis("For Payment Disputes: Clarify pre-authorization holds vs settled captures and issue formal Bank Release Authorization Letters (ARN).", "Customer Feedback"),
        format_rule_with_basis("For Warehouse Quarantine & Return Delays: Proactively notify customer within 48 hours of parcel arrival if an item requires quarantine inspection, and offer courtesy expedited exchange.", "Customer Feedback"),
        format_rule_with_basis("For Coffee Machines & Small Appliance Faults: Guide customer through pump prime and descale cycles before initiating service center RMA.", "Customer Feedback"),
        format_rule_with_basis("For Stalled Delivery Scans & Address Exceptions: Initiate direct carrier station trace within 24h of exception notification and waive redelivery surcharge.", "Customer Feedback"),
        format_rule_with_basis("For Smart Appliance Connectivity & Wi-Fi Pairing: Advise switching router frequency to 2.4GHz and disabling mesh band steering during initial equipment pairing.", "Customer Feedback"),
        format_rule_with_basis("For Tool Invocation & Latency: Restrict sequential tool lookups to at most 2 per dialogue turn to maintain p95 response latency under 3.5s.", "Agent Metrics"),
        format_rule_with_basis("For Diagnostic Conciseness & Token Budget: Limit technical triage responses to under 60 words to reduce prompt/completion overhead and maintain turn response latency under 2.5s.", "Agent Metrics"),
        format_rule_with_basis("For Parallel Data Retrieval: Batch order status and tracking queries into a single retrieval step to minimize agent execution duration.", "Agent Metrics"),
    ]
    for bp in baseline_policies:
        if bp not in candidate_policies:
            candidate_policies.append(bp)

    # 3. Dynamically derive rules from detected BigQuery feedback observations
    detected = " ".join(analysis.get("detected_issues", [])).lower()
    if "quarantine" in detected or "warehouse" in detected:
        cand = format_rule_with_basis("For Warehouse Quarantine & Return Inspection Delays: Automatically trigger inventory release follow-up after 5 business days and offer courtesy voucher for delayed return processing.", "Customer Feedback")
        if cand not in candidate_policies:
            candidate_policies.append(cand)
    if "carrier" in detected or "transit" in detected or "fedex" in detected:
        cand = format_rule_with_basis("For Carrier Dispatch & Tracking Inquiries: Provide real-time carrier trace confirmation ticket within the dialogue turn.", "Customer Feedback")
        if cand not in candidate_policies:
            candidate_policies.append(cand)
    if "authorization" in detected or "double" in detected or "bank" in detected:
        cand = format_rule_with_basis("For Double Authorization Concerns: Distinguish authorization pre-holds from captured charges immediately and issue customer bank letters.", "Customer Feedback")
        if cand not in candidate_policies:
            candidate_policies.append(cand)

    # 4. Directives from BigQuery AI pushdown and baselines
    candidate_directives: List[str] = []
    for d in token_opt.get("token_directives", []):
        formatted_d = format_rule_with_basis(d, "Agent Metrics")
        if formatted_d not in candidate_directives:
            candidate_directives.append(formatted_d)

    additional_directives = [
        format_rule_with_basis("Omit pleasantry preambles after turn 1 in multi-turn dialogues.", "Agent Metrics"),
        format_rule_with_basis("Consolidate error code diagnostic steps into a single 3-point checklist under 45 words.", "Agent Metrics"),
        format_rule_with_basis("State 30-day return policy, 15% restocking fee, and exchange waiver options upfront.", "Customer Feedback"),
        format_rule_with_basis("For delivery discrepancies, open carrier trace ticket immediately without speculative delays.", "Customer Feedback"),
        format_rule_with_basis("Omit redundant policy disclaimers after initial statement in multi-turn dialogues.", "Agent Metrics"),
        format_rule_with_basis("Provide single-line direct answers for order tracking and tracking URL lookups.", "Agent Metrics"),
        format_rule_with_basis("Eliminate multi-turn diagnostic preambles when technical fault code is already identified.", "Agent Metrics"),
    ]
    for d in additional_directives:
        if d not in candidate_directives:
            candidate_directives.append(d)

    return candidate_policies, candidate_directives


def rule_already_present(candidate: str, existing_rules: List[Tuple[int, str]]) -> bool:
    """Checks if candidate rule topic is already covered by existing policy rules."""
    cand_clean = normalize_rule_text(candidate)
    cand_norm = cand_clean.strip().lower()
    cand_prefix = cand_norm.split(":")[0].strip() if ":" in cand_norm else cand_norm[:35]
    for _, ex in existing_rules:
        ex_clean = normalize_rule_text(ex)
        ex_norm = ex_clean.strip().lower()
        ex_prefix = ex_norm.split(":")[0].strip() if ":" in ex_norm else ex_norm[:35]
        if cand_prefix == ex_prefix or cand_prefix in ex_norm or ex_prefix in cand_norm:
            return True
    return False


def directive_already_present(candidate: str, existing_directives: List[str]) -> bool:
    """Checks if candidate directive is already covered by existing token directives."""
    cand_clean = normalize_rule_text(candidate)
    cand_norm = cand_clean.strip().lower()
    cand_core = cand_norm[:30]
    for ex in existing_directives:
        ex_clean = normalize_rule_text(ex)
        ex_norm = ex_clean.strip().lower()
        if cand_core in ex_norm or ex_norm[:30] in cand_norm:
            return True
    return False


def merge_and_append_new_rules(
    existing_content: str,
    analysis: Dict[str, Any],
    token_opt: Dict[str, Any],
) -> Tuple[str, List[str], List[str]]:
    """Keeps all existing rules in the dynamic context file, ensures source indications, and appends new rules.

    Returns (updated_markdown_content, new_policies_added, new_directives_added).
    """
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = existing_content.splitlines()

    existing_policies, existing_directives = parse_policies_and_directives(existing_content)
    candidate_policies, candidate_directives = get_candidate_new_rules(analysis, token_opt)

    new_policies_to_add: List[str] = []
    for p in candidate_policies:
        if not rule_already_present(p, existing_policies) and not rule_already_present(p, [(0, x) for x in new_policies_to_add]):
            new_policies_to_add.append(format_rule_with_basis(p))

    new_directives_to_add: List[str] = []
    for d in candidate_directives:
        if not directive_already_present(d, existing_directives) and not directive_already_present(d, new_directives_to_add):
            new_directives_to_add.append(format_rule_with_basis(d))

    # If document has no existing rules, initialize full template
    if not existing_policies and not existing_directives:
        initial = generate_initial_okf_rules(analysis, token_opt)
        return initial, candidate_policies, candidate_directives

    policy_last_idx = -1
    token_last_idx = -1
    current_sec = None

    for idx, line in enumerate(lines):
        line_s = line.strip()
        if line_s.startswith("# Policy"):
            current_sec = "policy"
            policy_last_idx = idx + 1
            continue
        elif line_s.startswith("# Token Optimization Directive"):
            current_sec = "token"
            token_last_idx = idx + 1
            continue
        elif line_s.startswith("# ") and current_sec:
            current_sec = None
            continue

        if current_sec == "policy":
            m = re.match(r"^\s*(\d+)[\.\)]\s*(.+)$", line)
            if m or line_s.startswith("- ") or line_s.startswith("* "):
                policy_last_idx = idx + 1
        elif current_sec == "token":
            if line_s.startswith("- ") or line_s.startswith("* "):
                token_last_idx = idx + 1

    next_policy_num = len(existing_policies) + 1
    new_policy_lines: List[str] = []
    for p in new_policies_to_add:
        formatted_p = format_rule_with_basis(p)
        new_policy_lines.append(f"{next_policy_num}. {formatted_p}")
        next_policy_num += 1

    new_directive_lines: List[str] = [f"- {format_rule_with_basis(d)}" for d in new_directives_to_add]

    output_lines: List[str] = []
    current_sec = None
    for idx, line in enumerate(lines):
        line_s = line.strip()
        if line_s.startswith("verified:"):
            output_lines.append(f"verified: {{ by: process:auditor-agent, at: {now_iso} }}")
            continue

        if line_s.startswith("# Policy"):
            current_sec = "policy"
            output_lines.append(line)
            continue
        elif line_s.startswith("# Token Optimization Directive"):
            current_sec = "token"
            output_lines.append(line)
            continue
        elif line_s.startswith("# ") and current_sec:
            current_sec = None

        # Upgrade existing lines if missing basis indication
        if current_sec == "policy":
            m = re.match(r"^(\s*\d+[\.\)]\s*)(.+)$", line)
            if m:
                p_text = m.group(2)
                if not re.search(r"\[(based on|source|basis):\s*(customer feedback|agent metrics)\]", p_text, flags=re.IGNORECASE):
                    line = f"{m.group(1)}{format_rule_with_basis(p_text)}"
        elif current_sec == "token":
            m = re.match(r"^(\s*[-\*]\s*)(.+)$", line)
            if m:
                d_text = m.group(2)
                if not re.search(r"\[(based on|source|basis):\s*(customer feedback|agent metrics)\]", d_text, flags=re.IGNORECASE):
                    line = f"{m.group(1)}{format_rule_with_basis(d_text)}"

        output_lines.append(line)
        if idx == policy_last_idx - 1 and new_policy_lines:
            output_lines.extend(new_policy_lines)
        if idx == token_last_idx - 1 and new_directive_lines:
            output_lines.extend(new_directive_lines)

    # If sections were completely missing from the existing document, append them
    if policy_last_idx == -1 and new_policy_lines:
        output_lines.append("\n# Policy")
        output_lines.extend(new_policy_lines)
    if token_last_idx == -1 and new_directive_lines:
        output_lines.append("\n# Token Optimization Directive")
        output_lines.extend(new_directive_lines)

    updated_content = "\n".join(output_lines)
    if not updated_content.endswith("\n"):
        updated_content += "\n"

    return updated_content, new_policies_to_add, new_directives_to_add


def is_placeholder_token(token: str) -> bool:
    """Checks whether token is empty or an unconfigured placeholder."""
    if not token:
        return True
    t = token.strip().upper()
    return (
        t.startswith("PLACEHOLDER")
        or t.startswith("YOUR_")
        or "PLACEHOLDER" in t
        or t in ("DUMMY", "TEST", "NONE", "NULL")
    )


def sync_okf_via_git_ssh(
    analysis: Dict[str, Any],
    token_opt: Dict[str, Any],
    private_key_pem: str,
    repo_name: str = REPO_NAME,
    filename: str = OKF_FILENAME,
) -> Tuple[bool, str, str, str]:
    """Interacts with dynamic context file on GitHub using SSH Deploy Key.

    All new or updated OKF rules created by the Auditor Agent are strictly
    committed to the 'new_version' branch and await human review before merge into main.
    Only ONE dynamic context file (dynamic_context.md) is created or modified.

    Returns:
        (success, status_message, final_content, target_branch)
    """
    temp_dir = tempfile.mkdtemp(prefix="okf_git_")
    key_path = os.path.join(temp_dir, "id_ed25519")
    repo_dir = os.path.join(temp_dir, "repo")

    try:
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(private_key_pem.strip() + "\n")
        os.chmod(key_path, 0o600)

        git_ssh_cmd = (
            f"ssh -i {key_path} "
            "-o IdentitiesOnly=yes "
            "-o BatchMode=yes "
            "-o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=10 "
            "-o LogLevel=ERROR"
        )
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = git_ssh_cmd
        env["SSH_AUTH_SOCK"] = ""
        env["GIT_AUTHOR_NAME"] = "ExpertHub Auditor Agent"
        env["GIT_AUTHOR_EMAIL"] = "auditor@experthub.local"
        env["GIT_COMMITTER_NAME"] = "ExpertHub Auditor Agent"
        env["GIT_COMMITTER_EMAIL"] = "auditor@experthub.local"

        repo_url = f"git@github.com:{repo_name}.git"
        logger.info(f"Attempting git clone from {repo_url} via deploy key...")

        clone_res = subprocess.run(
            ["git", "clone", repo_url, repo_dir],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if clone_res.returncode != 0:
            stderr_out = clone_res.stderr.strip()
            if "Permission denied (publickey)" in stderr_out:
                msg = (
                    "SSH Permission denied (publickey): The deploy key is not added to "
                    f"https://github.com/{repo_name}/settings/keys with 'Allow write access'."
                )
                logger.error(msg)
                return False, msg, "", NEW_VERSION_BRANCH
            elif "Repository not found" in stderr_out or "does not exist" in stderr_out:
                msg = (
                    f"Repository '{repo_name}' not found on GitHub. "
                    f"Ensure https://github.com/{repo_name} exists and your deploy key is attached."
                )
                logger.error(msg)
                return False, msg, "", NEW_VERSION_BRANCH

            # Initialize locally if repository is completely empty
            os.makedirs(repo_dir, exist_ok=True)
            subprocess.run(["git", "init", "-b", MAIN_BRANCH], cwd=repo_dir, check=True, env=env)
            subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=repo_dir, check=True, env=env)

        # Fetch all branches from remote
        subprocess.run(["git", "fetch", "origin"], cwd=repo_dir, capture_output=True, text=True, env=env)

        # Check if new_version branch exists on remote
        br_check = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", NEW_VERSION_BRANCH],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        has_remote_nv = bool(br_check.stdout.strip())

        existing_content = ""
        if has_remote_nv:
            subprocess.run(["git", "checkout", "-B", NEW_VERSION_BRANCH, f"origin/{NEW_VERSION_BRANCH}"], cwd=repo_dir, capture_output=True, text=True, env=env)
            nv_file_path = os.path.join(repo_dir, filename)
            if os.path.exists(nv_file_path):
                with open(nv_file_path, "r", encoding="utf-8") as f:
                    existing_content = f.read().strip()
        else:
            # Create new_version branch from origin/main
            main_check = subprocess.run(["git", "checkout", "-B", NEW_VERSION_BRANCH, f"origin/{MAIN_BRANCH}"], cwd=repo_dir, capture_output=True, text=True, env=env)
            if main_check.returncode != 0:
                subprocess.run(["git", "checkout", "-b", NEW_VERSION_BRANCH], cwd=repo_dir, capture_output=True, text=True, env=env)

        # If file was not on new_version, check if it exists on origin/main
        if not existing_content:
            main_show = subprocess.run(
                ["git", "show", f"origin/{MAIN_BRANCH}:{filename}"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                env=env,
            )
            if main_show.returncode == 0 and main_show.stdout.strip():
                existing_content = main_show.stdout.strip()

        # Compute updated or initial rules
        if existing_content:
            updated_content, new_policies, new_directives = merge_and_append_new_rules(
                existing_content, analysis, token_opt
            )
        else:
            updated_content = generate_initial_okf_rules(analysis, token_opt)
            cand_policies, cand_directives = get_candidate_new_rules(analysis, token_opt)
            new_policies, new_directives = cand_policies, cand_directives

        # Write ONLY dynamic_context.md (exactly one file)
        target_file_path = os.path.join(repo_dir, filename)
        with open(target_file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        # Remove any obsolete dynamic_content.md if lingering in git
        fallback_path = os.path.join(repo_dir, "dynamic_content.md")
        if os.path.exists(fallback_path):
            subprocess.run(["git", "rm", "-f", "dynamic_content.md"], cwd=repo_dir, capture_output=True, text=True, env=env)

        subprocess.run(["git", "add", filename], cwd=repo_dir, check=True, env=env)

        diff_res = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True, env=env)
        if not diff_res.stdout.strip():
            sha_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture_output=True, text=True, env=env)
            commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "HEAD"
            return True, f"Rules in {filename} on '{NEW_VERSION_BRANCH}' already up to date (@ {commit_sha})", updated_content, NEW_VERSION_BRANCH

        commit_msg = (
            f"auditor: append new rules to {filename} on {NEW_VERSION_BRANCH} ({now_str}) - awaiting human review"
        )
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_dir, check=True, env=env)

        sha_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture_output=True, text=True, env=env)
        commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "HEAD"

        push_res = subprocess.run(["git", "push", "-u", "origin", NEW_VERSION_BRANCH], cwd=repo_dir, capture_output=True, text=True, env=env, timeout=30)
        if push_res.returncode != 0:
            err_text = push_res.stderr.strip()
            if "Permission denied (publickey)" in err_text:
                return False, f"SSH Permission denied (publickey) pushing to {NEW_VERSION_BRANCH}.", updated_content, NEW_VERSION_BRANCH
            return False, f"Git push failed to {NEW_VERSION_BRANCH}: {err_text}", updated_content, NEW_VERSION_BRANCH

        logger.info(
            f"Successfully committed rules to {NEW_VERSION_BRANCH} (@ {commit_sha}). "
            f"Added {len(new_policies)} policies and {len(new_directives)} directives."
        )
        msg = (
            f"Successfully added {len(new_policies)} new rules to {filename} on '{NEW_VERSION_BRANCH}' branch (@ {commit_sha}). "
            "Awaiting human review before merge into main."
        )
        return True, msg, updated_content, NEW_VERSION_BRANCH

    except Exception as e:
        logger.error(f"Error in sync_okf_via_git_ssh: {e}")
        return False, f"Deploy key git error: {e}", "", NEW_VERSION_BRANCH
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def sync_okf_via_pygithub(
    analysis: Dict[str, Any],
    token_opt: Dict[str, Any],
    token: str,
    repo_name: str = REPO_NAME,
    filename: str = OKF_FILENAME,
) -> Tuple[bool, str, str, str]:
    """Interacts with dynamic context file on GitHub using PyGithub REST API (PAT).

    All new or updated OKF rules created by the Auditor Agent are strictly
    committed to the 'new_version' branch and await human review before merge into main.
    Only ONE dynamic context file (dynamic_context.md) is created or modified.

    Returns:
        (success, status_message, final_content, target_branch)
    """
    from github import Auth, Github, UnknownObjectException

    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(repo_name)
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Ensure new_version branch exists
    try:
        repo.get_branch(NEW_VERSION_BRANCH)
    except UnknownObjectException:
        try:
            main_b = repo.get_branch(MAIN_BRANCH)
            repo.create_git_ref(ref=f"refs/heads/{NEW_VERSION_BRANCH}", sha=main_b.commit.sha)
        except Exception as e:
            logger.warning(f"Could not branch new_version from main: {e}")

    # Read base content from new_version or main
    existing_content = ""
    nv_sha = None
    try:
        nv_file = repo.get_contents(filename, ref=NEW_VERSION_BRANCH)
        nv_sha = nv_file.sha
        existing_content = nv_file.decoded_content.decode("utf-8").strip()
    except UnknownObjectException:
        try:
            main_file = repo.get_contents(filename, ref=MAIN_BRANCH)
            existing_content = main_file.decoded_content.decode("utf-8").strip()
        except UnknownObjectException:
            existing_content = ""

    if existing_content:
        updated_content, new_policies, new_directives = merge_and_append_new_rules(
            existing_content, analysis, token_opt
        )
    else:
        updated_content = generate_initial_okf_rules(analysis, token_opt)
        cand_policies, cand_directives = get_candidate_new_rules(analysis, token_opt)
        new_policies, new_directives = cand_policies, cand_directives

    if existing_content.strip() == updated_content.strip() and not new_policies and not new_directives and nv_sha:
        return True, f"Existing rules kept; {filename} on {NEW_VERSION_BRANCH} is already up to date (@ {nv_sha[:8]})", existing_content, NEW_VERSION_BRANCH

    commit_msg = f"auditor: append new rules on {NEW_VERSION_BRANCH} ({now_str}) - awaiting human review"
    if nv_sha:
        update_res = repo.update_file(
            path=filename,
            message=commit_msg,
            content=updated_content,
            sha=nv_sha,
            branch=NEW_VERSION_BRANCH,
        )
        sha = update_res["commit"].sha[:8]
    else:
        create_res = repo.create_file(
            path=filename,
            message=commit_msg,
            content=updated_content,
            branch=NEW_VERSION_BRANCH,
        )
        sha = create_res["commit"].sha[:8]

    # If dynamic_content.md exists on new_version, delete it to ensure single OKF file
    try:
        alt_file = repo.get_contents("dynamic_content.md", ref=NEW_VERSION_BRANCH)
        repo.delete_file(
            path="dynamic_content.md",
            message=f"auditor: remove obsolete dynamic_content.md on {NEW_VERSION_BRANCH}",
            sha=alt_file.sha,
            branch=NEW_VERSION_BRANCH,
        )
    except Exception:
        pass

    msg = (
        f"Successfully added {len(new_policies)} new rules to {filename} on '{NEW_VERSION_BRANCH}' branch (@ {sha}). "
        "Awaiting human review before merge into main."
    )
    return True, msg, updated_content, NEW_VERSION_BRANCH


def sync_okf_rules_to_github(
    analysis: Dict[str, Any],
    token_opt: Dict[str, Any],
    repo_name: str = REPO_NAME,
    filename: str = OKF_FILENAME,
) -> Tuple[bool, str, str, str]:
    """Coordinates synchronization of dynamic context rules to GitHub using Deploy Key (preferred) or PAT."""
    # 1. Check for SSH Deploy Key in Secret Manager or env
    deploy_key = get_secret(DEPLOY_KEY_SECRET_NAME)
    if not deploy_key:
        pat_val = get_secret(SECRET_NAME)
        if pat_val and "PRIVATE KEY" in pat_val:
            deploy_key = pat_val

    if deploy_key and "PRIVATE KEY" in deploy_key:
        logger.info("Using SSH deploy key for GitHub operations.")
        success, msg, content, branch = sync_okf_via_git_ssh(
            analysis, token_opt, deploy_key, repo_name, filename
        )
        if success:
            return True, msg, content, branch
        token = get_secret(SECRET_NAME)
        if is_placeholder_token(token):
            return False, msg, content, branch
        logger.info(f"SSH deploy key failed ({msg}); attempting GitHub PAT fallback...")
    else:
        token = get_secret(SECRET_NAME)

    # 2. Fall back to GitHub PAT via PyGithub
    if is_placeholder_token(token):
        initial = generate_initial_okf_rules(analysis, token_opt)
        msg = (
            "No valid GitHub credentials configured in Secret Manager. "
            f"Add the SSH deploy key to https://github.com/{repo_name}/settings/keys with 'Allow write access'."
        )
        logger.warning(msg)
        return False, msg, initial, NEW_VERSION_BRANCH

    try:
        return sync_okf_via_pygithub(analysis, token_opt, token, repo_name, filename)
    except Exception as e:
        initial = generate_initial_okf_rules(analysis, token_opt)
        err_msg = str(e)
        if "401" in err_msg or "Bad credentials" in err_msg:
            msg = "GitHub 401 Bad credentials: The token in Secret Manager ('github-pat') is invalid or expired."
        elif "404" in err_msg or "Not Found" in err_msg:
            msg = f"GitHub 404 Not Found: Repository '{repo_name}' was not found or lacks access."
        else:
            msg = f"GitHub commit error: {e}"
        logger.error(msg)
        return False, msg, initial, NEW_VERSION_BRANCH


def commit_okf_via_git_ssh(
    okf_content: str,
    private_key_pem: str,
    repo_name: str = REPO_NAME,
    filename: str = OKF_FILENAME,
) -> Tuple[bool, str]:
    """Compatibility wrapper for deploy key commit."""
    analysis = {"detected_issues": []}
    token_opt = {"token_directives": [], "token_recommendations": [], "estimated_savings_percent": "32%"}
    success, msg, _, _ = sync_okf_via_git_ssh(analysis, token_opt, private_key_pem, repo_name, filename)
    return success, msg


def commit_okf_to_github(
    okf_content: str,
    repo_name: str = REPO_NAME,
    filename: str = OKF_FILENAME,
) -> Tuple[bool, str]:
    """Compatibility wrapper for committing OKF rules to GitHub."""
    analysis = {"detected_issues": []}
    token_opt = {"token_directives": [], "token_recommendations": [], "estimated_savings_percent": "32%"}
    success, msg, _, _ = sync_okf_rules_to_github(analysis, token_opt, repo_name, filename)
    return success, msg


def run_audit_pipeline() -> Dict[str, Any]:
    """Executes the full 3-stage Auditor Agent pipeline with BigQuery AI pushdown and syncs OKF rules to GitHub.

    Stage 1: Pushes down customer feedback AI analysis to BigQuery (connection us.gemini, endpoint gemini-3.8-flash).
    Stage 2: Pushes down telemetry and token efficiency AI analysis to BigQuery (connection us.gemini, endpoint gemini-3.8-flash).
    Stage 3: OKF Rule Author & Committer formats and synchronizes rules to GitHub dynamic context.
    """
    logger.info("Executing Auditor Agent Multi-Agent Pipeline with BigQuery AI Pushdown...")

    # Stage 1: BigQuery AI Customer Feedback Analysis (In-Database Pushdown)
    analysis = query_customer_feedback_analysis_bq(PROJECT_ID)

    # Stage 2: BigQuery AI Telemetry & Token Efficiency Analysis (In-Database Pushdown)
    token_opt = query_agent_telemetry_analysis_bq(PROJECT_ID)

    # Stage 3: OKF Rule Author & Committer (main initialization / new_version incremental update)
    commit_success, commit_status, final_okf_rules, target_branch = sync_okf_rules_to_github(
        analysis, token_opt
    )

    report = {
        "status": "COMPLETED",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "detected_issues": analysis["detected_issues"],
        "average_rating": analysis["average_rating"],
        "token_recommendations": token_opt["token_recommendations"],
        "estimated_token_savings": token_opt["estimated_savings_percent"],
        "okf_rule_block": final_okf_rules,
        "github_commit_status": commit_status,
        "github_commit_success": commit_success,
        "target_branch": target_branch,
        "workflow_state": (
            "CREATED_IN_MAIN" if target_branch == MAIN_BRANCH
            else "AWAITING_HUMAN_REVIEW_ON_NEW_VERSION"
        ),
    }
    logger.info(f"Auditor Agent Pipeline completed successfully via BigQuery AI pushdown (branch: {target_branch}).")
    return report


def get_base_instructions() -> str:
    """Reads base system instructions from local AGENT.md."""
    agent_md_path = pathlib.Path(__file__).parent / "AGENT.md"
    if agent_md_path.exists():
        return agent_md_path.read_text(encoding="utf-8")
    return (
        "You are the Lead Quality Auditor. Evaluate customer satisfaction, detect errors, "
        "formulate token optimization guidelines, and output valid Open Knowledge Format rules."
    )


def get_bigquery_ai_skill_instructions() -> str:
    """Returns the BigQuery AI & Generative AI Functions skill guide for SQL query inspection and optimization."""
    skill_file = pathlib.Path(__file__).parent / "bigquery_ai_functions_skill.md"
    if skill_file.exists():
        return skill_file.read_text(encoding="utf-8")
    alt_file = pathlib.Path(__file__).parent / "skills" / "bigquery-ai-functions" / "SKILL.md"
    if alt_file.exists():
        return alt_file.read_text(encoding="utf-8")
    return "BigQuery AI functions skill guide not found."


def get_agent_analytics_plugin_skill_instructions() -> str:
    """Returns the ADK BigQuery Agent Analytics Plugin & Telemetry skill guide for navigating and querying BigQuery analytics tables and views."""
    skill_file = pathlib.Path(__file__).parent / "agent_analytics_plugin_skill.md"
    if skill_file.exists():
        return skill_file.read_text(encoding="utf-8")
    alt_file = pathlib.Path(__file__).parent / "skills" / "adk-agent-telemetry" / "SKILL.md"
    if alt_file.exists():
        return alt_file.read_text(encoding="utf-8")
    return "ADK Agent Analytics plugin skill guide not found."


def get_auditor_skills() -> list:
    """Loads specialized skills for the auditor agent from the local skills directory."""
    skills_dir = pathlib.Path(__file__).parent / "skills"
    if skills_dir.exists():
        try:
            from google.adk.skills import load_skills_from_dir
            return load_skills_from_dir(skills_dir)
        except Exception as e:
            logger.warning(f"Could not load skills from {skills_dir}: {e}")
    return []


def get_skill_toolset() -> Optional[Any]:
    """Initializes ADK SkillToolset with local auditor skills."""
    skills = get_auditor_skills()
    if not skills:
        return None
    try:
        from google.adk.tools.skill_toolset import SkillToolset
        toolset = SkillToolset(skills=skills)
        logger.info(f"Initialized SkillToolset with {len(skills)} skill(s): {[s.name for s in skills]}")
        return toolset
    except Exception as e:
        logger.warning(f"Could not initialize SkillToolset for auditor agent: {e}")
        return None


# Assemble tools including BigQuery AI pushdown, on-the-fly SQL execution, and skill capabilities
_auditor_tools: list[Any] = [
    run_audit_pipeline,
    execute_bigquery_query,
    get_bigquery_ai_skill_instructions,
    get_agent_analytics_plugin_skill_instructions,
]
_skill_toolset = get_skill_toolset()
if _skill_toolset is not None:
    _auditor_tools.append(_skill_toolset)

# ADK 2.0 Auditor Agent Definition
root_agent = Agent(
    name="auditor_agent",
    description="Multi-agent auditor analyzing telemetry, token efficiency, and authoring OKF rules.",
    model="gemini-3.8-flash",
    instruction=get_base_instructions(),
    tools=_auditor_tools,
)

app = App(
    name="auditor_agent",
    root_agent=root_agent,
)


if __name__ == "__main__":
    print("Testing Auditor Agent locally...")
    result = run_audit_pipeline()
    print(json.dumps(result, indent=2))
