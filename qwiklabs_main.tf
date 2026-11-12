# ==============================================================================
# Qwiklabs Startup Script (main.tf) for Lab 669021
# Drop-in replacement for the Qwiklabs authoring Terraform main.tf
# ==============================================================================

data "google_project" "current" {
  project_id = var.gcp_project_id
}

data "google_compute_network" "default" {
  project = var.gcp_project_id
  name    = "default"

  depends_on = [google_project_service.project_0]
}

# Reserve an IP range for Private Service Access (PSA)
resource "google_compute_global_address" "private_ip_alloc" {
  name          = "alloydb-psa-range"
  project       = var.gcp_project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = data.google_compute_network.default.id

  depends_on = [google_project_service.project_0]
}

# Create the Private Services Networking connection
resource "google_service_networking_connection" "vpc_connection" {
  network                 = data.google_compute_network.default.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]

  depends_on = [google_project_service.project_0]
}

# Private Service Connect network attachment for Vertex AI Agent Engine
resource "google_compute_network_attachment" "agent_engine_psc" {
  name                  = "agent-engine-psc-na"
  project               = var.gcp_project_id
  region                = "us-central1"
  description           = "Private Service Connect network attachment for Vertex AI Agent Engine"
  connection_preference = "ACCEPT_AUTOMATIC"

  subnetworks = [
    "projects/${var.gcp_project_id}/regions/us-central1/subnetworks/default"
  ]

  depends_on = [google_project_service.project_0]
}

# Grant AlloyDB Client & Database User IAM roles to Default Compute Service Account
resource "google_project_iam_member" "compute_alloydb_client" {
  project = var.gcp_project_id
  role    = "roles/alloydb.client"
  member  = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"

  depends_on = [google_project_service.project_0]
}

resource "google_project_iam_member" "compute_alloydb_db_user" {
  project = var.gcp_project_id
  role    = "roles/alloydb.databaseUser"
  member  = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"

  depends_on = [google_project_service.project_0]
}

# 1. AlloyDB Cluster (Private Service Connect enabled)
resource "google_alloydb_cluster" "apex" {
  cluster_id      = "apex"
  location        = "us-central1"
  project         = var.gcp_project_id
  deletion_policy = "FORCE"

  psc_config {
    psc_enabled = true
  }

  initial_user {
    user     = "postgres"
    password = "apex1234"
  }

  depends_on = [
    google_project_service.project_0
  ]
}

# 2. Primary Instance inside the apex cluster
resource "google_alloydb_instance" "apex" {
  cluster       = google_alloydb_cluster.apex.name
  instance_id   = "apex"
  instance_type = "PRIMARY"

  machine_config {
    cpu_count = 2
  }

  psc_instance_config {
    allowed_consumer_projects = [data.google_project.current.number]
  }

  # Public IP (with no authorized_external_networks) allows Cloud Run and Agent Engine
  # to connect via the AlloyDB Python Connector (mTLS + IAM) without VPC egress/DNS setup.
  network_config {
    enable_public_ip = true
  }

  database_flags = {
    "alloydb.iam_authentication"     = "on"
    "password.enforce_complexity"    = "on"
    "password.min_pass_length"       = "8"
    "password.min_uppercase_letters" = "0"
    "password.min_lowercase_letters" = "0"
    "password.min_numerical_chars"   = "0"
    "password.min_special_chars"     = "0"
  }

  client_connection_config {
    ssl_config {
      ssl_mode = "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    }
  }

  depends_on = [google_alloydb_cluster.apex]
}

# 3. AlloyDB IAM Database User for Default Compute SA (Cloud Run frontend & agents)
resource "google_alloydb_user" "compute_sa_iam_user" {
  cluster        = google_alloydb_cluster.apex.name
  user_id        = "${data.google_project.current.number}-compute@developer"
  user_type      = "ALLOYDB_IAM_USER"
  database_roles = ["alloydbsuperuser"]

  depends_on = [
    google_alloydb_instance.apex,
    google_project_iam_member.compute_alloydb_client,
    google_project_iam_member.compute_alloydb_db_user,
  ]
}
