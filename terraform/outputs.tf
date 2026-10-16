output "app_url" {
  description = "Cloud Run URL of the app. IAM-gated unless allow_unauthenticated = true; use `gcloud run services proxy` to browse it."
  value       = google_cloud_run_v2_service.app.uri
}

output "service_name" {
  value = google_cloud_run_v2_service.app.name
}

output "artifact_registry_repository" {
  description = "Artifact Registry Docker repository, e.g. for `docker push`."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (PROJECT:REGION:INSTANCE)."
  value       = google_sql_database_instance.main.connection_name
}

output "runtime_service_account_email" {
  value = google_service_account.runtime.email
}

output "deployer_service_account_email" {
  description = "Service account GitHub Actions assumes to deploy."
  value       = google_service_account.deployer.email
}

output "workload_identity_provider" {
  description = "Full resource name of the WIF provider — set as GCP_WORKLOAD_IDENTITY_PROVIDER in GitHub."
  value       = google_iam_workload_identity_pool_provider.github.name
}
