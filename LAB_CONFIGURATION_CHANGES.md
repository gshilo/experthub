# ExpertHub LAB – Configuration Changes

Record of every change made to deploy the full ExpertHub solution (AlloyDB, BigQuery,
Agent Engine agents, Cloud Run frontend) into the lab project. Executed on 2026-11-12
with the gcloud path from `deploy_all.sh` (Terraform is not installed in this environment).

| Item | Value |
|---|---|
| Project ID | `my-db-demos` |
| Project number | `596582393106` |
| Region | `us-central1` |
| BigQuery location | `US` |
| Runtime service account | `596582393106-compute@developer.gserviceaccount.com` (Compute default SA) |
| Frontend URL | https://experthub-frontend-596582393106.us-central1.run.app |

---

## 1. Differences from the defaults in the repo

The repo defaults target project `experthub-510907`. These values had to change for the lab:

| Setting | Repo default | Lab value | Why |
|---|---|---|---|
| Project | `experthub-510907` | `my-db-demos` | Lab project (gcloud default). Passed via `GOOGLE_CLOUD_PROJECT`. |
| `OKF_BUCKET_NAME` | `instructions91` | `my-db-demos-instructions91` | `instructions91` is a globally-unique bucket name already owned by another project. |
| AlloyDB password | `ChangeMeAlloyDB123!` | random, stored in Secret Manager `alloydb-postgres-password` | `password.enforce_complexity=on` and no plain-text passwords in the repo. |
| `agent_telemetry` dataset | expected to exist | created explicitly | Dataset was missing in the lab project. |

---

## 2. Code change

### `customer_service_agent/deploy.py`, `customer_agent/deploy.py`, `auditor_agent/deploy.py`

Each script rewrote `.agent_engine_config.json` with a fixed set of env vars, so deployed agents
always fell back to bucket `instructions91` and the default AlloyDB target. Added a
`PASSTHROUGH_ENV_VARS` tuple; any of these that are set in the shell are forwarded to Agent Engine:

```
BQ_LOCATION, OKF_BUCKET_NAME, OKF_BUCKET_LOCATION, GITHUB_SECRET_NAME,
ALLOYDB_REGION, ALLOYDB_CLUSTER, ALLOYDB_INSTANCE, ALLOYDB_DATABASE, ALLOYDB_IP_TYPE
```

Behaviour is unchanged when none of them are set. Running the deploy scripts also regenerates
the three `.agent_engine_config.json` files with the forwarded values.

---

## 3. IAM (project level)

| Member | Roles added |
|---|---|
| `596582393106-compute@developer.gserviceaccount.com` | `secretmanager.secretAccessor`, `bigquery.dataEditor`, `bigquery.jobUser`, `alloydb.client`, `alloydb.databaseUser`, `storage.objectAdmin` |
| `service-596582393106@gcp-sa-aiplatform-re.iam.gserviceaccount.com` (Reasoning Engine agent) | `bigquery.dataEditor`, `bigquery.jobUser`, `aiplatform.user`, `secretmanager.secretAccessor`, `alloydb.client`, `alloydb.databaseUser`, `storage.objectAdmin` |
| `service-596582393106@gcp-sa-aiplatform.iam.gserviceaccount.com` (Vertex AI agent) | `alloydb.client`, `alloydb.databaseUser` |
| `bqcx-596582393106-szha@gcp-sa-bigquery-condel.iam.gserviceaccount.com` (BQ `gemini` connection SA) | `aiplatform.user` |

Already present and left as is: the Compute SA's `aiplatform.user`, `run.admin`, `run.invoker`,
`iam.serviceAccountUser`, `cloudbuild.builds.editor`, `artifactregistry.admin`, `logging.logWriter`
and the BigQuery Connection service agent's `alloydb.client`. All required APIs were already enabled.

---

## 4. Secret Manager

| Secret | Content | Accessor |
|---|---|---|
| `github-pat` | Placeholder `ghp_PLACEHOLDER_REPLACE_ME` | Compute SA |
| `alloydb-postgres-password` | Password of AlloyDB user `postgres` | Compute SA |

Replace the GitHub PAT when you want the auditor to commit OKF rules to GitHub:

```bash
echo -n "ghp_your_real_token" | gcloud secrets versions add github-pat --data-file=- --project=my-db-demos
```

Read the AlloyDB password:

```bash
gcloud secrets versions access latest --secret=alloydb-postgres-password --project=my-db-demos
```

---

## 5. Cloud Storage

| Bucket | Location | Access |
|---|---|---|
| `gs://my-db-demos-instructions91` | `US`, uniform bucket-level access | `storage.objectAdmin` for the Compute SA and the Reasoning Engine agent |

Holds `dynamic_context.md` (OKF rules written by the auditor and read by the customer service agent).

---

## 6. AlloyDB

### Cluster and instance

```bash
gcloud alloydb clusters create apex --region=us-central1 \
  --password="<from secret alloydb-postgres-password>" \
  --enable-private-service-connect --project=my-db-demos

gcloud alloydb instances create apex --cluster=apex --region=us-central1 \
  --instance-type=PRIMARY --cpu-count=2 \
  --allowed-psc-projects=596582393106 \
  --assign-inbound-public-ip=ASSIGN_IPV4 \
  --database-flags="alloydb.iam_authentication=on,password.enforce_complexity=on" \
  --ssl-mode=ENCRYPTED_ONLY --project=my-db-demos
```

| Setting | Value |
|---|---|
| Cluster / instance | `apex` / `apex` (PRIMARY, 2 vCPU, PostgreSQL 18) |
| Connectivity | PSC enabled + public IP `35.223.58.38`, **no authorized networks** (connector-only: mTLS + IAM) |
| Flags | `alloydb.iam_authentication=on`, `password.enforce_complexity=on` |
| SSL | `ENCRYPTED_ONLY` |

### Database users

| User | Type | Roles | Used by |
|---|---|---|---|
| `postgres` | Built-in | `alloydbsuperuser` | Admin / AlloyDB Studio / BigQuery `alloydb` connection |
| `596582393106-compute@developer` | IAM (service account) | `alloydbsuperuser` | Cloud Run frontend and in-process agents |

### Database objects (database `apex`)

```sql
CREATE DATABASE apex;

CREATE TABLE IF NOT EXISTS customer_ratings (
    customer_id BIGINT NOT NULL,
    customer_name TEXT NOT NULL,
    rating INTEGER NOT NULL,
    description TEXT NOT NULL,
    timestamp TIMESTAMPTZ
);
GRANT ALL PRIVILEGES ON SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON TABLE customer_ratings TO PUBLIC;
```

The table is owned by `postgres`; the IAM user writes through the `PUBLIC` grant.

---

## 7. BigQuery

| Object | Details |
|---|---|
| Dataset `demo` | `US` |
| Dataset `agent_telemetry` | `US`. Table `agent_events` and the `v_*` views are created by `BigQueryAgentAnalyticsPlugin` on the first agent run. |
| Connection `gemini` | `CLOUD_RESOURCE`, `US`. SA granted `aiplatform.user` (used by `AI.GENERATE`). |
| Connection `alloydb` | `google-alloydb` connector → `apex/apex`, database `apex`, user `postgres` |
| View `demo.customer_ratings` | `EXTERNAL_QUERY(alloydb, "SELECT * FROM customer_ratings;")` |
| View `demo.customer_reviews` | Same query as `demo.customer_ratings` |

---

## 8. Vertex AI Agent Engine

Deployed with the lab env vars exported (see section 2):

```bash
export GOOGLE_CLOUD_PROJECT=my-db-demos BQ_LOCATION=US \
  OKF_BUCKET_NAME=my-db-demos-instructions91 OKF_BUCKET_LOCATION=US GITHUB_SECRET_NAME=github-pat \
  ALLOYDB_REGION=us-central1 ALLOYDB_CLUSTER=apex ALLOYDB_INSTANCE=apex ALLOYDB_DATABASE=apex ALLOYDB_IP_TYPE=PUBLIC
python customer_service_agent/deploy.py --project=my-db-demos --region=us-central1 --otel_to_cloud
python customer_agent/deploy.py         --project=my-db-demos --region=us-central1 --otel_to_cloud
python auditor_agent/deploy.py          --project=my-db-demos --region=us-central1 --otel_to_cloud
```

| Agent | Reasoning Engine ID |
|---|---|
| `customer_service_agent` | `98218549075509248` |
| `customer_agent` | `8679264689076568064` |
| `auditor_agent` | `1032152521801465856` |

The Cloud Run frontend runs the same agent code in-process; these engines are for the
Agent Engine console / playground and telemetry.

---

## 9. Cloud Run frontend

```bash
gcloud run deploy experthub-frontend --source . --region=us-central1 --project=my-db-demos \
  --service-account=596582393106-compute@developer.gserviceaccount.com \
  --no-invoker-iam-check --port=8080 --cpu=1 --memory=512Mi --timeout=300s \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=my-db-demos,GCP_REGION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global,VERTEX_AI_LOCATION=global,BQ_LOCATION=US,OKF_BUCKET_NAME=my-db-demos-instructions91,OKF_BUCKET_LOCATION=US,GITHUB_SECRET_NAME=github-pat,ALLOYDB_REGION=us-central1,ALLOYDB_CLUSTER=apex,ALLOYDB_INSTANCE=apex,ALLOYDB_DATABASE=apex,ALLOYDB_IP_TYPE=PUBLIC"
```

- Service: `experthub-frontend`, image in the existing Artifact Registry repo `cloud-run-source-deploy`.
- Public access via `--no-invoker-iam-check` (no `allUsers` binding).
- URL: https://experthub-frontend-596582393106.us-central1.run.app

---

## 10. Verification performed

| Check | Result |
|---|---|
| `bq query 'SELECT COUNT(*) FROM demo.customer_ratings'` (BigQuery → AlloyDB federation) | OK (0 rows, new table) |
| `GET /health` | `healthy` |
| `GET /` (UI) | HTTP 200 |
| `GET /api/agent/instructions` | HTTP 200 |
| `GET /api/customer-analysis/dashboard` (BigQuery + `AI.GENERATE`) | HTTP 200 |
| Cloud Run logs, severity ≥ ERROR, after deploy | none |
| End-to-end conversation → rating row in AlloyDB | not run; left for manual testing |

After a conversation finishes, the rating should show **"saved to AlloyDB"** in the UI and appear in:

```bash
bq query --use_legacy_sql=false --project_id=my-db-demos 'SELECT * FROM demo.customer_ratings ORDER BY timestamp DESC LIMIT 5'
```

---

## 11. Cleanup

```bash
P=my-db-demos
gcloud run services delete experthub-frontend --region=us-central1 --project=$P --quiet
for id in 98218549075509248 8679264689076568064 1032152521801465856; do
  curl -s -X DELETE -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    "https://us-central1-aiplatform.googleapis.com/v1/projects/$P/locations/us-central1/reasoningEngines/$id?force=true"
done
bq rm -r -f -d $P:demo; bq rm -r -f -d $P:agent_telemetry
bq rm -f --connection $P.US.gemini; bq rm -f --connection $P.US.alloydb
gcloud alloydb clusters delete apex --region=us-central1 --force --project=$P --quiet
gcloud secrets delete github-pat --project=$P --quiet
gcloud secrets delete alloydb-postgres-password --project=$P --quiet
gcloud storage rm -r gs://my-db-demos-instructions91
# then remove the IAM bindings listed in section 3 with gcloud projects remove-iam-policy-binding
```
