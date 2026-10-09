variable "project_id" {
  type        = string
  description = "Google Cloud Project ID where all resources will be deployed."
  default     = "experthub-510907"
}

variable "region" {
  type        = string
  description = "Google Cloud Region for Cloud Run, Artifact Registry, and Vertex AI resources."
  default     = "us-central1"
}

variable "bq_location" {
  type        = string
  description = "BigQuery dataset location (e.g. US multi-region or regional)."
  default     = "US"
}

variable "secret_name" {
  type        = string
  description = "Google Cloud Secret Manager secret name storing the GitHub PAT."
  default     = "github-pat"
}

variable "github_pat" {
  type        = string
  description = "GitHub Personal Access Token for OKF context commits. If empty, a placeholder is provisioned in Secret Manager."
  default     = ""
  sensitive   = true
}

variable "use_existing_service_account" {
  type        = bool
  description = "Whether to use an existing service account (e.g. Compute Engine default SA) instead of provisioning a new one."
  default     = true
}

variable "existing_service_account_email" {
  type        = string
  description = "Email of the existing service account to use if use_existing_service_account is true."
  default     = "537563976049-compute@developer.gserviceaccount.com"
}

variable "service_account_id" {
  type        = string
  description = "Service account ID to create if use_existing_service_account is false."
  default     = "experthub-app-sa"
}

variable "artifact_repository_id" {
  type        = string
  description = "Artifact Registry Docker repository ID."
  default     = "cloud-run-source-deploy"
}

variable "frontend_service_name" {
  type        = string
  description = "Name of the Google Cloud Run frontend service."
  default     = "experthub-frontend"
}

variable "frontend_image" {
  type        = string
  description = "Pre-built container image URI for Cloud Run frontend. If empty, points to Artifact Registry."
  default     = ""
}

variable "build_frontend_image" {
  type        = bool
  description = "Whether to build and push the frontend Docker image using Cloud Build during terraform apply."
  default     = false
}

variable "deploy_vertex_agents" {
  type        = bool
  description = "Whether to invoke agent deploy scripts for Vertex AI Agent Engine during terraform apply."
  default     = false
}

variable "customer_service_agent_id" {
  type        = string
  description = "Vertex AI Reasoning Engine ID for the Customer Service Agent."
  default     = "2556039354015285248"
}

variable "customer_agent_id" {
  type        = string
  description = "Vertex AI Reasoning Engine ID for the Customer Simulator Agent."
  default     = "8810413336526061568"
}

variable "auditor_agent_id" {
  type        = string
  description = "Vertex AI Reasoning Engine ID for the Auditor Agent."
  default     = "4360856904684011520"
}

variable "invoker_iam_disabled" {
  type        = bool
  description = "Whether to disable IAM invoker checks on Cloud Run (enables public access in organizations restricting allUsers)."
  default     = true
}

variable "allow_public_allusers" {
  type        = bool
  description = "Whether to bind roles/run.invoker to allUsers. Keep false if organization policies restrict domain sharing."
  default     = false
}

