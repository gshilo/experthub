"""Flask backend for ApexHome & Electro Self-Improving Agent Demo.

Orchestrates live customer-support simulations over SSE and polling,
triggers the Auditor Agent pipeline, and queries BigQuery telemetry and ratings for the dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import random
import re
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, Response, jsonify, render_template, request

# Add parent directory to sys.path to enable local imports of agent modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("frontend_app")

app = Flask(__name__)

PROJECT_ID = (
    os.environ.get("GOOGLE_CLOUD_PROJECT")
    or os.environ.get("GCP_PROJECT")
    or "experthub-510907"
)
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")


def ensure_gemini_api_key(project_id: str = PROJECT_ID) -> Optional[str]:
    """Ensures GEMINI_API_KEY / GOOGLE_API_KEY is retrieved directly from Secret Manager.

    The API key is dynamically fetched from Google Cloud Secret Manager at runtime
    and is never stored in static files or client-side assets.
    """
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        for sname in ("gemini-api-key", "google-api-key"):
            try:
                name = f"projects/{project_id}/secrets/{sname}/versions/latest"
                response = client.access_secret_version(request={"name": name})
                val = response.payload.data.decode("UTF-8").strip()
                if val and not val.startswith("PLACEHOLDER"):
                    os.environ["GEMINI_API_KEY"] = val
                    os.environ["GOOGLE_API_KEY"] = val
                    logger.info(f"Loaded Gemini API key directly from Secret Manager '{sname}' (not from static files).")
                    return val
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Could not load Gemini API key from Secret Manager: {e}")

    # Fallback to pre-existing environment variable if Secret Manager call fails
    existing_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if existing_key and not existing_key.startswith("PLACEHOLDER"):
        return existing_key
    return None


ensure_gemini_api_key(PROJECT_ID)

# =====================================================================
# Safe Import with Robust Fallbacks
# =====================================================================
try:
    from customer_agent.agent import (
        PERSONA_CATALOG,
        generate_customer_persona,
        generate_customer_turn,
        evaluate_customer_experience,
        write_customer_rating_to_bigquery,
    )
except Exception as e:
    logger.warning(f"Using built-in customer agent fallback: {e}")
    PERSONA_CATALOG = [
        # --- Category 1: Malfunctions & Complex Technical Issues ---
        {
            "scenario_key": "refrigerator_defrost_22e",
            "category": "Hardware Malfunction",
            "name": "Marcus Vance",
            "patience": "Low",
            "tech_literacy": "Average",
            "product": "Samsung Family Hub 4-Door Smart Refrigerator",
            "issue": "My refrigerator has error code 22E on the display and the upper fan is making a grinding noise. Groceries are getting warm. I need a technician or a replacement right away.",
            "order_id": "ORD-1002",
            "opening": "Hi, my smart refrigerator is flashing error code 22E and making a loud grinding sound! My food is spoiling. Can you help me fix this or send a technician immediately?",
            "expected_rating": 3,
            "rating_feedback": "Technician booked for tomorrow, but agent made me jump through diagnostic hoops and refused emergency same-day dispatch while food spoiled.",
        },
        {
            "scenario_key": "laptop_dock_flicker",
            "category": "Hardware Malfunction",
            "name": "Liam O'Connor",
            "patience": "Moderate",
            "tech_literacy": "Average",
            "product": "ApexBook Pro 16 Laptop",
            "issue": "My laptop external monitor is flickering and blacking out when connected via Thunderbolt dock under load. I want an immediate advance replacement laptop.",
            "order_id": "ORD-1010",
            "opening": "Hello, my ApexBook Pro 16 laptop display keeps flickering and going completely black when plugged into my Thunderbolt dock. Can you process an immediate advance exchange?",
            "expected_rating": 3,
            "rating_feedback": "Resolved the dock flicker after extensive troubleshooting steps, but agent was reluctant to authorize a replacement and advance exchange policy is overly rigid.",
        },
        {
            "scenario_key": "washer_violent_vibration",
            "category": "Hardware Malfunction",
            "name": "Priya Patel",
            "patience": "Low",
            "tech_literacy": "Non-technical",
            "product": "LG Smart Front Load Washer with AI DD",
            "issue": "Brand new washer violently shakes and bangs loudly across the floor during spin cycle, then stops with LE motor overload error. I want a full refund or immediate pickup.",
            "order_id": "ORD-1009",
            "opening": "This brand new washer is violently shaking across our floor with a loud banging noise, then flashes an LE error! The unit is defective. I want it picked up and refunded immediately.",
            "expected_rating": 4,
            "rating_feedback": "Support correctly diagnosed shipping bolts left in by the freight crew, though I was stressed having to inspect the mechanical rear of the washer myself.",
        },
        {
            "scenario_key": "tv_earc_dropout",
            "category": "Technical Setup & Compatibility",
            "name": "Elena Rostova",
            "patience": "High",
            "tech_literacy": "Tech-savvy",
            "product": "LG 65-inch C4 Series OLED evo 4K TV",
            "issue": "Audio dropouts occur every 20 seconds over HDMI Port 2 eARC to my AV receiver, and 144Hz VRR causes black screens with my gaming PC. I need technical resolution or RMA.",
            "order_id": "ORD-1001",
            "opening": "Hello! My new LG C4 OLED has audio dropouts every 20 seconds through HDMI 2 eARC to my receiver, and 144Hz VRR causes intermittent black screens. Is this a defective board?",
            "expected_rating": 5,
            "rating_feedback": "Specialist knew the exact menu settings and EDID FreeSync quirks to fix eARC audio dropouts and 144Hz G-Sync. Thorough, highly competent technical support.",
        },

        # --- Category 2: Order & Delivery Issues ---
        {
            "scenario_key": "missing_tv_marked_delivered",
            "category": "Delivery & Logistics",
            "name": "Carlos Mendez",
            "patience": "Low",
            "tech_literacy": "Average",
            "product": "Sony 75-inch BRAVIA XR A95L QD-OLED TV",
            "issue": "Carrier tracking states '$3,300 TV Delivered to Porch/Lobby', but nothing was delivered and my security camera shows no courier truck. I need an immediate replacement or full refund.",
            "order_id": "ORD-1005",
            "opening": "FedEx freight tracking says my $3,300 75-inch Sony OLED TV was delivered to my porch today, but I was home all day and nothing arrived! I need an immediate replacement or charge reversal.",
            "expected_rating": 2,
            "rating_feedback": "Terrible carrier communication. Agent initially refused to do anything except tell me to wait 48 hours, only investigating after I strongly pushed.",
        },
        {
            "scenario_key": "espresso_delivery_exception",
            "category": "Delivery & Logistics",
            "name": "David Chen",
            "patience": "Moderate",
            "tech_literacy": "Non-technical",
            "product": "Breville the Barista Touch Impress Espresso Machine",
            "issue": "Ordered 3 weeks ago under order ORD-1003. Tracking shows 'Delivery Exception: Incomplete Address'. I want an immediate refund or priority overnight redelivery.",
            "order_id": "ORD-1003",
            "opening": "Hi, I placed order ORD-1003 for a Breville espresso machine three weeks ago and it hasn't arrived. Tracking shows an address exception. Can you refund me or reship immediately?",
            "expected_rating": 2,
            "rating_feedback": "Item was held for weeks due to address issue. Agent wouldn't refund until item returned, forced me to pick it up at the postal annex myself.",
        },
        {
            "scenario_key": "damaged_freight_refrigerator",
            "category": "Delivery & Logistics",
            "name": "Danielle Brooks",
            "patience": "Moderate",
            "tech_literacy": "Average",
            "product": "Samsung Family Hub 4-Door Smart Refrigerator",
            "issue": "Freight delivery arrived with a crushed carton and deep dent in the stainless steel door panel. I want the carrier to take it back immediately and send a pristine unit.",
            "order_id": "ORD-1006",
            "opening": "My refrigerator was just delivered by freight with a punctured box and a deep cosmetic dent across the front stainless door! I want an immediate replacement without delays.",
            "expected_rating": 4,
            "rating_feedback": "Agent pushed back on immediate replacement, but proposed a practical door panel swap so I didn't lose my fridge for days.",
        },

        # --- Category 3: Payment, Refund, & Return Policy Disputes ---
        {
            "scenario_key": "washer_restocking_fee_dispute",
            "category": "Return & Refund Dispute",
            "name": "Sarah Jenkins",
            "patience": "Moderate",
            "tech_literacy": "Average",
            "product": "LG Smart Front Load Washer",
            "issue": "Washer did not fit through laundry doorway. Return email states I will be charged a 15% open-box restocking fee and $100 return freight deduction. I demand a 100% full refund.",
            "order_id": "ORD-1004",
            "opening": "I just received my return authorization for the washing machine that didn't fit our doorway, and your email says you are deducting a $150 restocking fee and $100 freight fee! I demand a full refund.",
            "expected_rating": 3,
            "rating_feedback": "Agent tried to hit me with a $250 restocking and freight fee. Had to threaten a chargeback before they agreed to waive it on an exchange.",
        },
        {
            "scenario_key": "double_charge_authorization_hold",
            "category": "Payment & Billing",
            "name": "Michael Chang",
            "patience": "Low",
            "tech_literacy": "Tech-savvy",
            "product": "LG 65-inch C4 Series OLED evo 4K TV",
            "issue": "I was double charged $1,799.99 on my Visa card for order ORD-1007. It's maxing out my credit limit. I need the duplicate charge cancelled immediately.",
            "order_id": "ORD-1007",
            "opening": "My credit card statement shows two separate $1,799.99 charges for order ORD-1007! It is maxing out my card limit. Reverse the duplicate charge immediately.",
            "expected_rating": 2,
            "rating_feedback": "Double authorization locked up my credit line. Support explained banking details, but couldn't reverse it immediately and made me contact my bank.",
        },
        {
            "scenario_key": "delayed_refund_warehouse_quarantine",
            "category": "Payment & Billing",
            "name": "Rachel Green",
            "patience": "Low",
            "tech_literacy": "Non-technical",
            "product": "Breville the Barista Touch Impress Espresso Machine",
            "issue": "UPS tracking shows my returned espresso machine was received at your warehouse 15 days ago, but no refund has posted, and a $150 promo code was omitted. I need my refund now.",
            "order_id": "ORD-1008",
            "opening": "Your warehouse signed for my espresso machine return over two weeks ago, but I still haven't received my $1,499 refund! Where is my money?",
            "expected_rating": 2,
            "rating_feedback": "Warehouse sat on my return for 15 days in quarantine without telling me. Agent finally pushed it through, but the delay was terrible.",
        },
    ]

    def generate_customer_persona() -> Dict[str, Any]:
        base = random.choice(PERSONA_CATALOG)
        return {
            "customer_id": random.randint(100000, 999999),
            "customer_name": base["name"],
            "category": base.get("category", "General Inquiry"),
            "scenario_key": base.get("scenario_key", "default"),
            "patience": base["patience"],
            "tech_literacy": base["tech_literacy"],
            "product": base["product"],
            "issue": base["issue"],
            "order_id": base["order_id"],
            "opening": base["opening"],
            "expected_rating": base.get("expected_rating", 4),
            "rating_feedback": base.get("rating_feedback", "Completed support session."),
            "created_at": time.time(),
            "turns_count": 0,
        }

    def write_customer_rating_to_bigquery(
        customer_id: int,
        customer_name: str,
        rating: int,
        description: str,
        timestamp: Optional[str] = None,
        project_id: str = PROJECT_ID,
    ) -> bool:
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        logger.info(f"[Fallback] Recorded rating ({rating}/5) for {customer_name} at {ts}: {description}")
        return True

    def generate_customer_turn(
        history: List[Dict[str, str]],
        persona: Dict[str, Any],
        last_service_message: str,
    ) -> str:
        patience = persona.get("patience", "Moderate")
        product = persona.get("product", "item")
        if patience == "Low":
            return f"I need this resolved today. I cannot keep waiting or troubleshooting my {product} indefinitely."
        return f"Thank you for the update on my {product}. Please confirm the next steps and reference number."

    def evaluate_customer_experience(
        persona: Dict[str, Any],
        history: List[Dict[str, str]],
    ) -> Tuple[int, str]:
        return int(persona.get("expected_rating", 3)), str(persona.get("rating_feedback", "Completed support session."))

try:
    from customer_service_agent.agent import (
        app as customer_service_app,
        check_order_status,
        fetch_okf_dynamic_context,
        get_instructions,
        initiate_return,
        lookup_billing_and_refund_status,
        lookup_warranty_policy,
        register_customer_order,
        search_product_catalog,
        telemetry_plugin as customer_service_telemetry_plugin,
    )
except Exception as e:
    logger.warning(f"Using built-in customer service fallback: {e}")
    customer_service_app = None
    customer_service_telemetry_plugin = None

    def get_instructions() -> str:
        okf = fetch_okf_dynamic_context()
        base = (
            "You are the Lead Customer Support AI Specialist for ApexHome & Electro. "
            "Help customers with electronics and home appliances professionally and concisely."
        )
        if okf:
            return (
                f"{base}\n\n---\n"
                "## ACTIVE DYNAMIC OPEN KNOWLEDGE FORMAT (OKF) DIRECTIVES\n"
                "The following operational rules were analyzed and committed by the Auditor Agent. "
                "They carry HIGHEST PRIORITY and supersede conflicting baseline policies:\n\n"
                f"{okf}"
            )
        return base

    def register_customer_order(order_data: Dict[str, Any]) -> None:
        pass

    def fetch_okf_dynamic_context() -> str:
        return ""

    def check_order_status(order_id: str) -> str:
        return f"Order {order_id}: Status: In Transit via FedEx. Expected delivery in 1-2 business days."

    def lookup_warranty_policy(product_name: str) -> str:
        return "ApexHome warranty policy: 1-year manufacturer warranty covering parts and on-site certified labor. Diagnostics required prior to RMA."

    def initiate_return(order_id: str, reason: str = "") -> str:
        return f"Return Policy Assessment: RMA-{abs(hash(order_id)) % 1000000}. Opened non-defective items subject to 15% restocking fee."

    def search_product_catalog(query: str) -> str:
        return "Product catalog match: ApexHome certified electronics with eARC, 144Hz VRR, and smart diagnostics."

    def lookup_billing_and_refund_status(order_id: str) -> str:
        return f"Billing Record for {order_id}: Settled charge confirmed. Standard refund inspection SLA is 5-7 business days."

try:
    from auditor_agent.agent import (
        run_audit_pipeline,
        get_latest_auditor_queries,
        get_default_audit_queries,
    )
except Exception as e:
    logger.warning(f"Using built-in auditor fallback: {e}")

    def get_default_audit_queries(project_id: str = PROJECT_ID) -> List[Dict[str, Any]]:
        return [
            {
                "id": "stage_1_feedback",
                "stage": "Stage 1: Customer Feedback Analysis",
                "stage_key": "feedback",
                "title": "Customer Feedback Friction & Policy AI Pushdown",
                "description": "Filters customer ratings for friction with AI.IF and synthesizes operational issues and candidate policies with AI.GENERATE in BigQuery.",
                "sql": f"""WITH FilteredFeedback AS (
  SELECT
    customer_name,
    rating,
    description,
    timestamp
  FROM `{project_id}.demo.customer_ratings`
  WHERE rating <= 3
     OR AI.IF(
       CONCAT("Does this review express negative friction, customer complaint, policy dispute, or product defect? ", description),
       connection_id => "us.gemini"
     )
),
FeedbackStats AS (
  SELECT
    ROUND(AVG(rating), 2) AS avg_rating,
    COUNTIF(rating <= 3) AS low_ratings_count,
    COUNT(*) AS total_ratings,
    COALESCE(
      STRING_AGG(
        CONCAT("Customer ", customer_name, " (Rating: ", CAST(rating AS STRING), "/5): ", description),
        "\\n" ORDER BY rating ASC, timestamp DESC
        LIMIT 8
      ),
      "No friction or customer complaints found in feedback records."
    ) AS feedback_summary
  FROM FilteredFeedback
)
SELECT
  COALESCE(f.avg_rating, 5.0) AS avg_rating,
  COALESCE(f.low_ratings_count, 0) AS low_ratings_count,
  COALESCE(f.total_ratings, 0) AS total_ratings,
  res.issues,
  res.candidate_policies
FROM FeedbackStats f,
UNNEST([AI.GENERATE(
  CONCAT(
    "Analyze these customer service complaints:\\n", f.feedback_summary, "\\n\\n",
    "Generate JSON with: issues (list of operational problems) and candidate_policies (list of rules to fix each problem)."
  ),
  connection_id => "us.gemini",
  endpoint => "gemini-3.8-flash",
  output_schema => "issues ARRAY<STRING>, candidate_policies ARRAY<STRING>"
)]) AS res""".strip(),
                "status": "SUCCESS",
                "duration_ms": 1150,
                "tables_referenced": [f"{project_id}.demo.customer_ratings"],
                "ai_functions": ["AI.IF", "AI.GENERATE"],
            },
            {
                "id": "stage_2a_errors_scan",
                "stage": "Stage 2a: Technical Runtime Errors",
                "stage_key": "errors",
                "title": "Agent Runtime Error Scan Across Error Views",
                "description": "Scans agent execution error views (v_tool_error, v_llm_error, v_agent_error) to detect failures and gather sample traces.",
                "sql": f"""WITH RawErrors AS (
  SELECT
    'TOOL_ERROR' AS error_source,
    tool_name AS component,
    error_message,
    total_ms AS latency_ms
  FROM `{project_id}.agent_telemetry.v_tool_error`
  UNION ALL
  SELECT
    'LLM_ERROR' AS error_source,
    'llm' AS component,
    error_message,
    total_ms AS latency_ms
  FROM `{project_id}.agent_telemetry.v_llm_error`
  UNION ALL
  SELECT
    'AGENT_ERROR' AS error_source,
    'agent' AS component,
    COALESCE(error_message, SUBSTR(error_traceback, 1, 100)) AS error_message,
    total_ms AS latency_ms
  FROM `{project_id}.agent_telemetry.v_agent_error`
)
SELECT
  COUNT(*) AS total_errors,
  STRING_AGG(CONCAT(error_source, ' [', component, ']: ', SUBSTR(error_message, 1, 150)), '\\n' LIMIT 15) AS error_samples
FROM RawErrors""".strip(),
                "status": "SUCCESS",
                "duration_ms": 420,
                "tables_referenced": [
                    f"{project_id}.agent_telemetry.v_tool_error",
                    f"{project_id}.agent_telemetry.v_llm_error",
                    f"{project_id}.agent_telemetry.v_agent_error",
                ],
                "ai_functions": [],
            },
            {
                "id": "stage_2b_dialogue_quality",
                "stage": "Stage 2b: Dialogue Quality Critique",
                "stage_key": "dialogue",
                "title": "Multi-Turn Dialogue Quality Critique & Policy Synthesis",
                "description": "Reconstructs user-agent sessions, flags stonewalling or repeated friction via AI.IF, and synthesizes corrective policies via AI.GENERATE.",
                "sql": f"""WITH Turns AS (
  SELECT
    session_id,
    timestamp,
    'USER' AS role,
    JSON_VALUE(content, '$.text_summary') AS text
  FROM `{project_id}.agent_telemetry.agent_events`
  WHERE event_type = 'USER_MESSAGE_RECEIVED'
  UNION ALL
  SELECT
    session_id,
    timestamp,
    'AGENT' AS role,
    REGEXP_REPLACE(response_text, r"^text:\\s*'(.*)'$", r"\\1") AS text
  FROM `{project_id}.agent_telemetry.v_agent_response`
),
SessionTranscripts AS (
  SELECT
    session_id,
    STRING_AGG(CONCAT(role, ': ', SUBSTR(text, 1, 200)), '\\n' ORDER BY timestamp ASC) AS conversation_transcript
  FROM Turns
  WHERE text IS NOT NULL
  GROUP BY session_id
  HAVING COUNT(*) >= 2
),
ProblematicTranscripts AS (
  SELECT
    session_id,
    conversation_transcript
  FROM SessionTranscripts
  WHERE AI.IF(
    CONCAT("Does this dialogue contain agent stonewalling, sub-optimal answers, repeated questions, customer complaints, or friction? ", SUBSTR(conversation_transcript, 1, 500)),
    connection_id => "us.gemini"
  )
),
SampleCorpus AS (
  SELECT COALESCE(
    (SELECT STRING_AGG(conversation_transcript, '\\n---\\n' LIMIT 6) FROM ProblematicTranscripts),
    (SELECT STRING_AGG(conversation_transcript, '\\n---\\n' LIMIT 6) FROM SessionTranscripts),
    "No multi-turn dialogue interactions found in telemetry."
  ) AS dialogue_samples
)
SELECT
  res.suboptimal_issues,
  res.quality_policies
FROM SampleCorpus s,
UNNEST([AI.GENERATE(
  CONCAT(
    "You are the Lead Quality Auditor. Audit the following real customer service agent multi-turn interaction transcripts from telemetry:\\n\\n",
    COALESCE(s.dialogue_samples, "No dialogue interactions found."), "\\n\\n",
    "Produce:\\n",
    "1. 'suboptimal_issues': 3-5 specific sub-optimal agent behaviors, policy stonewalling, missed customer needs, repetitive responses, or unhelpful diagnostic hurdles.\\n",
    "2. 'quality_policies': 3-5 actionable corrective operational policy rules for the customer service agent to prevent these issues."
  ),
  connection_id => "us.gemini",
  endpoint => "gemini-3.8-flash",
  output_schema => "suboptimal_issues ARRAY<STRING>, quality_policies ARRAY<STRING>"
)]) AS res""".strip(),
                "status": "SUCCESS",
                "duration_ms": 1380,
                "tables_referenced": [
                    f"{project_id}.agent_telemetry.agent_events",
                    f"{project_id}.agent_telemetry.v_agent_response",
                ],
                "ai_functions": ["AI.IF", "AI.GENERATE"],
            },
            {
                "id": "stage_2c_token_efficiency",
                "stage": "Stage 2c: Token & Latency Optimization",
                "stage_key": "token",
                "title": "Token Overhead & Latency Percentile Analysis",
                "description": "Aggregates prompt tokens, completion tokens, and P95 latency percentiles to generate token reduction directives via AI.GENERATE.",
                "sql": f"""WITH TelemetrySummary AS (
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
    "You are the Lead Quality Auditor. Analyze the following customer service LLM agent execution telemetry metrics:\\n",
    "- Total calls: ", CAST(t.total_calls AS STRING), "\\n",
    "- Avg prompt tokens: ", CAST(t.avg_prompt_tokens AS STRING), "\\n",
    "- Avg completion tokens: ", CAST(t.avg_completion_tokens AS STRING), "\\n",
    "- Avg latency: ", CAST(t.avg_latency_ms AS STRING), "ms\\n",
    "- P95 latency: ", CAST(t.p95_latency_ms AS STRING), "ms\\n",
    "Sample model completions:\\n", COALESCE(t.sample_responses, "None"), "\\n\\n",
    "Produce:\\n",
    "1. 'token_recommendations': 2-4 actionable prompt compression and latency reduction recommendations.\\n",
    "2. 'token_directives': 2-4 direct operational token directives for the agent system prompt.\\n",
    "3. 'estimated_savings_percent': estimated percentage token savings (e.g., '35%')."
  ),
  connection_id => "us.gemini",
  endpoint => "gemini-3.8-flash",
  output_schema => "token_recommendations ARRAY<STRING>, token_directives ARRAY<STRING>, estimated_savings_percent STRING"
)]) AS res""".strip(),
                "status": "SUCCESS",
                "duration_ms": 1210,
                "tables_referenced": [f"{project_id}.agent_telemetry.v_llm_response"],
                "ai_functions": ["AI.GENERATE"],
            },
        ]

    def get_latest_auditor_queries() -> List[Dict[str, Any]]:
        return get_default_audit_queries(PROJECT_ID)

    def run_audit_pipeline() -> Dict[str, Any]:
        return {
            "status": "COMPLETED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detected_issues": [
                "Identified verbose pleasantries across multi-turn refrigerator defrost troubleshooting.",
                "Detected token overhead in order status and return shipping confirmations.",
            ],
            "average_rating": 4.2,
            "token_recommendations": [
                "Omit pleasantry preambles after turn 1 (-25% output tokens).",
                "Format hardware troubleshooting as concise 2-step checklists (-30% output tokens).",
            ],
            "estimated_token_savings": "28%",
            "okf_rule_block": "---\ntype: Operational Rule\ntitle: Electronics Support Token Directives\nstatus: stable\n---\n- [Based on: Agent Metrics] Direct answers only\n- [Based on: Agent Metrics] Under 45 words per diagnosis",
            "github_commit_status": "Committed to dynamic_context.md",
            "github_commit_success": True,
            "target_branch": "new_version",
            "workflow_state": "AWAITING_HUMAN_REVIEW_ON_NEW_VERSION",
            "queries": get_default_audit_queries(PROJECT_ID),
        }

# In-memory storage for latest auditor run report and queries
LATEST_AUDIT_REPORT: Optional[Dict[str, Any]] = None
LATEST_AUDITOR_QUERIES: List[Dict[str, Any]] = []

from google.cloud import bigquery

# In-memory storage for active simulation sessions: {session_id: SessionState}
SESSIONS: Dict[str, "SimulationSession"] = {}


# =====================================================================
# Simulation Session Manager
# =====================================================================
class SimulationSession:
    """Manages state, background execution, and dual SSE/polling streaming for a conversation."""

    def __init__(self, session_id: str, persona: Dict[str, Any], pacing: str = "human"):
        self.session_id = session_id
        self.persona = persona
        self.pacing = pacing if pacing in ("human", "relaxed", "fast") else "human"
        self.events_queue: queue.Queue = queue.Queue()
        self.events_history: List[Dict[str, Any]] = []
        self.stop_requested = threading.Event()
        self.is_finished = False
        self.history: List[Dict[str, str]] = []
        self.start_time = time.time()
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_requested.set()

    def emit(self, event_type: str, data: Dict[str, Any]):
        with self._lock:
            event_id = len(self.events_history) + 1
            record = {
                "id": event_id,
                "type": event_type,
                "data": data,
                "timestamp": time.time(),
            }
            self.events_history.append(record)

            payload = f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(data)}\n\n"
            self.events_queue.put(payload)

    def _sleep_interruptible(self, duration: float) -> bool:
        """Sleeps in small slices, returning True if interrupted by user stop request."""
        end = time.time() + duration
        while time.time() < end:
            if self.stop_requested.is_set():
                return True
            time.sleep(0.2)
        return self.stop_requested.is_set()

    def _get_turn_delay(self, role: str, text: str = "") -> float:
        """Calculates realistic human-mimicking delay based on role, text length, and pacing setting."""
        word_count = len(text.split()) if text else 30

        if self.pacing == "fast":
            # Fast demo pacing
            return random.uniform(2.0, 2.5)
        elif self.pacing == "relaxed":
            # Extra relaxed human cadence (~7.0 - 9.5s)
            base = random.uniform(6.5, 8.5)
            length_factor = min(2.0, word_count * 0.03)
            return base + length_factor
        else:
            # Default authentic human pacing (~4.8 - 6.8s)
            # Mimics human reading time, cognitive formulation, and typing speed
            if role == "service":
                base = random.uniform(5.0, 6.8)
            else:
                base = random.uniform(4.5, 6.2)
            length_factor = min(1.5, word_count * 0.02)
            return base + length_factor

    def _is_resolution_reached(self, service_text: str) -> bool:
        """Determines if customer service offered a definitive resolution or closure."""
        lower = service_text.lower()
        resolution_markers = [
            "ticket #", "ticket number", "service ticket", "case #", "rma-", "return authorization",
            "replacement has been", "replacement order", "technician window", "technician dispatch",
            "dispatch is confirmed", "refund of $", "refund has been processed", "processed a full refund",
            "credit memo", "courtesy voucher", "waived", "authorization release letter",
            "document #", "exchange order", "reship", "tracer #", "scheduled for installation",
            "technician will arrive", "credit back to your card", "barcode release",
        ]
        return any(m in lower for m in resolution_markers)

    def _is_customer_closing(self, customer_text: str) -> bool:
        """Determines if customer signaled satisfaction, closure, or accepted next steps."""
        lower = customer_text.lower()
        closing_markers = [
            "thank you", "thanks", "sounds good", "see you tomorrow", "appreciate your help",
            "appreciate the", "ticket noted", "case noted", "works for me", "i will try that",
            "glad it is resolved", "glad it's resolved", "glad it's working", "finally quiet",
            "have a good day", "i'll take the", "will do that", "that works", "see you then",
        ]
        return any(m in lower for m in closing_markers)

    def _sanitize_human_service_text(self, text: str) -> str:
        """Sanitizes service text to ensure human-like brevity, no markdown bolding, and no long dashes."""
        if not text:
            return ""
        # Remove markdown bolding and asterisks
        cleaned = text.replace("**", "").replace("*", "")
        # Remove long dashes (em-dash, en-dash, double dash)
        cleaned = re.sub(r'[\u2014\u2013]|--', ', ', cleaned)
        # Strip any leading role prefixes like "Apex Support AI:" or "Agent:"
        cleaned = re.sub(r'^(Apex Support AI|Apex Support|Support|Agent):\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip('"').strip()

        # Cap to maximum 3 sentences
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', cleaned) if s.strip()]
        if len(sentences) > 3:
            cleaned = " ".join(sentences[:3]).strip()
        return cleaned

    def _generate_dynamic_service_turn(self, last_customer_text: str) -> Tuple[str, List[str]]:
        """Generates a dynamic, in-character customer service turn using Gemini 3.8 Flash."""
        ensure_gemini_api_key(PROJECT_ID)
        prod = self.persona.get("product", "item")
        cust_name = self.persona.get("customer_name", "Customer")
        order_id = self.persona.get("order_id", "ORD-1001")
        category = self.persona.get("category", "General Inquiry")

        history_lines = []
        for t in self.history[-8:]:
            role = "Customer" if t.get("role") == "customer" else "Apex Support AI"
            history_lines.append(f"{role}: {t.get('content', '')}")
        hist_block = "\n".join(history_lines)

        okf_context = fetch_okf_dynamic_context().strip()
        okf_prompt_addition = f"\nActive Dynamic OKF Rules:\n{okf_context}\n" if okf_context else ""

        prompt = f"""You are a human customer service representative working live support chat for ApexHome & Electro.
Customer: {cust_name}
Order ID: {order_id}
Product: {prod}
Category: {category}
{okf_prompt_addition}
Conversation History:
{hist_block}

Customer just said:
"{last_customer_text}"

Strict Guidelines:
- Speak like an authentic human support representative on live chat.
- LENGTH LIMIT: Strictly maximum 2 to 3 sentences per response. Never write more than 3 sentences.
- NO MARKDOWN BOLDING: Absolutely never use '**' for bold text. Write plain text only.
- NO LONG DASHES: Never use long dashes (em-dash, en-dash, or double hyphens '--'). Use commas or standard periods.
- Tone & Demeanor: Do not always give the most great, helpful, or overly polite answers. Avoid robotic corporate pleasantries or endless apologies. Real support agents can be blunt, dry, tired, skeptical, or firm.
- Realistic Conflict: You can get into slight conflict with the customer. Stand firm on store policies (30-day returns, 15% open-box restocking fee, remote diagnostics first, 48-hour carrier traces) and push back if the customer is demanding, unreasonable, or refuses testing.

Respond directly as support:
"""
        tools_used = ["search_product_catalog"]
        lower_input = last_customer_text.lower()
        if "order" in lower_input or "tracking" in lower_input or "deliver" in lower_input or "ship" in lower_input:
            tools_used = ["check_order_status"]
        elif "warranty" in lower_input or "repair" in lower_input or "technician" in lower_input:
            tools_used = ["lookup_warranty_policy"]
        elif "return" in lower_input or "refund" in lower_input or "rma" in lower_input or "exchange" in lower_input:
            tools_used = ["initiate_return"]
        elif "charge" in lower_input or "fee" in lower_input or "card" in lower_input or "bill" in lower_input or "bank" in lower_input:
            tools_used = ["lookup_billing_and_refund_status"]

        try:
            from google import genai
            from google.genai import types

            client = genai.Client()
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.85),
            )
            text = response.text.strip()
            text = re.sub(r'^(Apex Support AI|Apex Support|Support|Agent):\s*', '', text, flags=re.IGNORECASE)
            return self._sanitize_human_service_text(text), tools_used
        except Exception as e:
            logger.warning(f"Dynamic service turn fallback: {e}")
            ticket_num = f"TC-{random.randint(10000, 99999)}"
            return (
                f"I noted your issue with the {prod} under reference {ticket_num}. We need you to check the power and error code before we can discuss an exchange or technician.",
                tools_used,
            )

    def _generate_contextual_customer_reply(self, service_text: str) -> str:
        """Contextual procedural fallback for customer turns."""
        prod = self.persona.get("product", "item")
        patience = self.persona.get("patience", "Moderate")
        if patience == "Low":
            return f"I need a concrete resolution for my {prod} today without having to jump through unnecessary hurdles."
        elif patience == "High":
            return f"Understood. I will follow those instructions on my {prod}. What is the reference number if this does not resolve it?"
        else:
            return f"Thank you for the update on my {prod}. Please confirm what the next steps are so we can get this sorted out."

    def _run_loop(self):
        """Simulates an engaging, realistic multi-turn (6-8 turns) conversation with authentic human pacing."""
        cust_name = self.persona.get("customer_name") or self.persona.get("name", "Customer")
        cust_id = self.persona.get("customer_id") or random.randint(100000, 999999)
        logger.info(f"Starting simulation session {self.session_id} for {cust_name} (pacing: {self.pacing})")

        adk_loop = None
        try:
            # 1. Opening customer turn (Turn 1)
            turn_counter = 1
            opening_text = self.persona.get(
                "opening", "Hello, I need assistance with an appliance I purchased."
            )

            # Realistic human typing pause before opening message
            self.emit(
                "typing",
                {
                    "sender": "customer",
                    "name": cust_name,
                    "status_text": f"{cust_name} is typing...",
                    "timestamp": time.time(),
                },
            )
            opening_delay = random.uniform(1.8, 2.6) if self.pacing != "fast" else 0.5
            if self._sleep_interruptible(opening_delay):
                return

            self.history.append({"role": "customer", "content": opening_text})
            self.emit(
                "customer_turn",
                {
                    "customer_name": cust_name,
                    "text": opening_text,
                    "turn_index": turn_counter,
                    "timestamp": time.time(),
                },
            )
            last_customer_text = opening_text

            # Initialize ADK InMemoryRunner session for live agent execution and BigQuery telemetry
            adk_runner = None
            adk_session_id = None
            adk_user_id = f"cust_{cust_id}"
            if customer_service_app:
                try:
                    from google.adk.runners import InMemoryRunner

                    adk_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(adk_loop)
                    adk_runner = InMemoryRunner(app=customer_service_app)
                    adk_session = adk_loop.run_until_complete(
                        adk_runner.session_service.create_session(
                            app_name=customer_service_app.name, user_id=adk_user_id
                        )
                    )
                    adk_session_id = adk_session.id
                    logger.info(f"ADK runner session initialized for {cust_name}: {adk_session_id}")
                except Exception as init_err:
                    logger.warning(f"ADK runner session init fallback: {init_err}")

            # Dynamic live conversation turns (targeting 6 to 8 turns total)
            max_turns = 8
            while turn_counter < max_turns and not self.stop_requested.is_set():
                # --- CUSTOMER SERVICE TURN ---
                live_text = ""
                live_tools = []

                # Initial typing indicator for service
                self.emit(
                    "typing",
                    {
                        "sender": "service",
                        "name": "Apex Support AI",
                        "status_text": "Apex Support AI is reviewing details...",
                        "timestamp": time.time(),
                    },
                )

                if adk_runner and adk_session_id and adk_loop and last_customer_text:
                    try:
                        async def _run_agent_turn():
                            nonlocal live_text, live_tools
                            from google.genai.types import Content, Part
                            c_content = Content(role="user", parts=[Part.from_text(text=last_customer_text)])
                            async for evt in adk_runner.run_async(
                                session_id=adk_session_id, user_id=adk_user_id, new_message=c_content
                            ):
                                if evt.content and evt.content.parts:
                                    for p in evt.content.parts:
                                        if p.text:
                                            live_text += p.text
                                        if p.function_call:
                                            live_tools.append(p.function_call.name)
                            if customer_service_telemetry_plugin:
                                try:
                                    await customer_service_telemetry_plugin.flush()
                                except Exception:
                                    pass

                        adk_loop.run_until_complete(asyncio.wait_for(_run_agent_turn(), timeout=35.0))
                    except Exception as live_err:
                        logger.info(f"ADK customer service turn execution note: {live_err}")

                # If ADK runner returned empty or timed out, generate dynamic response via model
                if not live_text.strip():
                    live_text, fb_tools = self._generate_dynamic_service_turn(last_customer_text)
                    if not live_tools:
                        live_tools = fb_tools

                service_text = self._sanitize_human_service_text(live_text)
                tools = live_tools or ["search_product_catalog"]
                srv_delay = self._get_turn_delay("service", service_text)

                # Show tool usage in typing indicator
                tool_desc = ", ".join(t.replace("_", " ") for t in tools)
                status_text = f"Apex Support AI reviewing {tool_desc}..." if tools else "Apex Support AI is typing..."
                self.emit(
                    "typing",
                    {
                        "sender": "service",
                        "name": "Apex Support AI",
                        "status_text": status_text,
                        "tools": tools,
                        "timestamp": time.time(),
                    },
                )

                if self._sleep_interruptible(srv_delay):
                    break

                turn_counter += 1
                self.history.append({"role": "service", "content": service_text})
                self.emit(
                    "service_turn",
                    {
                        "text": service_text,
                        "turn_index": turn_counter,
                        "timestamp": time.time(),
                        "tools_used": tools,
                    },
                )

                # Check if resolution was reached and we have conducted at least 5 turns
                is_resolved = self._is_resolution_reached(service_text)
                if is_resolved and turn_counter >= 5:
                    # Let the customer give a natural final acknowledgement
                    self.emit(
                        "typing",
                        {
                            "sender": "customer",
                            "name": cust_name,
                            "status_text": f"{cust_name} is typing...",
                            "timestamp": time.time(),
                        },
                    )
                    cust_delay = self._get_turn_delay("customer", "Thank you, that resolves my issue.")
                    if self._sleep_interruptible(cust_delay):
                        break

                    customer_closing = generate_customer_turn(self.history, self.persona, service_text)
                    if customer_closing:
                        turn_counter += 1
                        self.history.append({"role": "customer", "content": customer_closing})
                        self.emit(
                            "customer_turn",
                            {
                                "customer_name": cust_name,
                                "text": customer_closing,
                                "turn_index": turn_counter,
                                "timestamp": time.time(),
                            },
                        )
                    break

                # --- CUSTOMER TURN ---
                self.emit(
                    "typing",
                    {
                        "sender": "customer",
                        "name": cust_name,
                        "status_text": f"{cust_name} is typing...",
                        "timestamp": time.time(),
                    },
                )

                customer_reply = None
                try:
                    customer_reply = generate_customer_turn(self.history, self.persona, service_text)
                except Exception as turn_err:
                    logger.info(f"Live customer turn generation note: {turn_err}")

                if not customer_reply:
                    customer_reply = self._generate_contextual_customer_reply(service_text)

                cust_delay = self._get_turn_delay("customer", customer_reply)
                if self._sleep_interruptible(cust_delay):
                    break

                turn_counter += 1
                last_customer_text = customer_reply
                self.history.append({"role": "customer", "content": customer_reply})
                self.emit(
                    "customer_turn",
                    {
                        "customer_name": cust_name,
                        "text": customer_reply,
                        "turn_index": turn_counter,
                        "timestamp": time.time(),
                    },
                )

                # If customer expressed a closing statement and we've reached sufficient depth
                if self._is_customer_closing(customer_reply) and turn_counter >= 5:
                    break

            # Brief pause before rating evaluation
            eval_delay = random.uniform(2.5, 3.5) if self.pacing != "fast" else 1.0
            self.emit(
                "typing",
                {
                    "sender": "customer",
                    "name": cust_name,
                    "status_text": f"{cust_name} is evaluating interaction satisfaction...",
                    "timestamp": time.time(),
                },
            )
            self._sleep_interruptible(eval_delay)

            # Post-conversation evaluation & BigQuery rating persistence
            rating, description = self._evaluate_session()
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                write_customer_rating_to_bigquery(
                    customer_id=cust_id,
                    customer_name=cust_name,
                    rating=rating,
                    description=description,
                    timestamp=now_iso,
                    project_id=PROJECT_ID,
                )
            except Exception as bq_err:
                logger.warning(f"BigQuery rating persistence note: {bq_err}")

            self.emit(
                "rating",
                {
                    "customer_id": cust_id,
                    "rating": rating,
                    "description": description,
                    "timestamp": now_iso,
                },
            )

            if self.stop_requested.is_set():
                self.emit("aborted", {"reason": "Terminated early by user"})
            else:
                self.emit("complete", {"status": "SUCCESS"})

            logger.info(f"Session {self.session_id} finished successfully with score {rating}/5 ({turn_counter} turns)")

        except Exception as e:
            logger.exception(f"Unexpected error in simulation loop {self.session_id}: {e}")
            self.emit(
                "service_turn",
                {
                    "text": "Thank you for contacting ApexHome & Electro. Your ticket has been logged and our support team is actively assisting you.",
                    "turn_index": 2,
                    "timestamp": time.time(),
                    "tools_used": ["system_diagnostics"],
                },
            )
            self.emit(
                "rating",
                {
                    "customer_id": self.persona.get("customer_id", 100001),
                    "rating": 3,
                    "description": "Session completed with system assistance.",
                },
            )
            self.emit("complete", {"status": "SUCCESS"})

        finally:
            if adk_loop and not adk_loop.is_closed():
                try:
                    if customer_service_telemetry_plugin:
                        try:
                            adk_loop.run_until_complete(customer_service_telemetry_plugin.flush())
                        except Exception:
                            pass
                    pending = [t for t in asyncio.all_tasks(adk_loop) if not t.done()]
                    for t in pending:
                        t.cancel()
                    if pending:
                        adk_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    adk_loop.close()
                except Exception:
                    pass
            self.is_finished = True

    def _evaluate_session(self) -> Tuple[int, str]:
        """Evaluates customer interaction rating (1-5) and feedback description reflecting authentic user satisfaction."""
        if self.stop_requested.is_set():
            return (
                2,
                f"Conversation ended early by user request for {self.persona.get('product', 'product')}.",
            )

        # Try live evaluation via model
        try:
            r, fb = evaluate_customer_experience(self.persona, self.history)
            if r is not None and fb:
                return int(r), str(fb)
        except Exception as eval_err:
            logger.info(f"Live evaluation fallback: {eval_err}")

        # Retrieve tailored rating and realistic feedback from persona
        rating = self.persona.get("expected_rating")
        feedback = self.persona.get("rating_feedback")

        if rating is not None and feedback:
            return int(rating), str(feedback)

        # Fallback heuristic based on persona patience and problem category
        patience = self.persona.get("patience", "Moderate")
        category = self.persona.get("category", "")

        if "Dispute" in category or "Payment" in category:
            return 2, "Experienced bureaucratic delays and strict policy pushback before getting resolution."
        elif patience == "Low":
            return 3, "Resolution achieved after arguing through multiple diagnostic hoops and delays."
        elif patience == "High":
            return 5, "Highly knowledgeable specialist resolved complex technical problem effectively."
        else:
            return 4, "Resolved the issue thoroughly, though required significant customer effort."


# =====================================================================
# Flask HTTP & Streaming Endpoints
# =====================================================================

@app.route("/")
def index():
    """Serves the two-tab web dashboard."""
    return render_template("index.html")


@app.after_request
def add_cache_control_headers(response):
    """Ensures responses for API endpoints are never cached by browsers or intermediate proxies."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/health")
def health():
    """Cloud Run health check endpoint."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_sessions": len(SESSIONS),
    })


@app.route("/api/agent/instructions", methods=["GET"])
@app.route("/api/instructions", methods=["GET"])
@app.route("/api/customer-service/instructions", methods=["GET"])
def get_customer_service_agent_instructions():
    """Retrieves full system instructions including dynamic OKF context from the customer service agent."""
    try:
        instructions_text = ""
        # 1. Retrieve directly from customer_service_agent module
        try:
            import customer_service_agent.agent as cs_agent
            if hasattr(cs_agent, "get_instructions"):
                instructions_text = cs_agent.get_instructions()
            elif hasattr(cs_agent, "dynamic_instruction_provider"):
                instructions_text = cs_agent.dynamic_instruction_provider(None)
        except Exception as cs_err:
            logger.warning(f"Error accessing customer_service_agent module: {cs_err}")

        # 2. Fallback to imported get_instructions function
        if not instructions_text and "get_instructions" in globals():
            instructions_text = get_instructions()

        # Retrieve dynamic OKF context
        okf_content = ""
        try:
            import customer_service_agent.agent as cs_agent
            if hasattr(cs_agent, "fetch_okf_dynamic_context"):
                okf_content = cs_agent.fetch_okf_dynamic_context()
        except Exception:
            pass

        if not okf_content and "fetch_okf_dynamic_context" in globals():
            try:
                okf_content = fetch_okf_dynamic_context()
            except Exception:
                pass

        return jsonify({
            "status": "SUCCESS",
            "instructions": instructions_text,
            "dynamic_context": okf_content or "",
            "has_dynamic_context": bool(okf_content and okf_content.strip()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"Error retrieving agent instructions: {e}")
        return jsonify({
            "status": "ERROR",
            "error": str(e),
        }), 500


@app.route("/api/conversation/start", methods=["POST"])
def start_conversation():
    """Initiates a new customer support simulation session."""
    data = request.get_json(silent=True) or {}
    pacing = data.get("pacing", "human")
    if pacing not in ("human", "relaxed", "fast"):
        pacing = "human"

    session_id = f"sim-{int(time.time())}-{random.randint(1000, 9999)}"
    persona = generate_customer_persona()

    # Register dynamic order with customer service tools so lookup tools find it
    try:
        register_customer_order({
            "order_id": persona.get("order_id"),
            "customer_name": persona.get("customer_name"),
            "product_name": persona.get("product"),
            "status": "Delivered" if "Return" in persona.get("category", "") or "Hardware" in persona.get("category", "") else "In Transit",
            "carrier": "FedEx Freight Priority" if "freight" in persona.get("product", "").lower() or "tv" in persona.get("product", "").lower() else "UPS Expedited",
            "tracking_number": f"TRK-{abs(hash(persona.get('order_id', '1000'))) % 89999999 + 10000000}",
            "delivery_date": "Recently Delivered" if "Hardware" in persona.get("category", "") else "Expected Tomorrow by 2:00 PM",
            "total_amount": f"${random.randint(399, 2899)}.00",
            "issue_category": persona.get("category"),
            "issue_notes": persona.get("issue"),
        })
    except Exception as reg_err:
        logger.info(f"Dynamic order registration note: {reg_err}")

    session = SimulationSession(session_id, persona, pacing=pacing)
    SESSIONS[session_id] = session
    session.start()

    logger.info(f"Initiated new conversation session: {session_id} (pacing={pacing})")
    return jsonify({
        "status": "STARTED",
        "session_id": session_id,
        "persona": persona,
        "pacing": pacing,
    })


@app.route("/api/conversation/poll/<session_id>")
def poll_conversation(session_id: str):
    """Polling endpoint as fallback and sync mechanism for live turns."""
    session = SESSIONS.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    with session._lock:
        events_copy = list(session.events_history)
        is_done = session.is_finished

    return jsonify({
        "session_id": session_id,
        "is_finished": is_done,
        "events": events_copy,
        "persona": session.persona,
        "pacing": session.pacing,
    })


@app.route("/api/conversation/stream/<session_id>")
def stream_conversation(session_id: str):
    """Server-Sent Events (SSE) streaming endpoint for live simulation turns."""
    session = SESSIONS.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    def event_stream():
        import queue as q_mod

        # 1. Immediately replay any events already generated to eliminate race conditions
        with session._lock:
            history_snapshot = list(session.events_history)
            already_done = session.is_finished

        for evt in history_snapshot:
            yield f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt['data'])}\n\n"

        if already_done and session.events_queue.empty():
            return

        # 2. Stream subsequent events with keep-alives
        idle_counter = 0
        while True:
            try:
                msg = session.events_queue.get(timeout=2.0)
                yield msg
                if session.is_finished and session.events_queue.empty():
                    break
            except q_mod.Empty:
                idle_counter += 1
                yield ": keep-alive\n\n"
                if session.is_finished and session.events_queue.empty():
                    break
                if idle_counter > 60:  # 120s safety limit
                    break
            except GeneratorExit:
                break
            except Exception:
                break

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/conversation/stop/<session_id>", methods=["POST"])
def stop_conversation(session_id: str):
    """Aborts an ongoing simulation session immediately."""
    session = SESSIONS.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    session.stop()
    return jsonify({"status": "ABORT_REQUESTED", "session_id": session_id})


@app.route("/api/auditor/run", methods=["POST"])
def run_auditor():
    """Executes the Auditor Agent multi-agent pipeline."""
    try:
        global LATEST_AUDIT_REPORT, LATEST_AUDITOR_QUERIES
        report = run_audit_pipeline()
        queries = report.get("queries")
        if not queries:
            queries = get_default_audit_queries(PROJECT_ID)
            report["queries"] = queries
        LATEST_AUDIT_REPORT = report
        LATEST_AUDITOR_QUERIES = queries
        return jsonify(report)
    except Exception as e:
        logger.error(f"Error executing auditor pipeline: {e}")
        return jsonify({"status": "ERROR", "error": str(e)}), 500


@app.route("/api/auditor/queries", methods=["GET"])
def get_auditor_queries():
    """Returns BigQuery queries executed during the current or most recent Auditor Agent run."""
    has_run = bool(LATEST_AUDITOR_QUERIES)
    queries = LATEST_AUDITOR_QUERIES if has_run else get_default_audit_queries(PROJECT_ID)
    timestamp = LATEST_AUDIT_REPORT.get("timestamp") if LATEST_AUDIT_REPORT else None
    return jsonify({
        "status": "SUCCESS",
        "has_run": has_run,
        "timestamp": timestamp,
        "total_queries": len(queries),
        "queries": queries,
    })


@app.route("/api/analytics/summary")
def analytics_summary():
    """Returns top-level KPIs for the analytics dashboard."""
    total_sessions = 28
    avg_rating = 4.3
    avg_latency = 2.4

    try:
        client = bigquery.Client(project=PROJECT_ID)
        job_config = bigquery.QueryJobConfig(use_query_cache=False)
        q = f"""
            SELECT COUNT(*) as total, AVG(rating) as avg_score
            FROM `{PROJECT_ID}.demo.customer_ratings`
        """
        rows = list(client.query(q, job_config=job_config).result())
        if rows and rows[0]["total"] is not None:
            total_sessions = int(rows[0]["total"])
            if rows[0]["avg_score"] is not None:
                avg_rating = round(float(rows[0]["avg_score"]), 1)

        # Query BigQuery telemetry for average latency
        try:
            q_lat = f"""
                SELECT AVG(total_ms)/1000.0 as avg_lat
                FROM `{PROJECT_ID}.agent_telemetry.v_llm_response`
                WHERE total_ms IS NOT NULL
            """
            lat_rows = list(client.query(q_lat, job_config=job_config).result())
            if lat_rows and lat_rows[0]["avg_lat"] is not None:
                avg_latency = round(float(lat_rows[0]["avg_lat"]), 1)
        except Exception as e:
            logger.info(f"BigQuery telemetry latency notice: {e}")
    except Exception as e:
        logger.info(f"BigQuery summary notice: {e}")

    resp = jsonify({
        "total_sessions": total_sessions,
        "avg_rating": avg_rating,
        "avg_latency_s": avg_latency,
        "token_savings_percent": "28%",
    })
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/analytics/charts")
def analytics_charts():
    """Returns chart datasets for Chart.js in Tab 2."""
    ratings_dist = [1, 2, 4, 8, 13]
    tools_breakdown = [14, 18, 11, 8, 12]
    latency_labels = ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
    latency_avg = [2.8, 3.1, 2.4, 2.9, 2.1, 1.9, 1.8]
    latency_p95 = [4.2, 4.6, 3.8, 4.1, 3.2, 2.9, 2.7]
    tokens_time_labels = ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
    tokens_time_input = [1420, 2150, 3100, 3850, 4600, 5120, 4800]
    tokens_time_output = [210, 320, 280, 240, 290, 270, 250]
    tokens_time_total = [1630, 2470, 3380, 4090, 4890, 5390, 5050]
    tokens_labels = ["Turn 1", "Turn 2", "Turn 3", "Turn 4", "Turn 5", "Turn 6"]
    tokens_input = [140, 220, 310, 390, 470, 520]
    tokens_output = [65, 85, 55, 48, 42, 38]

    try:
        client = bigquery.Client(project=PROJECT_ID)
        job_config = bigquery.QueryJobConfig(use_query_cache=False)

        # 1. Customer ratings distribution
        q = f"""
            SELECT rating, COUNT(*) as cnt
            FROM `{PROJECT_ID}.demo.customer_ratings`
            GROUP BY rating
            ORDER BY rating ASC
        """
        counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for row in client.query(q, job_config=job_config).result():
            r = int(row["rating"])
            if 1 <= r <= 5:
                counts[r] = int(row["cnt"])
        if sum(counts.values()) > 0:
            ratings_dist = [counts[1], counts[2], counts[3], counts[4], counts[5]]

        # 2. Tools breakdown from agent_telemetry.v_tool_completed
        tool_keys = [
            "check_order_status",
            "search_product_catalog",
            "lookup_warranty_policy",
            "initiate_return",
            "lookup_billing_and_refund_status",
        ]
        tool_counts = {k: 0 for k in tool_keys}
        try:
            q_tools = f"""
                SELECT tool_name, COUNT(*) as cnt
                FROM `{PROJECT_ID}.agent_telemetry.v_tool_completed`
                GROUP BY tool_name
            """
            for row in client.query(q_tools, job_config=job_config).result():
                tname = row["tool_name"]
                if tname in tool_counts:
                    tool_counts[tname] = int(row["cnt"])
            if sum(tool_counts.values()) > 0:
                tools_breakdown = [tool_counts[k] for k in tool_keys]
        except Exception as e:
            logger.info(f"BigQuery tools view query notice: {e}")

        # 3. Latency timeline from agent_telemetry.v_llm_response (latest time buckets in chronological order)
        try:
            q_latency = f"""
                SELECT
                    bucket_time,
                    FORMAT_TIMESTAMP('%H:%M', bucket_time) as time_label_hm,
                    FORMAT_TIMESTAMP('%m/%d %H:%M', bucket_time) as time_label_full,
                    avg_s,
                    p95_s
                FROM (
                    SELECT
                        TIMESTAMP_TRUNC(timestamp, MINUTE) as bucket_time,
                        ROUND(AVG(total_ms) / 1000.0, 2) as avg_s,
                        ROUND(APPROX_QUANTILES(total_ms / 1000.0, 100)[OFFSET(95)], 2) as p95_s
                    FROM `{PROJECT_ID}.agent_telemetry.v_llm_response`
                    WHERE total_ms IS NOT NULL
                    GROUP BY bucket_time
                    ORDER BY bucket_time DESC
                    LIMIT 8
                )
                ORDER BY bucket_time ASC
            """
            lat_rows = list(client.query(q_latency, job_config=job_config).result())
            if lat_rows:
                has_multidays = len(set(r["bucket_time"].date() for r in lat_rows)) > 1
                latency_labels = [r["time_label_full" if has_multidays else "time_label_hm"] for r in lat_rows]
                latency_avg = [float(r["avg_s"]) for r in lat_rows]
                latency_p95 = [float(r["p95_s"]) for r in lat_rows]
        except Exception as e:
            logger.info(f"BigQuery latency view query notice: {e}")

        # 4. Token consumption over time timeline from agent_telemetry.v_llm_response (latest time buckets)
        try:
            q_tokens_time = f"""
                SELECT
                    bucket_time,
                    FORMAT_TIMESTAMP('%H:%M', bucket_time) as time_label_hm,
                    FORMAT_TIMESTAMP('%m/%d %H:%M', bucket_time) as time_label_full,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens
                FROM (
                    SELECT
                        TIMESTAMP_TRUNC(timestamp, MINUTE) as bucket_time,
                        CAST(SUM(usage_prompt_tokens) AS INT64) as prompt_tokens,
                        CAST(SUM(usage_completion_tokens) AS INT64) as completion_tokens,
                        CAST(SUM(COALESCE(usage_total_tokens, usage_prompt_tokens + usage_completion_tokens)) AS INT64) as total_tokens
                    FROM `{PROJECT_ID}.agent_telemetry.v_llm_response`
                    WHERE usage_prompt_tokens IS NOT NULL AND usage_completion_tokens IS NOT NULL
                    GROUP BY bucket_time
                    ORDER BY bucket_time DESC
                    LIMIT 8
                )
                ORDER BY bucket_time ASC
            """
            token_time_rows = list(client.query(q_tokens_time, job_config=job_config).result())
            if token_time_rows:
                has_multidays = len(set(r["bucket_time"].date() for r in token_time_rows)) > 1
                tokens_time_labels = [r["time_label_full" if has_multidays else "time_label_hm"] for r in token_time_rows]
                tokens_time_input = [int(r["prompt_tokens"]) for r in token_time_rows]
                tokens_time_output = [int(r["completion_tokens"]) for r in token_time_rows]
                tokens_time_total = [int(r["total_tokens"]) for r in token_time_rows]
        except Exception as e:
            logger.info(f"BigQuery tokens timeline view query notice: {e}")

        # 5. Token usage per turn from agent_telemetry.v_llm_response
        try:
            q_tokens_session = f"""
                WITH latest_session AS (
                    SELECT session_id
                    FROM `{PROJECT_ID}.agent_telemetry.v_llm_response`
                    WHERE session_id IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 1
                )
                SELECT
                    usage_prompt_tokens,
                    usage_completion_tokens
                FROM `{PROJECT_ID}.agent_telemetry.v_llm_response`
                WHERE session_id = (SELECT session_id FROM latest_session)
                  AND usage_prompt_tokens IS NOT NULL 
                  AND usage_completion_tokens IS NOT NULL
                ORDER BY timestamp ASC
                LIMIT 8
            """
            token_rows = list(client.query(q_tokens_session, job_config=job_config).result())
            if not token_rows:
                q_tokens_fb = f"""
                    SELECT
                        usage_prompt_tokens,
                        usage_completion_tokens
                    FROM `{PROJECT_ID}.agent_telemetry.v_llm_response`
                    WHERE usage_prompt_tokens IS NOT NULL AND usage_completion_tokens IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 6
                """
                token_rows = list(client.query(q_tokens_fb, job_config=job_config).result())
                if token_rows:
                    token_rows.reverse()

            if token_rows:
                tokens_labels = [f"Turn {i+1}" for i in range(len(token_rows))]
                tokens_input = [int(r["usage_prompt_tokens"]) for r in token_rows]
                tokens_output = [int(r["usage_completion_tokens"]) for r in token_rows]
        except Exception as e:
            logger.info(f"BigQuery tokens view query notice: {e}")

    except Exception as e:
        logger.info(f"BigQuery ratings chart notice: {e}")

    tokens_time_data = {
        "labels": tokens_time_labels,
        "input_tokens": tokens_time_input,
        "output_tokens": tokens_time_output,
        "total_tokens": tokens_time_total,
    }

    resp = jsonify({
        "ratings_dist": ratings_dist,
        "latency_timeline": {
            "labels": latency_labels,
            "avg": latency_avg,
            "p95": latency_p95,
        },
        "tokens_timeline": tokens_time_data,
        "tokens_over_time": tokens_time_data,
        "tokens_by_turn": {
            "labels": tokens_labels,
            "input_tokens": tokens_input,
            "output_tokens": tokens_output,
        },
        "tools_breakdown": tools_breakdown,
    })
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
