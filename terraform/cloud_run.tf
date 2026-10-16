# One Cloud Run service, two containers (multi-container / sidecar deployment):
#   frontend (ingress, nginx, serves the SPA and reverse-proxies /api/*)
#   backend  (FastAPI on localhost:8000, never exposed on its own URL)
#
# Why not two services like the original layout: the backend has a login form with PoC
# demo credentials and must not be public, but an IAM-gated backend service can't be
# called by nginx without minting ID tokens. Co-locating them means one IAM gate in
# front of everything, and the frontend still reaches the backend same-origin. See
# docs/adrs/0020 and docs/runbooks/deploy-ats-avm-jam.md.
resource "google_cloud_run_v2_service" "app" {
  project             = var.project_id
  name                = var.app_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = merge(local.common_labels, { component = "app" })

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      name  = "frontend"
      image = var.frontend_image

      ports {
        container_port = 8080
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = var.frontend_cpu
          memory = var.frontend_memory
        }
      }

      # Templated into nginx's /api/* proxy target at container start
      # (frontend/default.conf.template). Same-instance localhost, plain HTTP.
      env {
        name  = "BACKEND_URL"
        value = "http://localhost:8000"
      }

      depends_on = ["backend"]
    }

    containers {
      name  = "backend"
      image = var.backend_image

      resources {
        # cpu_idle = true: CPU only while handling a request (scale-to-zero cost).
        cpu_idle = true
        limits = {
          cpu    = var.backend_cpu
          memory = var.backend_memory
        }
      }

      # PORT is only injected into the ingress container, so the backend CMD falls
      # back to its default of 8000.

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

      # The browser reaches the app over https (run.app) or via the local proxy on
      # localhost, where Chrome/Firefox still accept Secure cookies.
      env {
        name  = "SESSION_COOKIE_SECURE"
        value = "true"
      }

      dynamic "env" {
        for_each = var.backend_extra_env
        content {
          name  = env.key
          value = env.value
        }
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
        # CMD runs scripts/wait_and_seed.py before uvicorn binds the port — up to 60s of
        # DB-connect retries, then (on a fresh DB) a full portfolio seed/shadow-scoring
        # pass plus bcrypt user hashing. Budget generously; later cold starts succeed
        # early. The frontend container waits on this probe (depends_on).
        http_get {
          path = "/api/v1/health"
          port = 8000
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

  # CI/CD deploys new images with `gcloud run deploy` after this first creates the
  # service with the hello placeholder; don't let the next apply revert them.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[1].image,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.this,
    google_secret_manager_secret_iam_member.backend_access,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = var.allow_unauthenticated ? toset([]) : toset(var.invoker_members)
  project  = var.project_id
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = each.value
}
