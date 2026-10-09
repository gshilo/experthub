# Customer Simulator Agent (`customer_agent/`)

## 1. Overview
The **Customer Simulator Agent** simulates realistic human customer interactions with ApexHome & Electro's customer service. Built using **Google Agent Development Kit (ADK 2.0)** and powered by **Gemini 3.8 Flash** (`gemini-3.8-flash`), it generates novel customer personas live on every conversation trigger, conducts natural multi-turn conversations with human pacing, and autonomously rates the experience.

## 2. Live Model Persona Generation, Problem Diversity & Pacing
* **Live Model Generation (`gemini-3.8-flash`):** Replaced static catalog archetypes with real-time model persona synthesis. Each time a conversation is triggered, `generate_customer_persona()` generates a distinct, unique mixture of:
  * **Diverse Problem Domains:** Hardware malfunctions, shipping and delivery exceptions, duplicate billing authorization holds, return and 15% restocking fee disputes, HDMI 2.1 eARC / 144Hz VRR handshake sync, freight damage, missing parts, and Wi-Fi pairing hurdles.
  * **Broad Appliance & Electronics Spectrum:** Smart refrigerators, 4K/8K OLED TVs, front-load washer/dryer stacks, touchscreen espresso machines, workstation laptops, LiDAR robot vacuums, Dolby Atmos soundbars, smart induction cooktops, security camera hubs, and smart thermostats.
  * **Varied Customer Personalities:** Hurried professionals with tight schedules, elderly non-technical buyers, detail-oriented engineers, anxious homeowners, budget-conscious consumers, skeptical buyers with doorbell camera proof, and blunt/direct communicators.
  * **Variable Patience & Literacy:** Dynamically mixes Low, Moderate, and High patience with Non-technical, Average, and Tech-savvy technical backgrounds.
* **Live Multi-Turn Dialogue (`generate_customer_turn`):** Customer dialogue turns are synthesized live by the model in response to the service agent, with realistic resistance, authentic emotional arcs, and natural pushback against bureaucratic hurdles and fees.
* **Realistic Ratings (1–5 Stars):** Customer feedback is not always 5-star; scores realistically range from 1 to 5 depending on customer friction, delays, and resolution quality.
* **Human-Like Pacing:** Inserts authentic **~5–7 second delays** between turns with typing indicators and reading comprehension pauses to mirror genuine human typing and reading cadence in the live UI stream.

## 3. Conversation Termination Criteria
The simulation loop continues until **any** of the following conditions is satisfied:
1. **Issue Resolved:** The simulated customer's inquiry is satisfactorily answered or resolved.
2. **Customer Frustrated:** The persona's patience threshold is exhausted and they abandon the session.
3. **Session Timeout:** Elapsed time exceeds **5 minutes** (300 seconds).
4. **User Abort:** The user clicks the **"End conversation"** button in the web UI.

## 4. BigQuery Ratings Persistence (`demo.customer_ratings`)
Upon chat completion, the customer evaluates the conversation from their persona's viewpoint and writes a row to BigQuery:
* **Dataset:** `demo`
* **Table:** `customer_ratings`
* **Exact Schema:**
  * `customer_id`: `INTEGER` (Unique identifier)
  * `customer_name`: `STRING` (Customer's full name)
  * `rating`: `INTEGER` (1 to 5 scale)
  * `description`: `STRING` (Concise qualitative feedback explaining the score)
  * `timestamp`: `TIMESTAMP` (ISO 8601 UTC timestamp of rating submission)

Because personas and complaints are generated live with wide topical variety, the BigQuery ratings dataset receives a continuously diverse spectrum of feedback, enabling the **Auditor Agent** to discover diverse friction patterns and synthesize novel OKF operational rules.

## 5. Dependencies, Telemetry & Agent Engine Observability
In order to enable logging, telemetry, and Observability settings in Vertex AI Agent Engine, ensure all agents are using:
* `google-cloud-aiplatform[agent_engines]` ≥ v1.126.1
* `google-adk` ≥ v1.18.0
* `google-genai` ≥ v1.0.0
* Deployment configured with `--otel_to_cloud` and environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.

These version constraints ensure runtime execution tracing, OpenTelemetry Cloud Trace ingestion, and Cloud Logging function properly within the Agent Engine sandbox. The component `requirements.txt` specifies:
```text
google-cloud-aiplatform[agent_engines]>=1.126.1
google-adk>=1.18.0
google-genai>=1.0.0
google-cloud-bigquery>=3.46.0
google-cloud-bigquery-storage>=2.42.0
google-cloud-secret-manager>=2.31.0
pyarrow>=25.0.0
requests>=2.32.0
pydantic>=2.10.0
```

## 6. Deployment to Vertex AI Agent Engine
Deploy or redeploy the agent to **Vertex AI Agent Engine** using `deploy.py` (which includes `--otel_to_cloud` by default):

```bash
# Dry run validation
python customer_agent/deploy.py --dry-run

# Production deployment / redeployment with telemetry & observability
python customer_agent/deploy.py --project=experthub-510907 --region=us-central1 --otel_to_cloud
```
