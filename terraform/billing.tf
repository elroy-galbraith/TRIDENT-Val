# FinOps module: budget alerts + the destination dataset for GCP's Billing export to
# BigQuery. Gated on billing_account_id so the rest of the infra still applies cleanly
# for anyone who hasn't wired up billing-account-level access yet.
#
# What Terraform can't do here: actually turning on the export (Console: Billing >
# Billing export > Detailed usage cost, target = google_bigquery_dataset.billing_export)
# is a billing-account-level action with no Terraform resource or gcloud command behind
# it, and requires Billing Account Administrator on the account itself — see
# docs/deployment.md for the manual step-by-step.

data "google_project" "this" {
  project_id = var.project_id

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_notification_channel" "budget_email" {
  for_each     = var.billing_account_id != "" ? toset(var.budget_alert_emails) : toset([])
  project      = var.project_id
  display_name = "Budget alert: ${each.value}"
  type         = "email"

  labels = {
    email_address = each.value
  }

  depends_on = [google_project_service.apis]
}

resource "google_billing_budget" "this" {
  count           = var.billing_account_id != "" ? 1 : 0
  billing_account = var.billing_account_id
  display_name    = "${var.app_name} monthly budget"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency_code
      units         = tostring(var.budget_amount)
    }
  }

  # Actual-spend warnings at 50%/90%/100%, plus a forecasted-spend rule so a runaway
  # trajectory (e.g. a stuck autoscaler) alerts before the month actually closes over
  # budget, not after.
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [for _, c in google_monitoring_notification_channel.budget_email : c.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.apis]
}

resource "google_bigquery_dataset" "billing_export" {
  count         = var.billing_account_id != "" ? 1 : 0
  project       = var.project_id
  dataset_id    = replace("${var.app_name}_billing_export", "-", "_")
  friendly_name = "${var.app_name} billing export"
  description   = "Destination for the GCP Billing detailed usage cost export. The export itself is enabled manually in the Cloud Billing console, pointed at this dataset — see docs/deployment.md."
  location      = var.billing_export_dataset_location
  labels        = merge(local.common_labels, { component = "billing-export" })

  # Billing history is exactly the kind of thing a stray `terraform destroy` shouldn't
  # take out along with the compute it's describing.
  delete_contents_on_destroy = false

  depends_on = [google_project_service.apis]
}
