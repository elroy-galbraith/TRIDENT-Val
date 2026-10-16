resource "random_password" "session_secret" {
  length  = 64
  special = false
}

locals {
  # psycopg2 Cloud SQL Unix-socket DSN — no VPC connector needed, connects over the
  # same Cloud SQL Auth Proxy sidecar Cloud Run wires up via the `cloudsql` volume
  # in cloud_run.tf. backend/app/db.py already accepts a bare postgresql:// DSN.
  database_url = "postgresql+psycopg2://${google_sql_user.app.name}:${random_password.db_password.result}@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.main.connection_name}"

  secrets = {
    database-url                = local.database_url
    session-secret              = random_password.session_secret.result
    copilot-provider-api-key    = var.copilot_provider_api_key
    report-llm-provider-api-key = var.report_llm_provider_api_key
  }

  # copilot-provider-api-key and report-llm-provider-api-key are optional and
  # default to "" � Secret Manager rejects a version with an empty payload, so
  # skip creating a version until a real value is supplied (via tfvars or
  # `gcloud secrets versions add`). The secret resource itself is still created
  # for every key so IAM access and the Cloud Run secret_key_ref can bind to it.
  #
  # Built from the input variables only (never from local.secrets): database-url
  # depends on not-yet-created resources, so filtering local.secrets by value makes
  # for_each unknown at plan time and a first apply from empty state fails.
  secret_version_keys = toset(concat(
    ["database-url", "session-secret"],
    nonsensitive(var.copilot_provider_api_key != "") ? ["copilot-provider-api-key"] : [],
    nonsensitive(var.report_llm_provider_api_key != "") ? ["report-llm-provider-api-key"] : [],
  ))
}

resource "google_secret_manager_secret" "this" {
  for_each  = local.secrets
  project   = var.project_id
  secret_id = "${var.app_name}-${each.key}"
  labels    = merge(local.common_labels, { component = "secrets" })

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "this" {
  for_each    = local.secret_version_keys
  secret      = google_secret_manager_secret.this[each.value].id
  secret_data = local.secrets[each.value]
}

# Only the backend runtime SA reads secrets — the frontend never touches them.
resource "google_secret_manager_secret_iam_member" "backend_access" {
  for_each  = google_secret_manager_secret.this
  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
