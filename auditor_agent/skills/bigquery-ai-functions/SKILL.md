---
name: bigquery-ai-functions
description: Use when calling Gemini, TimesFM, TabFM, or embedding models directly from BigQuery SQL via AI.* and ML.* functions. Covers text/structured generation, managed filtering/scoring/classification/aggregation, embeddings, semantic/hybrid search, zero-shot forecasting, anomaly detection, tabular prediction, and multimodal document processing.
---

# BigQuery AI Functions (`AI.*` and `ML.*`)

This skill provides a comprehensive decision framework and syntax reference for executing generative and zero-shot foundation models directly inside BigQuery SQL.

---

## 1. Quick Decision Matrix: Which Function to Use?

### A. Text & Structured Data Generation
| Goal | Recommended Function | Function Type | When to Use |
| :--- | :--- | :--- | :--- |
| **General text or multi-column extraction (Row-level)** | `AI.GENERATE` | Scalar (`STRUCT`) | **Default choice.** Use for free-form text generation, translation, or extracting multiple typed columns via `output_schema` in a `SELECT` clause. Supports End-User Credentials (EUC) with zero `CREATE MODEL` setup. |
| **Tabular extraction across a table** | `AI.GENERATE_TABLE` | Table-Valued (TVF) | Use when passing an entire table as input and returning a new table with custom schema columns appended. Requires a remote model (`CREATE MODEL`). |
| **Typed scalar generation (`BOOL`, `INT64`, `FLOAT64`)** | `AI.GENERATE_BOOL`<br>`AI.GENERATE_INT`<br>`AI.GENERATE_DOUBLE` | Scalar (`STRUCT`) | Use when you need a strictly typed primitive return value (e.g., boolean flag, integer count, float score) **and** require control over model endpoints, parameters, Provisioned Throughput, or error status inspection. |
| **Fine-tuned models or 3rd-party/Open models** | `AI.GENERATE_TEXT`<br>*(or `ML.GENERATE_TEXT`)* | Table-Valued (TVF) | Use when calling supervised fine-tuned Gemini models, open weights (Gemma, Llama), or partner models (Claude) deployed on Vertex AI endpoints. |

### B. Managed Semantic Operators (Streamlined SQL)
*Note: Managed functions (`AI.IF`, `AI.SCORE`, `AI.CLASSIFY`, `AI.AGG`) return direct scalar values (`BOOL`, `FLOAT64`, `STRING`) rather than `STRUCT` wrappers. BigQuery automatically manages prompt rewriting and model selection.*

| Goal | Recommended Function | Return Type | When to Use |
| :--- | :--- | :--- | :--- |
| **Semantic filtering & joins** | `AI.IF` | `BOOL` | Use inside `WHERE` or `JOIN ... ON` clauses to filter rows or join tables using natural language conditions across text or images. Supports `optimization_mode => 'MINIMIZE_COST'` (model distillation) for millions of rows. |
| **Semantic ranking & rating** | `AI.SCORE` | `FLOAT64` | Use inside `ORDER BY` or `SELECT` to rate rows on subjective criteria (e.g., "giftability", rubric adherence, sentiment severity) and extract Top-K items. |
| **Zero-shot categorization** | `AI.CLASSIFY` | `STRING` or `ARRAY<STRING>` | Use inside `SELECT` or `GROUP BY` to assign inputs into a predefined list of categories (or category descriptions). Supports `optimization_mode` for high-volume datasets. |
| **Multi-row synthesis & summarization** | `AI.AGG` | `STRING` | Aggregate function (works with `GROUP BY`). Use to summarize thousands of logs, reviews, or images across rows—automatically handling batching across LLM context window limits. |

### C. Embeddings, Similarity & Search
| Goal | Recommended Function | Function Type | When to Use |
| :--- | :--- | :--- | :--- |
| **Generate vector embeddings (Inline)** | `AI.EMBED` | Scalar (`STRUCT`) | **Default choice for embeddings.** Converts text or multimodal `ObjectRefRuntime` data into `ARRAY<FLOAT64>` vectors without requiring `CREATE MODEL` when using EUC. |
| **Generate vector embeddings (Batch TVF)** | `AI.GENERATE_EMBEDDING`<br>*(or `ML.GENERATE_EMBEDDING`)* | Table-Valued (TVF) | Use for batch pipelines over a table where a remote model object is already managed, or when using legacy PCA/Matrix Factorization models. |
| **Ad-hoc pairwise similarity** | `AI.SIMILARITY` | Scalar (`FLOAT64`) | Use for quick, ad-hoc comparisons between two strings or images. Computes embeddings and cosine similarity in one step (avoid on massive tables without pre-materializing embeddings). |
| **Corpus semantic / hybrid search (Explicit vectors)** | `VECTOR_SEARCH` | Table-Valued (TVF) | Use to search a pre-embedded base table (optionally backed by a Vector Index). Add `lexical_search_columns` to perform Reciprocal Rank Fusion (RRF) hybrid search. |
| **Corpus semantic / hybrid search (Autonomous embeddings)** | `AI.SEARCH` | Table-Valued (TVF) | Use on tables configured with **Autonomous Embedding Generation**. Takes raw string queries directly and supports `mode => 'HYBRID'`. |

### D. Zero-Shot Predictive & Driver Analytics (No Training Required)
| Goal | Recommended Function | Backing Model | When to Use |
| :--- | :--- | :--- | :--- |
| **Time-series forecasting** | `AI.FORECAST` | TimesFM (up to 3.0) | Use for zero-shot univariate or multivariate forecasting (with covariates) without running `CREATE MODEL ... ARIMA_PLUS`. |
| **Time-series anomaly detection** | `AI.DETECT_ANOMALIES` | TimesFM (up to 3.0) | Use to flag historical or streaming time-series anomalies with zero model training step. |
| **Time-series evaluation** | `AI.EVALUATE` | TimesFM | Use to compute error metrics (`MAE`, `RMSE`, `MAPE`) comparing zero-shot TimesFM forecasts against holdout actuals. |
| **Zero-shot tabular prediction** | `AI.PREDICT` | TabFM | Use for rapid prototyping of classification or regression over tabular data without training a Boosted Tree or Linear model. |
| **Metric root-cause / driver analysis** | `AI.KEY_DRIVERS` | Automated Driver Analysis | Use when asking *why* a metric changed or which dimensions/features drive an outcome, without setting up a formal `CONTRIBUTION_ANALYSIS` model. |

### E. Token Sizing & Document Processing
| Goal | Recommended Function | Function Type | When to Use |
| :--- | :--- | :--- | :--- |
| **Pre-flight token & cost estimation** | `AI.COUNT_TOKENS` | Scalar (`INT64`) | **Always run before large jobs.** Free pre-flight check to count input tokens before executing paid generative queries. |
| **Structured Document AI parsing** | `ML.PROCESS_DOCUMENT` | Table-Valued (TVF) | Use with a Document AI processor (Invoice, Expense, Layout parser) via an Object Table to extract specialized form fields. |

---

## 2. Decision Trade-offs: Managed vs. General-Purpose vs. BQML

1. **Managed Functions (`AI.IF` / `AI.SCORE` / `AI.CLASSIFY` / `AI.AGG`) vs. `AI.GENERATE*`:**
   - **Use Managed Functions** when you want clean SQL syntax, direct primitive outputs (no `.result` unwrapping), automatic prompt optimization, or `optimization_mode => 'MINIMIZE_COST'` (which distills a fast proxy model on a sample to process millions of rows cheaply).
   - **Drop down to `AI.GENERATE` / `AI.GENERATE_BOOL` / `AI.GENERATE_DOUBLE`** when you need to pin a specific Gemini model version, tune generation parameters (`temperature`, `thinking_budget`), use **Provisioned Throughput** (`request_type => 'DEDICATED'`), or inspect per-row API error statuses (`.status`).

2. **Zero-Shot (`AI.FORECAST`, `AI.PREDICT`) vs. Trained BQML (`ARIMA_PLUS`, `BOOSTED_TREE_*`):**
   - **Use `AI.FORECAST` / `AI.PREDICT`** for instant, zero-maintenance baselines, cold-start series, or multivariate forecasting with TimesFM 3.0.
   - **Use `CREATE MODEL` (BQML)** when you need deterministic reproducibility, explainable feature weights/coefficients, scheduled retraining pipelines, or ultra-low-latency serving over massive tabular datasets.

---

## 3. Canonical SQL Patterns

### Pattern 1: Multi-Task Structured Extraction (`AI.GENERATE`)
Use a single `AI.GENERATE` call with `output_schema` to perform multiple NLP tasks in one pass.
> **Gotcha:** Specifying `output_schema` replaces the `.result` field with your custom schema fields directly on the returned `STRUCT`.

```sql
SELECT
  article_id,
  ai_output.summary,
  ai_output.sentiment,
  ai_output.key_entities
FROM (
  SELECT
    article_id,
    AI.GENERATE(
      ('Analyze this article: ', body),
      output_schema => 'summary STRING, sentiment STRING, key_entities ARRAY<STRING>',
      endpoint => 'gemini-2.5-flash'
    ) AS ai_output
  FROM `my_project.my_dataset.articles`
  WHERE publish_date = CURRENT_DATE()
);
```

### Pattern 2: Semantic Filtering, Classification, Scoring & Aggregation (`AI.IF`, `AI.CLASSIFY`, `AI.SCORE`, `AI.AGG`)
Combine managed functions naturally within standard SQL clauses (`WHERE`, `GROUP BY`, `ORDER BY`).

```sql
SELECT
  AI.CLASSIFY(review_text, categories => ['Shipping', 'Product Quality', 'Billing', 'Other']) AS issue_category,
  COUNT(*) AS total_reviews,
  AVG(AI.SCORE((review_text, 'Rate customer frustration from 1 (calm) to 10 (extremely angry)'))) AS avg_frustration,
  AI.AGG((review_text, 'Summarize the top 3 actionable complaints in bullet points')) AS category_summary
FROM `my_project.my_dataset.customer_reviews`
WHERE AI.IF((review_text, 'Does this review describe a negative customer experience?'))
GROUP BY issue_category
ORDER BY avg_frustration DESC;
```

### Pattern 3: Multimodal Analysis with Cloud Storage (`ObjectRefRuntime`)
To pass images, PDFs, audio, or video from Cloud Storage into `AI.GENERATE`, `AI.IF`, or `AI.EMBED`, convert the URI into an `ObjectRef` and then wrap it with `OBJ.GET_ACCESS_URL`.

```sql
SELECT
  uri,
  AI.GENERATE(
    (
      'Extract the item name and detect if the packaging is damaged.',
      OBJ.GET_ACCESS_URL(OBJ.MAKE_REF(uri, 'my_project.us.gcs_connection'), 'r')
    ),
    output_schema => 'item_name STRING, is_damaged BOOL, damage_description STRING'
  ) AS inspection
FROM `my_project.my_dataset.shipment_photos`;
```

### Pattern 4: Embeddings & Hybrid Vector Search (`AI.EMBED` + `VECTOR_SEARCH`)
Generate embeddings inline with `AI.EMBED` and combine semantic search with lexical BM25 keyword matching via `lexical_search_columns`.

```sql
SELECT
  base.product_id,
  base.title,
  distance
FROM VECTOR_SEARCH(
  TABLE `my_project.my_dataset.product_catalog_embedded`,
  'embedding_col',
  (SELECT AI.EMBED('waterproof hiking jacket gore-tex', endpoint => 'text-embedding-005').result AS embedding),
  top_k => 20,
  lexical_search_columns => ['title', 'description', 'sku']
);
```

### Pattern 5: Zero-Shot Multivariate Forecasting (`AI.FORECAST` with TimesFM 3.0)
Forecast multiple related target metrics simultaneously alongside external covariates without training a model.

```sql
SELECT *
FROM AI.FORECAST(
  TABLE `my_project.my_dataset.daily_bike_demand`,
  data_col => 'subscriber_trips',
  timestamp_col => 'trip_date',
  id_cols => ['station_id'],
  horizon => 14,
  model => 'TimesFM 3.0'
);
```

---

## 4. Critical Operational Gotchas & Best Practices

1. **`LIMIT` Does Not Reduce Billed AI Execution:**
   - Applying `LIMIT 10` at the outer query level often evaluates the AI function across the entire table *before* slicing the output. Always filter or materialize your sample inside a CTE or subquery **before** invoking an `AI.*` function:
     ```sql
     WITH sample AS (SELECT * FROM `dataset.huge_table` LIMIT 10)
     SELECT AI.GENERATE(('Summarize: ', text)).result FROM sample;
     ```
2. **`output_schema` Removes `.result`:**
   - Without `output_schema`, `AI.GENERATE(prompt)` returns a `STRUCT<result STRING, full_response JSON, status STRING>`.
   - With `output_schema => 'a STRING, b INT64'`, the `.result` field disappears and is replaced directly by `.a` and `.b` (`STRUCT<a STRING, b INT64, full_response JSON, status STRING>`).
3. **`NULL` Propagation in `STRUCT` Prompts:**
   - Prompts passed as a tuple/struct—e.g., `('Summarize: ', title, ' - ', body)`—concatenate fields like `CONCAT()`. If **any** column inside the tuple is `NULL`, the entire prompt evaluates to `NULL` and the row is skipped. Always wrap nullable columns in `IFNULL(col, '')`.
4. **`ObjectRef` vs. `ObjectRefRuntime`:**
   - `OBJ.MAKE_REF()` produces an `ObjectRef`. AI functions require an `ObjectRefRuntime` containing a signed access URL, produced by `OBJ.GET_ACCESS_URL(ref, 'r')`. Do not persist `ObjectRefRuntime` values in tables—their signed URLs expire within 6 hours.
5. **Managing Row-Level Failures (`max_error_ratio`):**
   - Managed functions (`AI.IF`, `AI.SCORE`, `AI.CLASSIFY`) return `NULL` when an individual row fails or hits safety filters. By default, `max_error_ratio => 1.0` allows queries to succeed even with partial row failures. Set `max_error_ratio => 0.05` if you want the query job to fail loud when more than 5% of rows fail.
6. **Pre-Flight Token Costing:**
   - Before running an LLM query over hundreds of thousands of rows, run `SELECT SUM(AI.COUNT_TOKENS(prompt_col)) FROM ...` to calculate exact input token volume and avoid quota exhaustion or unexpected billing spikes.
7. **Pin Foundation Model Versions for Reproducibility:**
   - Default endpoints for `AI.GENERATE` and `AI.FORECAST` (`TimesFM`) upgrade periodically. Always explicitly pass `endpoint => '...'` or `model => 'TimesFM 3.0'` in production pipelines so model updates do not silently shift numerical outputs.