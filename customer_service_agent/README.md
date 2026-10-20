# Customer Service Agent (`customer_service_agent/`)

## 1. Overview
The **Customer Service Agent** is an autonomous AI support specialist for **ApexHome & Electro**, built using **Google Agent Development Kit (ADK 2.0)** and powered by **Gemini 3.8 Flash** (`gemini-3.8-flash`). It handles customer pre-sale product evaluations, technical comparisons, live order tracking, return authorizations, and troubleshooting across electronics and home appliances.

## 2. Telemetry & Analytics (`agent_telemetry`)
This agent is instrumented with the **`BigQueryAgentAnalyticsPlugin`** from ADK 2.0:
* **Destination Dataset:** `agent_telemetry` (Location: `US` / `us-central1`).
* **Logged Metrics:** Request/response timestamps, latency measurements, input and output token consumption, tool invocation traces, error codes, and session attributes.
* **Auto-Provisioning:** The agent automatically verifies and creates the `agent_telemetry` dataset in BigQuery upon process initialization.

## 3. Dependencies, Telemetry & Agent Engine Observability
In order to enable logging, telemetry, and Observability settings in Vertex AI Agent Engine, ensure all agents are using:
* `google-cloud-aiplatform[agent_engines]` ≥ v1.126.1
* `google-adk` ≥ v1.18.0
* Deployment configured with `--otel_to_cloud` and runtime environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.

These version constraints ensure that OpenTelemetry traces, Cloud Trace spans, container-level execution logs, and Observability dashboard metrics flow directly into Google Cloud Observability from the Agent Engine environment. The agent dependencies are configured in `requirements.txt`:
```text
google-cloud-aiplatform[agent_engines]>=1.126.1
google-adk>=1.18.0
google-cloud-bigquery>=3.46.0
google-cloud-bigquery-storage>=2.42.0
google-cloud-secret-manager>=2.31.0
google-cloud-storage>=3.16.0
pyarrow>=25.0.0
PyGithub>=2.10.0
requests>=2.32.0
pydantic>=2.10.0
```

## 4. Self-Improving Dynamic Context (GitHub OKF Integration)
* **Access Token Retrieval:** Fetches the GitHub Personal Access Token at runtime from **Google Cloud Secret Manager** (`github-pat`).
* **Source Repository:** [`https://github.com/gshilo/experthub_context.git`](https://github.com/gshilo/experthub_context.git) (`main` branch).
* **Target File:** `dynamic_context.md` (with fallback to `dynamic_content.md`).
* **Caching Strategy:** 2-minute (120-second) TTL in-memory cache to ensure low per-turn latency while quickly picking up newly committed rules from the Auditor Agent without agent restarts.
* **Fallback Behavior:** Gracefully falls back to baseline operational policies if GitHub or Secret Manager is temporarily inaccessible.

## 5. Tools & Operational Policies
* `register_customer_order(order_id, customer_name, product, category, issue, ...)`: Dynamically registers runtime-generated customer orders and arbitrary appliances into the in-memory order registry so support tools seamlessly resolve dynamically synthesized customer inquiries without order or catalog deadlocks.
* `check_order_status(order_id)`: Checks real-time shipping carrier, delivery dates, logistics exception flags, and terminal hold notices (resolves registered dynamic orders as well as catalog mock orders).
* `search_product_catalog(query)`: Searches technical specifications, compatibility notes, and verified troubleshooting tips across the full catalog, with fuzzy fallback parsing for arbitrary smart home models.
* `lookup_warranty_policy(category_or_product)`: Explains 1-year manufacturer warranty terms, defect diagnostic requirements, on-site service booking, and advance replacement collateral hold policies.
* `initiate_return(order_id, reason)`: Evaluates return eligibility under strict store policies (30-day window, 15% open-box restocking fee, return freight deduction) and generates conditional Return Merchandise Authorization (RMA) codes.
* `lookup_billing_and_refund_status(order_id)`: Queries payment authorization holds vs settled charges, warehouse return inspection quarantine status, and credit memo processing.
* `get_instructions()`: Retrieves the full system instructions for the Customer Service Agent, combining baseline guidelines from `AGENT.md` with active dynamic directives received from the OKF file (`dynamic_context.md`) and strict response style mandates. Exposed as an agent tool and via module export for the frontend "Show instructions" button.

## 6. Response Formatting & Baseline vs. Post-Audit Behavior
* **Strict Sentence Limit:** Responses are capped at maximum 2 to 3 sentences per turn, matching authentic chat representative pacing.
* **Plain Text Only:** Zero markdown bolding (`**`) and zero long dashes (`—`, `–`, `--`).
* **Baseline Demeanor & Tool Gatekeeping (Pre-Audit):** When no Dynamic OKF Directives are active, the agent uses a dry, strictly procedural tone, withholds immediate tool-generated fee waivers or hassle-free approvals on early turns, insists on DIY troubleshooting first, enforces the 15% open-box restocking fee and 48-hour carrier trace waits, and offers only reluctant, conditional resolutions after customer pushback.
* **Post-Audit Improvement (OKF Directives Active):** When Dynamic OKF Directives from the Auditor Agent are active on `main`, they supersede baseline gatekeeping and friction so the agent proactively uses tool outputs to resolve customer issues smoothly.

## 7. Deployment to Vertex AI Agent Engine
Deploy or redeploy the agent to **Vertex AI Agent Engine** using `deploy.py` (which includes `--otel_to_cloud` by default):

```bash
# Dry run validation
python customer_service_agent/deploy.py --dry-run

# Production deployment / redeployment with telemetry & observability
python customer_service_agent/deploy.py --project=experthub-510907 --region=us-central1 --otel_to_cloud
```
