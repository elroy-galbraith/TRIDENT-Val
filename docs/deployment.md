# Deploying to Google Cloud (replacing Render)

Walkthrough for standing up the GCP infrastructure in `terraform/` and wiring up the
GitHub Actions pipeline in `.github/workflows/deploy.yml`. See
[ADR 0017](adrs/0017-gcp-cloud-run-terraform-infrastructure.md) for why this shape.

Everything here is a one-time setup. After it's done, deploys happen automatically on
every push to `main`.

## What you end up with

- **Cloud Run** — two services, `trident-val-backend` and `trident-val-frontend`
  (same split as Render's `trident-val-backend` / `trident-val-frontend`).
- **Cloud SQL (Postgres 16)** — replaces Render's managed Postgres.
- **Artifact Registry** — holds the Docker images GitHub Actions builds.
- **Secret Manager** — `DATABASE_URL`, `SESSION_SECRET`, and the two optional LLM API
  keys, injected into the backend container as env vars.
- **Workload Identity Federation** — lets GitHub Actions deploy without a stored
  service-account key.
- **Budget alerts + billing export dataset** (optional, see "Cost & FinOps" below) —
  spend threshold alerts and a BigQuery destination for GCP's billing export.

## 0. Prerequisites

- A GCP project with billing enabled. Note its project ID (not its display name).
- `gcloud` CLI installed and authenticated: `gcloud auth login`.
- `terraform` >= 1.7 installed ([download](https://developer.hashicorp.com/terraform/install)).
- Owner (or equivalent: Editor + Project IAM Admin + Service Usage Admin) on the
  project — the first apply enables APIs and grants IAM roles.

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login   # lets Terraform authenticate as you
```

## 1. Bootstrap the Terraform state bucket

Terraform can't create the bucket it stores its own state in, so this one step is
manual and happens before `terraform init`:

```bash
gcloud storage buckets create gs://trident-val-tfstate \
  --project=YOUR_PROJECT_ID \
  --location=us-central1 \
  --uniform-bucket-level-access
gcloud storage buckets update gs://trident-val-tfstate --versioning
```

Bucket names are globally unique across all of GCS — if `trident-val-tfstate` is
taken, pick another name and use it consistently in the next step.

Then uncomment the `backend "gcs"` block in `terraform/versions.tf` and set `bucket`
to whatever you created.

## 2. Configure variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`: set `project_id` to your GCP project ID, and check
`github_repository` matches this repo (`elroy-galbraith/trident-val`). Leave the two
API key variables blank for now — see step 6 for adding them without a full
`terraform apply`.

## 3. Apply

```bash
terraform init
terraform plan    # review what it's about to create
terraform apply
```

This takes a few minutes (Cloud SQL instance creation is the slow part). On success,
Terraform prints outputs including `backend_url`, `frontend_url`,
`deployer_service_account_email`, and `workload_identity_provider`.

At this point `frontend_url` and `backend_url` are live but serving Google's Cloud Run
"hello" placeholder image — the real app isn't deployed yet. That's expected; that's
what step 5 is for.

## 4. Wire up GitHub Actions

The workflow needs four repository **variables** (not secrets — none of these are
sensitive, since auth is via Workload Identity Federation, not a key). In the GitHub
repo: **Settings → Secrets and variables → Actions → Variables tab → New repository
variable**.

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | your project ID |
| `GCP_REGION` | `us-central1` (or whatever you set `region` to) |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `terraform output -raw workload_identity_provider` |
| `GCP_DEPLOYER_SA` | `terraform output -raw deployer_service_account_email` |

```bash
terraform output -raw workload_identity_provider
terraform output -raw deployer_service_account_email
```

## 5. First real deploy

Push to `main` (or run the workflow manually: **Actions → Deploy to Cloud Run → Run
workflow**). It builds both images, pushes them to Artifact Registry, and runs
`gcloud run deploy --image=...` against the two services Terraform created — from then
on, every push to `main` that touches `backend/`, `frontend/`, `model/`, or `scripts/`
redeploys automatically.

Watch it run under the repo's **Actions** tab. When it's green, open `frontend_url`
from step 3 — that's the app, live on GCP.

## 6. Setting the optional API keys

`COPILOT_PROVIDER_API_KEY` (AI copilot) and `REPORT_LLM_PROVIDER_API_KEY` (AI-drafted
report narrative) are optional — the app runs fine without them (see
`.env.example` at the repo root for what degrades). To turn them on after the fact,
without re-running `terraform apply`:

```bash
echo -n "sk-..." | gcloud secrets versions add trident-val-copilot-provider-api-key --data-file=-
echo -n "sk-..." | gcloud secrets versions add trident-val-report-llm-provider-api-key --data-file=-
```

Cloud Run reads the secret's `latest` version at container start, so the new value
takes effect on the next cold start / new revision — no redeploy strictly required,
though `gcloud run services update trident-val-backend --region=$REGION` forces one
immediately if you don't want to wait.

## 7. Custom domain (optional)

```bash
gcloud run domain-mappings create --service=trident-val-frontend \
  --domain=your-domain.example.com --region=$REGION
```

Follow the DNS records it prints (a `CNAME` or set of `A`/`AAAA` records at your
registrar). Cloud Run provisions and renews the TLS certificate automatically.

## Making infra changes later

Edit the `.tf` files, then from `terraform/`:

```bash
terraform plan
terraform apply
```

Common things you'll want to tune in `terraform.tfvars` as real usage shows up:
`db_tier` (Cloud SQL sizing — starts on the cheapest shared-core tier), `backend_cpu`
/ `backend_memory` / `backend_max_instances` (same for the frontend), and
`db_deletion_protection` (leave `true` outside of a throwaway/demo project).

## Cost

Cloud Run and Cloud SQL's `db-f1-micro` tier both have low idle cost (Cloud Run
scales to zero; the DB instance itself is the main fixed cost, roughly the range of a
small VM). This is sized to match Render's free tier, not for production load —
see ADR 0017's Consequences section.

## Cost & FinOps

Terraform manages two FinOps pieces, both gated on setting `billing_account_id` in
`terraform.tfvars` (find it with `gcloud billing accounts list`):

- **Budget alerts** (`terraform/billing.tf`) — a `google_billing_budget` against
  `budget_amount` (default $50/month), with alert thresholds at 50%/90%/100% of actual
  spend plus a 100%-of-*forecasted*-spend rule that fires before the month closes over
  budget. Billing Account Administrators/Users get notified by default; add more
  recipients via `budget_alert_emails`.
- **Billing export destination** — a BigQuery dataset (`billing_export_dataset_location`,
  default `US`) for GCP's detailed usage cost export. Terraform can provision the
  dataset but not the export wiring itself — enabling an export is a billing-account
  action GCP only exposes through the Console, with no Terraform resource or `gcloud`
  command behind it. That's the manual step below.
- **Cost-allocation labels** — every billable resource (Cloud Run, Cloud SQL, Artifact
  Registry, Secret Manager) carries `app`, `managed-by`, and a per-resource `component`
  label (`terraform/locals.tf`), so the export can be grouped by component without
  guessing at resource names.

Requires `roles/billing.costsManager` (or `roles/billing.admin`) on the billing account
for whoever runs `terraform apply` — a separate grant from the project-level roles in
step 0, since the budget and export dataset both reference the billing account
directly.

### 1. Enable the billing export

After `terraform apply` has created the dataset, note its ID:

```bash
terraform output -raw billing_export_dataset_id
```

Then, in the [Cloud Billing console](https://console.cloud.google.com/billing):
**Billing → Billing export → Detailed usage cost → Edit settings**, select this
project's `billing_export_dataset_id`, and save. Also turn on **Pricing export** in the
same panel — it's what lets you compute *effective* $/vCPU-hour and $/GiB-hour instead
of hardcoding list prices in queries. Data starts landing within a few hours; there's no
backfill for days before the export was enabled.

This creates two tables in the dataset: `gcp_billing_export_resource_v1_<BILLING_ACCOUNT_ID>`
(usage + cost, one row per SKU per resource per day) and `cloud_pricing_export`.

### 2. Build the rightsizing dashboard, not just a cost dashboard

A plain cost dashboard (spend over time, by service) only tells you *what you paid*.
Rightsizing needs spend compared against how much of what you provisioned actually got
used — that comparison differs by resource, because Cloud Run and Cloud SQL are billed
completely differently:

- **Cloud Run bills by actual usage** (vCPU-seconds and GiB-seconds consumed while
  handling a request, thanks to `cpu_idle = true` in `cloud_run.tf`) — so the billing
  export's `usage.amount_in_pricing_units` *is* a rightsizing signal on its own. Query it
  per service per day, divide by request count (join against Cloud Run's request-count
  metric, or approximate from Cloud Run's own logs) to get vCPU-seconds/request, and
  compare that against the provisioned ceiling (`backend_cpu`/`backend_memory` in
  `terraform.tfvars`). Consistently far below the ceiling → shrink the limit; frequently
  at or above it → that's your `backend_max_instances` headroom being eaten by
  per-request throttling, not a sizing win.
- **Cloud SQL bills flat-rate by tier**, so cost alone shows zero signal — a `db-f1-micro`
  costs the same whether it's at 5% or 95% CPU. Rightsizing it needs actual utilization,
  which lives in Cloud Monitoring, not the billing export. Two ways to get it into the
  same dashboard:
  - Easiest: Console → SQL instance → **Recommendations** tab. GCP's Active Assist
    recommender already computes tier-rightsizing suggestions from real utilization
    history — no setup required, just periodic review.
  - For a unified BigQuery view: schedule `gcloud recommender recommendations list
    --recommender=google.cloudsql.instance.PerformanceRecommender --project=$PROJECT
    --location=$REGION --format=json` (e.g. via Cloud Scheduler + a small Cloud
    Function, or even a cron'd `bq load`) into a companion table in the same dataset,
    and join it against the cost table by resource name.

Connect [Looker Studio](https://lookerstudio.google.com) to the `gcp_billing_export_resource_v1_*`
table as a BigQuery data source (start from GCP's built-in **Billing Reports** template
— Console → Billing → Reports → **Open in Looker Studio** — then extend it) and add:

- A **spend vs. provisioned-limit** table per Cloud Run service — `SUM(cost)` and
  `SUM(usage.amount_in_pricing_units)` grouped by `resource.name` and the `component`
  label, next to the static `backend_cpu`/`backend_memory` values from `terraform.tfvars`
  (enter these as a small manual/Looker Studio parameter table — the export doesn't know
  your Terraform variables).
- A **Cloud SQL utilization** chart if you built the recommender-export table, or just a
  static callout linking to the Console Recommendations tab if you didn't.
- A trend line of `SUM(cost)` against the `budget_amount` threshold, so the same
  dashboard answers both "are we about to blow the budget" and "where would trimming
  actually come from."

Because this is a single-project PoC (see ADR 0017), org-level tooling like Recommender
Hub's BigQuery export isn't set up here — the `gcloud recommender` polling approach above
covers the one resource (Cloud SQL) where cost alone can't tell you what to rightsize.

## Decommissioning Render

`render.yaml` has been removed now that the GCP deployment is confirmed live. If you
haven't already, delete the `trident-val-backend`/`trident-val-frontend` services and
the `trident-val-db` database from the Render dashboard to stop billing on that side.
