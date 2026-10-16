# Runbook: deploy TRIDENT-Val into `ats-avm-jam`

TRIDENT-Val runs in the same GCP project as the ATS AVM platform. Conventions come
from the ats_avm runbooks `gcp-access-and-cost-controls.md` and `gcp-local-setup.md`.
Design record: [ADR 0020](../adrs/0020-deploy-into-ats-avm-jam.md). Generic background:
[deployment.md](../deployment.md).

Nothing here has been applied. Every command below is for **you** to run.

## What gets created (44 resources)

- 2 Cloud Run services: `trident-val-backend`, `trident-val-frontend` (same layout as before)
- 1 Cloud SQL Postgres 16 instance (`db-f1-micro`) + database + user
- Artifact Registry repo `trident-val`; 4 Secret Manager secrets
- Service accounts: `trident-val-backend-run`, `trident-val-frontend-run`, `trident-val-gha-deployer`; a WIF pool and provider for GitHub
- Listings access (read-only): backend SA gets `bigquery.jobUser` (project) and `bigquery.dataViewer` on dataset `listings_raw` only
- Deployer IAM scoped to this stack's repo, two services and two runtime SAs (nothing project-wide)
- Enables 9 APIs (run, sqladmin, artifactregistry, secretmanager, iam, iamcredentials, sts, cloudresourcemanager, bigquery)

Estimated cost (list prices, my estimate): about **$12-15/month**: Cloud SQL
`db-f1-micro` (~$8-10) plus 10 GB SSD and backups (~$2-3). Cloud Run scales to zero;
Artifact Registry and Secret Manager are under $1. The existing project budget
($100/month) covers it; no budget is created here. The BigQuery 1 TiB/day cap limits
the explorer's queries; nothing caps Cloud Run or Cloud SQL spend (known gap in the
ats_avm runbook); `*_max_instances = 3` bounds Cloud Run.

## Access model: public, as before (owner decision)

Both services grant `allUsers` invoker (`allow_unauthenticated = true`), identical to
the current TRIDENT-Val deployment, with the PoC demo logins as shipped. This was an
explicit decision by the owner. Risk, recorded in ADR 0020: this project also holds AVM
data, and the public app's backend can read `listings_raw` (read-only). Anyone who
logs in with the demo credentials can use the listings explorer to read that dataset.
To tighten later without redesign: remove the demo users, or set
`allow_unauthenticated = false` (needs service-to-service auth work between the two
services), or limit `grant_listings_access`.

## 1. Environment (PowerShell)

```powershell
$env:CLOUDSDK_CORE_PROJECT="ats-avm-jam"; $env:GOOGLE_CLOUD_PROJECT="ats-avm-jam"; $env:GOOGLE_PROJECT="ats-avm-jam"
gcloud auth application-default login   # only if ADC is missing or expired
```

Per-shell only, same approach as gcp-local-setup.md.

## 2. One-time: state bucket (its own bucket, not the ats_avm one)

The ats_avm state bucket is readable by the data engineer (accepted risk in that
runbook) and this state holds the DB password, so this stack gets its own bucket.

```bash
gcloud storage buckets create gs://ats-avm-jam-trident-val-tfstate --project=ats-avm-jam --location=us-central1 --uniform-bucket-level-access --public-access-prevention
```

```bash
gcloud storage buckets update gs://ats-avm-jam-trident-val-tfstate --versioning
```

His project-level `storage.objectUser` also covers this bucket. Extend the IAM
condition from the ats_avm runbook to exclude `ats-avm-jam-trident-val-tfstate` too.

## 3. One-time: two extra roles for the `terraform@` service account

Checked on 2026-10-16 (read-only): `terraform@ats-avm-jam.iam.gserviceaccount.com`
already has run.admin, cloudsql.admin, secretmanager.admin, workloadIdentityPoolAdmin,
bigquery.admin, projectIamAdmin, serviceAccountAdmin, serviceUsageAdmin, storage.admin.
It lacks two roles this stack needs. Run as project owner:

```bash
gcloud projects add-iam-policy-binding ats-avm-jam --member="serviceAccount:terraform@ats-avm-jam.iam.gserviceaccount.com" --role="roles/artifactregistry.admin" --condition=None --format=none
```

```bash
gcloud projects add-iam-policy-binding ats-avm-jam --member="serviceAccount:terraform@ats-avm-jam.iam.gserviceaccount.com" --role="roles/iam.serviceAccountUser" --condition=None --format=none
```

`serviceAccountUser` lets Terraform create Cloud Run services that run as the new
runtime SAs. This edits the shared `terraform@` SA outside any Terraform state, so
update the roles list in the ats_avm runbook afterwards.

## 4. Configure, plan, apply

```powershell
$env:GOOGLE_IMPERSONATE_SERVICE_ACCOUNT="terraform@ats-avm-jam.iam.gserviceaccount.com"
cd terraform
copy terraform.tfvars.example terraform.tfvars
terraform init
terraform plan -out=tfplan
```

Expect `Plan: 44 to add, 0 to change, 0 to destroy.` Check that the only BigQuery IAM
changes are `jobUser` on the project and `dataViewer` on `listings_raw`. Then:

```powershell
terraform apply tfplan
```

About 10 minutes (Cloud SQL). Both services start on Google's placeholder image. If the
apply fails because the backend's startup probe (`/api/v1/health`) rejects the
placeholder, push real images once (build with the commands in
[deployment.md](../deployment.md) step 5's workflow: `backend/Dockerfile` from the repo
root, `frontend/Dockerfile` from `./frontend`) to
`us-central1-docker.pkg.dev/ats-avm-jam/trident-val/{backend,frontend}:bootstrap`, set
`backend_image` / `frontend_image` in `terraform.tfvars`, and re-run plan and apply.
I could not verify which case applies.

## 5. Flip CI to the new project (ORDER MATTERS)

`deploy.yml` deploys to whatever project the GitHub repo variables name. Until you flip
them, every push to `main` (including merging this branch) keeps deploying to the OLD
project. That is intentional: this branch's workflow is unchanged and works against
both. Do it in this order:

1. Apply (step 4) and keep the old deployment running.
2. Read the new values:
   ```powershell
   terraform output -raw workload_identity_provider
   terraform output -raw deployer_service_account_email
   ```
3. In GitHub (Settings > Secrets and variables > Actions > Variables) change
   `GCP_PROJECT_ID=ats-avm-jam`, `GCP_REGION=us-central1`,
   `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SA`.
4. Run the workflow manually (Actions > Deploy to Cloud Run > Run workflow). It replaces
   the placeholder images in the new project.
5. Open `frontend_url` (`terraform output -raw frontend_url`) and check it works.
6. Only then retire the old project's services and DB (see deployment.md).

Merging this branch to `main` before step 3 is safe; merging does not touch the new project.

## Optional: LLM keys, teardown

```bash
echo -n "sk-..." | gcloud secrets versions add trident-val-copilot-provider-api-key --data-file=- --project=ats-avm-jam
```

Teardown: set `db_deletion_protection = false`, apply, then `terraform destroy`. The
`listings_raw` IAM binding goes with it; nothing in the AVM stack changes.

## Boundaries with the ats_avm stack

- Separate state in its own bucket; nothing is imported from or shared with `env/dev`.
- `google_project_service` here may overlap API enablement the AVM stack adds later;
  enabling an enabled API is a no-op and `disable_on_destroy = false`.
- The `dataViewer` grant is additive (`google_bigquery_dataset_iam_member`). If the
  ats_avm stack ever manages `listings_raw` ACLs authoritatively, it will remove this
  grant, so tell that team.
