#!/usr/bin/env bash
# ==============================================================================
# deploy_terraform.sh
# Automates execution of the Terraform script deploying the Experthub demo.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${SCRIPT_DIR}/terraform"

AUTO_APPROVE=false
BUILD_IMAGE=false
DEPLOY_AGENTS=true
PROJECT_ID=""

print_usage() {
    echo "Usage: ./deploy_terraform.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -p, --project ID        Google Cloud Project ID (defaults to GOOGLE_CLOUD_PROJECT or gcloud config)"
    echo "  -y, --auto-approve      Automatically approve and apply Terraform changes"
    echo "  --build-image           Build frontend container using Cloud Build before deploying"
    echo "  --deploy-agents         Run Vertex AI Agent Engine deploy scripts (enabled by default)"
    echo "  --skip-agents           Skip Vertex AI Agent Engine deploy scripts"
    echo "  --plan-only             Run 'terraform plan' and exit"
    echo "  -h, --help              Show this help message"
}

PLAN_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--project)
            PROJECT_ID="${2:-}"
            shift 2
            ;;
        --project=*)
            PROJECT_ID="${1#*=}"
            shift
            ;;
        -y|--auto-approve)
            AUTO_APPROVE=true
            shift
            ;;
        --build-image)
            BUILD_IMAGE=true
            shift
            ;;
        --deploy-agents)
            DEPLOY_AGENTS=true
            shift
            ;;
        --skip-agents|--no-deploy-agents)
            DEPLOY_AGENTS=false
            shift
            ;;
        --plan-only)
            PLAN_ONLY=true
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

echo "========================================================================"
echo " ApexHome & Electro Demo: Terraform Automated Deployment"
echo "========================================================================"

# 1. Verify Terraform
if ! command -v terraform &> /dev/null; then
    echo "Error: 'terraform' CLI is not found in PATH." >&2
    echo "Please install Terraform >= 1.5.0: https://developer.hashicorp.com/terraform/downloads" >&2
    exit 1
fi
echo "[OK] Found Terraform: $(terraform version | head -n 1)"

# 2. Verify GCP authentication and resolve active project
ACTIVE_PROJECT="${PROJECT_ID}"
if [[ -z "${ACTIVE_PROJECT}" ]]; then
    ACTIVE_PROJECT="${GOOGLE_CLOUD_PROJECT:-${GCP_PROJECT:-}}"
fi
if [[ -z "${ACTIVE_PROJECT}" ]]; then
    ACTIVE_PROJECT="$(gcloud config get-value project 2>/dev/null || echo "")"
    if [[ "${ACTIVE_PROJECT}" == "(unset)" ]]; then
        ACTIVE_PROJECT=""
    fi
fi
if [[ -z "${ACTIVE_PROJECT}" ]]; then
    echo "Error: No Google Cloud Project ID detected." >&2
    echo "Specify '--project <PROJECT_ID>', export GOOGLE_CLOUD_PROJECT, or run 'gcloud config set project <PROJECT_ID>'." >&2
    exit 1
fi
echo "[OK] Active GCP Project: ${ACTIVE_PROJECT}"

# 3. Initialize Terraform & isolate state per project via workspace
echo ""
echo "--> Initializing Terraform in ${TF_DIR}..."
terraform -chdir="${TF_DIR}" init

echo ""
echo "--> Selecting Terraform workspace for project '${ACTIVE_PROJECT}'..."
terraform -chdir="${TF_DIR}" workspace select -or-create "${ACTIVE_PROJECT}"

# 3b. Reconcile pre-existing GCP resources into Terraform state (prevents 409 Already Exists errors)
echo ""
echo "--> Checking for pre-existing GCP resources to import into Terraform state..."
EXISTING_STATE="$(terraform -chdir="${TF_DIR}" state list 2>/dev/null || echo "")"

import_if_missing() {
    local tf_addr="$1"
    local import_id="$2"
    if ! echo "${EXISTING_STATE}" | grep -Fxq "${tf_addr}"; then
        echo "    Importing existing resource ${tf_addr} (${import_id})..."
        terraform -chdir="${TF_DIR}" import -var="project_id=${ACTIVE_PROJECT}" "${tf_addr}" "${import_id}" >/dev/null 2>&1 || true
    fi
}

# Import pre-existing BigQuery datasets & tables if present in the project
if bq --project_id="${ACTIVE_PROJECT}" show --dataset "${ACTIVE_PROJECT}:agent_telemetry" >/dev/null 2>&1; then
    import_if_missing "google_bigquery_dataset.agent_telemetry" "projects/${ACTIVE_PROJECT}/datasets/agent_telemetry"
fi
if bq --project_id="${ACTIVE_PROJECT}" show --dataset "${ACTIVE_PROJECT}:demo" >/dev/null 2>&1; then
    import_if_missing "google_bigquery_dataset.demo" "projects/${ACTIVE_PROJECT}/datasets/demo"
fi
if bq --project_id="${ACTIVE_PROJECT}" show "${ACTIVE_PROJECT}:demo.customer_ratings" >/dev/null 2>&1; then
    import_if_missing "google_bigquery_table.customer_ratings" "projects/${ACTIVE_PROJECT}/datasets/demo/tables/customer_ratings"
fi
if gcloud compute network-attachments describe agent-engine-psc-na --region=us-central1 --project="${ACTIVE_PROJECT}" --quiet >/dev/null 2>&1; then
    import_if_missing "google_compute_network_attachment.agent_engine_psc" "projects/${ACTIVE_PROJECT}/regions/us-central1/networkAttachments/agent-engine-psc-na"
fi

# Clean up tainted Cloud Run service from a prior failed deployment (where deletion_protection=true blocked replacement)
if echo "${EXISTING_STATE}" | grep -Fxq "google_cloud_run_v2_service.frontend"; then
    if terraform -chdir="${TF_DIR}" state show google_cloud_run_v2_service.frontend 2>/dev/null | head -n 5 | grep -q "(tainted)"; then
        echo "    Cleaning up tainted google_cloud_run_v2_service.frontend so it can be cleanly recreated..."
        gcloud run services delete experthub-frontend --region=us-central1 --project="${ACTIVE_PROJECT}" --quiet >/dev/null 2>&1 || true
        terraform -chdir="${TF_DIR}" state rm google_cloud_run_v2_service.frontend >/dev/null 2>&1 || true
    fi
fi

# 3c. Auto-detect whether frontend image exists in Artifact Registry
IMAGE_URI="us-central1-docker.pkg.dev/${ACTIVE_PROJECT}/cloud-run-source-deploy/experthub-frontend:latest"
if [[ "${BUILD_IMAGE}" == "false" ]]; then
    if ! gcloud artifacts docker images describe "${IMAGE_URI}" --project="${ACTIVE_PROJECT}" >/dev/null 2>&1; then
        echo "[INFO] Container image '${IMAGE_URI}' not found in Artifact Registry. Enabling Cloud Build (--build-image)."
        BUILD_IMAGE=true
    fi
fi

# 3d. Auto-detect Vertex AI Reasoning Engines & reconcile missing agent deployments
ENABLE_RE_IAM=false
CS_AGENT_ID=""
CUST_AGENT_ID=""
AUD_AGENT_ID=""
ACCESS_TOKEN="$(gcloud auth print-access-token 2>/dev/null || echo "")"
if [[ -n "${ACCESS_TOKEN}" ]]; then
    RE_LIST="$(curl -s -H "Authorization: Bearer ${ACCESS_TOKEN}" "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/${ACTIVE_PROJECT}/locations/us-central1/reasoningEngines" 2>/dev/null || echo "")"
    if echo "${RE_LIST}" | grep -q '"reasoningEngines"'; then
        ENABLE_RE_IAM=true
        CS_AGENT_ID="$(RE_JSON="${RE_LIST}" python3 -c 'import json, os; d=json.loads(os.environ.get("RE_JSON","{}")); print(next((r["name"].split("/")[-1] for r in d.get("reasoningEngines",[]) if r.get("displayName")=="customer_service_agent"), ""))' 2>/dev/null || echo "")"
        CUST_AGENT_ID="$(RE_JSON="${RE_LIST}" python3 -c 'import json, os; d=json.loads(os.environ.get("RE_JSON","{}")); print(next((r["name"].split("/")[-1] for r in d.get("reasoningEngines",[]) if r.get("displayName")=="customer_agent"), ""))' 2>/dev/null || echo "")"
        AUD_AGENT_ID="$(RE_JSON="${RE_LIST}" python3 -c 'import json, os; d=json.loads(os.environ.get("RE_JSON","{}")); print(next((r["name"].split("/")[-1] for r in d.get("reasoningEngines",[]) if r.get("displayName")=="auditor_agent"), ""))' 2>/dev/null || echo "")"
    fi
fi

if [[ "${DEPLOY_AGENTS}" == "true" ]]; then
    if [[ -z "${CS_AGENT_ID}" ]] && echo "${EXISTING_STATE}" | grep -Fxq "null_resource.deploy_customer_service_agent[0]"; then
        echo "    Agent 'customer_service_agent' missing in Agent Engine; marking for deployment..."
        terraform -chdir="${TF_DIR}" state rm "null_resource.deploy_customer_service_agent[0]" >/dev/null 2>&1 || true
    fi
    if [[ -z "${CUST_AGENT_ID}" ]] && echo "${EXISTING_STATE}" | grep -Fxq "null_resource.deploy_customer_agent[0]"; then
        echo "    Agent 'customer_agent' missing in Agent Engine; marking for deployment..."
        terraform -chdir="${TF_DIR}" state rm "null_resource.deploy_customer_agent[0]" >/dev/null 2>&1 || true
    fi
    if [[ -z "${AUD_AGENT_ID}" ]] && echo "${EXISTING_STATE}" | grep -Fxq "null_resource.deploy_auditor_agent[0]"; then
        echo "    Agent 'auditor_agent' missing in Agent Engine; marking for deployment..."
        terraform -chdir="${TF_DIR}" state rm "null_resource.deploy_auditor_agent[0]" >/dev/null 2>&1 || true
    fi
fi

# 4. Generate plan arguments
EXTRA_VARS=("-var=project_id=${ACTIVE_PROJECT}" "-var=deploy_vertex_agents=${DEPLOY_AGENTS}")
if [[ "${BUILD_IMAGE}" == "true" ]]; then
    EXTRA_VARS+=("-var=build_frontend_image=true")
fi
if [[ "${ENABLE_RE_IAM}" == "true" ]]; then
    EXTRA_VARS+=("-var=enable_reasoning_engine_iam=true")
fi
if [[ -n "${CS_AGENT_ID}" ]]; then
    EXTRA_VARS+=("-var=customer_service_agent_id=${CS_AGENT_ID}")
fi
if [[ -n "${CUST_AGENT_ID}" ]]; then
    EXTRA_VARS+=("-var=customer_agent_id=${CUST_AGENT_ID}")
fi
if [[ -n "${AUD_AGENT_ID}" ]]; then
    EXTRA_VARS+=("-var=auditor_agent_id=${AUD_AGENT_ID}")
fi

echo ""
echo "--> Generating Terraform Plan..."
terraform -chdir="${TF_DIR}" plan "${EXTRA_VARS[@]}"

if [[ "${PLAN_ONLY}" == "true" ]]; then
    echo ""
    echo "[OK] Plan completed. Exiting without applying changes (--plan-only)."
    exit 0
fi

# 5. Apply Terraform changes
echo ""
if [[ "${AUTO_APPROVE}" == "true" ]]; then
    echo "--> Applying Terraform changes (-auto-approve)..."
    terraform -chdir="${TF_DIR}" apply -auto-approve "${EXTRA_VARS[@]}"
else
    echo "--> Applying Terraform changes..."
    terraform -chdir="${TF_DIR}" apply "${EXTRA_VARS[@]}"
fi

echo ""
echo "========================================================================"
echo " Deployment Successfully Completed!"
echo "========================================================================"
FRONTEND_URL="$(terraform -chdir="${TF_DIR}" output -raw frontend_url 2>/dev/null || echo "N/A")"
echo "Public Cloud Run Frontend URL: ${FRONTEND_URL}"
echo ""
echo "Verify application health:"
echo "  curl -s ${FRONTEND_URL}/health"
echo "========================================================================"
