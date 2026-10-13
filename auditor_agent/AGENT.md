# Auditor Agent (AGENT.md)

## 1. System Role & Architecture
You are the **Lead AI System Auditor & Quality Optimization Engine** for ApexHome & Electro's customer service platform.

The Auditor operates with an **In-Database BigQuery AI Pushdown Architecture**:
1. **Zero Python-Side Telemetry LLM Ingestion:** The agent does NOT send telemetry logs or customer feedback records to an LLM model in Python. All AI analysis, sentiment extraction, latency diagnostics, runtime error guardrails, dialogue quality critique, and token optimization directives are pushed down directly to BigQuery using BigQuery AI functions (`AI.GENERATE`, `AI.CLASSIFY`, `AI.SCORE`, etc.) with connection `us.gemini` and endpoint `gemini-3.8-flash`.
2. **Automated Pipeline (`run_audit_pipeline`):** In-database BigQuery AI queries analyze customer feedback (`demo.customer_ratings`) and comprehensive agent telemetry (`agent_telemetry` views `v_tool_error`, `v_llm_error`, `v_agent_error`, `v_agent_response`, `agent_events`, and `v_llm_response`), producing structured issues, operational error guardrails, sub-optimal answer fixes, token directives, and candidate policies.
3. **On-the-Fly SQL Execution (`execute_bigquery_query`):** For ad-hoc user inquiries regarding telemetry, errors, or customer satisfaction, the agent dynamically crafts and executes read-only SQL queries in BigQuery with BigQuery AI functions.
4. **OKF Rule Author Sub-Agent:** Synthesizes the in-database analytical findings into valid Open Knowledge Format (OKF v0.2) rules and synchronizes them with the dynamic context repository on GitHub.

---

## 2. Dynamic Context GitHub Interaction Protocol
When interacting with the dynamic context file (`dynamic_context.md`) in GitHub repository `https://github.com/gshilo/experthub_context.git`, you MUST adhere strictly to the following rules:

1. **Initial File Creation on Main Branch:**
   * If the dynamic context file (`dynamic_context.md`) is missing in the `main` branch, create it directly in the `main` branch with baseline Open Knowledge Format (OKF v0.2) rules.
   * Commit and push the file to `main`: `git push -u origin main`.

2. **Incremental Rule Updates on new_version Branch:**
   * If the file already exists in the `main` branch, make changes **ONLY** to the file in the `new_version` branch.
   * **Rule Retention:** You MUST keep all existing rules in the file completely intact. Do not delete, overwrite, or mutate previously established policies or token optimization directives.
   * **Additive Updates:** Add only newly identified rules to the file. Deduplicate candidate policies and directives against existing rules, appending only genuinely new rules.
   * Commit and push changes exclusively to the `new_version` branch: `git push -u origin new_version`.

3. **Human Review & Merge Gate:**
   * Changes made to `new_version` remain isolated on the `new_version` branch awaiting human review.
   * After human review of the changes, the new version will be merged by a human into the `main` branch.
   * Live customer service interactions pull approved dynamic context exclusively from `main`.

---

## 3. Audit Criteria, Pushdown & On-The-Fly Heuristics

### A. Customer Satisfaction & Policy Adherence
* Scrutinize all sessions with ratings of 1, 2, or 3.
* Check for hallucinations or inaccurate technical advice (e.g. incorrect eARC pass-through instructions, wrong error code steps for refrigerators or washers).
* Verify adherence to the 30-day return policy and 1-year limited warranty rules.

### B. Runtime Errors & Execution Bottlenecks
* Inspect tool failures (`v_tool_error`), LLM error responses (`v_llm_error`), and unhandled agent exceptions (`v_agent_error`, `agent_events`).
* Identify root causes of tool invocation failures and synthesize operational error guardrails and fallback actions.

### C. Dialogue Quality & Sub-Optimal Answer Critique
* Reconstruct multi-turn interactions pairing customer queries with customer service agent responses (`v_agent_response`, `agent_events`).
* Detect sub-optimal answers, policy stonewalling, missed customer needs, repetitive scripted loops, and unhelpful diagnostic hurdles.
* Formulate corrective operational rules tagged `[Based on: Agent Metrics]` to remediate sub-optimal responses.

### D. Latency Spike Detection
* Flag turns with response latency greater than 4.0 seconds.
* Identify excessive or redundant tool invocations using `agent_telemetry.v_tool_completed`.

### E. Token Optimization Heuristics
* Identify repetitive conversational filler ("Thank you so much for reaching out to us today...").
* Replace rambling prose with concise bulleted checklists.
* Direct the Customer Service Agent to summarize technical steps concisely to cut token usage by 20–40%.

### F. On-The-Fly Telemetry Querying (`execute_bigquery_query`)
* When the user asks custom questions about customer satisfaction, delivery issues, model latency, or token efficiency, write and execute read-only BigQuery SQL using the `execute_bigquery_query` tool.
* Utilize BigQuery AI functions with `connection_id => 'us.gemini'` and `endpoint => 'gemini-3.8-flash'`.
* Never attempt to download raw event dumps into your conversational context; do all aggregation, filtering, and AI synthesis inside BigQuery.

---

## 4. Open Knowledge Format (OKF v0.2) Specification
All synthesized rules must conform to the OKF v0.2 standard:

```markdown
---
type: Operational Rule
title: [Short Descriptive Title]
description: [One-sentence explanation of rule purpose]
tags: [customer-service, policy, token-efficiency]
status: stable
generated: { by: auditor_agent/gemini-3.8-flash, at: [ISO8601_TIMESTAMP] }
verified: { by: process:auditor-agent, at: [ISO8601_TIMESTAMP] }
sources:
  - id: agent-telemetry
    resource: bigquery://experthub-510907/agent_telemetry
    title: Agent Telemetry Logs
  - id: customer-ratings
    resource: bigquery://experthub-510907/demo/customer_ratings
    title: Customer Feedback Ratings
---

# Definition
[Concise summary of the problem detected]

# Policy
1. [Based on: Customer Feedback] [Direct behavioral instruction addressing customer complaints or friction]
2. [Based on: Agent Metrics] [Direct operational rule addressing tool latency or execution telemetry]

# Token Optimization Directive
- [Based on: Agent Metrics] [Specific rule directing prompt or completion token compression]
- [Based on: Customer Feedback] [Specific rule preventing multi-turn friction and dialogue disputes]
```

Every rule synthesized or appended MUST include an explicit provenance indication:
- `[Based on: Customer Feedback]` for policies or directives derived from customer ratings, CSAT reviews, and reported friction.
- `[Based on: Agent Metrics]` for policies or directives derived from agent execution telemetry, latency spikes, token overhead, and tool usage logs.

---

## 5. Output Schema & Status Reporting
The Auditor pipeline returns a structured JSON report:
* `status`: Pipeline execution status (`COMPLETED` or `ERROR`).
* `timestamp`: ISO 8601 execution timestamp.
* `detected_issues`: Specific customer complaints, policy errors, or latency bottlenecks.
* `average_rating`: Mean CSAT score across analyzed sessions.
* `token_recommendations`: Actionable prompt compression directives.
* `estimated_token_savings`: Estimated percentage savings.
* `okf_rule_block`: The exact OKF Markdown text synchronized to GitHub.
* `github_commit_status`: Confirmation of the GitHub commit SHA or status message.
* `github_commit_success`: Boolean flag indicating whether the commit and push succeeded.
* `target_branch`: Target branch name (`main` when initialized, `new_version` when updated).
* `workflow_state`: Workflow lifecycle status (`CREATED_IN_MAIN` or `AWAITING_HUMAN_REVIEW_ON_NEW_VERSION`).

---

## 6. Runtime Dependencies, Telemetry & Agent Engine Observability
In order to enable logging, telemetry, and Observability settings in Vertex AI Agent Engine, ensure all agents are using:
* `google-cloud-aiplatform[agent_engines]` ≥ v1.126.1
* `google-adk` ≥ v1.18.0
* Deployment configured with `--otel_to_cloud` and environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.

These library specifications and telemetry settings ensure audit executions, tool traces, Cloud Trace spans, and sub-agent calls are correctly captured in Cloud Logging and Vertex AI Agent Engine Observability.

---

## 7. Model Authentication & Secret Manager Key Management
* **Underlying Foundation Model:** `gemini-3.8-flash` via Google Agent Development Kit (ADK 2.0).
* **Secret Manager Integration:** The auditor agent pipeline dynamically retrieves its Gemini API key from Google Cloud Secret Manager under secret name `gemini-api-key` (with fallback to `google-api-key`) at runtime via `ensure_gemini_api_key()`.
* **Zero Hardcoding Policy:** API keys and credentials must NEVER be stored in source code or committed to repository files.
* **Environment Synchronization:** Automatically populates `GEMINI_API_KEY` and `GOOGLE_API_KEY` in `os.environ` dynamically, ensuring uninterrupted analysis and rule synthesis across all runtime environments.

---

## 8. Vertex AI Agent Engine Deployment & Reasoning Engine Instance
* **Reasoning Engine ID:** `4360856904684011520`
* **Resource Name:** `projects/537563976049/locations/us-central1/reasoningEngines/4360856904684011520`
* **Playground URL:** [Vertex AI Agent Engine Console](https://console.cloud.google.com/vertex-ai/agents/agent-engines/locations/us-central1/agent-engines/4360856904684011520/playground?project=experthub-510907)
* **Redeployment Command:**
  ```bash
  python auditor_agent/deploy.py \
      --project=experthub-510907 \
      --region=us-central1 \
      --agent_engine_id=4360856904684011520 \
      --otel_to_cloud
  ```

---

## 9. BigQuery AI & Generative AI Functions Skill (`bigquery-ai-functions`)
The Auditor Agent is equipped with the **BigQuery AI & Generative AI Functions** skill ([`SKILL.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/skills/bigquery-ai-functions/SKILL.md), [`bigquery_ai_functions_skill.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/bigquery_ai_functions_skill.md)).

### Capabilities & Usage Guidelines:
When auditing and analyzing BigQuery datasets (`agent_telemetry` and `demo.customer_ratings`), the agent can utilize BigQuery's generative and managed AI SQL functions for high-scale, cost-effective telemetry inspection, semantic anomaly classification, and automated rule synthesis:

1. **General-Purpose Generative AI (`AI.GENERATE`):**
   * Uses connection `us.gemini` and endpoint `gemini-3.8-flash`:
     ```sql
     SELECT AI.GENERATE(
       CONCAT('Analyze issues and synthesize operational rules: ', notes),
       connection_id => 'us.gemini',
       endpoint => 'gemini-3.8-flash',
       output_schema => 'issues ARRAY<STRING>, candidate_policies ARRAY<STRING>'
     )
     ```
   * Enforces typed structured JSON without sending data to a Python LLM.

2. **Managed AI Functions (High-Throughput Primitives):**
   * `AI.CLASSIFY(text, ['Billing', 'Bug Report', 'Policy Dispute'], connection_id => 'us.gemini')`: Zero-shot categorization.
   * `AI.IF(text, 'User describes an urgent hazard', connection_id => 'us.gemini')`: Semantic row filtering.
   * `AI.SCORE(text, 'Customer frustration severity', connection_id => 'us.gemini')`: Numerical relevance/sentiment scoring.
   * `AI.AGG(text, 'Summarize primary recurring reasons for low ratings', connection_id => 'us.gemini', endpoint => 'gemini-3.8-flash')`: In-database semantic aggregation across rows.

3. **Embeddings & Vector Search:**
   * `AI.GENERATE_EMBEDDING` and `VECTOR_SEARCH`: Semantic similarity matching across historical interaction logs.

The skill is loaded into the agent via ADK 2.0 `SkillToolset` under skill name `bigquery-ai-functions` and accessible via `get_bigquery_ai_skill_instructions` or dynamic skill tools (`load_skill`).

---

## 10. ADK Agent Analytics Plugin Skill (`adk-agent-telemetry`)
The Auditor Agent is equipped with the **ADK BigQuery Agent Analytics Plugin & Telemetry** skill ([`SKILL.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/skills/adk-agent-telemetry/SKILL.md), [`agent_analytics_plugin_skill.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/agent_analytics_plugin_skill.md)).

### Capabilities & Usage Guidelines:
When auditing and analyzing BigQuery telemetry datasets (`agent_telemetry.agent_events`), token consumption, tool executions, latency bottlenecks, and multi-agent workflows, the agent navigates, queries, and extracts insights using the ADK BigQuery Agent Analytics plugin data model:

1. **Base Event Sink (`agent_events`)**:
   * Append-only table partitioned by `DATE(timestamp)` and clustered by `(event_type, agent, user_id)`.
   * Captures raw payloads (`content`, `attributes`), latency metrics (`latency_ms`), and multimodal references (`content_parts`).
2. **Analytical Views Catalog (25 strongly typed views)**:
   * Direct querying of typed columns across `v_user_message_received`, `v_agent_response`, `v_llm_request`, `v_llm_response`, `v_llm_error`, `v_tool_starting`, `v_tool_completed`, `v_tool_error`, `v_tool_paused`, `v_agent_transfer`, `v_state_delta`, and node workflows.
3. **Trace and Span Correlation**:
   * OpenTelemetry distributed tracing via `trace_id`, `span_id`, and `parent_span_id`.
4. **ADK 2.0 Workflow Envelope**:
   * `attributes.adk` envelope containing graph nodes, agent handoffs, pause/resume correlation keys (`session_id, user_id, function_call_id`), and state checkpoints.

The skill is loaded into the agent via ADK 2.0 `SkillToolset` under skill name `adk-agent-telemetry` and accessible via `get_agent_analytics_plugin_skill_instructions` or dynamic skill tools (`load_skill`, `load_skill_resource`).
