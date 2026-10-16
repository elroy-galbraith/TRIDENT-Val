variable "project_id" {
  description = "GCP project ID to deploy into. Shared with the ATS AVM platform."
  type        = string
  default     = "ats-avm-jam"
}

variable "region" {
  description = "GCP region for all regional resources (Cloud Run, Cloud SQL, Artifact Registry)."
  type        = string
  default     = "us-central1"
}

variable "app_name" {
  description = "Short name used as a prefix for all resource names."
  type        = string
  default     = "trident-val"
}

variable "github_repository" {
  description = <<-EOT
    GitHub repository allowed to assume the CI/CD deploy service account via Workload
    Identity Federation, as "owner/repo" (e.g. "elroy-galbraith/trident-val"). Only
    workflow runs from this exact repo can authenticate as the deployer.
  EOT
  type        = string
  default     = "elroy-galbraith/trident-val"
}

variable "db_tier" {
  description = <<-EOT
    Cloud SQL machine tier. db-f1-micro/db-g1-small are shared-core tiers meant for
    light dev/PoC workloads, not production SLAs — bump to a db-custom-* tier before
    real traffic.
  EOT
  type        = string
  default     = "db-f1-micro"
}

variable "db_version" {
  description = "Cloud SQL Postgres major version."
  type        = string
  default     = "POSTGRES_16"
}

variable "db_name" {
  description = "Application database name."
  type        = string
  default     = "trident"
}

variable "db_user" {
  description = "Application database user."
  type        = string
  default     = "trident"
}

variable "db_deletion_protection" {
  description = "Set false only when you intend `terraform destroy` to also drop the database."
  type        = bool
  default     = true
}

variable "backend_image" {
  description = <<-EOT
    Backend container image for the FIRST apply. The default hello placeholder will
    fail the backend sidecar's startup probe, so push real images first (see
    docs/runbooks/deploy-ats-avm-jam.md step 5). CI deploys later images and
    Terraform ignores image drift (cloud_run.tf).
  EOT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "frontend_image" {
  description = "Frontend container image. Same first-apply/ignore_changes treatment as backend_image."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "backend_cpu" {
  type    = string
  default = "1"
}

variable "backend_memory" {
  type    = string
  default = "1Gi"
}

variable "frontend_cpu" {
  type    = string
  default = "1"
}

variable "frontend_memory" {
  type    = string
  default = "256Mi"
}

variable "max_instances" {
  description = "Cloud Run max instances. Each instance holds a DB connection pool, so keep this small on db-f1-micro."
  type        = number
  default     = 2
}

variable "allow_unauthenticated" {
  description = <<-EOT
    Grant public (allUsers) invoker access. DEFAULT FALSE: the app ships PoC demo
    credentials and sits in a project that also holds AVM data, so it must not be
    reachable by the open internet. With false, only principals in invoker_members can
    call the service (browse via `gcloud run services proxy`, see the runbook).
  EOT
  type        = bool
  default     = false
}

variable "invoker_members" {
  description = "IAM members allowed to call the service when allow_unauthenticated is false, e.g. [\"user:you@example.com\"]."
  type        = list(string)
  default     = []
}

variable "grant_listings_access" {
  description = "Grant the runtime SA read-only access to the AVM listings dataset (bigquery.jobUser on the project + bigquery.dataViewer on listings_dataset_id). The dataset must already exist."
  type        = bool
  default     = true
}

variable "listings_dataset_id" {
  description = "BigQuery dataset (in project_id) holding listing_observation_raw, owned by the ats_avm stack."
  type        = string
  default     = "listings_raw"
}

variable "backend_extra_env" {
  description = "Extra NON-secret env vars for the backend container (e.g. config for the /listings explorer). Secrets belong in secrets.tf."
  type        = map(string)
  default     = {}
}

variable "copilot_provider_api_key" {
  description = "Optional: API key for the AI copilot proxy (COPILOT_PROVIDER_API_KEY). Leave blank to deploy with the copilot disabled; set later via `gcloud secrets versions add`."
  type        = string
  default     = ""
  sensitive   = true
}

variable "report_llm_provider_api_key" {
  description = "Optional: API key for AI-drafted report narrative (REPORT_LLM_PROVIDER_API_KEY). Leave blank to deploy with plain (non-AI) report sections; set later via `gcloud secrets versions add`."
  type        = string
  default     = ""
  sensitive   = true
}
