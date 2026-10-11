# BigQuery Analytical Views Reference

The ADK BigQuery Agent Analytics plugin automatically deploys a set of analytical views in the configured destination dataset.
These views flatten nested JSON payloads from the base table `agent_events` into strongly typed columns, avoiding verbose `JSON_VALUE` or `JSON_QUERY` expressions.

---

## 1. View Naming and Common Columns

Views follow the standard naming convention:
`{view_prefix}_{event_type_lowercase}` (by default, prefix is `v_`, yielding `v_llm_response`, `v_tool_completed`, etc.).

### Common Columns in All Views:
Every auto-created view includes the following standardized execution metadata columns:

| Column | Type | Description |
| :--- | :--- | :--- |
| `timestamp` | `TIMESTAMP` | UTC timestamp when event occurred. |
| `event_id` | `STRING` | Stable unique event identifier. |
| `event_type` | `STRING` | Name of the logged event type. |
| `agent` | `STRING` | Name of the agent producing the event. |
| `session_id` | `STRING` | Conversation or session ID. |
| `invocation_id` | `STRING` | Turn / execution execution run ID. |
| `user_id` | `STRING` | User identifier. |
| `trace_id` | `STRING` | 32-char hex distributed trace identifier. |
| `span_id` | `STRING` | 16-char hex operation span identifier. |
| `parent_span_id` | `STRING` | 16-char hex caller span identifier. |
| `status` | `STRING` | Event status (`'OK'` or `'ERROR'`). |
| `error_message` | `STRING` | Error diagnostic or model termination reason. |
| `is_truncated` | `BOOLEAN` | Whether payload was truncated. |

---

## 2. Complete Catalog of Views

### A. Model & LLM Views

#### 1. `v_llm_request`
* **Source Event**: `LLM_REQUEST`
* **Description**: Captures prompts sent to models, model configurations, and exposed tool definitions.
* **Specific Columns**:
  * `model` (`STRING`): Model name requested (from `attributes.model`).
  * `request_content` (`JSON`): Prompt messages and system instructions (from `content`).
  * `llm_config` (`JSON`): Model hyperparameters such as temperature, top_p, etc. (from `attributes.llm_config`).
  * `tools` (`JSON` / `ARRAY<STRING>`): Tools made available to the model (from `attributes.tools`).

#### 2. `v_llm_response`
* **Source Event**: `LLM_RESPONSE`
* **Description**: Captures model completions, detailed token usage metrics, cache hit rate, and latency.
* **Specific Columns**:
  * `response` (`STRING` / `JSON`): Generated candidate text or tool call decisions.
  * `usage_prompt_tokens` (`INT64`): Prompt tokens consumed.
  * `usage_completion_tokens` (`INT64`): Output candidate tokens generated.
  * `usage_total_tokens` (`INT64`): Total tokens consumed.
  * `usage_cached_tokens` (`INT64`): Cached tokens reused.
  * `usage_thinking_tokens` (`INT64`): Reasoning / thinking tokens (for reasoning models).
  * `usage_tool_use_tokens` (`INT64`): Tokens consumed by tool invocation payloads.
  * `context_cache_hit_rate` (`FLOAT64`): Fraction of prompt served from cache (`cached / prompt`).
  * `total_ms` (`INT64`): Total duration of LLM call in milliseconds.
  * `ttft_ms` (`INT64`): Time-to-first-token in milliseconds.
  * `model_version` (`STRING`): Resolved backend model version.
  * `usage_metadata` (`JSON`): Raw usage metadata object.
  * `cache_metadata` (`JSON`): Cache details (cache name, creation time, TTL).
  * `cache_type` (`STRING`): Type of cache used.
  * `finish_reason` (`STRING`): Completion termination reason (`'STOP'`, `'MAX_TOKENS'`, etc.).

#### 3. `v_llm_error`
* **Source Event**: `LLM_ERROR`
* **Description**: Captures model invocation failures (e.g., quota exhaustion, 429 errors, safety blocks).
* **Specific Columns**:
  * `total_ms` (`INT64`): Elapsed time before failure occurred.
  * *(Plus common `error_message` and `status = 'ERROR'`)*

---

### B. Tool Execution & Suspension Views

#### 4. `v_tool_starting`
* **Source Event**: `TOOL_STARTING`
* **Description**: Emitted when a tool invocation begins.
* **Specific Columns**:
  * `tool_name` (`STRING`): Name of the invoked tool.
  * `tool_args` (`JSON`): Arguments passed to the tool.
  * `tool_origin` (`STRING`): Tool provenance category:
    * `LOCAL` (`FunctionTool`)
    * `MCP` (`McpTool` via Model Context Protocol)
    * `SUB_AGENT` (`AgentTool` sub-agent wrapper)
    * `A2A` (`RemoteA2aAgent` via Agent2Agent protocol)
    * `TRANSFER_AGENT` (`TransferToAgentTool`)
    * `TRANSFER_A2A` (`TransferToAgentTool` wrapping remote A2A)
    * `UNKNOWN`

#### 5. `v_tool_completed`
* **Source Event**: `TOOL_COMPLETED`
* **Description**: Emitted when tool execution succeeds.
* **Specific Columns**:
  * `tool_name` (`STRING`): Tool name.
  * `tool_result` (`JSON` / `STRING`): Value returned by the tool.
  * `tool_origin` (`STRING`): Origin category (e.g., `LOCAL`, `MCP`, `SUB_AGENT`).
  * `total_ms` (`INT64`): Duration of tool execution in milliseconds.
  * `pause_kind` (`STRING`): Pause classification (`'tool'` for resumed asynchronous tools).
  * `function_call_id` (`STRING`): Unique function call ID pairing this completion with its preceding `TOOL_PAUSED` event.

#### 6. `v_tool_error`
* **Source Event**: `TOOL_ERROR`
* **Description**: Emitted when tool execution fails with an exception.
* **Specific Columns**:
  * `tool_name` (`STRING`): Tool name.
  * `tool_args` (`JSON`): Arguments that led to the error.
  * `tool_origin` (`STRING`): Origin category.
  * `total_ms` (`INT64`): Duration before the failure occurred.
  * *(Plus common `error_message`)*

#### 7. `v_tool_paused`
* **Source Event**: `TOOL_PAUSED`
* **Description**: Emitted when a long-running tool yields or suspends across conversation turns, or when HITL input is requested.
* **Specific Columns**:
  * `tool_name` (`STRING`): Suspended tool name.
  * `tool_args` (`JSON`): Input parameters provided to the tool.
  * `pause_kind` (`STRING`): Cause of pause (`'tool'`, `'hitl_credential'`, `'hitl_confirmation'`, `'hitl_input'`).
  * `function_call_id` (`STRING`): Call correlation ID used to match with subsequent `v_tool_completed`.

---

### C. Agent Lifecycle & Messages

#### 8. `v_user_message_received`
* **Source Event**: `USER_MESSAGE_RECEIVED`
* **Description**: Captures raw incoming user queries and prompts.
* **Specific Columns**: Common columns.

#### 9. `v_agent_starting`
* **Source Event**: `AGENT_STARTING`
* **Description**: Agent activation and configuration.
* **Specific Columns**:
  * `agent_instruction` (`STRING`): System instructions/prompt guiding this agent's behavior.

#### 10. `v_agent_completed`
* **Source Event**: `AGENT_COMPLETED`
* **Description**: Agent execution completion marker.
* **Specific Columns**:
  * `total_ms` (`INT64`): Total duration the agent was active.

#### 11. `v_agent_error`
* **Source Event**: `AGENT_ERROR`
* **Description**: Unhandled agent-level runtime exceptions.
* **Specific Columns**:
  * `total_ms` (`INT64`): Duration before error occurred.
  * `error_traceback` (`STRING`): Sanitized stack trace.

#### 12. `v_agent_response`
* **Source Event**: `AGENT_RESPONSE`
* **Description**: The final text response produced by the agent and sent back to the user.
* **Specific Columns**:
  * `response_text` (`STRING`): Final answer text sent to the user.
  * `source_event_id` (`STRING`): ADK runtime event ID producing the response.
  * `source_event_author` (`STRING`): Name of the agent that formulated the response.
  * `source_event_branch` (`STRING`): Active execution branch name.

#### 13. `v_invocation_starting`
* **Source Event**: `INVOCATION_STARTING`
* **Description**: Marks the beginning of an individual turn / invocation run.

#### 14. `v_invocation_completed`
* **Source Event**: `INVOCATION_COMPLETED`
* **Description**: Marks normal termination of an invocation run.

#### 15. `v_invocation_error`
* **Source Event**: `INVOCATION_ERROR`
* **Description**: Unhandled runner-level failure terminating the turn.
* **Specific Columns**:
  * `error_traceback` (`STRING`): Sanitized stack trace.

---

### D. Multi-Agent & Workflow Views (ADK 2.0)

#### 16. `v_agent_transfer`
* **Source Event**: `AGENT_TRANSFER`
* **Description**: Multi-agent delegation / handoff (e.g., triage/coordinator router transferring to a specialist).
* **Specific Columns**:
  * `from_agent` (`STRING`): Delegating agent.
  * `to_agent` (`STRING`): Recipient agent.
  * `source_event_id` (`STRING`): Event ID initiating handoff.

#### 17. `v_agent_state_checkpoint`
* **Source Event**: `AGENT_STATE_CHECKPOINT`
* **Description**: Snapshots of agent state during or at completion of execution.
* **Specific Columns**:
  * `agent_state` (`JSON`): State variable snapshot.
  * `agent_state_type` (`STRING`): State schema type.
  * `end_of_agent` (`BOOLEAN`): `TRUE` indicates terminal checkpoint at the end of the agent's run.
  * `source_event_id` (`STRING`): Source event ID.

#### 18. `v_event_compaction`
* **Source Event**: `EVENT_COMPACTION`
* **Description**: Context-window compaction events summarizing earlier turns in long sessions.
* **Specific Columns**:
  * `start_seconds` (`FLOAT64`): Window start in epoch seconds.
  * `end_seconds` (`FLOAT64`): Window end in epoch seconds.
  * `window_start` (`TIMESTAMP`): Start of compacted message window.
  * `window_end` (`TIMESTAMP`): End of compacted message window.
  * `compacted_content` (`STRING`): Generated summary string replacing the window.

#### 19. `v_node_output`
* **Source Event**: `NODE_OUTPUT`
* **Description**: Terminal output emitted by a specific node in a graph workflow.
* **Specific Columns**:
  * `node_path` (`STRING`): Graph node hierarchy path (e.g., `'workflow/process_order@run-1'`).
  * `node_run_id` (`STRING`): Unique execution ID for this node run.
  * `node_parent_run_id` (`STRING`): Parent node run ID.
  * `output` (`JSON`): Output payload emitted by the node.

#### 20. `v_node_error`
* **Source Event**: `NODE_ERROR`
* **Description**: Failure emitted by a specific node in a graph workflow.
* **Specific Columns**:
  * `node_path` (`STRING`): Graph node hierarchy path.
  * `node_run_id` (`STRING`): Unique execution ID for this node run.
  * `node_parent_run_id` (`STRING`): Parent node run ID.
  * `error_code` (`STRING`): Workflow node error code (e.g., `'VALIDATION_FAILED'`).

---

### E. Human-in-the-Loop (HITL) Views

#### 21. `v_hitl_credential_request`
* **Source Event**: `HITL_CREDENTIAL_REQUEST`
* **Description**: Triggered by `adk_request_credential` tool to request user credentials (e.g., OAuth tokens).
* **Specific Columns**: `tool_name`, `tool_args`.

#### 22. `v_hitl_confirmation_request`
* **Source Event**: `HITL_CONFIRMATION_REQUEST`
* **Description**: Triggered by `adk_request_confirmation` tool to request user approval prior to executing a sensitive action.
* **Specific Columns**: `tool_name`, `tool_args`.

#### 23. `v_hitl_input_request`
* **Source Event**: `HITL_INPUT_REQUEST`
* **Description**: Triggered by `adk_request_input` tool to request free-form user clarifications or parameters.
* **Specific Columns**: `tool_name`, `tool_args`.

*Note: Completed HITL interactions emit `HITL_*_REQUEST_COMPLETED` in the base `agent_events` table (or pair with `v_tool_completed` via `function_call_id`).*

---

### F. Inter-Agent & State Views

#### 24. `v_a2a_interaction`
* **Source Event**: `A2A_INTERACTION`
* **Description**: Logs communications with remote external agents via the Agent2Agent protocol.
* **Specific Columns**:
  * `response_content` (`JSON` / `STRING`): Response returned by the remote agent.
  * `a2a_task_id` (`STRING`): A2A task identifier.
  * `a2a_context_id` (`STRING`): A2A context identifier.
  * `a2a_request` (`JSON`): Full outgoing A2A request payload.
  * `a2a_response` (`JSON`): Full incoming A2A response payload.

#### 25. `v_state_delta`
* **Source Event**: `STATE_DELTA`
* **Description**: Captures incremental modifications to session state variables made by tools.
* **Specific Columns**:
  * `state_delta` (`JSON`): Key-value state mutations. Keys starting with `temp:` are automatically sanitized to `"[REDACTED]"`.

---

## 3. Language & Runtime Differences

* **Python**: Emits all events and creates all 25 views by default.
* **Java (v1.7.0+)**: Views created only when `createViews(true)` is configured. Emits `TOOL_PAUSED` and pause/resume pairing keys, but does **not** emit `AGENT_TRANSFER`, `AGENT_STATE_CHECKPOINT`, `EVENT_COMPACTION`, `AGENT_ERROR`, `INVOCATION_ERROR`, `NODE_OUTPUT`, or `NODE_ERROR`. Exposes `text_summary` instead of `response_text` on `v_agent_response`.
* **Kotlin**: Logs `INVOCATION_STARTING` and `INVOCATION_COMPLETED` only; does not create views.
