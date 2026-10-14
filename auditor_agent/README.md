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
   * Accesses GitHub credentials securely from **Google Cloud Secret Manager** (SSH deploy key `github-deploy-key` or PAT `github-pat`).
   * **Branch Interaction Rules:**
     * If `dynamic_context.md` is missing in `main` branch, creates it directly on `main`.
     * If `dynamic_context.md` already exists, makes changes **ONLY** to the file in `new_version` branch, preserving existing rules and only adding new rules to the file.
     * Changes remain in `new_version` branch until reviewed by a human and merged into `main`.

## 3. Audit Report Output Schema
Each invocation returns a structured report containing:
* `detected_issues`: Specific customer complaints, policy errors, or latency bottlenecks.
* `average_rating`: Mean score across analyzed sessions.
* `token_recommendations`: Actionable prompt compression directives.
* `estimated_token_savings`: Estimated percentage savings.
* `okf_rule_block`: The exact OKF Markdown text synchronized to GitHub.
* `github_commit_status`: Confirmation of the GitHub commit SHA or status message.
* `target_branch`: Target branch name (`main` or `new_version`).
* `workflow_state`: Workflow status (`CREATED_IN_MAIN` or `AWAITING_HUMAN_REVIEW_ON_NEW_VERSION`).

## 4. Dependencies, Telemetry & Agent Engine Observability
In order to enable logging, telemetry, and Observability settings in Vertex AI Agent Engine, ensure all agents are using:
* `google-cloud-aiplatform[agent_engines]` ≥ v1.126.1
* `google-adk` ≥ v1.18.0
* Deployment configured with `--otel_to_cloud` and runtime environment variables `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.

These library versions provide OpenTelemetry tracing, Cloud Trace export, structured log streaming, and telemetry capture within the Vertex AI Agent Engine runtime. Dependencies are defined in `requirements.txt`:
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

## 5. Deployment to Vertex AI Agent Engine
Deploy or redeploy the agent to **Vertex AI Agent Engine** using `deploy.py` (which includes `--otel_to_cloud` by default):

```bash
# Dry run validation
python auditor_agent/deploy.py --dry-run

# Production deployment / redeployment with telemetry & observability
python auditor_agent/deploy.py --project=experthub-510907 --region=us-central1 --otel_to_cloud
```

## 6. GitHub PAT Configuration in Secret Manager
To enable the Auditor Agent to push generated OKF rules directly to GitHub:
1. Generate a GitHub Personal Access Token:
   * **Classic PAT:** Select `repo` scope (Full control of private repositories).
   * **Fine-Grained PAT:** Select target repository `gshilo/experthub_context` with **Contents: Read and Write** permissions.
2. Add the token to Google Cloud Secret Manager (version update):
   ```bash
   echo -n "ghp_YOUR_TOKEN" | gcloud secrets versions add github-pat --data-file=-
   ```
3. If the secret contains the initial deployment placeholder (`PLACEHOLDER_GITHUB_PAT`), the Auditor Agent safely validates rules locally and provides explicit instructions in the UI without throwing unhandled exceptions.

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

