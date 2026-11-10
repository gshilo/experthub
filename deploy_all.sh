#!/usr/bin/env bash
# ==============================================================================
# deploy_all.sh - Step-by-Step Student Deployment Guide for Google Cloud Shell
# ==============================================================================
# This file is structured so students can copy and paste commands ONE AT A TIME
# directly into Google Cloud Shell (or terminal).
#
# No complicated bash loops, no subshell forks, and no nested heredocs.
# ==============================================================================

# If invoked as a script with a step argument (e.g. ./deploy_all.sh step3 or ./deploy_all.sh 3),
# jump directly to that step.
if [[ -n "${1:-}" ]]; then
  STEP_ARG="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
  case "${STEP_ARG}" in
    3|step3|step_3|"step 3")
      echo "=== Executing STEP 3: Configure IAM Permissions ==="
      export PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
      export PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')}"
      export COMPUTE_SA="${COMPUTE_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
      export RE_SA="${RE_SA:-service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com}"
      export VERTEX_SA="${VERTEX_SA:-service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com}"
      export BQ_CONN_SA="${BQ_CONN_SA:-service-${PROJECT_NUMBER}@gcp-sa-bigqueryconnection.iam.gserviceaccount.com}"

      echo "Project ID: ${PROJECT_ID}"
      echo "Project Number: ${PROJECT_NUMBER}"
      echo "Granting IAM roles to Compute Service Account: ${COMPUTE_SA}..."
      for role in \
        "roles/secretmanager.secretAccessor" \
        "roles/bigquery.dataEditor" \
        "roles/bigquery.jobUser" \
        "roles/aiplatform.user" \
        "roles/alloydb.client" \
        "roles/alloydb.databaseUser" \
        "roles/run.admin" \
        "roles/run.invoker" \
        "roles/iam.serviceAccountUser" \
        "roles/cloudbuild.builds.editor" \
        "roles/artifactregistry.admin" \
        "roles/logging.logWriter" \
        "roles/storage.objectAdmin"; do
        gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="${role}" --quiet
      done

      echo "Initializing Vertex AI Reasoning Engine service agent..."
      gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}"
      sleep 10

      echo "Granting IAM roles to Reasoning Engine Service Agent: ${RE_SA}..."
      for role in \
        "roles/bigquery.dataEditor" \
        "roles/bigquery.jobUser" \
        "roles/aiplatform.user" \
        "roles/secretmanager.secretAccessor" \
        "roles/alloydb.client" \
        "roles/alloydb.databaseUser" \
        "roles/storage.objectAdmin"; do
        gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="${role}" --quiet
      done

      echo "Granting IAM roles to Vertex AI Service Agent: ${VERTEX_SA}..."
      for role in \
        "roles/alloydb.client" \
        "roles/alloydb.databaseUser"; do
        gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${VERTEX_SA}" --role="${role}" --quiet
      done

      echo "Initializing BigQuery Connection service agent..."
      gcloud beta services identity create --service=bigqueryconnection.googleapis.com --project="${PROJECT_ID}"
      sleep 10

      echo "Granting IAM roles to BigQuery Connection Service Agent: ${BQ_CONN_SA}..."
      gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${BQ_CONN_SA}" --role="roles/alloydb.client" --quiet

      echo "[SUCCESS] Step 3 completed successfully without issues."
      exit 0
      ;;
    9|step9|step_9|"step 9")
      echo "=== Executing STEP 9: Build and Deploy Frontend Web App to Cloud Run ==="
      export PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
      export PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')}"
      export COMPUTE_SA="${COMPUTE_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
      export REGION="${REGION:-us-central1}"
      export BQ_LOCATION="${BQ_LOCATION:-US}"
      export FRONTEND_SERVICE="${FRONTEND_SERVICE:-experthub-frontend}"
      export OKF_BUCKET_NAME="${OKF_BUCKET_NAME:-instructions91}"
      export OKF_BUCKET_LOCATION="${OKF_BUCKET_LOCATION:-US}"

      echo "Project ID: ${PROJECT_ID}"
      echo "Deploying Cloud Run service: ${FRONTEND_SERVICE} in region: ${REGION}..."
      gcloud run deploy "${FRONTEND_SERVICE}" \
        --source . \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --service-account="${COMPUTE_SA}" \
        --allow-unauthenticated \
        --port=8080 \
        --cpu=1 \
        --memory=512Mi \
        --timeout=300s \
        --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCP_REGION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global,BQ_LOCATION=${BQ_LOCATION},OKF_BUCKET_NAME=${OKF_BUCKET_NAME},OKF_BUCKET_LOCATION=${OKF_BUCKET_LOCATION},GITHUB_SECRET_NAME=github-pat" \
        --quiet

      FRONTEND_URL="$(gcloud run services describe "${FRONTEND_SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)")"
      echo "[SUCCESS] Step 9 completed successfully without issues."
      echo "Deployed Service URL: ${FRONTEND_URL}"
      exit 0
      ;;
    *)
      echo "Unknown step argument: $1"
      echo "Usage to run a specific step: ./deploy_all.sh step3 (or copy and paste steps sequentially)"
      exit 1
      ;;
  esac
fi


# ==============================================================================
# STEP 0: Set Your Environment Variables
# ==============================================================================
# Copy and run these export commands. Replace the placeholder values with your
# own project ID, passwords, and tokens.

export PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
# If PROJECT_ID is empty above, set it explicitly:
# export PROJECT_ID="your-gcp-project-id"

export REGION="us-central1"
export BQ_LOCATION="US"
export ALLOYDB_PASSWORD="ChangeMeAlloyDB123!"
export GITHUB_PAT="ghp_..."

export ALLOYDB_CLUSTER="apex"
export ALLOYDB_INSTANCE="apex"
export ALLOYDB_DATABASE="apex"
export ARTIFACT_REPO="experthub-repo"
export FRONTEND_SERVICE="experthub-frontend"
export OKF_BUCKET_NAME="instructions91"
export OKF_BUCKET_LOCATION="US"


# ==============================================================================
# STEP 1: Set Project & Resolve Project Number
# ==============================================================================

# Set the active project in gcloud
gcloud config set project "${PROJECT_ID}"

# Retrieve and save your project number
export PROJECT_NUMBER="$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')"
echo "Project Number: ${PROJECT_NUMBER}"

# Define service account email addresses for subsequent IAM bindings
export COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
export RE_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
export VERTEX_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com"
export BQ_CONN_SA="service-${PROJECT_NUMBER}@gcp-sa-bigqueryconnection.iam.gserviceaccount.com"


# ==============================================================================
# STEP 2: Enable Required Google Cloud APIs
# ==============================================================================

gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  bigquery.googleapis.com \
  bigqueryconnection.googleapis.com \
  alloydb.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  compute.googleapis.com \
  iam.googleapis.com \
  storage.googleapis.com


# ==============================================================================
# STEP 3: Configure IAM Permissions
# ==============================================================================

# Ensure required variables are set if Step 3 is executed independently
export PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
export PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')}"
export COMPUTE_SA="${COMPUTE_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
export RE_SA="${RE_SA:-service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com}"
export VERTEX_SA="${VERTEX_SA:-service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com}"
export BQ_CONN_SA="${BQ_CONN_SA:-service-${PROJECT_NUMBER}@gcp-sa-bigqueryconnection.iam.gserviceaccount.com}"

# Grant IAM roles to Default Compute Service Account
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/alloydb.client"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/alloydb.databaseUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/run.admin"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/run.invoker"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/iam.serviceAccountUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/cloudbuild.builds.editor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/artifactregistry.admin"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/logging.logWriter"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/storage.objectAdmin"

# Initialize Vertex AI Reasoning Engine service agent and grant roles
gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}"
sleep 10
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/alloydb.client"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/alloydb.databaseUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/storage.objectAdmin"

# Grant roles to Vertex AI Service Agent
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${VERTEX_SA}" --role="roles/alloydb.client"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${VERTEX_SA}" --role="roles/alloydb.databaseUser"

# Initialize BigQuery Connection service agent and grant alloydb.client role
gcloud beta services identity create --service=bigqueryconnection.googleapis.com --project="${PROJECT_ID}"
sleep 10
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${BQ_CONN_SA}" --role="roles/alloydb.client"


# ==============================================================================
# STEP 4: Create Cloud Secret Manager Secrets
# ==============================================================================

# Create GitHub Personal Access Token secret
echo -n "${GITHUB_PAT}" | gcloud secrets create github-pat --data-file=- --replication-policy="automatic" --project="${PROJECT_ID}"

# Grant access on secret to Compute Service Account
gcloud secrets add-iam-policy-binding github-pat --member="serviceAccount:${COMPUTE_SA}" --role="roles/secretmanager.secretAccessor" --project="${PROJECT_ID}"


# ==============================================================================
# STEP 4B: Create Google Cloud Storage Bucket for OKF Dynamic Context
# ==============================================================================

# Create Google Cloud Storage bucket for dynamic_context.md in location US
gcloud storage buckets create "gs://${OKF_BUCKET_NAME}" \
  --project="${PROJECT_ID}" \
  --location="${OKF_BUCKET_LOCATION}" \
  --uniform-bucket-level-access 2>/dev/null || echo "Bucket gs://${OKF_BUCKET_NAME} already exists."

# Ensure Compute and Reasoning Engine service accounts have objectAdmin permissions on the bucket
gcloud storage buckets add-iam-policy-binding "gs://${OKF_BUCKET_NAME}" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/storage.objectAdmin"

gcloud storage buckets add-iam-policy-binding "gs://${OKF_BUCKET_NAME}" \
  --member="serviceAccount:${RE_SA}" \
  --role="roles/storage.objectAdmin"


# ==============================================================================
# STEP 5: Provision AlloyDB Cluster, Instance & Database
# ==============================================================================

# 1. Create AlloyDB Cluster (takes ~5-10 minutes)
gcloud alloydb clusters create "${ALLOYDB_CLUSTER}" \
  --region="${REGION}" \
  --password="${ALLOYDB_PASSWORD}" \
  --enable-private-service-connect \
  --project="${PROJECT_ID}"

# 2. Create AlloyDB Primary Instance (takes ~5-10 minutes)
gcloud alloydb instances create "${ALLOYDB_INSTANCE}" \
  --cluster="${ALLOYDB_CLUSTER}" \
  --region="${REGION}" \
  --instance-type="PRIMARY" \
  --cpu-count=2 \
  --allowed-psc-projects="${PROJECT_NUMBER}" \
  --database-flags="alloydb.iam_authentication=on" \
  --ssl-mode="ENCRYPTED_ONLY" \
  --project="${PROJECT_ID}"


# ------------------------------------------------------------------------------
# TABLE INITIALIZATION IN GOOGLE CLOUD CONSOLE / ALLOYDB STUDIO:
# Navigate to: Google Cloud Console -> AlloyDB -> Clusters -> apex -> apex instance -> AlloyDB Studio
# Authenticate using user: postgres and your $ALLOYDB_PASSWORD, select database 'apex',
# and execute the following SQL statement:
#
# CREATE TABLE IF NOT EXISTS customer_ratings (
#     customer_id BIGINT NOT NULL,
#     customer_name TEXT NOT NULL,
#     rating INTEGER NOT NULL,
#     description TEXT NOT NULL,
#     timestamp TIMESTAMPTZ
# );
# GRANT ALL PRIVILEGES ON SCHEMA public TO PUBLIC;
# GRANT ALL PRIVILEGES ON TABLE customer_ratings TO PUBLIC;
# ------------------------------------------------------------------------------


# ==============================================================================
# STEP 6: Provision BigQuery Datasets, Connections & Federated Views
# ==============================================================================

# 1. Create Datasets
bq mk -d --location="${BQ_LOCATION}" --project_id="${PROJECT_ID}" demo
bq mk -d --location="${BQ_LOCATION}" --project_id="${PROJECT_ID}" agent_telemetry

# 2. Create BigQuery Cloud Resource Connection for Vertex AI (Gemini)
bq mk --connection \
  --location="${BQ_LOCATION}" \
  --project_id="${PROJECT_ID}" \
  --connection_type=CLOUD_RESOURCE \
  gemini

# 3. Retrieve Vertex AI Connection Service Account and grant aiplatform.user role
export BQ_VERTEX_SA="$(bq show --format=prettyjson --connection --location=${BQ_LOCATION} ${PROJECT_ID}.${BQ_LOCATION}.gemini | grep 'serviceAccountId' | head -1 | cut -d '"' -f 4)"
echo "Vertex AI Connection SA: ${BQ_VERTEX_SA}"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${BQ_VERTEX_SA}" --role="roles/aiplatform.user"

# 4. Create BigQuery Connection to AlloyDB
export ALLOYDB_RESOURCE="//alloydb.googleapis.com/projects/${PROJECT_ID}/locations/${REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ALLOYDB_INSTANCE}"
export ACCESS_TOKEN="$(gcloud auth print-access-token)"

curl -X POST "https://bigqueryconnection.googleapis.com/v1/projects/${PROJECT_ID}/locations/${BQ_LOCATION}/connections?connectionId=alloydb" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"friendlyName\":\"alloydb\",\"configuration\":{\"connectorId\":\"google-alloydb\",\"asset\":{\"googleCloudResource\":\"${ALLOYDB_RESOURCE}\",\"database\":\"postgres\"},\"authentication\":{\"usernamePassword\":{\"username\":\"postgres\",\"password\":{\"plaintext\":\"${ALLOYDB_PASSWORD}\"}}}}}"

# 5. Create BigQuery Federated Views pointing to AlloyDB
bq mk --use_legacy_sql=false \
  --view="SELECT * FROM EXTERNAL_QUERY(\"projects/${PROJECT_ID}/locations/${BQ_LOCATION}/connections/alloydb\", \"SELECT * FROM customer_ratings;\")" \
  --project_id="${PROJECT_ID}" \
  demo.customer_ratings

bq mk --use_legacy_sql=false \
  --view="SELECT * FROM EXTERNAL_QUERY(\"projects/${PROJECT_ID}/locations/${BQ_LOCATION}/connections/alloydb\", \"SELECT * FROM customer_ratings;\")" \
  --project_id="${PROJECT_ID}" \
  demo.customer_reviews


# ==============================================================================
# STEP 7: Clone Application Repository & Prepare Python Virtual Environment
# ==============================================================================

# 1. Clone repository branch 'cloudday' and change directory
git clone -b cloudday https://github.com/gshilo/experthub.git
cd experthub

# 2. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# 3. Install dependencies for agents and frontend
pip install -r customer_service_agent/requirements.txt
pip install -r customer_agent/requirements.txt
pip install -r auditor_agent/requirements.txt
pip install -r frontend/requirements.txt


# ==============================================================================
# STEP 8: Deploy Agents to Vertex AI Agent Engine
# ==============================================================================

# Deploy Customer Service Agent
python customer_service_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud

# Deploy Customer Simulator Agent
cat << 'EOF' > customer_agent/.agent_engine_config.json
{
  "env_vars": {
    "GOOGLE_GENAI_USE_VERTEXAI": "true",
    "VERTEX_AI_LOCATION": "global",
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"
  }
}
EOF
python customer_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud

# Deploy Auditor Agent
python auditor_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud


# ==============================================================================
# STEP 9: Build and Deploy Frontend Web App to Cloud Run
# ==============================================================================

# Ensure required variables are set if Step 9 is executed independently
export PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
export PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')}"
export COMPUTE_SA="${COMPUTE_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
export REGION="${REGION:-us-central1}"
export BQ_LOCATION="${BQ_LOCATION:-US}"
export FRONTEND_SERVICE="${FRONTEND_SERVICE:-experthub-frontend}"
export OKF_BUCKET_NAME="${OKF_BUCKET_NAME:-instructions91}"
export OKF_BUCKET_LOCATION="${OKF_BUCKET_LOCATION:-US}"

gcloud run deploy "${FRONTEND_SERVICE}" \
  --source . \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${COMPUTE_SA}" \
  --no-invoker-iam-check \
  --port=8080 \
  --cpu=1 \
  --memory=512Mi \
  --timeout=300s \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCP_REGION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global,VERTEX_AI_LOCATION=global,BQ_LOCATION=${BQ_LOCATION},OKF_BUCKET_NAME=${OKF_BUCKET_NAME},OKF_BUCKET_LOCATION=${OKF_BUCKET_LOCATION},GITHUB_SECRET_NAME=github-pat"

# Retrieve and print the deployed web application URL
gcloud run services describe "${FRONTEND_SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)"
