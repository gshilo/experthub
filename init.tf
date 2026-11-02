# ==============================================================================
# init.tf - Terraform Configuration for Steps 1-5 of deploy_all.sh
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

# ==============================================================================
# STEP 0: Variables (Environment Configuration)
# ==============================================================================

variable "project_id" {
  type        = string
  description = "Google Cloud Project ID where all resources will be deployed."
}

variable "region" {
  type        = string
  description = "Google Cloud Region for AlloyDB and regional resources."
  default     = "us-central1"
}

variable "bq_location" {
  type        = string
  description = "BigQuery location."
  default     = "US"
}

variable "alloydb_password" {
  type        = string
  description = "Initial password for the AlloyDB postgres user."
  default     = "ChangeMeAlloyDB123!"
  sensitive   = true
}

variable "gemini_api_key" {
  type        = string
  description = "Gemini API key stored in Cloud Secret Manager."
  default     = "AIzaSy..."
  sensitive   = true
}

variable "github_pat" {
  type        = string
  description = "GitHub Personal Access Token stored in Cloud Secret Manager."
  default     = "ghp_..."
  sensitive   = true
}

variable "alloydb_cluster" {
  type        = string
  description = "AlloyDB cluster ID."
  default     = "apex"
}

variable "alloydb_instance" {
  type        = string
  description = "AlloyDB primary instance ID."
  default     = "apex"
}

variable "alloydb_database" {
  type        = string
  description = "AlloyDB database name."
  default     = "apex"
}

variable "okf_bucket_name" {
  type        = string
  description = "Google Cloud Storage bucket name for OKF dynamic context."
  default     = "instructions91"
}

variable "okf_bucket_location" {
  type        = string
  description = "Google Cloud Storage bucket location for OKF dynamic context."
  default     = "US"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ==============================================================================
# STEP 1: Set Project & Resolve Project Number
# ==============================================================================

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  project_number = data.google_project.current.number

  # Service account email addresses for IAM bindings
  compute_sa = "${local.project_number}-compute@developer.gserviceaccount.com"
  re_sa      = "service-${local.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
  vertex_sa  = "service-${local.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
  bq_conn_sa = "service-${local.project_number}@gcp-sa-bigqueryconnection.iam.gserviceaccount.com"
}

# ==============================================================================
# STEP 2: Enable Required Google Cloud APIs
# ==============================================================================

locals {
  required_apis = [
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "bigquery.googleapis.com",
    "bigqueryconnection.googleapis.com",
    "alloydb.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "storage.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each                   = toset(local.required_apis)
  project                    = var.project_id
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}

# ==============================================================================
# STEP 3: Configure IAM Permissions
# ==============================================================================

locals {
  compute_sa_roles = [
    "roles/secretmanager.secretAccessor",
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/aiplatform.user",
    "roles/alloydb.client",
    "roles/alloydb.databaseUser",
    "roles/run.admin",
    "roles/run.invoker",
    "roles/iam.serviceAccountUser",
    "roles/cloudbuild.builds.editor",
    "roles/artifactregistry.admin",
    "roles/logging.logWriter",
    "roles/storage.objectAdmin",
  ]

  re_sa_roles = [
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/secretmanager.secretAccessor",
    "roles/alloydb.client",
    "roles/alloydb.databaseUser",
    "roles/storage.objectAdmin",
  ]

  vertex_sa_roles = [
    "roles/alloydb.client",
    "roles/alloydb.databaseUser",
  ]
}

# Grant IAM roles to Default Compute Service Account
resource "google_project_iam_member" "compute_sa_roles" {
  for_each = toset(local.compute_sa_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${local.compute_sa}"

  depends_on = [google_project_service.apis]
}

# Initialize Vertex AI and BigQuery Connection service agents
resource "google_project_service_identity" "aiplatform_identity" {
  provider = google-beta
  project  = var.project_id
  service  = "aiplatform.googleapis.com"

  depends_on = [google_project_service.apis]
}

resource "google_project_service_identity" "bigqueryconnection_identity" {
  provider = google-beta
  project  = var.project_id
  service  = "bigqueryconnection.googleapis.com"

  depends_on = [google_project_service.apis]
}

# Ensure Reasoning Engine and BigQuery Connection service identities propagate
resource "null_resource" "init_service_identities" {
  provisioner "local-exec" {
    command = <<-EOT
      gcloud beta services identity create --service=aiplatform.googleapis.com --project="${var.project_id}" --quiet || true
      gcloud beta services identity create --service=bigqueryconnection.googleapis.com --project="${var.project_id}" --quiet || true
      sleep 10
    EOT
  }

  depends_on = [
    google_project_service.apis,
    google_project_service_identity.aiplatform_identity,
    google_project_service_identity.bigqueryconnection_identity,
  ]
}

# Grant IAM roles to Reasoning Engine Service Agent
resource "google_project_iam_member" "re_sa_roles" {
  for_each = toset(local.re_sa_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${local.re_sa}"

  depends_on = [null_resource.init_service_identities]
}

# Grant IAM roles to Vertex AI Service Agent
resource "google_project_iam_member" "vertex_sa_roles" {
  for_each = toset(local.vertex_sa_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${local.vertex_sa}"

  depends_on = [null_resource.init_service_identities]
}

# Grant alloydb.client role to BigQuery Connection Service Agent
resource "google_project_iam_member" "bq_conn_sa_alloydb_client" {
  project = var.project_id
  role    = "roles/alloydb.client"
  member  = "serviceAccount:${local.bq_conn_sa}"

  depends_on = [null_resource.init_service_identities]
}

# ==============================================================================
# STEP 4: Create Cloud Secret Manager Secrets
# ==============================================================================

# Gemini API Key secret
resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "gemini-api-key"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "gemini_api_key_version" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = var.gemini_api_key
}

resource "google_secret_manager_secret_iam_member" "gemini_api_key_compute_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_sa}"
}

# GitHub Personal Access Token secret
resource "google_secret_manager_secret" "github_pat" {
  secret_id = "github-pat"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "github_pat_version" {
  secret      = google_secret_manager_secret.github_pat.id
  secret_data = var.github_pat
}

resource "google_secret_manager_secret_iam_member" "github_pat_compute_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.github_pat.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_sa}"
}

# ==============================================================================
# STEP 4B: Create Google Cloud Storage Bucket for OKF Dynamic Context
# ==============================================================================

resource "google_storage_bucket" "okf_bucket" {
  name                        = var.okf_bucket_name
  project                     = var.project_id
  location                    = var.okf_bucket_location
  uniform_bucket_level_access = true
  force_destroy               = true

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "okf_bucket_compute_admin" {
  bucket = google_storage_bucket.okf_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.compute_sa}"
}

resource "google_storage_bucket_iam_member" "okf_bucket_re_admin" {
  bucket = google_storage_bucket.okf_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.re_sa}"

  depends_on = [null_resource.init_service_identities]
}

# ==============================================================================
# STEP 5: Provision AlloyDB Cluster, Instance & Database
# ==============================================================================

resource "google_alloydb_cluster" "cluster" {
  cluster_id      = var.alloydb_cluster
  location        = var.region
  project         = var.project_id
  deletion_policy = "FORCE"

  initial_user {
    user     = "postgres"
    password = var.alloydb_password
  }

  psc_config {
    psc_enabled = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_alloydb_instance" "primary" {
  cluster       = google_alloydb_cluster.cluster.name
  instance_id   = var.alloydb_instance
  instance_type = "PRIMARY"

  machine_config {
    cpu_count = 2
  }

  psc_instance_config {
    allowed_consumer_projects = [local.project_number]
  }

  database_flags = {
    "alloydb.iam_authentication" = "on"
  }

  client_connection_config {
    ssl_config {
      ssl_mode = "ENCRYPTED_ONLY"
    }
  }
}

# ==============================================================================
# Outputs
# ==============================================================================

output "project_id" {
  description = "Google Cloud Project ID."
  value       = var.project_id
}

output "project_number" {
  description = "Google Cloud Project Number."
  value       = local.project_number
}

output "okf_bucket_url" {
  description = "GCS bucket URL for OKF dynamic context."
  value       = google_storage_bucket.okf_bucket.url
}

output "alloydb_cluster_name" {
  description = "AlloyDB cluster resource name."
  value       = google_alloydb_cluster.cluster.name
}

output "alloydb_instance_name" {
  description = "AlloyDB primary instance resource name."
  value       = google_alloydb_instance.primary.name
}
