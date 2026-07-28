resource "google_cloud_run_v2_service" "backend" {
  project             = var.project_id
  name                = "${var.app_name}-backend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = merge(local.common_labels, { component = "backend" })

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
        # Explicitly set: setting `resources.limits` at all makes the provider
        # default cpu_idle to false (CPU always allocated), which needs >=512Mi
        # and defeats scale-to-zero cost savings. true restores the normal
        # Cloud Run default (CPU only allocated while handling a request).
        cpu_idle = true
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

      # Omitted entirely (rather than pointed at a "latest" version that may not
      # exist yet) when the corresponding tfvar is left blank — see secrets.tf.
      dynamic "env" {
        for_each = contains(local.secret_version_keys, "copilot-provider-api-key") ? [1] : []
        content {
          name = "COPILOT_PROVIDER_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this["copilot-provider-api-key"].secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = contains(local.secret_version_keys, "report-llm-provider-api-key") ? [1] : []
        content {
          name = "REPORT_LLM_PROVIDER_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this["report-llm-provider-api-key"].secret_id
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        # CMD runs scripts/wait_and_seed.py before uvicorn ever binds the port — up to 60s
        # of DB-connect retries, then (on a fresh DB) a full portfolio seed/shadow-scoring
        # pass plus bcrypt user hashing. Budget generously for that cold-start path; once
        # seeded, later cold starts return in a couple seconds and the probe succeeds early.
        http_get {
          path = "/api/v1/health"
        }
        initial_delay_seconds = 10
        period_seconds        = 10
        timeout_seconds       = 3
        failure_threshold     = 60
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
  labels              = merge(local.common_labels, { component = "frontend" })

  template {
    service_account = google_service_account.frontend.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.frontend_max_instances
    }

    containers {
      image = var.frontend_image

      resources {
        cpu_idle = true
        limits = {
          cpu    = var.frontend_cpu
          memory = var.frontend_memory
        }
      }

      # Templated into nginx's reverse-proxy target for /api/* at container start
      # (see frontend/default.conf.template) — Cloud Run only knows the backend's
      # URL after Terraform creates it, so this can't be baked in at build time.
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
