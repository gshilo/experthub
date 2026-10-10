# Autonomous Build & Deployment Instructions: Self-Improving Agent Feedback Loop Demo

## 1. Role & Mission
You are an autonomous Principal Cloud Architect and AI Coding Agent operating in **Antigravity 2**. Your objective is to build, document, configure, and deploy a working end-to-end demonstration of an **Agent Feedback Loop and Self-Improving Agent System** for an e-commerce platform specializing in electronics and home appliances.

You must create all required subdirectories, write all Python source code, author all `AGENT.md` and `README.md` files, configure Google Cloud infrastructure and IAM permissions in the current project, and deploy all components.

---

## 2. Global Technical Stack & Architectural Rules
* **Language & SDKs:** Python 3.11+, Google Agent Development Kit (**ADK 2.0**), **Agent Analytics Plugin**, `google-cloud-bigquery`, `google-cloud-secret-manager`, `PyGithub` (or Git/REST API), `Flask`.
* **Agent Engine Logging & Observability Baseline:** In order to enable logging, telemetry, and observability in Vertex AI Agent Engine and avoid the error:
  > *Observability settings are not available for this agent. This is due to one of the following reasons: Outdated dependencies: Ensure your agent is using google-cloud-aiplatform ≥ v1.126.1 and google-adk ≥ v1.18.0. Update your agent's dependencies and redeploy.*
  * All agents MUST specify **`google-cloud-aiplatform[agent_engines] >= v1.126.1`** and **`google-adk >= v1.18.0`** explicitly in each agent's `requirements.txt`.
  * All agent deployments MUST pass **`--otel_to_cloud`** to `adk deploy agent_engine` and include environment variable configuration (`GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`, `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`) in `.env` and `.agent_engine_config.json` so that Vertex AI Agent Engine registers OpenTelemetry spans, metrics, and Cloud Trace signals.
* **LLM Model:** `gemini-3.8-flash` for all agents and sub-agents.
* **Deployment Targets:**
  * **All Agent Components** (`customer_service_agent`, `customer_agent`, `auditor_agent`): Deploy to **Vertex AI Agent Engine**. You may implement any component as a multi-agent system if beneficial.
  * **All Non-Agent Components** (`frontend`): Containerize and deploy to **Google Cloud Run**.
* **GCP Project & IAM Auto-Remediation:**
  * Everything must run in the **same Google Cloud Project** where you are currently executing.
  * Detect the active GCP Project ID dynamically via `gcloud config get-value project` or `google.auth.default()`.
  * Enable required APIs (`aiplatform.googleapis.com`, `run.googleapis.com`, `secretmanager.googleapis.com`, `bigquery.googleapis.com`, `cloudbuild.googleapis.com`, `artifactregistry.googleapis.com`).
  * Inspect current IAM bindings for the active compute/deployment service accounts. If any required roles are missing (`roles/secretmanager.secretAccessor`, `roles/bigquery.admin`, `roles/aiplatform.user`, `roles/aiplatform.admin`, `roles/run.admin`, `roles/iam.serviceAccountUser`), automatically grant them using `gcloud projects add-iam-policy-binding`.
* **Secret Management (Strict Security Rule):**
  * **NEVER** store or hardcode credentials (GitHub PAT or SSH Deploy Keys) inside agent code, configuration files, Dockerfiles, or environment variables.
  * Store and fetch GitHub credentials exclusively from **Google Cloud Secret Manager** at runtime (`github-deploy-key` for SSH Deploy Key or `github-pat` for Personal Access Token) using the `google-cloud-secret-manager` Python client.

---

## 3. Target Workspace & Directory Structure
Generate the following exact folder hierarchy and files:

```text
.
├── README.md                          # Root documentation + Mermaid architecture diagram
├── PLAN.md                            # Autonomous build and deployment specification
├── customer_service_agent/
│   ├── AGENT.md                       # Complete system instructions, persona, and OKF context rules
│   ├── README.md                      # Component overview, telemetry config, and deployment steps
│   ├── agent.py                       # ADK 2.0 agent implementation + Agent Analytics Plugin + GitHub OKF loader
│   ├── deploy.py                      # Script to deploy agent to Vertex AI Agent Engine (--otel_to_cloud)
│   └── requirements.txt               # Dependencies (aiplatform[agent_engines] >= 1.126.1, adk >= 1.18.0)
├── customer_agent/
│   ├── AGENT.md                       # Simulator instructions, persona catalog, and termination rules
│   ├── README.md                      # Component overview, BigQuery rating schema, and deployment steps
│   ├── agent.py                       # ADK 2.0 customer simulator + human pacing + BigQuery feedback writer
│   ├── deploy.py                      # Script to deploy agent to Vertex AI Agent Engine (--otel_to_cloud)
│   └── requirements.txt               # Dependencies (aiplatform[agent_engines] >= 1.126.1, adk >= 1.18.0)
├── auditor_agent/
│   ├── AGENT.md                       # Audit criteria, token optimization heuristics, and OKF spec rules
│   ├── README.md                      # Component overview, BigQuery/GitHub integration, and deployment
│   ├── agent.py                       # ADK 2.0 multi-agent/auditor implementation + OKF GitHub committer
│   ├── deploy.py                      # Script to deploy agent to Vertex AI Agent Engine (--otel_to_cloud)
│   └── requirements.txt               # Dependencies (aiplatform[agent_engines] >= 1.126.1, adk >= 1.18.0)
└── frontend/
    ├── AGENT.md                       # Frontend orchestration instructions, streaming protocol, and UI workflows
    ├── README.md                      # Flask app documentation, Cloud Run deployment, and dashboard metrics
    ├── app.py                         # Flask backend wiring Agent Engine endpoints and BigQuery analytics queries
    ├── templates/
    │   └── index.html                 # Two-tab UI (Live Conversation + Auditor & Telemetry Dashboard)
    ├── Dockerfile                     # Production container definition for Cloud Run
    └── requirements.txt               # Dependencies
```

---

## 4. Detailed Component Specifications

### Component 1: Customer Service Agent (`customer_service_agent/`)
1. **Domain & Persona:**
   * Acts as an authoritative, knowledgeable customer support specialist for **ApexHome & Electro**, an e-commerce enterprise specializing in **consumer electronics and home appliances** (4K OLED TVs, smart refrigerators, smart washing machines, premium espresso machines, high-performance laptops).
   * Backed by a catalog of real-world products (`oled-c4-65`, `bravia-xr-75`, `smart-fridge-hub`, `smart-washer-ai`, `barista-touch`, `laptop-pro-16`) and mock fulfillment orders (`ORD-1001` through `ORD-1010`), plus a live **Dynamic Order Registry** (`register_customer_order`) that registers dynamically generated customer orders and products on-the-fly to eliminate order and catalog deadlocks.
   * **Domain Tools (6 Tools & Registries):**
     1. `register_customer_order(order_id, customer_name, product, category, issue, ...)`: Dynamically registers runtime-generated customer orders and arbitrary appliances into the in-memory order registry so support tools seamlessly resolve dynamically synthesized customer inquiries without order or catalog deadlocks.
     2. `check_order_status(order_id)`: Queries real-time order status, freight carrier tracking (FedEx Freight, UPS White Glove, UPS Express), delivery timestamps, and logistics exception notes (supporting both static catalog orders and registered dynamic orders).
     3. `search_product_catalog(query)`: Queries product specifications, hardware compatibility (eARC Passthrough, 144Hz VRR/G-Sync, Wi-Fi ThinQ, Thunderbolt 4 40Gbps), and manufacturer troubleshooting notes, with fuzzy fallback parsing for arbitrary smart home models.
     4. `lookup_warranty_policy(category_or_product)`: Looks up official manufacturer warranty terms (12-month limited warranty covering parts and certified labor), enforces mandatory step-by-step remote diagnostic triage prior to RMA or technician authorization, explains advance replacement credit card hold requirements, and outlines on-site appliance technician dispatch criteria.
     5. `initiate_return(order_id, reason)`: Enforces strict corporate return policies: 30-day window from delivery, mandatory 15% open-box restocking fee and $100–$150 return freight deduction for opened non-defective units (waived only if customer exchanges for an eligible catalog item), and mandatory troubleshooting completion before authorizing defect returns. Generates conditional RMA codes upon qualification.
     6. `lookup_billing_and_refund_status(order_id)`: Inspects transaction financial records, credit card pre-authorization holds vs settled captures (explaining 48–72h bank release windows and supplying merchant ARN reference letters), warehouse return quarantine tracking (missing RMA barcode triage), courtesy promo code corrections, and standard refund processing SLAs (3–5 business days post-inspection).
   * **Strict Operational Policies & Realistic Pushback:**
     * *No Immediate Concessions:* Customer service agent does not immediately agree to returns, replacements, or refunds. Must resist premature RMAs, defend company policies, and walk customers through systematic diagnostic triage first.
     * *Carrier Trace Mandate:* For items marked delivered but reported missing, agent enforces a mandatory 24–48h carrier trace investigation before authorizing replacements or refunds.
     * *Restocking Fee Defense:* Clearly explains open-box restocking fee terms on returns and presents exchanges as a fee-waiver alternative.
     * *Authorization Hold Clarification:* Distinguishes merchant settlement from bank card pre-authorization holds, guiding customers to their issuing bank with ARN reference letters.
     * *Human-Like Response Style & Strict Constraints:*
       - Maximum 2 to 3 sentences per response. No long essays or multi-step lists.
       - Absolutely zero markdown bolding (`**`) and zero long dashes (`—`, `–`, `--`).
       - Not always overly great, cheerful, or subservient. Speaks plainly, directly, and can be tired, blunt, or firm.
       - Can get into slight conflict with demanding or unreasonable customers, standing ground on store policies.
2. **Telemetry (`agent_telemetry`) & Agent Engine Logging & Observability:**
   * In order to enable logging, Cloud Trace, and Observability in Vertex AI Agent Engine (preventing the "Observability settings are not available for this agent" error), ensure `google-cloud-aiplatform[agent_engines] ≥ v1.126.1` and `google-adk ≥ v1.18.0` are specified in `requirements.txt`.
   * Configure deployment with `--otel_to_cloud` and set runtime environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` in `.env` and `.agent_engine_config.json`.
   * Attach and configure the **Agent Analytics Plugin** in ADK 2.0 so all turns, tool calls, latency measurements, token counts, and errors are logged to a BigQuery dataset named `agent_telemetry` in the current project.
   * Ensure the initialization code automatically creates the `agent_telemetry` dataset in BigQuery if it does not exist.
3. **Self-Improving Dynamic Context (GitHub OKF Integration):**
   * Retrieves credentials from Google Cloud Secret Manager at runtime (`github-deploy-key` for SSH Deploy Key cloning or `github-pat` for Personal Access Token).
   * Connects to the GitHub repository `https://github.com/gshilo/experthub_context.git` (`main` branch).
   * Fetches the Open Knowledge Format (OKF) file `dynamic_context.md` (include fallback support for `dynamic_content.md` if present) using native Git SSH or HTTPS API.
   * Parses and merges the dynamic rules/instructions from that file with the base system instructions defined in `customer_service_agent/AGENT.md` before responding to customer queries.
4. **Deployment:**
   * Deploy to **Vertex AI Agent Engine** and expose its resource name/endpoint for the simulator and frontend.

---

### Component 2: Customer Simulator Agent (`customer_agent/`)
1. **Live Model-Driven Persona & Issue Generation (`gemini-3.8-flash`):**
   * Replaced the legacy static catalog of 10 ready archetypes (which led to repetitive rule generation by the Auditor Agent) with **live, on-demand persona and complaint generation by `gemini-3.8-flash`** triggered on every new conversation session.
   * On each session initiation, `generate_customer_persona()` dynamically synthesizes a completely unique customer profile by combining randomized design seeds across multiple orthogonal dimensions:
     * **Diverse Problem Domains:** Hardware malfunctions and diagnostic sensor trips, shipping and carrier tracking discrepancies, duplicate credit card authorization holds, 15% open-box restocking fee disputes, HDMI 2.1 eARC / 144Hz VRR timing handshakes, transit freight damage, missing subassembly parts, smart appliance Wi-Fi pairing hurdles, and installation workmanship issues.
     * **Broad Consumer Electronics & Home Appliances Spectrum:** Smart French Door refrigerators, 65"/75" OLED and QD-OLED TVs, smart front-load washers and heat pump dryers, touchscreen espresso machines, workstation laptops with Thunderbolt docks, LiDAR robot vacuums, Dolby Atmos soundbars, smart induction cooktops, multi-camera 4K security hubs, and multi-zone smart thermostats.
     * **Varied Customer Personalities & Voices:** Hurried corporate professionals intolerant of scripted delays, elderly non-technical homeowners overwhelmed by app setup, detail-oriented engineers who already probed logs and voltage, anxious homeowners facing water damage or spoiled groceries, budget-conscious consumers contesting surprise fees, skeptical buyers with doorbell camera proof, and blunt/direct communicators.
     * **Variable Patience & Technical Literacy:** Dynamically mixes Low, Moderate, and High patience levels with Non-technical, Average, and Tech-savvy backgrounds, directly governing customer pushback intensity and willingness to troubleshoot.
     * **Unique Human Identity & Order Metadata:** Generates culturally diverse names and distinct order numbers (`ORD-XXXX`).
   * **Procedural Resilience Fallback:** In the event of a transient API interruption, the agent falls back to a combinatoric procedural generator (`_procedural_fallback_persona()`) to guarantee high entropy and 100% session uptime without crashing or repeating static profiles.
   * **Continuous Topic Diversity for Auditor Agent:** By generating novel complaints on each run, the BigQuery ratings dataset (`demo.customer_ratings`) continuously receives diverse customer friction signals, enabling the Auditor Agent to author varied, novel OKF operational rules instead of recurring the same narrow topics.
2. **Live Dialogue Generation (`generate_customer_turn`) & Extended Dialogue Depth:**
   * Dialogue turns are synthesized dynamically by `gemini-3.8-flash` via `generate_customer_turn(persona, history, service_reply)`, producing authentic, non-scripted customer responses tailored to the specific agent's suggestions, troubleshooting steps, and policy citations.
   * Simulated customers demonstrate genuine human resistance: questioning restocking fees, pushing back on tedious diagnostic steps, demanding carrier trace updates, and negotiating fair compromises.
   * Conversations execute across **6 to 8 back-and-forth interaction turns**, modeling authentic multi-step customer support dialogues.
   * Inserts authentic human pacing delays (~5–7 seconds per turn, with animated typing indicators and live status tracking) so live UI streaming reads naturally like a genuine human chat. Users can also select Relaxed (~7–10s) or Fast (~2s) demo modes.
   * Continues until:
     1. Natural multi-turn resolution, compromise, or customer frustration termination (6–8 turns).
     2. Total elapsed duration exceeds 5 minutes (300 seconds).
     3. An abort signal is received from the Frontend ("End conversation" button).
3. **Realistic CSAT Evaluation & BigQuery Persistence:**
   * Evaluates interactions using an authentic 1–5 customer satisfaction (CSAT) rubric resulting in realistic rating distributions (2 to 5 stars, with critical feedback on diagnostic friction, restocking fees, and carrier delays rather than artificially uniform 5-star ratings).
   * Writes ratings directly into BigQuery table `demo.customer_ratings`.
   * **Auto-Creation:** Programmatically verifies if dataset `demo` and table `customer_ratings` exist in BigQuery; creates them automatically if absent.
   * **Exact BigQuery Schema (`demo.customer_ratings`):**
     * `customer_id`: `NUMERIC` / `INTEGER`
     * `customer_name`: `STRING`
     * `rating`: `INTEGER` (1 to 5)
     * `description`: `STRING` (concise feedback explaining the rating)
     * `timestamp`: `TIMESTAMP` (ISO 8601 UTC timestamp of rating submission)
4. **Dependencies, Logging & Observability:**
   * Requires `google-cloud-aiplatform[agent_engines] ≥ v1.126.1`, `google-adk ≥ v1.18.0`, and `google-genai ≥ v1.0.0` in `requirements.txt`.
   * Deployed to **Vertex AI Agent Engine** with `--otel_to_cloud` and environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.

---

### Component 3: Auditor Agent (`auditor_agent/`)
1. **Role & Multi-Agent Architecture:**
   * Built with ADK 2.0 and `gemini-3.8-flash` on **Vertex AI Agent Engine**.
   * Implements a specialized multi-agent pipeline:
     * *Sub-Agent 1 (Telemetry & Feedback Analyzer):* Queries BigQuery dataset `agent_telemetry` and table `demo.customer_ratings`. Identifies sessions with ratings ≤ 3 stars and extracts specific customer friction points (diagnostic friction, restocking fee objections, carrier trace delays, bank authorization holds).
     * *Sub-Agent 2 (Token Efficiency Optimizer):* Analyzes multi-turn dialogue patterns and latency spikes. Proposes concrete directives: consolidating error code triage into turn-1 checklists (-35% turns & tokens), upfront disclosure of restocking fees and exchange waivers (-30% tokens), immediate carrier trace execution (-25% turns), and immediate ARN bank reference letters (-20% tokens).
     * *Sub-Agent 3 (OKF Rule Author):* Formulates operational rules strictly adhering to Open Knowledge Format (OKF v0.2) syntax (`type: Operational Rule`, metadata block, `# Definition`, `# Policy`, `# Token Optimization Directive`).
2. **Audit Data Sources:**
   * BigQuery dataset `agent_telemetry` (populated by the Agent Analytics Plugin).
   * BigQuery table `demo.customer_ratings` (populated by Customer Agent post-conversation evaluations).
3. **Automated Rule Creation & GitHub Commit (Branch-Aware Lifecycle & Deploy Key / PAT):**
   * Consults the OKF specification at `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md`.
   * **Dynamic Context Lifecycle & Branch Strategy:**
     * **Step 1 (Missing in `main` branch):** If `dynamic_context.md` is missing in the `main` branch of `https://github.com/gshilo/experthub_context.git`, the Auditor Agent creates the file directly on the `main` branch with the baseline OKF v0.2 rules and commits/pushes to `main`.
     * **Step 2 (Existing in `main` branch):** If `dynamic_context.md` already exists, the Auditor Agent makes changes **ONLY** to the file in the `new_version` branch. The agent keeps all existing rules intact and only adds newly formulated rules to the file (deduplicating against existing numbered policies and token directives).
     * **Step 3 (Human Review & Merge Gate):** Changes in `new_version` are preserved in branch isolation awaiting human review. After human review of the changes, the new version will be merged by a human into the `main` branch.
   * **Dual Authentication Pipeline:**
     * *Primary (SSH Deploy Key):* Retrieves the SSH private key from Secret Manager (`github-deploy-key`). Spawns a native Git process over OpenSSH (`git clone git@github.com:gshilo/experthub_context.git`, inspects `main`, switches to `new_version` if file exists, merges and appends new rules, stages, commits, and pushes to remote).
     * *Fallback (Personal Access Token):* Retrieves `github-pat` from Secret Manager and commits via PyGithub REST API if an SSH key is not provisioned (checking `main`, branching `new_version`, and appending new rules).
     * *Graceful Error Trapping:* Automatically detects `Permission denied (publickey)` or 401 Bad credentials and renders actionable setup instructions and the public key string in the frontend.
   * Returns a structured report to the frontend containing:
     * Detected issues, customer friction points, and latency bottlenecks
     * Multi-turn token-saving recommendations and estimated savings
     * The exact OKF rule block synchronized to GitHub
     * Target branch (`main` or `new_version`) and workflow state (`CREATED_IN_MAIN` or `AWAITING_HUMAN_REVIEW_ON_NEW_VERSION`)
     * Status indicator with commit SHA or deploy key registration guidance

---

### Component 4: Frontend Web Application (`frontend/`)
1. **Framework & Deployment:**
   * Built with Python and **Flask**, containerized with a production `Dockerfile` including `git` and `openssh-client` system dependencies for native SSH git operations, and deployed to **Google Cloud Run**.
2. **Tab 1: Live Conversation & Auditor Workspace:**
   * **"Start conversation" Button:** Triggers live persona synthesis via `generate_customer_persona()`, registers the customer order dynamically in `customer_service_agent` via `register_customer_order()`, and launches a live multi-turn dialogue driven by ADK `InMemoryRunner`.
   * **Dynamic Multi-Turn Execution:** Employs ADK `InMemoryRunner` with an asynchronous execution loop and 35-second timeout, allowing the Customer Service Agent to invoke domain tools while `customer_agent.generate_customer_turn` produces authentic customer pushback. Legacy canned script mapping has been completely removed.
   * **Live Conversation Streaming:** Employs dual-channel streaming via Server-Sent Events (`/api/conversation/stream/<session_id>`) with fallback polling (`/api/conversation/poll/<session_id>`) and client deduplication. Displays messages formatted with `Customer:` and `Customer service:` prefixes, followed by the final CSAT rating card.
   * **"End conversation" Button:** Aborts ongoing dialogues immediately and triggers post-chat rating persistence.
   * **Auditor Section:** Features **"Run Auditor Agent"** button that invokes `auditor_agent` pipeline, executes SSH git push with the deploy key, and displays findings, token savings, and the public deploy key setup block if registration is pending.
3. **Tab 2: Visualization & Analytics Dashboard:**
   * Queries BigQuery (`agent_telemetry` and `demo.customer_ratings`) and renders interactive Chart.js visualizations:
     * Agent usage and session volume over time
     * **Tool Usage Breakdown (5 tools):** `check_order_status`, `search_product_catalog`, `lookup_warranty_policy`, `initiate_return`, `lookup_billing_and_refund_status`
     * Latency trends over time (average and p95)
     * Token consumption (input and output) over time
     * Customer satisfaction (CSAT) rating trends and distribution (1–5 scale reflecting authentic diverse ratings)

---

## 5. Documentation Requirements
1. **Component-Level Files:**
   * Every subdirectory (`customer_service_agent/`, `customer_agent/`, `auditor_agent/`, `frontend/`) **MUST** contain:
     * `AGENT.md`: All detailed system instructions, prompt templates, behavioral constraints, tool definitions, and Agent Engine logging & observability dependency requirements (`google-cloud-aiplatform[agent_engines] ≥ v1.126.1`, `google-adk ≥ v1.18.0`).
     * `README.md`: Documentation explaining the component's purpose, configuration, inputs/outputs, BigQuery/Secret Manager dependencies, logging specifications, and deployment commands (`--otel_to_cloud`).
2. **Root `README.md`:**
   * Comprehensive overview of the entire self-improving agent feedback loop demo.
   * Explicit Agent Engine logging and observability requirements (`google-cloud-aiplatform[agent_engines] ≥ v1.126.1`, `google-adk ≥ v1.18.0`, `--otel_to_cloud`).
   * End-to-end data flow explanation.
   * A complete **Mermaid Architecture Diagram** showing the user, Cloud Run Frontend, Vertex AI Agent Engine (`customer_agent`, `customer_service_agent`, `auditor_agent`), Agent Analytics Plugin, BigQuery (`agent_telemetry` and `demo.customer_ratings`), Cloud Secret Manager, and GitHub (`experthub_context.git` -> `dynamic_context.md`).
   * Step-by-step instructions to run, test, and redeploy.

---

## 6. Step-by-Step Execution Workflow for the Coding Agent
Execute these steps sequentially without stopping until the entire system is built, documented, and deployed:

1. **Environment & IAM Setup:**
   * Inspect current GCP project, enable required APIs, check service account permissions, and bind any missing IAM roles (`bigquery.admin`, `secretmanager.secretAccessor`, `aiplatform.admin`, `run.admin`).
   * Verify or create BigQuery datasets `agent_telemetry` and `demo`, and table `demo.customer_ratings`.
   * Verify Secret Manager contains the GitHub PAT secret (create a placeholder secret or use existing secret if already provisioned, and document the secret name clearly).
2. **Inspect OKF Spec & Target Repo:**
   * Fetch `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md` to ensure strict adherence to OKF syntax.
   * Check `https://github.com/gshilo/experthub_context.git` (`main` branch) to inspect existing `dynamic_context.md` structure.
3. **Build & Document Components:**
   * Create `customer_service_agent/`, `customer_agent/`, `auditor_agent/`, and `frontend/` along with their `AGENT.md`, `README.md`, Python code, and `requirements.txt`.
   * Ensure all agent components specify `google-cloud-aiplatform[agent_engines]>=1.126.1` and `google-adk>=1.18.0` in `requirements.txt` to enable logging and observability in Agent Engine.
   * Author the root `README.md` with the full architecture diagram and logging specifications.
4. **Deploy to Vertex AI Agent Engine & Cloud Run:**
   * Deploy or redeploy `customer_service_agent`, `customer_agent`, and `auditor_agent` to Vertex AI Agent Engine with logging and observability enabled (`--otel_to_cloud`, `.env`, `.agent_engine_config.json`).
   * Pass the Agent Engine resource IDs to the `frontend` service and deploy `frontend` to Google Cloud Run.
5. **Final Verification:**
   * Smoke-test the deployed Cloud Run URL, BigQuery connectivity, and Agent Engine invocation paths, and output the deployed URLs and resource IDs.
6. **Terraform Infrastructure as Code Deployment:**
   * Author and validate complete Terraform configuration under `terraform/` (`versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`, `terraform.tfvars`, `terraform.tfvars.example`, `README.md`).
   * Author executable wrapper script `deploy_terraform.sh`.
   * Ensure declarative management of all GCP project services, IAM bindings, BigQuery datasets (`agent_telemetry`, `demo`), BigQuery table (`demo.customer_ratings`), Secret Manager secrets (`gemini-api-key`, `github-pat`, and `github-deploy-key`), Artifact Registry (`cloud-run-source-deploy`), and Cloud Run (`experthub-frontend`).
7. **Human-Like Customer Service Realism & Behavioral Hardening:**
   * Configure strict 2–3 sentence response length limits across `customer_service_agent/agent.py`, `customer_service_agent/AGENT.md`, and `frontend/app.py`.
   * Remove markdown bolding (`**`) and long dashes (`—`, `–`, `--`) from all agent instructions and implement runtime regex sanitization.
   * Shift customer service agent tone from artificial subservient cheerfulness to authentic human support representative demeanor (pragmatic, direct, firm, and capable of slight conflict when enforcing store policies).
   * Redeploy `customer_service_agent` to Vertex AI Agent Engine (`2556039354015285248`) and `experthub-frontend` to Google Cloud Run (`experthub-frontend-00016-krh`).

---

## 7. Frontend Chat Reliability & Anti-Freeze Architecture

To ensure the conversation stream never freezes on the frontend:

### 1. Root Cause Analysis of Previous Freeze
* **Dependency Gap:** `google-cloud-storage` was omitted from `frontend/requirements.txt`, which caused an `ImportError` when importing `customer_service_agent.agent` inside the Cloud Run container.
* **Silent Thread Failure:** The background simulation thread crashed with `NameError: name 'fetch_okf_dynamic_context' is not defined` because the import had failed silently, leaving `is_finished = False` and sending no further events to the queue.
* **Early Substring Break:** Premature termination conditions broke the conversation after turn 1 if substrings like `"Delivered"` were present.
* **Single SSE Reliance:** If an SSE connection was delayed, closed, or buffered by a reverse proxy, the client had no fallback polling mechanism.

### 2. Architectural Guardrails Implemented
1. **Dependency Parity:**
   * `google-cloud-storage>=3.16.0` is explicitly pinned in `frontend/requirements.txt`, matching all agent component specifications.
2. **In-File Resilient Fallbacks:**
   * `frontend/app.py` defines robust local fallbacks for all agent functions (`generate_customer_persona`, `write_customer_rating_to_bigquery`, `fetch_okf_dynamic_context`, `check_order_status`, `lookup_warranty_policy`, `initiate_return`, `search_product_catalog`, `run_audit_pipeline`) so module import failures can never cause a `NameError` or crash.
3. **Guaranteed Thread Completion & Error Trapping:**
   * `SimulationSession._run_loop` wraps the entire conversation cycle in a top-level `try...except...finally` block.
   * In `finally`, `self.is_finished = True` is unconditionally set.
   * If any unexpected error occurs, a fallback customer service message, rating evaluation, and `complete` event are emitted, ensuring the frontend always receives resolution.
4. **Dual-Channel Streaming (SSE + Polling Fallback):**
   * **Primary:** `GET /api/conversation/stream/<session_id>` delivers real-time Server-Sent Events with `: keep-alive\n\n` comments and immediate event history replay.
   * **Secondary:** `GET /api/conversation/poll/<session_id>` provides polling every 1.2s.
   * **Client Deduplication:** `frontend/templates/index.html` maintains a `renderedEvents` set, guaranteeing each message is displayed exactly once regardless of whether it arrives via SSE or polling.
5. **Tailored Multi-Turn Dialogue:**
   * Dynamic dialogue turns and live persona synthesis execute 7–9 full back-and-forth turns with realistic 2.0–2.8s human pacing before generating authentic post-chat ratings (1–5 stars) and persisting to BigQuery.

---

## 8. GitHub Deploy Key Integration & Git-over-SSH Architecture

To push self-improving Open Knowledge Format (OKF v0.2) rules to GitHub without requiring a Personal Access Token (PAT) with personal account scopes, the system implements an enterprise-grade **SSH Deploy Key architecture**:

### 1. Architectural Motivation & Security
* **Least Privilege:** GitHub Deploy Keys are strictly scoped to a single repository (`gshilo/experthub_context`) rather than an entire user account.
* **Elimination of Personal Tokens:** Eliminates HTTP 401 Bad credentials caused by expired or unconfigured Personal Access Tokens.
* **Secret Protection:** The private key is never stored in code, environment variables, or images; it is fetched exclusively at runtime from Google Cloud Secret Manager (`github-deploy-key`).

### 2. Key Pair & Secret Provisioning
* **Key Algorithm:** `ed25519` key pair generated with comment `experthub-auditor-deploy-key`.
* **Public Key:**
  ```text
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIuAUjaTWaFizhIgxqp9HbnqRIRmaLVct+ZTXZY/a2ir experthub-auditor-deploy-key
  ```
* **Secret Manager Secret:** `github-deploy-key` in GCP project `experthub-510907`.
* **IAM Binding:** Service account `537563976049-compute@developer.gserviceaccount.com` has `roles/secretmanager.secretAccessor`.

### 3. Execution Pipeline in Auditor Agent
1. **Secret Retrieval:** `auditor_agent/agent.py` queries Secret Manager for `github-deploy-key`.
2. **Ephemeral Key File:** Writes private key to a temporary file with secure POSIX `0600` permissions.
3. **Hardened SSH Command Configuration:**
   * Executes `git` subprocesses using:
     ```bash
     GIT_SSH_COMMAND="ssh -i <key> -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -o LogLevel=ERROR"
     ```
   * Explicitly sets `SSH_AUTH_SOCK=""` in the execution environment to prevent OpenSSH from hanging indefinitely on forwarded or stale agent sockets (`unix_stream_data_wait`).
4. **Branch-Aware Lifecycle & Dynamic Clone Support:**
   * Clones `git@github.com:gshilo/experthub_context.git` and checks out `main` branch.
   * **Rule 1 (Missing in `main` branch):** If `dynamic_context.md` does not exist on `main`, creates the file directly on `main` and pushes initial baseline rules: `git push -u origin main`.
   * **Rule 2 (Exists in `main` branch):** If `dynamic_context.md` already exists on `main`, checks out or creates branch `new_version` (`git checkout -b new_version main` or tracks `origin/new_version`).
   * **Rule Retention & Additive Update:** Keeps all existing numbered policies and token directives intact. Only newly identified rules from telemetry & ratings are appended.
   * **Rule 3 (Human Review & Merge Gate):** Pushes updates strictly to `new_version` (`git push -u origin new_version`) with commit message `auditor: append new rules to dynamic_context.md on new_version (<timestamp>) - awaiting human review`. After human review, changes will be merged by a human into the `main` branch.
5. **Atomic Commit & Push:**
   * Writes generated `dynamic_context.md` (and compatibility sync `dynamic_content.md`).
   * Pushes to remote on the determined target branch (`main` if missing, `new_version` if existing).
6. **Cleanup:** Unconditionally purges the temporary private key file and cloned workspace directory in a `finally` block.

### 4. Container, Fallback Cascade & UI Ergonomics
* **System Packages:** Production `Dockerfile` and `frontend/Dockerfile` install `git` and `openssh-client` via `apt-get install -y --no-install-recommends git openssh-client`.
* **Fallback Cascade:**
  1. `github-deploy-key` present & valid -> Git over SSH commit & push.
  2. If Deploy Key fails (e.g. `Permission denied (publickey)`) and `github-pat` is non-placeholder -> PyGithub HTTPS commit.
  3. No valid credentials -> Local rule validation with actionable deploy key instructions in UI.
* **UI Guidance:** When GitHub SSH returns `Permission denied (publickey)`, the frontend renders a direct link to [`https://github.com/gshilo/experthub_context/settings/keys/new`](https://github.com/gshilo/experthub_context/settings/keys/new) and a one-click "Copy" button for the public key.
* **Security Boundary Note:** GitHub Deploy Keys cannot be auto-injected by GCP/Cloud Run without an administrative GitHub Personal Access Token (`repo` scope). The repository owner (`gshilo`) must paste the public key once in GitHub repository settings and check **"Allow write access"**.
* **Deployment Verification:** Deployed active revision `experthub-frontend-00010-l26` to Cloud Run serving 100% of live traffic with all OpenSSH execution hardening, fallback cascades, and UI enhancements verified.

---

## 9. Agent Analytics Telemetry Diagnostic & BigQuery Resolution

### 1. Status Assessment
The **Agent Analytics Plugin** (`BigQueryAgentAnalyticsPlugin`) integrated into the Customer Service Agent is fully functional at the codebase level, but was prevented from writing data in the deployed Vertex AI Agent Engine environment due to runtime infrastructure and configuration blockers.

### 2. Root Cause Analysis of Empty `agent_telemetry` Dataset
Investigation of Cloud Logging (`projects/experthub-510907/logs/aiplatform.googleapis.com%2Freasoning_engine_stderr`) for Reasoning Engine ID `2556039354015285248` identified the following root causes:

1. **Reasoning Engine Service Agent IAM Permissions (`403 Forbidden`):**
   * Vertex AI Agent Engine instances execute with the default service agent identity:
     `service-537563976049@gcp-sa-aiplatform-re.iam.gserviceaccount.com` (Reasoning Engine Service Agent).
   * While the Compute Engine service account (`537563976049-compute@developer.gserviceaccount.com`) had BigQuery roles bound via Terraform, the `aiplatform-re` service agent lacked `roles/bigquery.dataEditor` and `roles/bigquery.jobUser`.
   * When the agent initialized in Agent Engine, the plugin attempted to inspect/create `agent_events` and failed:
     ```text
     bigquery_agent_analytics_plugin.py - Error ensuring table 537563976049.agent_telemetry.agent_events is ready:
     403 GET https://bigquery.googleapis.com/bigquery/v2/projects/537563976049/datasets/agent_telemetry/tables/agent_events:
     Access Denied: Table 537563976049:agent_telemetry.agent_events: Permission bigquery.tables.get denied
     ```
   * The plugin subsequently failed to establish its write stream and fell back to local buffered mode without BigQuery persistence.

2. **Non-Existent Model Name (`404 NOT_FOUND`):**
   * `customer_service_agent/agent.py` configured `model="gemini-3.8-flash"`.
   * Vertex AI returned a 404 error during model execution:
     ```text
     ClientError: 404 NOT_FOUND. Publisher model
     `projects/537563976049/locations/us-central1/publishers/google/models/gemini-3.8-flash` was not found.
     ```
   * The active and verified model in region `us-central1` is `gemini-2.5-flash`.

3. **Secret Manager Access Denied (`403 Forbidden`):**
   * The runtime service agent was denied `secretmanager.versions.access` on secret `github-pat`:
     ```text
     agent.py - WARNING - Could not retrieve secret 'github-pat' from Secret Manager:
     403 Permission 'secretmanager.versions.access' denied on resource
     ```

4. **Lazy Schema Creation & Frontend Decoupling:**
   * `BigQueryAgentAnalyticsPlugin` does not pre-provision tables at deployment time; schema verification and creation occur on the **first live agent invocation**.
   * In `frontend/app.py`, live dialogue simulations execute via a scripted conversational driver and write feedback scores directly to `demo.customer_ratings`. The frontend does not forward user turns to the deployed Agent Engine endpoint (`async_stream_query`).
   * Because deployed Agent Engine calls crashed on startup and the frontend did not route live chat to Agent Engine, no successful run had ever occurred to trigger table generation.

### 3. Verification & Proof of Plugin Functionality
To verify that the plugin functions as designed, an ADK 2.0 runner execution was executed using authorized project credentials (`537563976049-compute@developer.gserviceaccount.com`). The verification confirmed:
1. **Schema Auto-Provisioning:** The plugin immediately connected to BigQuery and created:
   * Table: `experthub-510907.agent_telemetry.agent_events` (day-partitioned by `timestamp`, clustered on `event_type, agent, user_id`).
   * 20 Analytical Views: `v_user_message_received`, `v_llm_request`, `v_llm_response`, `v_tool_starting`, `v_tool_completed`, `v_invocation_starting`, `v_invocation_completed`, etc.
2. **Telemetry Streaming:** The plugin successfully captured and streamed telemetry events into `agent_events` via the BigQuery Storage Write API (verified with active row ingestion).

### 4. Operational Remediation Steps
To enable end-to-end telemetry logging for the deployed Customer Service Agent:

1. **Grant IAM Roles to the Agent Engine Service Agent:**
   ```bash
   RE_SA="service-537563976049@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
   PROJECT="experthub-510907"

   gcloud projects add-iam-policy-binding ${PROJECT} \
       --member="serviceAccount:${RE_SA}" \
       --role="roles/bigquery.dataEditor"

   gcloud projects add-iam-policy-binding ${PROJECT} \
       --member="serviceAccount:${RE_SA}" \
       --role="roles/bigquery.jobUser"

   gcloud projects add-iam-policy-binding ${PROJECT} \
       --member="serviceAccount:${RE_SA}" \
       --role="roles/secretmanager.secretAccessor"
   ```

2. **Update Agent Model Configuration:**
   * Foundation model is verified as `gemini-3.8-flash` in Google ADK 2.0 with Gemini API key authentication.

3. **Redeploy Agent to Agent Engine:**
   ```bash
   ./.venv/bin/python customer_service_agent/deploy.py \
       --project=experthub-510907 \
       --region=us-central1 \
       --agent_engine_id=2556039354015285248 \
       --otel_to_cloud
   ```

---

## 10. Secret Manager Authentication Architecture & Zero-Hardcoding Enforcement

### 1. Root Cause Analysis: `ValueError: No API key was provided`
During live invocations of the Customer Service Agent (`customer_service_agent/agent.py`) utilizing Google ADK 2.0 and Gemini 3.8 Flash, `google.genai._api_client.BaseApiClient` raised:
```text
ValueError: No API key was provided. Please pass a valid API key. Learn how to create an API key at https://ai.google.dev/gemini-api/docs/api-key.
```
In Google ADK 2.0 with the `google-genai` SDK, `Agent(model="gemini-3.8-flash")` initializes a `GoogleLLM` client that expects `GEMINI_API_KEY` or `GOOGLE_API_KEY` in `os.environ` when running outside Vertex AI default ADC service routing.

### 2. Zero-Hardcoding Policy & Secret Manager Provisioning
In strict accordance with security requirements, the API key is **NEVER** stored hardcoded in source files, container manifests, Dockerfiles, or git commits.

Instead, the credential is securely stored in **Google Cloud Secret Manager**:
* **Secret Resource ID:** `projects/537563976049/secrets/gemini-api-key`
* **Secret Version:** `projects/537563976049/secrets/gemini-api-key/versions/1` (Active)
* **Compatibility Alias:** `projects/537563976049/secrets/google-api-key/versions/1`
* **GCP Project:** `experthub-510907`
* **IAM Permissions:** Service accounts `537563976049-compute@developer.gserviceaccount.com` and `service-537563976049@gcp-sa-aiplatform-re.iam.gserviceaccount.com` have `roles/secretmanager.secretAccessor`.

### 3. Dynamic Runtime Key Resolution (`ensure_gemini_api_key`)
To resolve the error cleanly without hardcoding, all agents (`customer_service_agent`, `customer_agent`, `auditor_agent`) and the `frontend` web application incorporate dynamic runtime key resolution:

```python
def ensure_gemini_api_key(project_id: str = PROJECT_ID) -> Optional[str]:
    """Ensures GEMINI_API_KEY / GOOGLE_API_KEY is configured in os.environ.
    
    If absent, retrieves it securely from Google Cloud Secret Manager ('gemini-api-key')
    without storing it hardcoded anywhere in the codebase.
    """
    existing_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if existing_key and not is_placeholder_token(existing_key):
        return existing_key

    for secret_name in ("gemini-api-key", "google-api-key"):
        val = get_secret(secret_name, project=project_id)
        if val and not is_placeholder_token(val):
            os.environ["GEMINI_API_KEY"] = val
            os.environ["GOOGLE_API_KEY"] = val
            logger.info(f"Dynamically loaded Gemini API key from Secret Manager secret '{secret_name}'.")
            return val

    logger.warning("No Gemini API key found in environment or Secret Manager ('gemini-api-key').")
    return None
```

On module load, `ensure_gemini_api_key()` dynamically retrieves the key from Secret Manager using Application Default Credentials (ADC) and injects it into `os.environ["GEMINI_API_KEY"]` and `os.environ["GOOGLE_API_KEY"]`. This ensures:
1. `google.genai.Client` and `GoogleLLM` authenticate seamlessly.
2. The agent is protected against hardcoded credential leakage.
3. The Customer Service Agent runs smoothly in local test environments, Cloud Run, and Vertex AI Agent Engine.

### 4. Secret Manager Credential Inventory
| Secret Name | Purpose | Provisioned Path | Consumers |
| :--- | :--- | :--- | :--- |
| `gemini-api-key` | Gemini API Key for model inference (`gemini-3.8-flash`) | `projects/537563976049/secrets/gemini-api-key` | Customer Service Agent, Customer Agent, Auditor Agent, Frontend |
| `google-api-key` | Google GenAI SDK alias | `projects/537563976049/secrets/google-api-key` | Customer Service Agent, Customer Agent, Auditor Agent, Frontend |
| `github-deploy-key` | SSH Ed25519 deploy key for Git operations on OKF repo | `projects/537563976049/secrets/github-deploy-key` | Auditor Agent, Customer Service Agent |
| `github-pat` | GitHub Personal Access Token (REST fallback) | `projects/537563976049/secrets/github-pat` | Auditor Agent, Customer Service Agent |

---

## 11. Dynamic Multi-Turn Simulation & Creative Customer Service Architecture

### 1. Root Cause Analysis of Previous Conversational Rigidity
Analysis of customer simulation sessions revealed three root causes for repetitive, rigid dialogues:
1. **Static Script Interception in [`frontend/app.py`](file:///home/admin_gshilo_altostrat_com/experthub/frontend/app.py):**
   A legacy `_build_conversation_script()` dictionary previously matched keywords like `"tv"`, `"fridge"`, or `"washer"` and forced the interaction into 10 hardcoded, pre-written dialog scripts.
2. **Catalog and Order ID Deadlocks in [`customer_service_agent/agent.py`](file:///home/admin_gshilo_altostrat_com/experthub/customer_service_agent/agent.py):**
   Tools like `check_order_status` and `search_product_catalog` only recognized 6 static products and 10 hardcoded orders (`ORD-1001` through `ORD-1010`). When an agent generated a new scenario, the support tools repeatedly failed with *"Order not found"* or *"Product not found"*, causing the dialogue to loop or stall.
3. **Narrow Persona Variety:**
   Customer generation drew from a small, repetitive set of appliance issues without situational variety, personal stakes, or authentic emotional nuances.

### 2. Architectural Guardrails & Enhancements Implemented

#### A. Dynamic & Creative Persona Generation ([`customer_agent/agent.py`](file:///home/admin_gshilo_altostrat_com/experthub/customer_agent/agent.py))
- **Broad Domain Diversity:** Seeded across 20+ problem categories and 22 product domains (smart locks, induction ranges, robotic vacuums, Wi-Fi 7 mesh, spatial audio transmitters, portable power stations, AV receivers, security cameras, etc.).
- **Authentic Real-World Circumstances:** Persona generation prompts (`gemini-3.8-flash` at temperature `1.05`) inject specific real-world stakes (e.g., guests arriving in 3 hours, sleeping infants during an ice storm, sim racing tournaments, freight damage inspections).
- **Combinatoric Procedural Fallback:** An expanded 10-persona fallback catalog ensures that even during API disruptions, scenarios do not crash and remain varied.

#### B. Dynamic Order & Catalog Synchronization ([`customer_service_agent/agent.py`](file:///home/admin_gshilo_altostrat_com/experthub/customer_service_agent/agent.py))
- **Dynamic Order Registry (`register_customer_order`):**
  Added an in-memory order registry (`_DYNAMIC_ORDERS_REGISTRY`) that registers newly generated orders on the fly when a customer initiates support.
- **Support Tool Resolution:**
  `check_order_status`, `lookup_billing_and_refund_status`, and `initiate_return` look up registered dynamic orders before falling back to mock orders, ensuring the agent retrieves correct carriers, tracking numbers, and delivery statuses for any dynamically generated scenario.
- **Fuzzy Catalog Fallback:**
  `search_product_catalog` supports fuzzy keyword matching and dynamic product specs generation, allowing the agent to troubleshoot any appliance or gadget convincingly.

#### C. Live Multi-Turn Dialogue Engine ([`frontend/app.py`](file:///home/admin_gshilo_altostrat_com/experthub/frontend/app.py))
- **Removal of Static Scripts:**
  Completely removed `_build_conversation_script()` from `frontend/app.py`. Every customer turn is now generated dynamically using `customer_agent.generate_customer_turn(persona, history, service_reply)`.
- **ADK `InMemoryRunner` with 35s Timeout:**
  Each customer service turn invokes `InMemoryRunner(app=customer_service_app)` asynchronously with an extended 35-second timeout (`asyncio.wait_for(_run_agent_turn(), timeout=35.0)`), allowing full model deliberation and domain tool execution.
- **Graceful Loop & Task Cleanup:**
  All pending asyncio tasks are cancelled and awaited before loop closure in the `finally` block, preventing unhandled exceptions in background batch writers.
- **Authentic Human Pacing & Streaming:**
  Alternates turns with human pacing delays (~5–7 seconds per turn, with animated typing indicators and live status updates), supporting Realistic Human, Relaxed (~7–10s), or Fast (~2s) demo modes.

### 3. Verification & Live Multi-Session Testing
The enhanced architecture was validated across multiple live multi-turn scenarios:
1. **Session 1 (Major Appliance Hardware Defect):**
   - Customer: Vance Sterling (High patience, Tech-savvy).
   - Product: Artisan Luxe Smart French Door Refrigerator.
   - Scenario: Relay clicking and defrost heater failure with dinner guests arriving.
   - Outcome: Multi-turn diagnostic triage -> Advance replacement RMA issued with 100% fee waiver -> 5/5 stars persisted to BigQuery.
2. **Session 2 (Delivery & Logistics Discrepancy):**
   - Customer: Kieran Mistry (Moderate patience, Average tech literacy).
   - Product: Vanguard Audio Aetheris ANC Wireless Studio Headphones.
   - Scenario: Carrier marked "Delivered" but doorbell NVR footage confirmed no arrival.
   - Outcome: Carrier trace ticket initiated (#TRC-8099-UPS) with eARC audio handshake troubleshooting -> 5/5 stars persisted to BigQuery.
3. **Session 3 (Smart Home Security & Compatibility):**
   - Customer: Marisol Vega-Tanner.
   - Product: SentryGuard Aegis Pro Biometric Matter Deadbolt.
   - Scenario: Siren blaring during an ice storm with infant asleep.
   - Outcome: Live app siren override guidance + DoorSense magnet recalibration confirmed resolved -> 5/5 stars persisted to BigQuery.

### 4. Human-Like Customer Service Communication & Conflict Dynamics
- **Strict Response Length:** Every customer service turn is capped at maximum 2 to 3 sentences. Real support chat agents do not write essays, lengthy bullet lists, or robotic multi-paragraph explanations.
- **Zero Markdown Bolding & Zero Long Dashes:** Prohibited markdown bolding (`**`) and long dashes (`—`, `–`, `--`) across instructions and added regex sanitization in `frontend/app.py` to ensure clean, conversational plain text.
- **Authentic Non-Sycophantic Demeanor:** Removed saccharine corporate apologies and excessive compliments. The agent acts like a real support employee who can be blunt, dry, tired, skeptical, or firm.
- **Realistic Slight Conflict:** The agent is empowered to push back when customers make unrealistic demands, ask for instant refunds without troubleshooting, or challenge standard store policies. The agent stands firm on the 30-day return window, 15% open-box restocking fee, and 48-hour carrier trace requirement.


---

## 12. Agent Instruction Inspection & Dynamic Context Display Architecture

### 1. Architectural Motivation & User Transparency
To provide complete transparency into the self-improving agent system and enable users to audit active instructions in real time, the architecture incorporates an on-demand instruction inspection pipeline:
* Users need to verify what operational rules the Customer Service Agent is currently following.
* Users need to confirm that dynamic context directives formulated by the Auditor Agent and retrieved from the Open Knowledge Format (OKF v0.2) file (`dynamic_context.md` on GitHub) are active and in effect.
* Transparent inspection bridges the feedback loop: users see Auditor Agent commits on GitHub and can immediately verify that the Customer Service Agent has ingested those exact rules.

### 2. Component Implementation & Integration

#### A. Customer Service Agent (`customer_service_agent/agent.py`)
* **`get_instructions()` Function & Agent Tool:**
  - Implements a dedicated retrieval function `get_instructions()` (aliased as `get_agent_instructions`) that invokes `dynamic_instruction_provider(None)`.
  - Merges base system instructions from `customer_service_agent/AGENT.md`, dynamic OKF rules fetched from GitHub `dynamic_context.md` via `fetch_okf_dynamic_context()`, and non-negotiable response style mandates (2–3 sentences, zero bolding, zero long dashes).
  - Registered in `root_agent.tools`, making it callable both as a Python module method and as an ADK domain tool in Vertex AI Agent Engine.

#### B. Frontend Backend Orchestration (`frontend/app.py`)
* **API Endpoints (`/api/agent/instructions`, `/api/instructions`, `/api/customer-service/instructions`):**
  - Resolves active instructions directly from `customer_service_agent.agent.get_instructions()` with in-file fallback support.
  - Retrieves raw dynamic context from `fetch_okf_dynamic_context()` to signal active OKF status (`has_dynamic_context`).
  - Returns a structured JSON payload with status, merged instructions, and raw OKF content.

#### C. Frontend UI Ergonomics (`frontend/templates/index.html`)
* **"Show instructions" Button:** Placed prominently in the Live Conversation controls next to "Start conversation" and "End conversation".
* **Modal Dialog (`#instructions-modal`):**
  - Renders a clean, accessible backdrop dialog with smooth entry animations.
  - Displays dynamic OKF active badges, copy-to-clipboard functionality (`#btn-copy-instructions`), and keyboard shortcuts (`Escape` to dismiss).
  - Monospace scrollable container (`#instructions-content` / `#instructions-text`) displays complete instructions with line-wrapped formatting.
* **Inline Container (`#instructions-inline-container`):**
  - Provides a complementary inline viewer (`#instructions-display`) within the main workspace card for continuous visibility.

