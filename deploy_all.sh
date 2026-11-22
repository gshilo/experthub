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
export GEMINI_API_KEY="AIzaSy..."
export GITHUB_DEPLOY_KEY_FILE="${HOME}/.ssh/experthub_deploy_key"

export ARTIFACT_REPO="experthub-repo"
export FRONTEND_SERVICE="experthub-frontend"


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


# ==============================================================================
# STEP 2: Enable Required Google Cloud APIs
# ==============================================================================

gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  bigquery.googleapis.com \
  bigqueryconnection.googleapis.com \
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
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/run.invoker"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${COMPUTE_SA}" --role="roles/storage.objectAdmin"

# Initialize Vertex AI Reasoning Engine service agent and grant roles
gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${RE_SA}" --role="roles/storage.objectAdmin"


# ==============================================================================
# STEP 4: Create Cloud Secret Manager Secrets
# ==============================================================================

# Create Gemini API Key secret (if not already created)
gcloud secrets describe gemini-api-key --project="${PROJECT_ID}" >/dev/null 2>&1 || \
  echo -n "${GEMINI_API_KEY}" | gcloud secrets create gemini-api-key --data-file=- --replication-policy="automatic" --project="${PROJECT_ID}"

# Create GitHub SSH Deploy Key secret (used for gshilo/experthub_context OKF sync)
# Ensure ${GITHUB_DEPLOY_KEY_FILE} points to your private ed25519 deploy key and its
# public key is added with write access in GitHub Repo Settings -> Deploy keys.
if ! gcloud secrets describe github-deploy-key --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud secrets create github-deploy-key --data-file="${GITHUB_DEPLOY_KEY_FILE}" --replication-policy="automatic" --project="${PROJECT_ID}"
else
  echo "Secret 'github-deploy-key' already exists in project ${PROJECT_ID}."
fi

# Grant access on secrets to Compute and Reasoning Engine Service Accounts
gcloud secrets add-iam-policy-binding gemini-api-key --member="serviceAccount:${COMPUTE_SA}" --role="roles/secretmanager.secretAccessor" --project="${PROJECT_ID}"
gcloud secrets add-iam-policy-binding github-deploy-key --member="serviceAccount:${COMPUTE_SA}" --role="roles/secretmanager.secretAccessor" --project="${PROJECT_ID}"
gcloud secrets add-iam-policy-binding github-deploy-key --member="serviceAccount:${RE_SA}" --role="roles/secretmanager.secretAccessor" --project="${PROJECT_ID}"


# ==============================================================================
# STEP 5: Provision BigQuery Datasets, Native Ratings Table & Connections
# ==============================================================================

# 1. Create Datasets (if not already present)
bq show --project_id="${PROJECT_ID}" demo >/dev/null 2>&1 || \
  bq mk -d --location="${BQ_LOCATION}" --project_id="${PROJECT_ID}" demo
bq show --project_id="${PROJECT_ID}" agent_telemetry >/dev/null 2>&1 || \
  bq mk -d --location="${BQ_LOCATION}" --project_id="${PROJECT_ID}" agent_telemetry

# 2. Create Native BigQuery Customer Ratings Table (if not already present)
bq show --project_id="${PROJECT_ID}" demo.customer_ratings >/dev/null 2>&1 || \
  bq mk --table \
    --project_id="${PROJECT_ID}" \
    demo.customer_ratings \
    customer_id:INTEGER,customer_name:STRING,description:STRING,rating:INTEGER,timestamp:DATETIME

# 3. Create BigQuery Cloud Resource Connection for Vertex AI (Gemini)
bq mk --connection \
  --location="${BQ_LOCATION}" \
  --project_id="${PROJECT_ID}" \
  --connection_type=CLOUD_RESOURCE \
  gemini

# 4. Retrieve Vertex AI Connection Service Account and grant aiplatform.user role
export BQ_VERTEX_SA="$(bq show --format=prettyjson --connection --location=${BQ_LOCATION} ${PROJECT_ID}.${BQ_LOCATION}.gemini | grep 'serviceAccountId' | head -1 | cut -d '\"' -f 4)"
echo "Vertex AI Connection SA: ${BQ_VERTEX_SA}"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${BQ_VERTEX_SA}" --role="roles/aiplatform.user"


# ==============================================================================
# STEP 6: Prepare Python Virtual Environment
# ==============================================================================

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

pip install -r customer_service_agent/requirements.txt
pip install -r customer_agent/requirements.txt
pip install -r auditor_agent/requirements.txt
pip install -r frontend/requirements.txt


# ==============================================================================
# STEP 7: Deploy Agents to Vertex AI Agent Engine
# ==============================================================================

# Deploy Customer Service Agent
python customer_service_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud

# Deploy Customer Simulator Agent
python customer_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud

# Deploy Auditor Agent
python auditor_agent/deploy.py --project="${PROJECT_ID}" --region="${REGION}" --otel_to_cloud


# ==============================================================================
# STEP 8: Build and Deploy Frontend Web App to Cloud Run
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
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCP_REGION=${REGION},BQ_LOCATION=${BQ_LOCATION},GITHUB_DEPLOY_KEY_SECRET_NAME=github-deploy-key"

# Retrieve and print the deployed web application URL
gcloud run services describe "${FRONTEND_SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)"
