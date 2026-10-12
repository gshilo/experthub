# ADK 2.0 Metadata Envelope & Workflow Mechanics

ADK 2.0 introduces multi-agent workflows (agents transferring control, checkpointing state, compacting conversations) and asynchronous, long-running tools that pause and resume across turns.
The BigQuery Agent Analytics plugin logs these events and attaches an **`attributes.adk`** metadata envelope to every row.

---

## 1. The `attributes.adk` Envelope

The envelope ties BigQuery log rows directly to ADK runtime graph executions and events.

### Envelope Structure:
```json
{
  "attributes": {
    "adk": {
      "schema_version": "1",
      "app_name": "my_agent_app",
      "source_event_id": "evt-abc12345",
      "node": {
        "path": "workflows/order_fulfillment/validate_step@run-42",
        "run_id": "run-42",
        "parent_run_id": "run-1"
      },
      "branch": "main",
      "scope": {
        "id": "loopA@42",
        "kind": "node_run"
      },
      "route": "standard_checkout",
      "rewind_before_invocation_id": null,
      "pause_kind": "tool",
      "function_call_id": "call-xyz789"
    }
  }
}
```

### Envelope Fields:
* **`schema_version`** (`STRING`): Always `"1"`.
* **`app_name`** (`STRING`): The name passed to the ADK `App(...)` instance.
* **`source_event_id`** (`STRING`): The unique identifier of the originating ADK runtime event.
* **`node`** (`JSON` / `STRUCT`):
  * `path`: Hierarchical graph node path.
  * `run_id`: Unique identifier for the specific execution of this node.
  * `parent_run_id`: Identifier of the parent node's execution (or `NULL` for root).
* **`branch`** (`STRING`): Active execution branch name.
* **`scope`** (`JSON`):
  * `id`: Scope identifier (e.g., `'loopA@42'`).
  * `kind`: Scope kind (`'node_run'`, `'function_call'`, `'route'`, `'render_ui_widgets'`).
* **`route`** (`STRING`): Active dynamic route taken in graph execution.
* **`rewind_before_invocation_id`** (`STRING`): Set when state rewinding occurs.
* **`pause_kind`** (`STRING`): Reason for execution suspension: `'tool'`, `'hitl_credential'`, `'hitl_confirmation'`, or `'hitl_input'`.
* **`function_call_id`** (`STRING`): Stable identifier connecting a tool pause to its resumption.

### Querying the Envelope in SQL:
To query envelope fields from the base table `agent_events`:
```sql
SELECT
  timestamp,
  event_type,
  JSON_VALUE(attributes, '$.adk.app_name') AS app_name,
  JSON_VALUE(attributes, '$.adk.source_event_id') AS source_event_id,
  JSON_VALUE(attributes, '$.adk.node.path') AS node_path,
  JSON_VALUE(attributes, '$.adk.pause_kind') AS pause_kind,
  JSON_VALUE(attributes, '$.adk.function_call_id') AS function_call_id
FROM `your-project-id.your_dataset.agent_events`
WHERE JSON_VALUE(attributes, '$.adk.node.path') IS NOT NULL;
```
*(Note: Analytical views like `v_tool_paused`, `v_node_output`, and `v_agent_transfer` already expose these as flat columns).*

---

## 2. Multi-Agent Transfers (`AGENT_TRANSFER`)

In collaborative or router-specialist architectures, control is handed off between agents:
* **Event Type**: `AGENT_TRANSFER`
* **Dedicated View**: `v_agent_transfer`
* **Payload Structure**:
  ```json
  {
    "event_type": "AGENT_TRANSFER",
    "content": {
      "from_agent": "coordinator_agent",
      "to_agent": "billing_specialist"
    },
    "attributes": {
      "adk": {
        "source_event_id": "evt-transfer-101"
      }
    }
  }
  ```
* **Analysis**: Trace the sequence of agent delegations across a conversation turn to evaluate routing efficiency.

---

## 3. Agent State Checkpoints (`AGENT_STATE_CHECKPOINT`)

Agents capture snapshots of their internal variables during and at the end of runs:
* **Event Type**: `AGENT_STATE_CHECKPOINT`
* **Dedicated View**: `v_agent_state_checkpoint`
* **Payload Structure**:
  ```json
  {
    "event_type": "AGENT_STATE_CHECKPOINT",
    "content": {
      "agent_state": { "order_id": 98124, "approval_step": "completed" },
      "end_of_agent": false
    },
    "attributes": {
      "adk": { "source_event_id": "evt-checkpoint-202" }
    }
  }
  ```
* **End-of-Agent Marker**: When an agent completes its lifecycle, a checkpoint with `end_of_agent: true` is emitted. In `v_agent_state_checkpoint`, `agent_state_type` helps distinguish a populated state from a null end-of-run marker.

---

## 4. Long-Running Tool Pause and Resume Pairing

When a tool yields execution (waiting for async jobs, human approvals, or webhooks):
1. The tool emits a **`TOOL_PAUSED`** event (view `v_tool_paused`) with `function_call_id` and `pause_kind = 'tool'` (or HITL kinds).
2. When the result is supplied in a subsequent turn, a **`TOOL_COMPLETED`** event (view `v_tool_completed`) is logged with the **identical `function_call_id`**.

### Measuring Paused Duration in SQL:
```sql
SELECT
  p.session_id,
  p.tool_name,
  p.function_call_id,
  p.timestamp AS paused_at,
  c.timestamp AS resumed_at,
  TIMESTAMP_DIFF(c.timestamp, p.timestamp, SECOND) AS paused_duration_seconds
FROM `your-project-id.your_dataset.v_tool_paused` AS p
JOIN `your-project-id.your_dataset.v_tool_completed` AS c
  USING (session_id, user_id, function_call_id)
WHERE p.pause_kind = 'tool'
ORDER BY paused_at DESC;
```

---

## 5. Workflow Node Outputs and Errors (`NODE_OUTPUT`, `NODE_ERROR`)

In DAG-based graph workflows, each node execution can emit terminal results:
* **`NODE_OUTPUT`** (view `v_node_output`): Emitted when a node completes and produces output distinct from conversation messages.
  * Fields: `node_path`, `node_run_id`, `node_parent_run_id`, `output`.
* **`NODE_ERROR`** (view `v_node_error`): Emitted when a node encounters a execution failure.
  * Fields: `node_path`, `node_run_id`, `node_parent_run_id`, `error_code`, `error_message`.

---

## 6. Context Compaction (`EVENT_COMPACTION`)

To avoid exceeding model context limits during long conversations, ADK periodically compacts a range of earlier events into an executive summary:
* **Event Type**: `EVENT_COMPACTION`
* **Dedicated View**: `v_event_compaction`
* **Columns**:
  * `window_start`: Start timestamp of the compacted message range.
  * `window_end`: End timestamp of the compacted message range.
  * `compacted_content`: The summarized prompt text injected into subsequent context windows.

---

## 7. The Context Graph (Decision Property Graph)

Beyond tabular event logs, the [BigQuery Agent Analytics SDK](https://github.com/GoogleCloudPlatform/BigQuery-Agent-Analytics-SDK) supports materializing a **Property Graph** directly in BigQuery:
* **Artifacts**: Defined using BigQuery's `CREATE PROPERTY GRAPH` DDL over the `agent_events` table.
* **Entities**: Nodes representing Requests, Agents, Decisions, Tool Invocations, and Outcomes.
* **Querying**: Allows querying agent reasoning trees using **Graph Query Language (GQL)**:
  ```sql
  GRAPH `your-project-id.your_dataset.agent_decision_graph`
  MATCH (req:Request)-[:RESULTED_IN]->(decision:Decision)-[:INVOKED]->(t:ToolCall)
  WHERE req.session_id = 'session-123'
  RETURN req, decision, t;
  ```
