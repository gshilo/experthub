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
DEPLOY_AGENTS=false

print_usage() {
    echo "Usage: ./deploy_terraform.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -y, --auto-approve      Automatically approve and apply Terraform changes"
    echo "  --build-image           Build frontend container using Cloud Build before deploying"
    echo "  --deploy-agents         Run Vertex AI Agent Engine deploy scripts"
    echo "  --plan-only             Run 'terraform plan' and exit"
    echo "  -h, --help              Show this help message"
}

PLAN_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
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

# 2. Verify GCP authentication
ACTIVE_PROJECT="$(gcloud config get-value project 2>/dev/null || echo "")"
if [[ -z "${ACTIVE_PROJECT}" ]]; then
    ACTIVE_PROJECT="${GOOGLE_CLOUD_PROJECT:-experthub-510907}"
fi
echo "[OK] Active GCP Project: ${ACTIVE_PROJECT}"

# 3. Initialize Terraform
echo ""
echo "--> Initializing Terraform in ${TF_DIR}..."
terraform -chdir="${TF_DIR}" init

# 4. Generate plan arguments
EXTRA_VARS=()
if [[ "${BUILD_IMAGE}" == "true" ]]; then
    EXTRA_VARS+=("-var=build_frontend_image=true")
fi
if [[ "${DEPLOY_AGENTS}" == "true" ]]; then
    EXTRA_VARS+=("-var=deploy_vertex_agents=true")
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
