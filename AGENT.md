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
         │      Dynamic OKF Rules via GitHub Repository        │
         │   (main = production rules; new_version = review)   │
         └─────────────────────────────────────────────────────┘
```

The system consists of three specialized agents:
1. [**Customer Service Agent**](file:///home/admin_gshilo_altostrat_com/experthub/customer_service_agent/AGENT.md): Realistic human-like customer support agent on live chat (max 2-3 sentences, plain text without bolding or long dashes, non-sycophantic tone with realistic pushback and slight conflict when defending store policies).
2. [**Customer Simulator Agent**](file:///home/admin_gshilo_altostrat_com/experthub/customer_agent/AGENT.md): Model-driven simulator (`gemini-3.8-flash`) generating novel personas, diverse complaints, and authentic multi-turn pushback live on every session trigger.
3. [**Auditor Agent**](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/AGENT.md): Multi-stage analytical engine evaluating CSAT ratings and telemetry, formulating token optimizations, and authoring Open Knowledge Format (OKF v0.2) rules.

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
| `github-deploy-key` | `latest` (v1) | Ed25519 SSH Deploy Key for Git read/write operations | Auditor Agent, Customer Service Agent |
| `github-pat` | `latest` (v1) | GitHub Personal Access Token (REST API fallback) | Auditor Agent, Customer Service Agent |

### Dynamic Runtime Key Resolution (`ensure_gemini_api_key`)
At application and agent startup, each component invokes `ensure_gemini_api_key(project_id)`:
1. Inspects `os.environ` for existing `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
2. If absent or placeholder, queries Google Cloud Secret Manager for secret `gemini-api-key` (falling back to `google-api-key`).
3. Dynamically injects the retrieved key into `os.environ["GEMINI_API_KEY"]` and `os.environ["GOOGLE_API_KEY"]`.
4. Initializes `google.genai.Client` and ADK `GoogleLLM`, completely eliminating the `ValueError: No API key was provided` runtime exception.

---

## 3. Dynamic Context & GitHub Branch Lifecycle

The system self-improves by maintaining an Open Knowledge Format (OKF v0.2) document (`dynamic_context.md`) in the GitHub repository `https://github.com/gshilo/experthub_context.git`.

### GitHub Interaction Protocol:
1. **Initial File Creation on `main` Branch:**
   * If `dynamic_context.md` is missing from the `main` branch, the Auditor Agent initializes the file directly on `main` with baseline operational policies and token directives.
2. **Incremental Updates on `new_version` Branch:**
   * If `dynamic_context.md` already exists on `main`, the Auditor Agent makes changes **ONLY** to the file on the `new_version` branch.
   * **Rule Retention:** All existing rules are strictly preserved; no existing policies or directives are removed or overwritten.
   * **Additive Expansion:** Only newly formulated policies and directives are appended.
3. **Human Review & Merge Gate:**
   * Changes on `new_version` remain isolated pending human review and approval.
   * After human verification, changes are merged into `main` by an authorized operator.
   * The Customer Service Agent consumes dynamic context strictly from the `main` branch in production.

---

## 4. Agent Profiles & Reference Documentation

* [**Customer Service Agent Documentation (`customer_service_agent/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/customer_service_agent/AGENT.md): Realistic human-like customer support representative protocols, strict 2-3 sentence response limits, zero markdown bolding (`**`), zero long dashes, dynamic order registry (`register_customer_order`), instruction inspection tool (`get_instructions`), fuzzy catalog search, and realistic slight conflict when defending store policies.
* [**Customer Simulator Agent Documentation (`customer_agent/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/customer_agent/AGENT.md): Live model-based persona synthesis (`gemini-3.8-flash`), live turn generation (`generate_customer_turn`), diverse mixtures of problem domains, products, personalities, and patience, multi-turn dialogue progression, and BigQuery customer ratings persistence rubric (`demo.customer_ratings`).
* [**Auditor Agent Documentation (`auditor_agent/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/AGENT.md): 3-stage sequential multi-agent audit pipeline (Telemetry Analyzer, Token Efficiency Optimizer, OKF Author & Committer), BigQuery AI & Generative AI Functions skill (`bigquery-ai-functions`), and GitHub sync protocol.
* [**Frontend Application Documentation (`frontend/AGENT.md`)**](file:///home/admin_gshilo_altostrat_com/experthub/frontend/AGENT.md): Flask orchestration, dynamic ADK `InMemoryRunner` session execution, SSE streaming protocol, "Show instructions" inspection modal and API (`/api/agent/instructions`), telemetry graphs, and human-in-the-loop review interface.

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

### 4. Human-Like Customer Service Communication & Behavioral Realism
* **Strict Sentence Limit:** Customer service agent responses are strictly capped at 2 to 3 sentences maximum per turn. No essays, multi-paragraph explanations, or multi-step bulleted lists.
* **Plain Text Only (Zero Bolding & Long Dashes):** Absolutely zero markdown bolding (`**`) and zero long dashes (`—`, `–`, `--`) in responses. Plain conversational chat text only.
* **Non-Sycophantic Demeanor:** Replaced artificial, sugary bot cheerfulness and profuse apologies with authentic human customer support tone: matter-of-fact, tired, blunt, skeptical, or firm.
* **Realistic Conflict & Pushback:** The agent can get into slight conflict with the customer when appropriate. Instead of immediately caving in to angry demands, the agent stands firm on company policy: enforcing the 30-day return window, defending the 15% open-box restocking fee, requiring remote diagnostic triage before authorizing technicians or RMAs, and insisting on the 48-hour carrier trace window for missing deliveries.

