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

  # State lives in its OWN bucket, not the ats_avm bucket (ats-avm-jam-tfstate): that
  # bucket is readable by the AVM data engineer via a project-level objectUser grant,
  # and this state holds the DB password and session secret in plaintext. The bucket is
  # created by hand (see docs/runbooks/deploy-ats-avm-jam.md step 2) because Terraform
  # can't create the bucket that stores its own state.
  backend "gcs" {
    bucket = "ats-avm-jam-trident-val-tfstate"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
