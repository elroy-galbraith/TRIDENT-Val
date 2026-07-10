terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state keeps the DB password, session secret, etc. out of anyone's local
  # machine and lets GitHub Actions plan against the same state. The bucket must
  # exist before `terraform init` (Terraform can't create the thing it stores state
  # in) — see docs/deployment.md for the one-time `gcloud storage buckets create`
  # step, then uncomment this block and run `terraform init -migrate-state`.
  #
  # backend "gcs" {
  #   bucket = "trident-val-tfstate"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
