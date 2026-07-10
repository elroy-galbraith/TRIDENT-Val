resource "google_cloud_run_v2_service" "backend" {
  project             = var.project_id
  name                = "${var.app_name}-backend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.backend.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.backend_max_instances
    }

    containers {
      image = var.backend_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = var.backend_cpu
          memory = var.backend_memory
        }
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.this["database-url"].secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.this["session-secret"].secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "SESSION_COOKIE_SECURE"
        value = "true"
      }

      env {
        name = "COPILOT_PROVIDER_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.this["copilot-provider-api-key"].secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "REPORT_LLM_PROVIDER_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.this["report-llm-provider-api-key"].secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        http_get {
          path = "/api/v1/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 6
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  # CI/CD (GitHub Actions) deploys new images with `gcloud run deploy` after this
  # module first creates the service with the hello-world placeholder — Terraform
  # otherwise reverts every CI deploy back to var.backend_image on the next apply.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.this,
  ]
}

resource "google_cloud_run_v2_service" "frontend" {
  project             = var.project_id
  name                = "${var.app_name}-frontend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.frontend.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.frontend_max_instances
    }

    containers {
      image = var.frontend_image

      resources {
        limits = {
          cpu    = var.frontend_cpu
          memory = var.frontend_memory
        }
      }

      # Consumed by frontend/docker-entrypoint.sh to build nginx's reverse-proxy
      # target for /api/* at container start (see that file for why this can't be
      # baked into the image at build time — Cloud Run only knows the backend's URL
      # after Terraform creates it).
      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = google_cloud_run_v2_service.backend.location
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = google_cloud_run_v2_service.frontend.location
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
