variable "project_id" {
  description = "GCP project ID to deploy into."
  type        = string
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
    Backend container image. Left as the Cloud Run hello-world placeholder on first
    apply; the GitHub Actions workflow deploys the real image afterwards and
    Terraform is told to ignore drift on this field (see cloud_run.tf) so it doesn't
    fight CI/CD deploys.
  EOT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "frontend_image" {
  description = "Frontend container image. Same placeholder/ignore_changes treatment as backend_image."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "backend_cpu" {
  type    = string
  default = "1"
}

variable "backend_memory" {
  type    = string
  default = "512Mi"
}

variable "backend_max_instances" {
  type    = number
  default = 3
}

variable "frontend_cpu" {
  type    = string
  default = "1"
}

variable "frontend_memory" {
  type    = string
  default = "256Mi"
}

variable "frontend_max_instances" {
  type    = number
  default = 3
}

variable "allow_unauthenticated" {
  description = <<-EOT
    Grant public (allUsers) invoker access on both Cloud Run services, mirroring the
    current Render setup where the frontend and backend are both public HTTPS
    endpoints (the frontend reverse-proxies /api/* to the backend server-side, so
    browser requests stay same-origin even though the backend URL itself is public).
    Turn off only if you're ready to also add service-to-service auth.
  EOT
  type        = bool
  default     = true
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
