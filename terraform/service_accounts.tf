# Runtime identity for the backend Cloud Run service: reads DB/session/LLM secrets,
# connects to Cloud SQL and (read-only) queries the AVM listings dataset. Deliberately
# not the project default compute SA, which is broad, in a project shared with AVM.
resource "google_service_account" "backend" {
  project      = var.project_id
  account_id   = "${var.app_name}-backend-run"
  display_name = "${var.app_name} backend (Cloud Run)"

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "backend_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Runtime identity for the frontend service: serves the static build and proxies
# /api/*, so it needs no project-level roles at all.
resource "google_service_account" "frontend" {
  project      = var.project_id
  account_id   = "${var.app_name}-frontend-run"
  display_name = "${var.app_name} frontend (Cloud Run)"

  depends_on = [google_project_service.apis]
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
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Additive (non-authoritative) so it never clobbers the dataset's existing ACL, which
# the ats_avm Terraform owns. The dataset must already exist.
resource "google_bigquery_dataset_iam_member" "runtime_listings_viewer" {
  count      = var.grant_listings_access ? 1 : 0
  project    = var.project_id
  dataset_id = var.listings_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.backend.email}"
}

# Identity GitHub Actions assumes (via Workload Identity Federation, see
# workload_identity.tf) to build and deploy on every push — no exported JSON key.
resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "${var.app_name}-gha-deployer"
  display_name = "${var.app_name} GitHub Actions deployer"

  depends_on = [google_project_service.apis]
}

# Everything below is scoped to this stack's own resources (repo / service / runtime SAs)
# rather than project-wide, because the project is shared with the AVM platform.
resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.docker.location
  repository = google_artifact_registry_repository.docker.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_developer" {
  for_each = {
    backend  = google_cloud_run_v2_service.backend
    frontend = google_cloud_run_v2_service.frontend
  }
  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a revision that runs as a runtime SAs requires actAs on it (scoped to just
# these two SAs, not project-wide serviceAccountUser).
resource "google_service_account_iam_member" "deployer_actas" {
  for_each = {
    backend  = google_service_account.backend
    frontend = google_service_account.frontend
  }
  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
