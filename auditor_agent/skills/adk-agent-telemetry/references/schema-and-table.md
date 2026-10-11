# BigQuery Table Schema: `agent_events`

In the destination BigQuery dataset configured for the ADK BigQuery Agent Analytics plugin, the primary table is **`agent_events`**. It contains all raw telemetry emitted by the plugin.

---

## 1. DDL Definition

```sql
CREATE TABLE `your-project-id.your_dataset.agent_events` (
  timestamp TIMESTAMP NOT NULL OPTIONS(description="The UTC time at which the event was logged."),
  event_id STRING OPTIONS(description="Unique ID assigned before enqueue and preserved across Storage Write API retries."),
  event_type STRING OPTIONS(description="Indicates the type of event being logged (e.g., 'LLM_REQUEST', 'TOOL_COMPLETED')."),
  agent STRING OPTIONS(description="The name of the ADK agent or author associated with the event."),
  session_id STRING OPTIONS(description="A unique identifier to group events within a single conversation or user session."),
  invocation_id STRING OPTIONS(description="A unique identifier for each individual agent execution or turn within a session."),
  user_id STRING OPTIONS(description="The identifier of the user associated with the current session."),
  trace_id STRING OPTIONS(description="32-char hex trace ID. Inherited from the ambient OpenTelemetry span when one is active; otherwise generated per invocation by the plugin."),
  span_id STRING OPTIONS(description="16-char hex span ID for this specific operation. Tracked on the plugin's internal stack; the root invocation span may reuse the ambient OTel span id, while child BQAA spans are generated internally. No OpenTelemetry span is created or exported."),
  parent_span_id STRING OPTIONS(description="16-char hex span ID of the immediate caller, used to reconstruct the parent-child execution tree."),
  content JSON OPTIONS(description="The event-specific data (payload) stored as JSON."),
  content_parts ARRAY<STRUCT<
    mime_type STRING,
    uri STRING,
    object_ref STRUCT<
      uri STRING,
      version STRING,
      authorizer STRING,
      details JSON
    >,
    text STRING,
    part_index INT64,
    part_attributes STRING,
    storage_mode STRING
  >> OPTIONS(description="Detailed content parts for multi-modal data and offloaded payloads."),
  attributes JSON OPTIONS(description="Arbitrary key-value pairs for additional metadata (e.g., 'root_agent_name', 'model_version', 'usage_metadata', 'session_metadata', 'custom_tags', and 'adk' envelope)."),
  latency_ms JSON OPTIONS(description="Latency measurements (e.g., total_ms, time_to_first_token_ms)."),
  status STRING OPTIONS(description="The outcome of the event, typically 'OK' or 'ERROR'."),
  error_message STRING OPTIONS(description="Sanitized error or model termination diagnostic."),
  is_truncated BOOLEAN OPTIONS(description="Flag indicates if content was truncated.")
)
PARTITION BY DATE(timestamp)
CLUSTER BY event_type, agent, user_id;
```

---

## 2. Partitioning & Clustering Strategy

- **Partition Key**: `DATE(timestamp)`.
  - **Always filter by `timestamp`** in queries (e.g., `WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)`) to restrict scanned partitions and optimize query speed and costs.
- **Clustering Keys**: `(event_type, agent, user_id)`.
  - Filtering by `event_type` (e.g., `'LLM_RESPONSE'`), `agent` (e.g., `'customer_service_agent'`), or `user_id` takes advantage of clustered block pruning.

---

## 3. Detailed Column Specification

| Column | Type | Nullable | Description & Practical Usage |
| :--- | :--- | :--- | :--- |
| `timestamp` | `TIMESTAMP` | NO | UTC event timestamp. Used for partitioning, sequencing events, and ordering execution traces. |
| `event_id` | `STRING` | YES | Stable unique event identifier generated before enqueue. Enables deduplication across Storage Write API retries. |
| `event_type` | `STRING` | YES | Name of event type (e.g., `LLM_REQUEST`, `LLM_RESPONSE`, `TOOL_COMPLETED`, `AGENT_TRANSFER`, etc.). Clustered column. |
| `agent` | `STRING` | YES | Name of the ADK agent author producing the event. Clustered column. |
| `session_id` | `STRING` | YES | End-to-end conversation or user session grouping identifier. Correlates all turns in a conversation. |
| `invocation_id` | `STRING` | YES | Identifies a single execution turn or run within a session. Correlates events in one agent step. |
| `user_id` | `STRING` | YES | The external end-user identifier. Clustered column. |
| `trace_id` | `STRING` | YES | 32-character hex trace identifier. Joins directly to Cloud Trace / ambient OpenTelemetry spans. |
| `span_id` | `STRING` | YES | 16-character hex identifier for this specific operation/event. |
| `parent_span_id` | `STRING` | YES | 16-character hex identifier of the caller span. Enables parent-child execution DAG reconstruction. |
| `content` | `JSON` | YES | Event-specific payload (prompts, tool args, tool results, state deltas, error traceback). |
| `content_parts` | `ARRAY<STRUCT>` | YES | Multimodal data parts (images, audio, files) and offloaded large payloads. See section 5. |
| `attributes` | `JSON` | YES | Metadata dictionary containing `root_agent_name`, `model_version`, `usage_metadata`, `session_metadata`, custom tags, and the `adk` workflow envelope. |
| `latency_ms` | `JSON` | YES | Duration measurements: `{"total_ms": <int>, "time_to_first_token_ms": <int>}`. |
| `status` | `STRING` | YES | Operation outcome: `'OK'` or `'ERROR'`. |
| `error_message` | `STRING` | YES | Sanitized error diagnostic or model termination reason. |
| `is_truncated` | `BOOLEAN` | YES | `TRUE` if payload exceeded inline limits and was truncated (when GCS offload is not configured). |

---

## 4. OpenTelemetry Tracing Semantics

The plugin uses an internal stack to maintain hierarchical parent-child traces without requiring external OTel collector infrastructure:
1. **Root Invocation Span**: When run inside an environment with an active ambient OpenTelemetry span (e.g., Vertex AI Agent Engine, Google Cloud Run with Cloud Trace), `trace_id` inherits the active 32-character hex trace ID, and the root span reuses the ambient span ID.
2. **Child Spans**: Child operations (`LLM_REQUEST`, `TOOL_STARTING`, sub-agents) generate 16-character hex span IDs internally and set `parent_span_id` to their caller's `span_id`.
3. **No Active Span Fallback**: If no ambient span is active, the plugin generates a per-invocation `trace_id` automatically, preserving the hierarchy in BigQuery.
4. **Cloud Trace Joining**: Because `trace_id` matches Cloud Trace, you can join BigQuery logs with Cloud Logging and Cloud Trace spans.

---

## 5. `content_parts` and Cloud Storage Offloading

When large payloads (exceeding `max_content_length`, e.g., 500 KB) or multimodal items (images, audio, video) are processed, the plugin offloads them to Google Cloud Storage (configured via `gcs_bucket_name`).

### Schema of `content_parts` ARRAY elements:

| Field | Type | Description |
| :--- | :--- | :--- |
| `part_index` | `INT64` | 0-based sequence position of the part in the message/content. |
| `mime_type` | `STRING` | MIME type (e.g., `'text/plain'`, `'image/png'`, `'audio/wav'`). |
| `storage_mode` | `STRING` | `'INLINE'` (data embedded in row) or `'GCS_REFERENCE'` (offloaded to GCS). |
| `text` | `STRING` | Inline text, or placeholder string like `"[MEDIA OFFLOADED]"` / `"AAAA... [OFFLOADED]"`. |
| `uri` | `STRING` | Optional direct URI if provided by source. |
| `part_attributes`| `STRING` | Optional attributes associated with this specific content part. |
| `object_ref` | `STRUCT` | BigQuery Object Reference pointing to the offloaded GCS object: |
| &nbsp;&nbsp;↳ `uri` | `STRING` | Full Cloud Storage URI: `gs://<bucket>/<date>/<event_id>/<file>`. |
| &nbsp;&nbsp;↳ `authorizer` | `STRING` | BigQuery Cloud Resource Connection (e.g., `"us.bqml_connection"`). |
| &nbsp;&nbsp;↳ `version` | `STRING` | GCS generation / version identifier. |
| &nbsp;&nbsp;↳ `details` | `JSON` | Metadata including `{"gcs_metadata": {"content_type": "..."}}`. |

### Accessing Offloaded Objects:
If `connection_id` is configured, you can generate read-signed URLs directly in SQL using BigQuery's object functions:
```sql
SELECT
  timestamp,
  part.mime_type,
  part.object_ref.uri AS gcs_uri,
  STRING(OBJ.GET_ACCESS_URL(part.object_ref, 'r').access_urls.read_url) AS signed_url
FROM `your-project-id.your_dataset.agent_events`,
UNNEST(content_parts) AS part
WHERE part.storage_mode = 'GCS_REFERENCE';
```
