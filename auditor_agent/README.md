# Auditor Agent (`auditor_agent/`)

## 1. Overview
The **Auditor Agent** is an autonomous quality, latency, and token-efficiency inspection engine for the customer service platform. Built using **Google Agent Development Kit (ADK 2.0)** and powered by **Gemini 3.8 Flash** (`gemini-3.8-flash`), it executes a sequential multi-agent workflow to evaluate live interactions, compress prompt token usage, and automatically publish refined rules in Open Knowledge Format (OKF v0.2) to GitHub.

## 2. Multi-Agent Sequential Architecture
The Auditor coordinates three specialized sub-agents with an **In-Database BigQuery AI Pushdown Architecture**:
1. **Telemetry & Feedback Analyzer Sub-Agent:**
   * Queries BigQuery dataset `agent_telemetry` and table `demo.customer_ratings`.
   * Pushes down AI analysis to BigQuery using **`AI.IF`** for semantic filtering of customer friction and sub-optimal dialogues, and **`AI.GENERATE`** for actionable rule formulation.
   * Flags low customer ratings (≤3/5), policy mistakes, and latency spikes exceeding 3.5 seconds.
2. **Token Efficiency Optimizer Sub-Agent:**
   * Analyzes prompt and completion tokens dynamically via BigQuery AI metrics pushdown.
   * Eliminates boilerplate pleasantries and formulates structured brevity directives for a 20–45% token reduction with zero static templates.
3. **OKF Rule Author & Committer Sub-Agent:**
   * Generates formal YAML + Markdown rules strictly conforming to the **Open Knowledge Format (OKF v0.2)** specification.
   * **100% Dynamic Rule Formulation:** Formulates rules dynamically based purely on current telemetry and customer feedback findings. Zero hardcoded rule templates.
   * **Legacy Rule Scrubbing & Deduplication:** Automatically purges any legacy static rules and deduplicates candidate rules using semantic token similarity.
   * Pushes updated rules over SSH to GitHub repository `gshilo/experthub_context` on branch `new_version` using the SSH deploy key stored in Secret Manager (`github-deploy-key`).
   * **Branching & Merge Workflow:**
     * Bases `new_version` on `origin/new_version` if it exists, otherwise creates `new_version` from `origin/main`.
     * Merges newly generated rules into existing `dynamic_context.md` and pushes to `origin/new_version` (`AWAITING_HUMAN_REVIEW`) for review before merging into `main`.

## 3. Audit Report Output Schema
Each invocation returns a structured report containing:
* `detected_issues`: Specific customer complaints, policy errors, or latency bottlenecks.
* `average_rating`: Mean score across analyzed sessions.
* `token_recommendations`: Actionable prompt compression directives.
* `estimated_token_savings`: Estimated percentage savings.
* `okf_rule_block`: The exact OKF Markdown text pushed to GitHub.
* `github_commit_status`: Status message including the GitHub commit SHA.
* `github_commit_success`: Boolean indicating whether the GitHub commit and push succeeded.
* `target_branch`: Target GitHub branch (`new_version`).
* `repo`: Target GitHub repository (`gshilo/experthub_context`).
* `workflow_state`: Workflow lifecycle state (`AWAITING_HUMAN_REVIEW`).
* `okf_file`: Target OKF filename (`dynamic_context.md`).

## 4. Dependencies, Telemetry & Agent Engine Observability
In order to enable logging, telemetry, and Observability settings in Vertex AI Agent Engine, ensure all agents are using:
* `google-cloud-aiplatform[agent_engines]` ≥ v1.126.1
* `google-adk` ≥ v1.18.0
* Deployment configured with `--otel_to_cloud` and runtime environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`, `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`, and `GITHUB_DEPLOY_KEY_SECRET_NAME=github-deploy-key`.

These library versions provide OpenTelemetry tracing, Cloud Trace export, structured log streaming, and telemetry capture within the Vertex AI Agent Engine runtime. Dependencies are defined in `requirements.txt`:
```text
google-cloud-aiplatform[agent_engines]>=1.126.1
google-adk>=1.18.0
google-cloud-bigquery>=3.46.0
google-cloud-bigquery-storage>=2.42.0
google-cloud-secret-manager>=2.31.0
pyarrow>=25.0.0
requests>=2.32.0
pydantic>=2.10.0
google-genai>=1.0.0
```

## 5. Deployment to Vertex AI Agent Engine
Deploy or redeploy the agent to **Vertex AI Agent Engine** using `deploy.py` (which includes `--otel_to_cloud` by default):

```bash
# Dry run validation
python auditor_agent/deploy.py --dry-run

# Production deployment / redeployment with telemetry & observability
python auditor_agent/deploy.py --project=experthub-510907 --region=us-central1 --otel_to_cloud
```

## 6. GitHub SSH Deploy Key Configuration in Secret Manager
To enable the Auditor Agent to push generated OKF rules to GitHub over SSH:
1. Generate an Ed25519 SSH deploy keypair and add the public key to `https://github.com/gshilo/experthub_context/settings/keys` with **Allow write access** enabled.
2. Store the private key in Google Cloud Secret Manager under secret name `github-deploy-key` (overrideable via `GITHUB_DEPLOY_KEY_SECRET_NAME`):
   ```bash
   gcloud secrets versions add github-deploy-key --data-file=/path/to/id_ed25519
   ```
3. If the secret is missing or contains a placeholder value, the Auditor Agent safely returns the generated OKF rules with an actionable error message without leaking any temporary key files.

## 7. BigQuery AI & Generative AI Functions Skill
The Auditor Agent includes the **BigQuery AI & Generative AI Functions** skill:
* **Skill File Location:** [`skills/bigquery-ai-functions/SKILL.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/skills/bigquery-ai-functions/SKILL.md) and [`bigquery_ai_functions_skill.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/bigquery_ai_functions_skill.md)
* **ADK Skill Identifier:** `bigquery-ai-functions`
* **Toolset:** Registered via Google ADK 2.0 `SkillToolset` and exposed through `get_bigquery_ai_skill_instructions` tool.
* **Capabilities:** Enables SQL-native generative AI inspection (`AI.GENERATE`, `AI.GENERATE_TEXT`), natural language semantic filtering (`AI.IF`), scoring (`AI.SCORE`), zero-shot classification (`AI.CLASSIFY`), aggregation (`AI.AGG`), and vector embeddings (`AI.GENERATE_EMBEDDING`, `VECTOR_SEARCH`) across telemetry logs and customer feedback in BigQuery.

## 8. ADK Agent Analytics Plugin Skill
The Auditor Agent includes the **ADK BigQuery Agent Analytics Plugin & Telemetry** skill:
* **Skill File Location:** [`skills/adk-agent-telemetry/SKILL.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/skills/adk-agent-telemetry/SKILL.md) and [`agent_analytics_plugin_skill.md`](file:///home/admin_gshilo_altostrat_com/experthub/auditor_agent/agent_analytics_plugin_skill.md)
* **ADK Skill Identifier:** `adk-agent-telemetry`
* **Toolset:** Registered via Google ADK 2.0 `SkillToolset` and exposed through `get_agent_analytics_plugin_skill_instructions` tool.
* **Capabilities:** Enables navigating, querying, and analyzing BigQuery telemetry tables (`agent_events`) and the 25 strongly typed analytical views (`v_*`), inspecting token usage and costs, debugging tool execution failures, correlating pause/resume tool calls, and tracing multi-agent workflow handoffs.

