# Runtime identity for the backend Cloud Run service: reads DB/session/LLM secrets
# and connects to Cloud SQL. Deliberately not the project default compute SA, which
# is broader than this service needs.
resource "google_service_account" "backend" {
  project      = var.project_id
  account_id   = "${var.app_name}-backend-run"
  display_name = "${var.app_name} backend (Cloud Run)"
}

resource "google_project_iam_member" "backend_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Runtime identity for the frontend Cloud Run service. It only serves the static
# build and reverse-proxies /api/*, so it needs no project-level roles at all.
resource "google_service_account" "frontend" {
  project      = var.project_id
  account_id   = "${var.app_name}-frontend-run"
  display_name = "${var.app_name} frontend (Cloud Run)"
}

# Identity GitHub Actions assumes (via Workload Identity Federation, see
# workload_identity.tf) to build and deploy on every push — no exported JSON key.
resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "${var.app_name}-gha-deployer"
  display_name = "${var.app_name} GitHub Actions deployer"
}

resource "google_project_iam_member" "deployer_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a Cloud Run revision that *runs as* backend/frontend requires the
# deployer to be able to actAs those runtime service accounts. Scoped to just
# these two SAs rather than a project-wide roles/iam.serviceAccountUser grant.
resource "google_service_account_iam_member" "deployer_actas_backend" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_actas_frontend" {
  service_account_id = google_service_account.frontend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
