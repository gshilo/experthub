---
name: bigquery-ai-functions
license: Apache-2.0
metadata:
  author: experthub-auditor
  version: "1.0"
description: >-
  A comprehensive guide for agents to write, inspect, and optimize SQL queries using
  Google BigQuery's generative AI, managed AI, and vector embedding capabilities.
---

# Skill: BigQuery AI & Generative AI Functions

## Description
A comprehensive guide for agents to write, inspect, and optimize SQL queries using Google BigQuery's generative AI, managed AI, and vector embedding capabilities.

---

## 1. Overview & Function Taxonomy

BigQuery provides two main categories of Generative AI SQL functions:

1. **General-Purpose AI Functions**
   - Provide full control over the remote model, prompt templates, parameters (temperature, max output tokens, etc.), and custom structured schemas.
   - Ideal for complex extraction, RAG, custom reasoning, and multimodal inputs (images, audio, video, PDFs).
   - Functions: `AI.GENERATE`, `AI.GENERATE_TEXT` (table-valued, legacy equivalent: `ML.GENERATE_TEXT`), `AI.GENERATE_TABLE`, `AI.GENERATE_BOOL`, `AI.GENERATE_INT`, `AI.GENERATE_DOUBLE`.

2. **Managed AI Functions**
   - High-level, streamlined SQL functions optimized by BigQuery for cost, latency, and scale (can scale to millions/billions of rows).
   - Automatically select model tiers behind the scenes.
   - Functions:
     - `AI.IF`: Natural language row filtering in `WHERE` or `JOIN` clauses.
     - `AI.SCORE`: Natural language scoring/ranking in `ORDER BY` or scoring columns.
     - `AI.CLASSIFY`: Natural language categorization in `SELECT` or `GROUP BY`.
     - `AI.AGG`: Natural language summarization or aggregation across rows.

3. **Embeddings & Vector Search**
   - Functions: `AI.GENERATE_EMBEDDING` (recommended) or `ML.GENERATE_EMBEDDING`, paired with `VECTOR_SEARCH` or `AI.SEARCH`.

---

## 2. Prerequisites & Remote Model Setup

Before invoking models via BigQuery SQL, an external connection and a remote model definition in BigQuery ML are typically required.

### 2.1 Create Cloud Resource Connection
```sql
-- Done via bq CLI or Cloud Console:
-- bq mk --connection --location=US --project_id=PROJECT_ID --connection_type=CLOUD_RESOURCE my-connection
```
Grant the connection's service account the **Vertex AI User** (`roles/aiplatform.user`) role.

### 2.2 Create Remote Model Reference
```sql
CREATE OR REPLACE MODEL `my_project.my_dataset.gemini_model`
REMOTE WITH CONNECTION `my_project.us.my-connection`
OPTIONS (
  ENDPOINT = 'gemini-1.5-pro' -- or 'gemini-1.5-flash'
);
```

For embeddings:
```sql
CREATE OR REPLACE MODEL `my_project.my_dataset.text_embedding_model`
REMOTE WITH CONNECTION `my_project.us.my-connection`
OPTIONS (
  ENDPOINT = 'text-embedding-005' -- or 'multimodalembedding@001'
);
```

---

## 3. General-Purpose AI Functions

### 3.1 `AI.GENERATE` (Flexible Inference & Multimodal)
Takes a string, struct, or `ObjectRef` (GCS objects) and returns a struct containing `result`, `full_response`, and `status`.

#### Basic Text Prompt:
```sql
SELECT
  id,
  AI.GENERATE(
    MODEL `my_dataset.gemini_model`,
    CONCAT('Summarize this support ticket in under 20 words: ', ticket_text)
  ).result AS summary
FROM `my_dataset.support_tickets`;
```

#### Structured Output via `output_schema`:
Extract entities into a typed struct:
```sql
SELECT
  id,
  AI.GENERATE(
    MODEL `my_dataset.gemini_model`,
    CONCAT('Extract the customer name, sentiment, and action items: ', ticket_text),
    output_schema => 'STRUCT<customer_name STRING, sentiment STRING, action_items ARRAY<STRING>>'
  ).result AS parsed_output
FROM `my_dataset.support_tickets`;
```

#### Multimodal Input with `OBJ.MAKE_REF`:
```sql
SELECT
  uri,
  AI.GENERATE(
    MODEL `my_dataset.gemini_model`,
    STRUCT(
      'Describe the contents and condition of this damage report image' AS prompt_text,
      OBJ.MAKE_REF(uri) AS image
    )
  ).result AS image_analysis
FROM `my_dataset.vehicle_images`;
```

---

### 3.2 `AI.GENERATE_TEXT` (Table-Valued Function)
Accepts a subquery or table reference that contains a `prompt` column:
```sql
SELECT *
FROM AI.GENERATE_TEXT(
  MODEL `my_dataset.gemini_model`,
  (
    SELECT
      ticket_id,
      CONCAT('Classify this customer query into Technical, Billing, or General: ', message) AS prompt
    FROM `my_dataset.messages`
  ),
  STRUCT(
    0.2 AS temperature,
    256 AS max_output_tokens
  )
);
```
*Note: In older codebases, `ML.GENERATE_TEXT` follows an identical pattern; recommend `AI.GENERATE_TEXT` for modern queries.*

---

## 4. Managed AI Functions (Optimized SQL Primitives)

Use these for clean, high-performance querying without manually defining prompt boilerplate or parsing raw model outputs.

### 4.1 `AI.IF` (Semantic Filtering)
```sql
SELECT customer_id, review_text
FROM `my_dataset.customer_reviews`
WHERE AI.IF(review_text, 'The user describes an urgent safety hazard');
```

### 4.2 `AI.SCORE` (Semantic Ranking)
Generates a numerical score between 0.0 and 1.0 based on criteria:
```sql
SELECT
  review_id,
  product_id,
  review_text,
  AI.SCORE(review_text, 'How enthusiastic and positive is this review?') AS enthusiasm_score
FROM `my_dataset.reviews`
ORDER BY enthusiasm_score DESC
LIMIT 10;
```

### 4.3 `AI.CLASSIFY` (Zero-Shot Categorization)
Classifies inputs into an array of allowed categories:
```sql
SELECT
  AI.CLASSIFY(ticket_text, ['Billing', 'Bug Report', 'Feature Request', 'Onboarding']) AS category,
  COUNT(1) AS ticket_count
FROM `my_dataset.support_tickets`
GROUP BY category;
```

### 4.4 `AI.AGG` (Semantic Aggregation)
Summarizes multiple rows of data into high-level insights:
```sql
SELECT
  department,
  AI.AGG(exit_interview_notes, 'Summarize the primary recurring reasons employees leave this department') AS exit_summary
FROM `my_dataset.hr_records`
GROUP BY department;
```

---

## 5. Embeddings & Vector Search

### 5.1 Generating Embeddings (`AI.GENERATE_EMBEDDING`)
```sql
CREATE OR REPLACE TABLE `my_dataset.product_embeddings` AS
SELECT *
FROM AI.GENERATE_EMBEDDING(
  MODEL `my_dataset.text_embedding_model`,
  (
    SELECT product_id, description AS content
    FROM `my_dataset.catalog`
  )
);
```

### 5.2 Creating a Vector Index
```sql
CREATE VECTOR INDEX product_vindex
ON `my_dataset.product_embeddings`(embedding)
OPTIONS(distance_type = 'COSINE', index_type = 'IVF');
```

### 5.3 Performing `VECTOR_SEARCH`
```sql
SELECT
  query.query_text,
  base.product_id,
  base.description,
  distance
FROM VECTOR_SEARCH(
  TABLE `my_dataset.product_embeddings`,
  'embedding',
  (
    SELECT embedding, content AS query_text
    FROM AI.GENERATE_EMBEDDING(
      MODEL `my_dataset.text_embedding_model`,
      (SELECT 'ergonomic wireless mouse for travel' AS content)
    )
  ),
  top_k => 5,
  distance_type => 'COSINE'
);
```

---

## 6. Agent Decision Matrix & Heuristics

When designing queries or generating code:

| Goal / Requirement | Recommended Function | Reason |
|---|---|---|
| Need structured JSON/Struct output | `AI.GENERATE(..., output_schema => '...')` | Built-in JSON schema enforcement; type safety. |
| Multimodal input (GCS images, PDFs, audio) | `AI.GENERATE` + `OBJ.MAKE_REF` | Native integration with BigLake object references. |
| Fast filtering in `WHERE` / `JOIN` | `AI.IF` | Managed, cost-efficient, concise boolean logic. |
| Grouping/aggregating text clusters | `AI.CLASSIFY` or `AI.AGG` | Direct SQL grouping support without manual model outputs. |
| High-throughput bulk text processing | `AI.GENERATE_TEXT` / `AI.GENERATE` | Tunable batch parameters, temperature, token limits. |
| Semantic search / RAG | `AI.GENERATE_EMBEDDING` + `VECTOR_SEARCH` | Scalable approximate nearest neighbor (ANN) lookup. |

---

## 7. Operational Best Practices & Quotas

- **Region Alignment:** The BigQuery dataset and the Vertex AI connection/model endpoint must exist in the same multi-region or region (e.g., `US` to `US`, `europe-west4` to `europe-west4`).
- **Quota Modes:** When using high-volume inference, specify quota mode (`SHARED`, `DEDICATED`, or `UNSPECIFIED`) to avoid Vertex AI dynamic shared quota exhaustion.
- **Cost Management:**
  - Avoid using LLMs for deterministic text manipulations (use standard SQL regex, string functions).
  - Use smaller/faster models (`gemini-1.5-flash`) for classification and extraction; save larger models (`gemini-1.5-pro`) for nuanced synthesis.
  - Pre-filter datasets with traditional `WHERE` clauses before feeding records to generative AI functions.
