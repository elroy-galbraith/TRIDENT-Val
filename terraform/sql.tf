# Cloud SQL instance names are reserved for ~7 days after deletion, so a random
# suffix avoids a name clash if the instance is ever destroyed and recreated.
resource "random_id" "db_suffix" {
  byte_length = 2
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "main" {
  project             = var.project_id
  name                = "${var.app_name}-db-${random_id.db_suffix.hex}"
  region              = var.region
  database_version    = var.db_version
  deletion_protection = var.db_deletion_protection

  settings {
    edition           = "ENTERPRISE"
    tier              = var.db_tier
    availability_type = "ZONAL"
    disk_autoresize   = true
    # Current usage is a 10GB minimum-size disk holding ~2.9k demo properties — 20GB is
    # generous headroom while still capping a runaway/looping write from silently
    # growing the disk (and the bill) unbounded.
    disk_autoresize_limit = 20

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = false
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "app" {
  project  = var.project_id
  name     = var.db_name
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "app" {
  project  = var.project_id
  name     = var.db_user
  instance = google_sql_database_instance.main.name
  password = random_password.db_password.result
}
