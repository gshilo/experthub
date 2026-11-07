data "google_project" "current" {
  project_id = var.project_id
}

# ==============================================================================
# 1. API Services Enablement
# ==============================================================================
locals {
  required_services = [
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "bigquery.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "storage.googleapis.com"
  ]
}

resource "google_project_service" "apis" {
  for_each                   = toset(local.required_services)
  project                    = var.project_id
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}

# ==============================================================================
# 2. Service Account & IAM Roles
# ==============================================================================
resource "google_service_account" "app_sa" {
  count        = var.use_existing_service_account ? 0 : 1
  account_id   = var.service_account_id
  display_name = "Experthub Application Service Account"
  description  = "Dedicated service account for Experthub Cloud Run and Vertex AI agents"
  project      = var.project_id

  depends_on = [google_project_service.apis]
}

locals {
  app_service_account_email = var.use_existing_service_account ? (
    var.existing_service_account_email != "" ? var.existing_service_account_email : "${data.google_project.current.number}-compute@developer.gserviceaccount.com"
  ) : google_service_account.app_sa[0].email

  sa_roles = [
    "roles/secretmanager.secretAccessor",
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/aiplatform.user",
    "roles/alloydb.client",
    "roles/run.invoker",
    "roles/storage.admin",
    "roles/artifactregistry.writer",
    "roles/logging.logWriter"
  ]
}

resource "google_project_iam_member" "sa_permissions" {
  for_each = toset(local.sa_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${local.app_service_account_email}"

  depends_on = [google_project_service.apis]
}

# Vertex AI Reasoning Engine / Agent Engine Service Agent IAM permissions
locals {
  reasoning_engine_sa_email = "service-${data.google_project.current.number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
  reasoning_engine_roles = [
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/secretmanager.secretAccessor",
    "roles/alloydb.client",
    "roles/storage.objectAdmin"
  ]
}

resource "google_project_iam_member" "reasoning_engine_permissions" {
  for_each = (var.enable_reasoning_engine_iam || var.deploy_vertex_agents) ? toset(local.reasoning_engine_roles) : toset([])
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${local.reasoning_engine_sa_email}"

  depends_on = [
    google_project_service.apis,
    null_resource.deploy_customer_service_agent,
    null_resource.deploy_customer_agent,
    null_resource.deploy_auditor_agent
  ]
}

# ==============================================================================
# 3. Google Cloud Secret Manager (GitHub PAT for OKF Rules)
# ==============================================================================
resource "google_secret_manager_secret" "github_pat" {
  secret_id = var.secret_name
  project   = var.project_id

  labels = {
    app       = "experthub"
    component = "github-okf"
  }

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "github_pat_version" {
  count       = var.github_pat != "" ? 1 : 0
  secret      = google_secret_manager_secret.github_pat.id
  secret_data = var.github_pat
}

resource "google_secret_manager_secret_iam_member" "sa_secret_access" {
  secret_id = google_secret_manager_secret.github_pat.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.app_service_account_email}"
}


resource "google_secret_manager_secret" "github_deploy_key" {
  secret_id = "github-deploy-key"
  project   = var.project_id

  labels = {
    app       = "experthub"
    component = "github-deploy-key"
  }

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "sa_deploy_key_access" {
  secret_id = google_secret_manager_secret.github_deploy_key.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.app_service_account_email}"
}

# ==============================================================================
# 3c. Google Cloud Secret Manager (Gemini API Key)
# ==============================================================================
resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "gemini-api-key"
  project   = var.project_id

  labels = {
    app       = "experthub"
    component = "gemini-api"
  }

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "sa_gemini_api_key_access" {
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.app_service_account_email}"
}

# ==============================================================================
# 4. BigQuery Telemetry & Rating Datasets and Tables
# ==============================================================================

# Telemetry dataset for Agent Analytics Plugin
resource "google_bigquery_dataset" "agent_telemetry" {
  dataset_id                 = "agent_telemetry"
  friendly_name              = "Agent Analytics Telemetry"
  description                = "Telemetry dataset populated by ADK 2.0 Agent Analytics Plugin"
  location                   = var.bq_location
  project                    = var.project_id
  delete_contents_on_destroy = false

  labels = {
    app       = "experthub"
    component = "telemetry"
  }

  depends_on = [google_project_service.apis]
}

# Demo dataset for Customer Ratings
resource "google_bigquery_dataset" "demo" {
  dataset_id                 = "demo"
  friendly_name              = "ApexHome Customer Ratings"
  description                = "Customer ratings and feedback dataset for ApexHome & Electro demo"
  location                   = var.bq_location
  project                    = var.project_id
  delete_contents_on_destroy = false

  labels = {
    app       = "experthub"
    component = "ratings"
  }

  depends_on = [google_project_service.apis]
}

# Customer Ratings Table
resource "google_bigquery_table" "customer_ratings" {
  dataset_id          = google_bigquery_dataset.demo.dataset_id
  table_id            = "customer_ratings"
  project             = var.project_id
  description         = "Customer post-conversation evaluation ratings (1-5) and feedback"
  deletion_protection = false

  schema = jsonencode([
    {
      name = "customer_id"
      type = "INTEGER"
    },
    {
      name = "customer_name"
      type = "STRING"
    },
    {
      name = "rating"
      type = "INTEGER"
    },
    {
      name = "description"
      type = "STRING"
    },
    {
      name = "timestamp"
      type = "TIMESTAMP"
      mode = "NULLABLE"
    }
  ])

  labels = {
    app = "experthub"
  }
}

# ==============================================================================
# 5. Artifact Registry (Frontend Docker Container Repository)
# ==============================================================================
resource "google_artifact_registry_repository" "frontend_repo" {
  repository_id = var.artifact_repository_id
  location      = var.region
  project       = var.project_id
  description   = "Docker repository for Experthub Cloud Run frontend"
  format        = "DOCKER"

  labels = {
    app = "experthub"
  }

  depends_on = [google_project_service.apis]
}

# ==============================================================================
# 6. Container Image Build (Optional automated Cloud Build)
# ==============================================================================
locals {
  default_image_tag  = "latest"
  target_image_uri   = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repository_id}/experthub-frontend:${local.default_image_tag}"
  frontend_image_url = var.frontend_image != "" ? var.frontend_image : local.target_image_uri
}

resource "null_resource" "build_frontend" {
  count = var.build_frontend_image ? 1 : 0

  triggers = {
    dockerfile_sha       = filesha256("${path.module}/../Dockerfile")
    app_sha              = filesha256("${path.module}/../frontend/app.py")
    template_sha         = filesha256("${path.module}/../frontend/templates/index.html")
    auditor_sha          = filesha256("${path.module}/../auditor_agent/agent.py")
    customer_service_sha = filesha256("${path.module}/../customer_service_agent/agent.py")
  }

  provisioner "local-exec" {
    command = "gcloud builds submit --project=${var.project_id} --tag=${local.target_image_uri} ${path.module}/.."
  }

  depends_on = [
    google_artifact_registry_repository.frontend_repo,
    google_project_service.apis,
    google_project_iam_member.sa_permissions
  ]
}

# ==============================================================================
# 7. Vertex AI Agent Engine Deployment Provisioners (Automated by default)
# ==============================================================================
resource "google_compute_network_attachment" "agent_engine_psc" {
  name                  = "agent-engine-psc-na"
  project               = var.project_id
  region                = var.region
  description           = "Private Service Connect network attachment for Vertex AI Agent Engine"
  connection_preference = "ACCEPT_AUTOMATIC"

  subnetworks = [
    "projects/${var.project_id}/regions/${var.region}/subnetworks/default"
  ]

  depends_on = [google_project_service.apis]
}

resource "null_resource" "prepare_agent_venv" {
  count = var.deploy_vertex_agents ? 1 : 0

  triggers = {
    cs_reqs   = filesha256("${path.module}/../customer_service_agent/requirements.txt")
    cust_reqs = filesha256("${path.module}/../customer_agent/requirements.txt")
    aud_reqs  = filesha256("${path.module}/../auditor_agent/requirements.txt")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "test -x .venv/bin/adk || (python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r customer_service_agent/requirements.txt -r customer_agent/requirements.txt -r auditor_agent/requirements.txt)"
  }
}

resource "null_resource" "deploy_customer_service_agent" {
  count = var.deploy_vertex_agents ? 1 : 0

  triggers = {
    project_id = var.project_id
    region     = var.region
    agent_code = filesha256("${path.module}/../customer_service_agent/agent.py")
    agent_md   = filesha256("${path.module}/../customer_service_agent/AGENT.md")
    reqs       = filesha256("${path.module}/../customer_service_agent/requirements.txt")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = ".venv/bin/python3 customer_service_agent/deploy.py --project=${var.project_id} --region=${var.region} --otel_to_cloud"
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret.github_pat,
    google_bigquery_dataset.agent_telemetry,
    null_resource.prepare_agent_venv
  ]
}

resource "null_resource" "deploy_customer_agent" {
  count = var.deploy_vertex_agents ? 1 : 0

  triggers = {
    project_id = var.project_id
    region     = var.region
    agent_code = filesha256("${path.module}/../customer_agent/agent.py")
    agent_md   = filesha256("${path.module}/../customer_agent/AGENT.md")
    reqs       = filesha256("${path.module}/../customer_agent/requirements.txt")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = ".venv/bin/python3 customer_agent/deploy.py --project=${var.project_id} --region=${var.region} --otel_to_cloud"
  }

  depends_on = [
    google_project_service.apis,
    google_bigquery_table.customer_ratings,
    google_compute_network_attachment.agent_engine_psc,
    null_resource.prepare_agent_venv
  ]
}

resource "null_resource" "deploy_auditor_agent" {
  count = var.deploy_vertex_agents ? 1 : 0

  triggers = {
    project_id = var.project_id
    region     = var.region
    agent_code = filesha256("${path.module}/../auditor_agent/agent.py")
    agent_md   = filesha256("${path.module}/../auditor_agent/AGENT.md")
    reqs       = filesha256("${path.module}/../auditor_agent/requirements.txt")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = ".venv/bin/python3 auditor_agent/deploy.py --project=${var.project_id} --region=${var.region} --otel_to_cloud"
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret.github_pat,
    google_bigquery_dataset.agent_telemetry,
    google_bigquery_table.customer_ratings,
    null_resource.prepare_agent_venv
  ]
}

# ==============================================================================
# 8. Google Cloud Run Service (Frontend Web Application)
# ==============================================================================
resource "google_cloud_run_v2_service" "frontend" {
  name                 = var.frontend_service_name
  location             = var.region
  project              = var.project_id
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = var.invoker_iam_disabled
  deletion_protection  = false

  template {
    service_account = local.app_service_account_email
    timeout         = "300s"

    scaling {
      max_instance_count = 100
    }

    containers {
      image = local.frontend_image_url

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "BQ_LOCATION"
        value = var.bq_location
      }
      env {
        name  = "GITHUB_SECRET_NAME"
        value = var.secret_name
      }
      env {
        name  = "CUSTOMER_SERVICE_AGENT_ID"
        value = var.customer_service_agent_id
      }
      env {
        name  = "CUSTOMER_AGENT_ID"
        value = var.customer_agent_id
      }
      env {
        name  = "AUDITOR_AGENT_ID"
        value = var.auditor_agent_id
      }

      startup_probe {
        period_seconds    = 240
        timeout_seconds   = 240
        failure_threshold = 1
        tcp_socket {
          port = 8080
        }
      }
    }
  }

  labels = {
    app       = "experthub"
    component = "frontend"
  }

  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.frontend_repo,
    null_resource.build_frontend,
    null_resource.deploy_customer_service_agent,
    null_resource.deploy_customer_agent,
    null_resource.deploy_auditor_agent
  ]
}

# Allow unauthenticated web traffic for the demo frontend (if organization policy permits allUsers)
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  count    = var.allow_public_allusers ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
