output "frontend_url" {
  description = "The public URL of the deployed Cloud Run Frontend Web Application."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "frontend_service_name" {
  description = "Cloud Run service resource name."
  value       = google_cloud_run_v2_service.frontend.name
}

output "bigquery_datasets" {
  description = "BigQuery datasets provisioned for the demo."
  value = {
    agent_telemetry = google_bigquery_dataset.agent_telemetry.dataset_id
    demo            = google_bigquery_dataset.demo.dataset_id
  }
}

output "customer_ratings_table" {
  description = "BigQuery customer ratings table resource ID."
  value       = "${google_bigquery_dataset.demo.dataset_id}.${google_bigquery_table.customer_ratings.table_id}"
}

output "secret_manager_github_pat" {
  description = "Secret Manager secret name for GitHub Personal Access Token."
  value       = google_secret_manager_secret.github_pat.name
}

output "secret_manager_gemini_api_key" {
  description = "Secret Manager secret name for Gemini API Key."
  value       = google_secret_manager_secret.gemini_api_key.name
}

output "artifact_registry_repository" {
  description = "Artifact Registry Docker repository."
  value       = google_artifact_registry_repository.frontend_repo.name
}

output "vertex_ai_agent_ids" {
  description = "Vertex AI Agent Engine (Reasoning Engine) IDs configured for the demo."
  value = {
    customer_service_agent = var.customer_service_agent_id
    customer_agent         = var.customer_agent_id
    auditor_agent          = var.auditor_agent_id
  }
}

output "service_account_email" {
  description = "Service account email attached to the Cloud Run workload."
  value       = local.app_service_account_email
}

output "project_id" {
  description = "Google Cloud Project ID."
  value       = var.project_id
}

output "region" {
  description = "Google Cloud Region."
  value       = var.region
}
