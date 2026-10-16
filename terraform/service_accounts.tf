# Single runtime identity for the trident-val Cloud Run service (frontend + backend
# containers share an instance and therefore a service account). Deliberately not the
# project default compute SA: this is a shared project and that SA is broad.
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${var.app_name}-run"
  display_name = "${var.app_name} runtime (Cloud Run)"

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "runtime_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# --- Read-only access to the ATS AVM listings data (for the /listings explorer) ---
#
# bigquery.jobUser is project-level because query jobs run in a project; on its own it
# can run queries but read nothing. dataViewer is granted on the one dataset only, so
# the app cannot read any other AVM dataset and cannot write anywhere in BigQuery.
resource "google_project_iam_member" "runtime_bigquery_job_user" {
  count   = var.grant_listings_access ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Additive (non-authoritative) so it never clobbers the dataset's existing ACL, which
# the ats_avm Terraform owns. The dataset must already exist.
resource "google_bigquery_dataset_iam_member" "runtime_listings_viewer" {
  count      = var.grant_listings_access ? 1 : 0
  project    = var.project_id
  dataset_id = var.listings_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

# Identity GitHub Actions assumes (via Workload Identity Federation, see
# workload_identity.tf) to build and deploy on every push — no exported JSON key.
resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "${var.app_name}-gha-deployer"
  display_name = "${var.app_name} GitHub Actions deployer"

  depends_on = [google_project_service.apis]
}

# Everything below is scoped to this stack's own resources (repo / service / runtime SA)
# rather than project-wide, because the project is shared with the AVM platform.
resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.docker.location
  repository = google_artifact_registry_repository.docker.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_developer" {
  project  = var.project_id
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a revision that runs as the runtime SA requires actAs on it.
resource "google_service_account_iam_member" "deployer_actas_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
