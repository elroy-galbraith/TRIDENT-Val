resource "google_artifact_registry_repository" "docker" {
  project       = var.project_id
  location      = var.region
  repository_id = var.app_name
  format        = "DOCKER"
  description   = "Backend and frontend container images for ${var.app_name}."

  # CI pushes a new backend/frontend image, tagged with the deploying commit SHA, on
  # every push to main — with no cleanup, storage grows unbounded forever. Keep the 10
  # most recent versions of each image outright, and beyond that, only prune ones
  # older than 30 days (so a recent rollback target is never at risk of deletion).
  cleanup_policies {
    id     = "keep-minimum-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  cleanup_policies {
    id     = "delete-old-versions"
    action = "DELETE"
    condition {
      older_than = "2592000s"
    }
  }

  depends_on = [google_project_service.apis]
}
