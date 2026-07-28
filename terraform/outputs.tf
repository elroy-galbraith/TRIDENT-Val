output "backend_url" {
  description = "Public URL of the backend Cloud Run service."
  value       = google_cloud_run_v2_service.backend.uri
}

output "frontend_url" {
  description = "Public URL of the frontend Cloud Run service — this is the app URL."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "artifact_registry_repository" {
  description = "Artifact Registry Docker repository, e.g. for `docker push`."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (PROJECT:REGION:INSTANCE)."
  value       = google_sql_database_instance.main.connection_name
}

output "deployer_service_account_email" {
  description = "Service account GitHub Actions assumes to deploy."
  value       = google_service_account.deployer.email
}

output "workload_identity_provider" {
  description = "Full resource name of the WIF provider — set as the workload_identity_provider input to google-github-actions/auth in CI."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "billing_export_dataset_id" {
  description = "BigQuery dataset to target when enabling the Billing export in the Cloud Billing console (see docs/deployment.md). Null if billing_account_id isn't set."
  value       = var.billing_account_id != "" ? google_bigquery_dataset.billing_export[0].dataset_id : null
}
