# Cost-allocation labels applied to every billable resource, so the BigQuery billing
# export (billing.tf, docs/deployment.md) can be grouped by component without
# guessing at resource names.
locals {
  common_labels = {
    app        = var.app_name
    managed-by = "terraform"
  }
}
