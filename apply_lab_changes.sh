#!/usr/bin/env bash
# ==============================================================================
# apply_lab_changes.sh
#
# Re-applies every change recorded in LAB_CONFIGURATION_CHANGES.md:
#   1. Code: PASSTHROUGH_ENV_VARS in the three agent deploy.py scripts
#   2. IAM bindings          3. Secret Manager     4. Cloud Storage
#   5. AlloyDB (cluster, instance, users, database, table)
#   6. BigQuery (datasets, connections, federated views)
#   7. Agent Engine deploy   8. Cloud Run frontend 9. Verification
#
# Safe to re-run: each step skips resources that already exist.
# Run from the repository root. Run a subset with: STEPS="1 5 6" ./apply_lab_changes.sh
# ==============================================================================
set -euo pipefail

export PROJECT_ID="${PROJECT_ID:-my-db-demos}"
export REGION="${REGION:-us-central1}"
export BQ_LOCATION="${BQ_LOCATION:-US}"
export OKF_BUCKET_NAME="${OKF_BUCKET_NAME:-${PROJECT_ID}-instructions91}"
export OKF_BUCKET_LOCATION="${OKF_BUCKET_LOCATION:-US}"
export GITHUB_SECRET_NAME="${GITHUB_SECRET_NAME:-github-pat}"
export GITHUB_PAT="${GITHUB_PAT:-ghp_PLACEHOLDER_REPLACE_ME}"
export ALLOYDB_REGION="${ALLOYDB_REGION:-${REGION}}"
export ALLOYDB_CLUSTER="${ALLOYDB_CLUSTER:-apex}"
export ALLOYDB_INSTANCE="${ALLOYDB_INSTANCE:-apex}"
export ALLOYDB_DATABASE="${ALLOYDB_DATABASE:-apex}"
export ALLOYDB_IP_TYPE="${ALLOYDB_IP_TYPE:-PUBLIC}"
# Hard-coded postgres password; must match ALLOYDB_PASSWORD in customer_agent/agent.py.
export ALLOYDB_PASSWORD="apex1234"
# enforce_complexity must stay on with a public IP; the minimums are lowered so apex1234 is accepted.
ALLOYDB_FLAGS="alloydb.iam_authentication=on,password.enforce_complexity=on,password.min_pass_length=8,password.min_uppercase_letters=0,password.min_lowercase_letters=0,password.min_numerical_chars=0,password.min_special_chars=0"
export FRONTEND_SERVICE="${FRONTEND_SERVICE:-experthub-frontend}"
STEPS="${STEPS:-1 2 3 4 5 6 7 8 9}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_ROOT}"
PYTHON="${REPO_ROOT}/.venv/bin/python"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
want() { [[ " ${STEPS} " == *" $1 "* ]]; }

gcloud config set project "${PROJECT_ID}" >/dev/null
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
export COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
export RE_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
export VERTEX_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com"
export BQ_CONN_SA="service-${PROJECT_NUMBER}@gcp-sa-bigqueryconnection.iam.gserviceaccount.com"
echo "Project: ${PROJECT_ID} (${PROJECT_NUMBER})  Region: ${REGION}  Bucket: ${OKF_BUCKET_NAME}"

grant() {  # grant <member> <role...>
  local member="$1"; shift
  for role in "$@"; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="${member}" --role="roles/${role}" --condition=None --quiet >/dev/null
    echo "  ${member} -> ${role}"
  done
}

alloydb_password() {
  echo -n "${ALLOYDB_PASSWORD}"
}

# ------------------------------------------------------------------------------
# 1. Code change: forward lab env vars from deploy.py to Agent Engine
# ------------------------------------------------------------------------------
if want 1; then
  log "1. Patching agent deploy.py scripts"
  PATCH_FILE="$(mktemp)"
  cat > "${PATCH_FILE}" <<'EOF_PATCH'
diff --git a/auditor_agent/deploy.py b/auditor_agent/deploy.py
index fd29a89..a702319 100755
--- a/auditor_agent/deploy.py
+++ b/auditor_agent/deploy.py
@@ -8,6 +8,19 @@ import sys
 from typing import Optional
 
 
+PASSTHROUGH_ENV_VARS = (
+    "BQ_LOCATION",
+    "OKF_BUCKET_NAME",
+    "OKF_BUCKET_LOCATION",
+    "GITHUB_SECRET_NAME",
+    "ALLOYDB_REGION",
+    "ALLOYDB_CLUSTER",
+    "ALLOYDB_INSTANCE",
+    "ALLOYDB_DATABASE",
+    "ALLOYDB_IP_TYPE",
+)
+
+
 def parse_args():
     parser = argparse.ArgumentParser(description="Deploy Auditor Agent to Vertex AI Agent Engine.")
     parser.add_argument(
@@ -82,19 +95,18 @@ def main():
 
     config_path = os.path.join(agent_dir, ".agent_engine_config.json")
     import json
+    env_vars = {
+        "GOOGLE_GENAI_USE_VERTEXAI": "true",
+        "VERTEX_AI_LOCATION": "global",
+        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
+        "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
+    }
+    # Forward per-project lab settings (bucket, AlloyDB target) when set in the shell.
+    for key in PASSTHROUGH_ENV_VARS:
+        if os.environ.get(key):
+            env_vars[key] = os.environ[key]
     with open(config_path, "w", encoding="utf-8") as f:
-        json.dump(
-            {
-                "env_vars": {
-                    "GOOGLE_GENAI_USE_VERTEXAI": "true",
-                    "VERTEX_AI_LOCATION": "global",
-                    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
-                    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
-                }
-            },
-            f,
-            indent=2,
-        )
+        json.dump({"env_vars": env_vars}, f, indent=2)
 
     adk_bin = os.path.join(agent_dir, "..", ".venv", "bin", "adk")
     if not os.path.exists(adk_bin):
diff --git a/customer_agent/deploy.py b/customer_agent/deploy.py
index d0f2cb7..d956dbb 100755
--- a/customer_agent/deploy.py
+++ b/customer_agent/deploy.py
@@ -8,6 +8,19 @@ import sys
 from typing import Optional
 
 
+PASSTHROUGH_ENV_VARS = (
+    "BQ_LOCATION",
+    "OKF_BUCKET_NAME",
+    "OKF_BUCKET_LOCATION",
+    "GITHUB_SECRET_NAME",
+    "ALLOYDB_REGION",
+    "ALLOYDB_CLUSTER",
+    "ALLOYDB_INSTANCE",
+    "ALLOYDB_DATABASE",
+    "ALLOYDB_IP_TYPE",
+)
+
+
 def parse_args():
     parser = argparse.ArgumentParser(description="Deploy Customer Simulator Agent to Vertex AI Agent Engine.")
     parser.add_argument(
@@ -90,19 +103,18 @@ def main():
 
     config_path = os.path.join(agent_dir, ".agent_engine_config.json")
     import json
+    env_vars = {
+        "GOOGLE_GENAI_USE_VERTEXAI": "true",
+        "VERTEX_AI_LOCATION": "global",
+        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
+        "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
+    }
+    # Forward per-project lab settings (bucket, AlloyDB target) when set in the shell.
+    for key in PASSTHROUGH_ENV_VARS:
+        if os.environ.get(key):
+            env_vars[key] = os.environ[key]
     with open(config_path, "w", encoding="utf-8") as f:
-        json.dump(
-            {
-                "env_vars": {
-                    "GOOGLE_GENAI_USE_VERTEXAI": "true",
-                    "VERTEX_AI_LOCATION": "global",
-                    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
-                    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
-                }
-            },
-            f,
-            indent=2,
-        )
+        json.dump({"env_vars": env_vars}, f, indent=2)
 
     adk_bin = os.path.join(agent_dir, "..", ".venv", "bin", "adk")
     if not os.path.exists(adk_bin):
diff --git a/customer_service_agent/deploy.py b/customer_service_agent/deploy.py
index 4631282..dfed2fc 100755
--- a/customer_service_agent/deploy.py
+++ b/customer_service_agent/deploy.py
@@ -8,6 +8,19 @@ import sys
 from typing import Optional
 
 
+PASSTHROUGH_ENV_VARS = (
+    "BQ_LOCATION",
+    "OKF_BUCKET_NAME",
+    "OKF_BUCKET_LOCATION",
+    "GITHUB_SECRET_NAME",
+    "ALLOYDB_REGION",
+    "ALLOYDB_CLUSTER",
+    "ALLOYDB_INSTANCE",
+    "ALLOYDB_DATABASE",
+    "ALLOYDB_IP_TYPE",
+)
+
+
 def parse_args():
     parser = argparse.ArgumentParser(description="Deploy Customer Service Agent to Vertex AI Agent Engine.")
     parser.add_argument(
@@ -82,19 +95,18 @@ def main():
 
     config_path = os.path.join(agent_dir, ".agent_engine_config.json")
     import json
+    env_vars = {
+        "GOOGLE_GENAI_USE_VERTEXAI": "true",
+        "VERTEX_AI_LOCATION": "global",
+        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
+        "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
+    }
+    # Forward per-project lab settings (bucket, AlloyDB target) when set in the shell.
+    for key in PASSTHROUGH_ENV_VARS:
+        if os.environ.get(key):
+            env_vars[key] = os.environ[key]
     with open(config_path, "w", encoding="utf-8") as f:
-        json.dump(
-            {
-                "env_vars": {
-                    "GOOGLE_GENAI_USE_VERTEXAI": "true",
-                    "VERTEX_AI_LOCATION": "global",
-                    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
-                    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
-                }
-            },
-            f,
-            indent=2,
-        )
+        json.dump({"env_vars": env_vars}, f, indent=2)
 
     # Check for required ADK binary
     adk_bin = os.path.join(agent_dir, "..", ".venv", "bin", "adk")
EOF_PATCH
  if git apply --check "${PATCH_FILE}" 2>/dev/null; then
    git apply "${PATCH_FILE}"
    echo "  Patch applied."
  elif git apply --reverse --check "${PATCH_FILE}" 2>/dev/null; then
    echo "  Already applied, skipping."
  else
    echo "  ERROR: patch does not apply cleanly; deploy.py files differ from expected." >&2
    exit 1
  fi
  rm -f "${PATCH_FILE}"
fi

# ------------------------------------------------------------------------------
# 2. IAM (project level)
# ------------------------------------------------------------------------------
if want 2; then
  log "2. IAM bindings"
  gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}" >/dev/null 2>&1 || true
  gcloud beta services identity create --service=bigqueryconnection.googleapis.com --project="${PROJECT_ID}" >/dev/null 2>&1 || true

  grant "serviceAccount:${COMPUTE_SA}" \
    secretmanager.secretAccessor bigquery.dataEditor bigquery.jobUser aiplatform.user \
    alloydb.client alloydb.databaseUser storage.objectAdmin \
    run.admin run.invoker iam.serviceAccountUser cloudbuild.builds.editor \
    artifactregistry.admin logging.logWriter
  grant "serviceAccount:${RE_SA}" \
    bigquery.dataEditor bigquery.jobUser aiplatform.user secretmanager.secretAccessor \
    alloydb.client alloydb.databaseUser storage.objectAdmin
  grant "serviceAccount:${VERTEX_SA}" alloydb.client alloydb.databaseUser
  grant "serviceAccount:${BQ_CONN_SA}" alloydb.client
  # The BigQuery 'gemini' connection SA is granted aiplatform.user in step 6.
fi

# ------------------------------------------------------------------------------
# 3. Secret Manager
# ------------------------------------------------------------------------------
if want 3; then
  log "3. Secrets"
  if ! gcloud secrets describe "${GITHUB_SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo -n "${GITHUB_PAT}" | gcloud secrets create "${GITHUB_SECRET_NAME}" \
      --data-file=- --replication-policy=automatic --project="${PROJECT_ID}"
  else
    echo "  ${GITHUB_SECRET_NAME} exists."
  fi

  gcloud secrets add-iam-policy-binding "${GITHUB_SECRET_NAME}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${COMPUTE_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null
fi

# ------------------------------------------------------------------------------
# 4. Cloud Storage bucket for OKF dynamic context
# ------------------------------------------------------------------------------
if want 4; then
  log "4. Bucket gs://${OKF_BUCKET_NAME}"
  if ! gcloud storage buckets describe "gs://${OKF_BUCKET_NAME}" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${OKF_BUCKET_NAME}" --project="${PROJECT_ID}" \
      --location="${OKF_BUCKET_LOCATION}" --uniform-bucket-level-access
  else
    echo "  Bucket exists."
  fi
  for sa in "${COMPUTE_SA}" "${RE_SA}"; do
    gcloud storage buckets add-iam-policy-binding "gs://${OKF_BUCKET_NAME}" \
      --member="serviceAccount:${sa}" --role="roles/storage.objectAdmin" >/dev/null
  done
fi

# ------------------------------------------------------------------------------
# 5. AlloyDB
# ------------------------------------------------------------------------------
if want 5; then
  log "5. AlloyDB ${ALLOYDB_CLUSTER}/${ALLOYDB_INSTANCE}"
  if ! gcloud alloydb clusters describe "${ALLOYDB_CLUSTER}" --region="${ALLOYDB_REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud alloydb clusters create "${ALLOYDB_CLUSTER}" --region="${ALLOYDB_REGION}" \
      --password="$(alloydb_password)" --enable-private-service-connect --project="${PROJECT_ID}"
  else
    echo "  Cluster exists."
  fi

  if ! gcloud alloydb instances describe "${ALLOYDB_INSTANCE}" --cluster="${ALLOYDB_CLUSTER}" --region="${ALLOYDB_REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    # Public IP with no authorized networks: only the AlloyDB connector (mTLS + IAM) can connect.
    gcloud alloydb instances create "${ALLOYDB_INSTANCE}" --cluster="${ALLOYDB_CLUSTER}" \
      --region="${ALLOYDB_REGION}" --instance-type=PRIMARY --cpu-count=2 \
      --allowed-psc-projects="${PROJECT_NUMBER}" \
      --assign-inbound-public-ip=ASSIGN_IPV4 \
      --database-flags="${ALLOYDB_FLAGS}" \
      --ssl-mode=ENCRYPTED_ONLY --project="${PROJECT_ID}"
  elif ! gcloud alloydb instances describe "${ALLOYDB_INSTANCE}" --cluster="${ALLOYDB_CLUSTER}" \
       --region="${ALLOYDB_REGION}" --project="${PROJECT_ID}" --format='json(databaseFlags)' \
       | grep -q '"password.min_uppercase_letters": "0"'; then
    echo "  Instance exists; relaxing password complexity minimums (instance restarts)."
    gcloud alloydb instances update "${ALLOYDB_INSTANCE}" --cluster="${ALLOYDB_CLUSTER}" \
      --region="${ALLOYDB_REGION}" --database-flags="${ALLOYDB_FLAGS}" --project="${PROJECT_ID}"
  else
    echo "  Instance exists."
  fi

  # Set the built-in postgres user's password to the hard-coded value used by the agents.
  gcloud alloydb users set-password postgres --cluster="${ALLOYDB_CLUSTER}" \
    --region="${ALLOYDB_REGION}" --password="$(alloydb_password)" --project="${PROJECT_ID}" >/dev/null

  IAM_DB_USER="${COMPUTE_SA%.gserviceaccount.com}"
  if ! gcloud alloydb users list --cluster="${ALLOYDB_CLUSTER}" --region="${ALLOYDB_REGION}" \
       --project="${PROJECT_ID}" --format='value(name)' | grep -q "/users/${IAM_DB_USER}\$"; then
    gcloud alloydb users create "${IAM_DB_USER}" --cluster="${ALLOYDB_CLUSTER}" \
      --region="${ALLOYDB_REGION}" --type=IAM_BASED --db-roles=alloydbsuperuser --project="${PROJECT_ID}"
  else
    echo "  IAM user ${IAM_DB_USER} exists."
  fi

  # Database + table, created through the AlloyDB Python connector as postgres.
  [[ -x "${PYTHON}" ]] || { echo "ERROR: ${PYTHON} not found. Create .venv and install frontend/requirements.txt." >&2; exit 1; }
  ALLOYDB_PASSWORD="$(alloydb_password)" "${PYTHON}" -I - <<'EOF_PY'
import os
from google.cloud.alloydb.connector import Connector, IPTypes

uri = "projects/{}/locations/{}/clusters/{}/instances/{}".format(
    os.environ["PROJECT_ID"], os.environ["ALLOYDB_REGION"],
    os.environ["ALLOYDB_CLUSTER"], os.environ["ALLOYDB_INSTANCE"])
db_name = os.environ["ALLOYDB_DATABASE"]
ip_type = IPTypes[os.environ["ALLOYDB_IP_TYPE"]]

with Connector() as connector:
    def connect(db):
        return connector.connect(uri, "pg8000", user="postgres",
                                 password=os.environ["ALLOYDB_PASSWORD"], db=db, ip_type=ip_type)

    conn = connect("postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    if cur.fetchone():
        print(f"  Database {db_name} exists.")
    else:
        cur.execute(f'CREATE DATABASE "{db_name}"')
        print(f"  Database {db_name} created.")
    conn.close()

    conn = connect(db_name)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customer_ratings (
            customer_id BIGINT NOT NULL,
            customer_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            description TEXT NOT NULL,
            timestamp TIMESTAMPTZ
        )""")
    cur.execute("GRANT ALL PRIVILEGES ON SCHEMA public TO PUBLIC")
    cur.execute("GRANT ALL PRIVILEGES ON TABLE customer_ratings TO PUBLIC")
    conn.close()
    print("  Table customer_ratings ready.")
EOF_PY
fi

# ------------------------------------------------------------------------------
# 6. BigQuery
# ------------------------------------------------------------------------------
if want 6; then
  log "6. BigQuery"
  for ds in demo agent_telemetry; do
    if ! bq show --project_id="${PROJECT_ID}" "${PROJECT_ID}:${ds}" >/dev/null 2>&1; then
      bq mk -d --location="${BQ_LOCATION}" --project_id="${PROJECT_ID}" "${ds}"
    else
      echo "  Dataset ${ds} exists."
    fi
  done

  if ! bq show --connection --location="${BQ_LOCATION}" "${PROJECT_ID}.${BQ_LOCATION}.gemini" >/dev/null 2>&1; then
    bq mk --connection --location="${BQ_LOCATION}" --project_id="${PROJECT_ID}" \
      --connection_type=CLOUD_RESOURCE gemini
  else
    echo "  Connection gemini exists."
  fi
  BQ_VERTEX_SA="$(bq show --format=prettyjson --connection --location="${BQ_LOCATION}" \
    "${PROJECT_ID}.${BQ_LOCATION}.gemini" | grep 'serviceAccountId' | head -1 | cut -d '"' -f 4)"
  grant "serviceAccount:${BQ_VERTEX_SA}" aiplatform.user

  # Recreate so the stored postgres password always matches ALLOYDB_PASSWORD.
  if bq show --connection --location="${BQ_LOCATION}" "${PROJECT_ID}.${BQ_LOCATION}.alloydb" >/dev/null 2>&1; then
    bq rm -f --connection "${PROJECT_ID}.${BQ_LOCATION}.alloydb"
  fi
  ALLOYDB_RESOURCE="//alloydb.googleapis.com/projects/${PROJECT_ID}/locations/${ALLOYDB_REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ALLOYDB_INSTANCE}"
  BODY="$(ALLOYDB_RESOURCE="${ALLOYDB_RESOURCE}" ALLOYDB_PASSWORD="$(alloydb_password)" python3 -I -c '
import json, os
print(json.dumps({"friendlyName": "alloydb", "configuration": {
  "connectorId": "google-alloydb",
  "asset": {"googleCloudResource": os.environ["ALLOYDB_RESOURCE"], "database": os.environ["ALLOYDB_DATABASE"]},
  "authentication": {"usernamePassword": {"username": "postgres",
                                          "password": {"plaintext": os.environ["ALLOYDB_PASSWORD"]}}}}}))')"
  curl -sf -X POST \
    "https://bigqueryconnection.googleapis.com/v1/projects/${PROJECT_ID}/locations/${BQ_LOCATION}/connections?connectionId=alloydb" \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "Content-Type: application/json" -d "${BODY}" >/dev/null
  unset BODY
  echo "  Connection alloydb created."

  VIEW_SQL="SELECT * FROM EXTERNAL_QUERY(\"projects/${PROJECT_ID}/locations/${BQ_LOCATION}/connections/alloydb\", \"SELECT * FROM customer_ratings;\")"
  for view in customer_ratings customer_reviews; do
    if ! bq show --project_id="${PROJECT_ID}" "${PROJECT_ID}:demo.${view}" >/dev/null 2>&1; then
      bq mk --use_legacy_sql=false --view="${VIEW_SQL}" --project_id="${PROJECT_ID}" "demo.${view}"
    else
      echo "  View demo.${view} exists."
    fi
  done
fi

# ------------------------------------------------------------------------------
# 7. Vertex AI Agent Engine (deploy.py forwards the exported lab env vars)
# ------------------------------------------------------------------------------
if want 7; then
  log "7. Deploying agents to Agent Engine"
  # Note: each run creates new Reasoning Engines; delete old ones (see section 11 of the doc).
  for agent in customer_service_agent customer_agent auditor_agent; do
    "${PYTHON}" "${agent}/deploy.py" --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud
  done
fi

# ------------------------------------------------------------------------------
# 8. Cloud Run frontend
# ------------------------------------------------------------------------------
if want 8; then
  log "8. Deploying Cloud Run frontend"
  gcloud run deploy "${FRONTEND_SERVICE}" --source . --region="${REGION}" --project="${PROJECT_ID}" \
    --service-account="${COMPUTE_SA}" \
    --no-invoker-iam-check --port=8080 --cpu=1 --memory=512Mi --timeout=300s \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCP_REGION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global,VERTEX_AI_LOCATION=global,BQ_LOCATION=${BQ_LOCATION},OKF_BUCKET_NAME=${OKF_BUCKET_NAME},OKF_BUCKET_LOCATION=${OKF_BUCKET_LOCATION},GITHUB_SECRET_NAME=${GITHUB_SECRET_NAME},ALLOYDB_REGION=${ALLOYDB_REGION},ALLOYDB_CLUSTER=${ALLOYDB_CLUSTER},ALLOYDB_INSTANCE=${ALLOYDB_INSTANCE},ALLOYDB_DATABASE=${ALLOYDB_DATABASE},ALLOYDB_IP_TYPE=${ALLOYDB_IP_TYPE}"
fi

# ------------------------------------------------------------------------------
# 9. Verification
# ------------------------------------------------------------------------------
if want 9; then
  log "9. Verification"
  bq query --use_legacy_sql=false --project_id="${PROJECT_ID}" --format=pretty \
    'SELECT COUNT(*) AS rows_in_alloydb FROM demo.customer_ratings'
  URL="$(gcloud run services describe "${FRONTEND_SERVICE}" --region="${REGION}" \
    --project="${PROJECT_ID}" --format='value(status.url)' 2>/dev/null || true)"
  if [[ -n "${URL}" ]]; then
    for path in /health / /api/agent/instructions /api/customer-analysis/dashboard; do
      printf '  %-36s HTTP %s\n' "${path}" "$(curl -s -o /dev/null -w '%{http_code}' "${URL}${path}")"
    done
    echo "  Frontend: ${URL}"
  else
    echo "  Frontend service ${FRONTEND_SERVICE} not found."
  fi
fi

log "Done."
