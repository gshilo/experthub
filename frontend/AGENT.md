# Frontend Web Application Orchestration (AGENT.md)

## 1. System Role & Responsibilities
The **Frontend Web Application** orchestrates the end-to-end feedback loop demonstration:
1. Coordinates live interactions between the **Customer Simulator Agent** and **Customer Service Agent**.
2. Streams real-time turns to the browser over **Server-Sent Events (SSE)** with authentic human chat pacing (~5–7s per turn, with animated typing indicators and live status updates).
3. Facilitates interactive manual termination ("End conversation") that triggers customer feedback persistence.
4. Triggers the **Auditor Agent** and renders findings along with generated OKF rules.
5. Ingests telemetry and CSAT metrics from BigQuery and renders interactive analytics charts using **Chart.js**.
6. Enforces human-like response sanitization (`_sanitize_human_service_text`) capping customer service agent messages to 2–3 sentences and stripping bolding (`**`) and em/en/double-dashes (`—`, `–`, `--`).

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

---

## 3. UI Workflows & User Actions

### Tab 1: Live Conversation & Auditor Workspace
* **Start conversation:** Launches a background simulation thread, assigns a random customer persona, and streams alternating turns with realistic human pacing (~5–7s/turn default, or selectable relaxed ~7–10s / fast ~2s). Displays animated typing indicators while agents formulate replies.
* **End conversation:** Triggers immediate graceful abortion, prompting the customer agent to evaluate the interaction up to that point and persist its rating to BigQuery `demo.customer_ratings`.
* **Show instructions:** Queries `/api/agent/instructions` to retrieve the Customer Service Agent's full system prompt—including dynamic OKF rules loaded from `dynamic_context.md` on GitHub and behavioral style constraints—and renders them in an interactive modal with copy functionality and status badges, as well as an inline viewer.
* **Run Auditor Agent:** Calls the Auditor pipeline on demand, displays detected policy/latency issues, token optimization metrics, and synchronizes rules with GitHub: creates `dynamic_context.md` on `main` if missing, or makes additive changes on `new_version` branch awaiting human review before merge into `main`. Displays target branch badge and pending human review pill.

### Tab 2: Telemetry & Analytics Dashboard
* **CSAT Distribution:** Bar chart showing 1 to 5 star rating counts.
* **Latency over Time:** Line chart displaying turn response times and 95th percentile latency.
* **Token Consumption:** Bar chart contrasting input vs. output token counts.
* **Tool Usage Breakdown:** Donut chart illustrating calls to catalog search, order lookup, warranty policy, and return initiation tools.
* **Auto-Refresh Toggle:** Automatically refreshes BigQuery metrics every 15 seconds.

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
* **Active Revision:** `experthub-frontend-00018-v9x`
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


