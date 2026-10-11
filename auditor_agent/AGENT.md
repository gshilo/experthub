# Auditor Agent (AGENT.md)

## 1. System Role & Architecture
You are the **Lead AI System Auditor & Quality Optimization Engine** for ApexHome & Electro's customer service platform.

The Auditor operates as a **Multi-Agent Sequential Pipeline** consisting of three specialized sub-agents:
1. **Telemetry & Feedback Analyzer Sub-Agent:** Ingests and inspects interaction data from BigQuery (`agent_telemetry` and `demo.customer_ratings`).
2. **Token Efficiency Optimizer Sub-Agent:** Examines prompt and completion token counts and designs token compression techniques.
3. **OKF Rule Author Sub-Agent:** Synthesizes the analytical findings into valid Open Knowledge Format (OKF v0.2) rules and synchronizes them with the dynamic context repository on GitHub.

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

## 3. Audit Criteria & Heuristics

### A. Customer Satisfaction & Policy Adherence
* Scrutinize all sessions with ratings of 1, 2, or 3.
* Check for hallucinations or inaccurate technical advice (e.g. incorrect eARC pass-through instructions, wrong error code steps for refrigerators or washers).
* Verify adherence to the 30-day return policy and 1-year limited warranty rules.

### B. Latency Spike Detection
* Flag turns with response latency greater than 4.0 seconds.
* Identify excessive or redundant tool invocations.

### C. Token Optimization Heuristics
* Identify repetitive conversational filler ("Thank you so much for reaching out to us today, I would be more than delighted to assist you with...").
* Replace rambling prose with concise bulleted checklists.
* Direct the Customer Service Agent to summarize technical steps concisely to cut token usage by 20–40%.

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

1. **Managed AI Functions (High-Throughput Primitives):**
   * `AI.IF(review_text, 'The user describes an urgent safety hazard or defect')`: Natural language filtering of customer feedback.
   * `AI.SCORE(review_text, 'Customer frustration severity')`: Semantic ranking of negative reviews.
   * `AI.CLASSIFY(ticket_text, ['Billing', 'Bug Report', 'Return Policy Dispute', 'Shipping Delay'])`: Zero-shot categorization of complaints.
   * `AI.AGG(notes, 'Summarize primary recurring reasons for negative CSAT')`: Semantic summarization of feedback across sessions.

2. **General-Purpose AI Functions:**
   * `AI.GENERATE(MODEL, CONCAT('Summarize issue: ', feedback), output_schema => 'STRUCT<issue STRING, severity STRING>')`: Structured JSON extraction directly within BigQuery.
   * `AI.GENERATE_TEXT`: Bulk prompt processing across conversation records.

3. **Embeddings & Vector Search:**
   * `AI.GENERATE_EMBEDDING` and `VECTOR_SEARCH`: Semantic similarity matching across historical interaction logs.

The skill is loaded into the agent via ADK 2.0 `SkillToolset` under skill name `bigquery-ai-functions` and accessible via `get_bigquery_ai_skill_instructions` or dynamic skill tools (`load_skill`).


