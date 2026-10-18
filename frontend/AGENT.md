# Frontend Web Application Orchestration (AGENT.md)

## 1. System Role & Responsibilities
The **Frontend Web Application** orchestrates the end-to-end feedback loop demonstration:
1. Coordinates live interactions between the **Customer Simulator Agent** and **Customer Service Agent**.
2. Streams real-time turns to the browser over **Server-Sent Events (SSE)** with authentic human chat pacing (~5–7s per turn, with animated typing indicators and live status updates).
3. Facilitates interactive manual termination ("End conversation") that triggers customer feedback persistence.
4. Triggers the **Auditor Agent** and renders findings along with generated OKF rules.
5. Ingests telemetry and CSAT metrics from BigQuery and renders interactive analytics charts using **Chart.js**.
6. Enforces human-like response sanitization (`_sanitize_human_service_text`) capping customer service agent messages to 2–3 sentences and stripping bolding (`**`) and em/en/double-dashes (`—`, `–`, `--`), while aligning its dynamic service turn fallback (`_generate_dynamic_service_turn_static`) with strict baseline gatekeeping/friction pre-Audit and proactive resolution when Dynamic OKF Directives are active.

---

## 2. Server-Sent Events (SSE) Protocol

### Endpoint: `GET /api/conversation/stream/<session_id>`
Content-Type: `text/event-stream`

### Event Types:
* `event: init`: Emitted immediately upon session launch with generated customer persona (`customer_name`, `product`, `issue`).
* `event: typing`: Emitted during typing and system review/search periods (`sender`, `name`, `status_text`, `tools`, `timestamp`).
* `event: customer_turn`: Emitted when the simulated customer speaks (`text`, `turn_index`, `timestamp`).
* `event: service_turn`: Emitted when the customer service agent responds (`text`, `turn_index`, `tools_called`, `latency_ms`).
* `event: rating`: Emitted when the customer rates the interaction (`rating` [1–5], `description`, `customer_id`).
* `event: complete`: Emitted when the session is finalized and persisted.
* `event: aborted`: Emitted when the user manually terminates the dialogue early.

### Endpoint: `POST /api/conversation/prewarm`
Triggers and reports status of the 2-slot background dialog pre-warming pool (`PREWARM_POOL_TARGET = 2`). Each pre-warmed slot prepares a live Customer Persona (Turn 1), dynamic order registration, ADK `InMemoryRunner` session on a shared persistent event loop, OKF dynamic context, and the first Customer Service reply (Turn 2). Consuming a slot via `POST /api/conversation/start` immediately triggers background replenishment, and `POST /api/auditor/run` invalidates and rebuilds the pool with the updated OKF rules.

---

## 3. UI Workflows & User Actions

### Tab 1: Live Conversation & Auditor Workspace
* **Start conversation:** Pops a pre-warmed dialog slot (`< 50ms` response time), renders the customer's opening message (Turn 1) in `~0.3s` and the pre-warmed Customer Service reply (Turn 2) in `~1.5s`, and streams Turn 3+ live while overlapping LLM generation with the current turn's typing animation. Displays animated typing indicators while agents formulate replies.
* **End conversation:** Triggers immediate graceful abortion, prompting the customer agent to evaluate the interaction up to that point and persist its rating to BigQuery `demo.customer_ratings`.
* **Show instructions:** Queries `/api/agent/instructions` to retrieve the Customer Service Agent's full system prompt—including dynamic OKF rules loaded from `dynamic_context.md` on GitHub and behavioral style constraints—and renders them in an interactive modal with copy functionality and status badges, as well as an inline viewer.
* **Run Auditor Agent:** Calls the Auditor pipeline on demand, displays detected policy/latency issues, token optimization metrics, and synchronizes rules with GitHub: creates `dynamic_context.md` on `main` if missing, or makes additive changes on `new_version` branch awaiting human review before merge into `main`. Displays target branch badge and pending human review pill.

### Tab 2: Telemetry & Analytics Dashboard
* **CSAT Distribution:** Bar chart showing 1 to 5 star rating counts.
* **Latency over Time:** Line chart displaying turn response times and 95th percentile latency.
* **Token Consumption:** Bar chart contrasting input vs. output token counts.
* **Tool Usage Breakdown:** Donut chart illustrating calls to catalog search, order lookup, warranty policy, and return initiation tools.
* **Auto-Refresh Toggle:** Automatically refreshes BigQuery metrics every 15 seconds.

### Tab 3: Customer Analysis (Auditor AI & A2UI 0.9.1)
* **Static Dashboard (Top Section):**
  * **Customer Sentiment:** Sentiment distribution (Positive, Neutral, Negative) computed with BigQuery AI reasoning (`AI.CLASSIFY` / `AI.GENERATE`).
  * **Customer Satisfaction:** Star rating distribution (1-5 stars) and verbal feedback praises/complaints synthesized directly in BigQuery from `demo.customer_ratings`.
  * **Product Rating by Returns & Defects:** Product-level ratings, defect incidence %, return counts, and primary reported defect descriptions.
  * **Auditor BigQuery AI Pushdown Trace:** Expandable view of the SQL query, duration (~850ms), and AI functions used (`AI.IF`, `AI.GENERATE`).
  * **Refresh Analysis:** On-demand refresh button backed by `/api/customer-analysis/dashboard` with 60-second in-memory caching.
* **Dynamic Query & Visualization (Bottom Section):**
  * **Natural Language Text Box:** Enables users to ask arbitrary customer service, defect, return, or satisfaction questions.
  * **One-Click Suggestion Chips:** Quick execution for popular queries ("Satisfaction over time", "Top defect complaints by product", "Negative verbal feedback drivers", "Return reasons vs star ratings", "Appliance sentiment breakdown").
  * **Auditor Agent Backend (`POST /api/customer-analysis/query`):** Pushes down AI reasoning to BigQuery with BigQuery AI functions and formats response into **A2UI 0.9.1** protocol format.
  * **A2UI 0.9.1 Client Engine:** Standard-compliant client renderer converting A2UI v0.9.1 adjacency list messages (`createSurface`, `updateComponents`, `updateDataModel`) into interactive cards, metric callouts, responsive tables, and dynamic Chart.js visualizations.
  * **Auditor SQL Trace & A2UI Inspector:** Collapsible panel showing the executed BigQuery SQL with execution duration, plus a dedicated "View A2UI 0.9.1 JSON" modal.

---

## 4. Runtime Dependencies, Telemetry & Agent Engine Observability
In order to enable logging, telemetry, and Observability settings in Vertex AI Agent Engine across the orchestration pipeline, ensure all agents are using:
* `google-cloud-aiplatform[agent_engines]` ≥ v1.126.1
* `google-adk` ≥ v1.18.0
* Deployment configured with `--otel_to_cloud` and environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.

These library standards provide comprehensive Cloud Logging capture, OpenTelemetry tracing, and Observability integration across all deployed agents.

---

## 5. Model Authentication & Secret Manager Key Management
* **Gemini Model Authentication:** The frontend and its coordinated agents dynamically load the Gemini API key from Google Cloud Secret Manager (`gemini-api-key` / `google-api-key`) via `ensure_gemini_api_key()`.
* **Zero-Hardcoding Policy:** The application does not store API keys in plaintext or hardcode them in Dockerfiles or Cloud Run environment variables.
* **Seamless Runtime Resolution:** On startup, `ensure_gemini_api_key()` populates `os.environ["GEMINI_API_KEY"]` and `os.environ["GOOGLE_API_KEY"]` dynamically, completely eliminating `ValueError: No API key was provided` across local and Cloud Run environments.

---

## 6. Cloud Run Deployment & Service Configuration
* **Service Name:** `experthub-frontend`
* **Active Revision:** `experthub-frontend-00028-zfg`
* **Live Service URL:** [https://experthub-frontend-537563976049.us-central1.run.app](https://experthub-frontend-537563976049.us-central1.run.app)
* **Associated Agent Engine IDs:**
  * `CUSTOMER_SERVICE_AGENT_ID`: `2556039354015285248`
  * `CUSTOMER_AGENT_ID`: `8810413336526061568`
  * `AUDITOR_AGENT_ID`: `4360856904684011520`
* **Redeployment Command:**
  ```bash
  gcloud run deploy experthub-frontend \
      --source . \
      --region us-central1 \
      --project experthub-510907 \
      --allow-unauthenticated \
      --set-env-vars GOOGLE_CLOUD_PROJECT=experthub-510907,GCP_REGION=us-central1,CUSTOMER_SERVICE_AGENT_ID=2556039354015285248,CUSTOMER_AGENT_ID=8810413336526061568,AUDITOR_AGENT_ID=4360856904684011520
  ```


