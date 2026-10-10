# Frontend Web Application (`frontend/`)

## 1. Overview
The **Frontend Web Application** provides the unified user interface for the Self-Improving Agent Feedback Loop demo. Built with **Flask** and **Chart.js**, containerized with **Docker**, and deployed to **Google Cloud Run**, it coordinates live interactions between the Customer Simulator Agent and the Customer Service Agent, streams conversations in real time via Server-Sent Events (SSE), triggers the Auditor Agent pipeline, and visualizes system telemetry stored in BigQuery.

## 2. Web Interface Architecture

### Tab 1: Live Conversation & Auditor Workspace
* **"Start conversation" Button:** Spawns an asynchronous worker thread that instantiates a randomized customer persona from the electronics and appliance catalog, streams alternating turns with realistic human chat pacing (~5–7s per turn, with animated typing indicators and live status updates), and logs the customer's post-chat satisfaction score. Includes a pacing selector for Realistic Human, Relaxed (~7–10s), or Fast (~2s) demo modes.
* **"End conversation" Button:** Gracefully aborts an in-progress session, triggering early evaluation and immediate feedback persistence to BigQuery.
* **"Show instructions" Button:** Queries `/api/agent/instructions` to fetch the Customer Service Agent's active system prompt (incorporating base policies from `AGENT.md` alongside dynamic OKF directives loaded from GitHub `dynamic_context.md` and behavioral mandates) and presents them to the user in a full-featured modal dialog and inline viewer.
* **Auditor Workspace:** Features an on-demand **"Run Auditor Agent"** button that invokes the Auditor pipeline, displays detected bottlenecks, highlights token efficiency gains, and presents the committed Open Knowledge Format (OKF v0.2) rules.

### Tab 2: Visualization & Telemetry Analytics Dashboard
Queries Google BigQuery (`agent_telemetry` and `demo.customer_ratings`) and visualizes:
1. **Customer Satisfaction (CSAT) Distribution:** 1 to 5 star ratings.
2. **Response Latency Over Time:** Average turn latency and 95th percentile spikes.
3. **Token Consumption Over Time:** Prompt input, completion output, and total tokens tracked across telemetry timeline timestamps.
4. **Tool Invocations Breakdown:** Catalog searches, order status checks, warranty lookups, and return requests.
5. **Turn-by-Turn Token Breakdown:** Multi-turn conversational prompt and completion token evolution.

## 3. Dependencies, Telemetry & Agent Engine Observability
In order to enable logging, telemetry, and Observability settings in Vertex AI Agent Engine, ensure all agents are using:
* `google-cloud-aiplatform[agent_engines]` ≥ v1.126.1
* `google-adk` ≥ v1.18.0
* Deployment configured with `--otel_to_cloud` and environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.

Frontend dependencies in `requirements.txt` reflect this compatibility baseline:
```text
Flask>=3.1.0
gunicorn>=23.0.0
google-cloud-aiplatform[agent_engines]>=1.126.1
google-adk>=1.18.0
google-cloud-bigquery>=3.46.0
google-cloud-bigquery-storage>=2.42.0
google-cloud-secret-manager>=2.31.0
pyarrow>=25.0.0
requests>=2.32.0
PyGithub>=2.10.0
pydantic>=2.10.0
```

## 4. Production Deployment to Google Cloud Run

To build and deploy the frontend container to Cloud Run with public access:

```bash
# Build and deploy from repository root
gcloud run deploy experthub-frontend \
    --source . \
    --region us-central1 \
    --project experthub-510907 \
    --allow-unauthenticated \
    --set-env-vars GOOGLE_CLOUD_PROJECT=experthub-510907,GCP_REGION=us-central1
```
