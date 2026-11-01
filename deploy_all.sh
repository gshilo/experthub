#!/usr/bin/env bash
# ==============================================================================
# deploy_all.sh - Step-by-Step Student Deployment Guide for Google Cloud Shell
# ==============================================================================
# This file is structured so students can copy and paste commands ONE AT A TIME
# directly into Google Cloud Shell (or terminal).
#
# No complicated bash loops, no subshell forks, and no nested heredocs.
# ==============================================================================


# ==============================================================================
# STEP 0: Set Your Environment Variables
# ==============================================================================
# Copy and run these export commands. Replace the placeholder values with your
# own project ID, passwords, and API keys.

export PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
# If PROJECT_ID is empty above, set it explicitly:
# export PROJECT_ID="your-gcp-project-id"

export REGION="us-central1"
export BQ_LOCATION="US"
export ALLOYDB_PASSWORD="ChangeMeAlloyDB123!"
export GEMINI_API_KEY="AIzaSy..."
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

# Grant IAM roles to Default Compute Service Account
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/alloydb.client"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/run.invoker"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/storage.objectAdmin"

# Initialize Vertex AI Reasoning Engine service agent and grant roles
gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}"
sleep 10
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/alloydb.client"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/storage.objectAdmin"

# Initialize BigQuery Connection service agent and grant alloydb.client role
gcloud beta services identity create --service=bigqueryconnection.googleapis.com --project="${PROJECT_ID}"
sleep 10
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${BQ_CONN_SA}" --role="roles/alloydb.client"


# ==============================================================================
# STEP 4: Create Cloud Secret Manager Secrets
# ==============================================================================

# Create Gemini API Key secret
echo -n "${GEMINI_API_KEY}" | gcloud secrets create gemini-api-key --data-file=- --replication-policy="automatic" --project="${PROJECT_ID}"

# Create GitHub Personal Access Token secret
echo -n "${GITHUB_PAT}" | gcloud secrets create github-pat --data-file=- --replication-policy="automatic" --project="${PROJECT_ID}"

# Grant access on secrets to Compute Service Account
gcloud secrets add-iam-policy-binding gemini-api-key --member="serviceAccount:${COMPUTE_SA}" --role="roles/secretmanager.secretAccessor" --project="${PROJECT_ID}"
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
python customer_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud

# Deploy Auditor Agent
python auditor_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud


# ==============================================================================
# STEP 9: Build and Deploy Frontend Web App to Cloud Run
# ==============================================================================

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
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCP_REGION=${REGION},BQ_LOCATION=${BQ_LOCATION},OKF_BUCKET_NAME=${OKF_BUCKET_NAME},OKF_BUCKET_LOCATION=${OKF_BUCKET_LOCATION},GITHUB_SECRET_NAME=github-pat"

# Retrieve and print the deployed web application URL
gcloud run services describe "${FRONTEND_SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)"
