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

## Decommissioning Render

`render.yaml` has been removed now that the GCP deployment is confirmed live. If you
haven't already, delete the `trident-val-backend`/`trident-val-frontend` services and
the `trident-val-db` database from the Render dashboard to stop billing on that side.
