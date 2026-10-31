# ExpertHub Agent Ecosystem Specification (`AGENT.md`)

Welcome to the **ApexHome & Electro Self-Improving Agent System** specification. This document outlines the architecture, personas, behavioral protocols, dynamic context integration, and security/credential management across all autonomous agents in the ExpertHub platform.

---

## 1. System Architecture Overview

ExpertHub is a closed-loop, self-improving multi-agent system built on the **Google Agent Development Kit (ADK 2.0)**, powered by **Gemini 3.8 Flash**, integrated with **Vertex AI Agent Engine**, **BigQuery Agent Analytics**, and **Google Cloud Secret Manager**.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ExpertHub Multi-Agent System                    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         ▼                          ▼                          ▼
┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│  Customer Agent  │       │ Customer Service │       │  Auditor Agent   │
│   (Simulator)    │       │     Agent        │       │  (Optimization)  │
└────────┬─────────┘       └────────┬─────────┘       └────────┬─────────┘
         │                          │                          │
         │   Evaluations / Ratings  │   Telemetry & Spans      │
         └─────────────┬────────────┴─────────────┬────────────┘
                       ▼                          ▼
         ┌─────────────────────────────────────────────────────┐
         │     BigQuery Datasets (demo & agent_telemetry)      │
         └─────────────────────────┬───────────────────────────┘
                                   │
                                   ▼
         ┌─────────────────────────────────────────────────────┐
         │ Dynamic OKF Rules in Cloud Storage (instructions91) │
         │               (dynamic_context.md)                  │
         └─────────────────────────────────────────────────────┘
```

The system consists of three specialized agents:
1. [**Customer Service Agent**](file:///home/admin_gshilo_altostrat_com/experthub/customer_service_agent/AGENT.md): Realistic human-like customer support agent on live chat (max 2-3 sentences, plain text without bolding or long dashes, non-sycophantic tone with realistic pushback and slight conflict when defending store policies).
2. [**Customer Simulator Agent**](file:///home/admin_gshilo_altostrat_com/experthub/customer_agent/AGENT.md): Model-driven simulator (`gemini-3.8-flash`) generating novel personas, diverse complaints, and authentic multi-turn pushback live on every session trigger.
3. [**Auditor Agent**](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/AGENT.md): Multi-stage analytical engine evaluating CSAT ratings and telemetry, formulating token optimizations, authoring Open Knowledge Format (OKF v0.2) rules, and powering the Customer Analysis engine with in-database BigQuery AI functions and A2UI 0.9.1 dynamic visualizations.

---

## 2. Model Authentication & Secret Manager Credentials

### Zero Hardcoding Policy
In accordance with Google Cloud enterprise security best practices:
* **API keys are NEVER stored hardcoded in source code, configuration files, Dockerfiles, or git repositories.**
* Credentials are securely provisioned and stored in **Google Cloud Secret Manager**.

### Secret Manager Credential Inventory
| Secret ID | Version | Description | Target Component |
| :--- | :--- | :--- | :--- |
| `gemini-api-key` | `latest` (v1) | Gemini API Key for model inference (`gemini-3.8-flash`) | Customer Service, Customer, Auditor, Frontend |
| `google-api-key` | `latest` (v1) | Compatibility alias for Google GenAI SDK | Customer Service, Customer, Auditor, Frontend |

### Dynamic Runtime Key Resolution (`ensure_gemini_api_key`)
At application and agent startup, each component invokes `ensure_gemini_api_key(project_id)`:
1. Inspects `os.environ` for existing `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
2. If absent or placeholder, queries Google Cloud Secret Manager for secret `gemini-api-key` (falling back to `google-api-key`).
3. Dynamically injects the retrieved key into `os.environ["GEMINI_API_KEY"]` and `os.environ["GOOGLE_API_KEY"]`.
4. Initializes `google.genai.Client` and ADK `GoogleLLM`, completely eliminating the `ValueError: No API key was provided` runtime exception.

---

## 3. Dynamic Context & Google Cloud Storage Lifecycle

The system self-improves by maintaining an Open Knowledge Format (OKF v0.2) document (`dynamic_context.md`) in Google Cloud Storage bucket `instructions91` (`US` multi-region).

### Storage & Dynamic Loading Protocol:
1. **Bucket Creation on First Load:**
   * If the bucket `instructions91` does not exist on the Customer Service Agent's first dynamic context load, it is created automatically.
   * If the Auditor Agent runs before the Customer Service Agent has initialized the bucket, the Auditor Agent also creates it automatically.
2. **Direct Overwrite with Rule Merging:**
   * The Auditor Agent reads existing OKF rules from `gs://instructions91/dynamic_context.md` (if present).
   * Formulates new operational rules based on BigQuery feedback and telemetry analysis, deduplicating candidate rules against existing policies.
   * Merges and appends newly formulated policies and directives directly into `gs://instructions91/dynamic_context.md`.
3. **Live Context Consumption:**
   * The Customer Service Agent retrieves dynamic directives from `gs://instructions91/dynamic_context.md` with TTL caching.
   * When dynamic rules are present, they supersede baseline friction and gatekeeping. If the file is not yet populated, the agent uses its baseline demeanor.

---

## 4. Agent Profiles & Reference Documentation

* [**Customer Service Agent Documentation (`customer_service_agent/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/customer_service_agent/AGENT.md): Realistic human-like customer support representative protocols, strict 2-3 sentence response limits, zero markdown bolding (`**`), zero long dashes, dynamic order registry (`register_customer_order`), instruction inspection tool (`get_instructions`), fuzzy catalog search, and realistic slight conflict when defending store policies.
* [**Customer Simulator Agent Documentation (`customer_agent/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/customer_agent/AGENT.md): Live model-based persona synthesis (`gemini-3.8-flash`), live turn generation (`generate_customer_turn`), diverse mixtures of problem domains, products, personalities, and patience, multi-turn dialogue progression, and BigQuery customer ratings persistence rubric (`demo.customer_ratings`).
* [**Auditor Agent Documentation (`auditor_agent/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/AGENT.md): 3-stage sequential multi-agent audit pipeline (Telemetry Analyzer, Token Efficiency Optimizer, OKF Author & Committer), BigQuery AI pushdown engine (`query_customer_analysis_static_bq`, `process_customer_analysis_query`), dynamic A2UI 0.9.1 protocol generation, BigQuery AI functions skill (`bigquery-ai-functions`), ADK Agent Analytics telemetry skill (`adk-agent-telemetry`), and GitHub sync protocol.
* [**Frontend Application Documentation (`frontend/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/frontend/AGENT.md): Flask orchestration, dynamic ADK `InMemoryRunner` session execution, SSE streaming protocol, Customer Analysis tab (static BigQuery AI dashboard & dynamic A2UI 0.9.1 surfaces), "Show instructions" inspection modal and API (`/api/agent/instructions`), telemetry graphs, and human-in-the-loop review interface.

---

## 5. Runtime Dependencies & Observability Standards

All agents and services adhere to the following dependency and telemetry baselines:
* `google-cloud-aiplatform[agent_engines]` ≥ `1.126.1`
* `google-adk` ≥ `1.18.0`
* `google-genai` ≥ `1.0.0`
* `google-cloud-secret-manager` ≥ `2.31.0`
* `google-cloud-bigquery` ≥ `3.46.0`
* `google-cloud-storage` ≥ `3.16.0`
* Telemetry enabled via `--otel_to_cloud`, exporting traces, spans, and metrics to Google Cloud Trace, BigQuery, and Vertex AI Agent Engine Observability.

---

## 6. Deployed Vertex AI Agent Engine Endpoints & Reasoning Engine IDs

The multi-agent ecosystem is actively deployed to Google Cloud across the following managed resources:

| Component | Architecture | Resource Identifier | Console URL | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Customer Service Agent** | Vertex AI Agent Engine | `projects/537563976049/locations/us-central1/reasoningEngines/2556039354015285248` | [Playground](https://console.cloud.google.com/vertex-ai/agents/agent-engines/locations/us-central1/agent-engines/2556039354015285248/playground?project=experthub-510907) | Active / Deployed |
| **Customer Simulator Agent** | Vertex AI Agent Engine | `projects/537563976049/locations/us-central1/reasoningEngines/8810413336526061568` | [Playground](https://console.cloud.google.com/vertex-ai/agents/agent-engines/locations/us-central1/agent-engines/8810413336526061568/playground?project=experthub-510907) | Active / Deployed |
| **Auditor Agent** | Vertex AI Agent Engine | `projects/537563976049/locations/us-central1/reasoningEngines/4360856904684011520` | [Playground](https://console.cloud.google.com/vertex-ai/agents/agent-engines/locations/us-central1/agent-engines/4360856904684011520/playground?project=experthub-510907) | Active / Deployed |
| **Frontend Web Application** | Google Cloud Run | Service: `experthub-frontend` | [Live Web App](https://experthub-frontend-537563976049.us-central1.run.app) | Serving 100% Traffic |

### Component Redeployment Commands:
```bash
# Redeploy Customer Service Agent to Vertex AI Agent Engine
python customer_service_agent/deploy.py \
    --project=experthub-510907 \
    --region=us-central1 \
    --agent_engine_id=2556039354015285248 \
    --otel_to_cloud

# Redeploy Customer Simulator Agent to Vertex AI Agent Engine
python customer_agent/deploy.py \
    --project=experthub-510907 \
    --region=us-central1 \
    --agent_engine_id=8810413336526061568 \
    --otel_to_cloud

# Redeploy Auditor Agent to Vertex AI Agent Engine
python auditor_agent/deploy.py \
    --project=experthub-510907 \
    --region=us-central1 \
    --agent_engine_id=4360856904684011520 \
    --otel_to_cloud

# Redeploy Frontend Web Application to Google Cloud Run
gcloud run deploy experthub-frontend \
    --source . \
    --region us-central1 \
    --project experthub-510907 \
    --allow-unauthenticated \
    --set-env-vars GOOGLE_CLOUD_PROJECT=experthub-510907,GCP_REGION=us-central1
```

---

## 7. Dynamic Simulation & Creative Customer Service Architecture

To eliminate conversational rigidity, repetitive dialogues, and rigid script formulas, the interaction pipeline was re-architected across all three layers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Frontend Orchestrator (app.py)                  │
│  - Triggers live persona synthesis                                     │
│  - Automatically registers order in Customer Service Agent             │
│  - Executes live back-and-forth loop using ADK InMemoryRunner (35s)   │
│  - Emits real-time SSE events with human pacing (5-7s)                 │
└──────────────────┬──────────────────────────────────┬──────────────────┘
                   │                                  │
                   ▼                                  ▼
      ┌─────────────────────────┐        ┌─────────────────────────┐
      │ Customer Simulator Agent│        │ Customer Service Agent  │
      │   (customer_agent)      │        │ (customer_service_agent)│
      ├─────────────────────────┤        ├─────────────────────────┤
      │ • 20+ Problem Domains   │        │ • Dynamic Order Registry│
      │ • 22 Product Categories │        │ • Fuzzy Catalog Lookup  │
      │ • Live Persona Synthesis│        │ • Creative Compromises  │
      │ • Live Turn Generation  │        │ • Diagnostic Checklists │
      │ • Authentic Pushback    │        │ • BigQuery Telemetry    │
      │ • Evaluates CSAT (1-5)  │        │ • Dynamic OKF Rules     │
      └─────────────────────────┘        └─────────────────────────┘
```

### 1. Elimination of Legacy Canned Scripts
* **Legacy Bottleneck:** Previously, `frontend/app.py` employed static keyword matching (`_build_conversation_script`) mapping terms like `"tv"`, `"fridge"`, or `"washer"` into 10 hardcoded dialog scripts.
* **Modern Architecture:** Canned scripts have been completely removed. Conversations are 100% generated live in real time using `gemini-3.8-flash`, with `generate_customer_turn()` producing authentic customer replies to actual service statements.

### 2. Elimination of Catalog and Order Deadlocks
* **Legacy Bottleneck:** Customer Service tools (`check_order_status`, `lookup_billing_and_refund_status`, `initiate_return`) originally checked only 10 hardcoded orders (`ORD-1001` through `ORD-1010`) and 6 static products. When the simulator generated a new order ID or appliance, tools failed with *"Order not found"*, stalling the dialogue.
* **Modern Solution (`register_customer_order`):**
  * `customer_service_agent/agent.py` exposes `register_customer_order(...)`, maintaining an in-memory dynamic order registry (`_DYNAMIC_ORDERS_REGISTRY`).
  * On every session initiation, `frontend/app.py` registers the customer's dynamically generated order, shipping carrier, tracking number, and product specifications.
  * `search_product_catalog()` includes fuzzy fallback parsing so arbitrary consumer appliances and electronic gadgets are recognized and provided with technical specs.

### 3. Emotional Realism & Authentic Multi-Turn Progression
* **Domain & Circumstantial Diversity:** Seeded across 20+ problem categories (firmware handshakes, defrost errors, carrier misdeliveries, pre-auth holds, restocking fees) and high-stakes real-world contexts (sleeping infant during storm, guests arriving in 2 hours, sim racing tournaments).
* **Variable Pushback:** Customers have distinct patience levels (Low, Moderate, High) and do not concede on turn 1 or 2. They question fees, verify diagnostics, and negotiate alternatives.

### 4. Human-Like Customer Service Communication & Baseline vs. Post-Audit Behavior
* **Strict Sentence Limit:** Customer service agent responses are strictly capped at 2 to 3 sentences maximum per turn. No essays, multi-paragraph explanations, or multi-step bulleted lists.
* **Plain Text Only (Zero Bolding & Long Dashes):** Absolutely zero markdown bolding (`**`) and zero long dashes (`—`, `–`, `--`) in responses. Plain conversational chat text only.
* **Baseline Demeanor & Strict Gatekeeping (Pre-Audit):** When no Dynamic OKF Directives are active, the agent acts like a dry, strictly procedural rep who withholds immediate fee waivers or hassle-free approvals on early turns (even when internal tools output pre-generated RMA codes or waiver notes), insists on DIY troubleshooting first, enforces the 15% open-box restocking fee and 48-hour carrier trace waits, and offers only reluctant, conditional resolutions after customer pushback.
* **Post-Audit Improvement (OKF Directives Active):** When Dynamic OKF Directives from the Auditor Agent are present on `main`, they supersede baseline gatekeeping and friction, enabling the agent to proactively issue RMAs, waive restocking/freight fees on defects or exchanges, schedule technicians, and resolve issues smoothly.

