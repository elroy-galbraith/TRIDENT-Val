# Cost-allocation labels applied to every billable resource, so the project-wide
# billing export (owned by the ats_avm stack) can be filtered to this app by label.
locals {
  common_labels = {
    app        = var.app_name
    managed-by = "terraform"
  }
}
