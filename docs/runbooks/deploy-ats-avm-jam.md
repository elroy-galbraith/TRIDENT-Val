# Runbook: deploy TRIDENT-Val into `ats-avm-jam`

TRIDENT-Val runs in the same GCP project as the ATS AVM platform. Conventions come
from the ats_avm runbooks `gcp-access-and-cost-controls.md` and `gcp-local-setup.md`.
Design rationale: [ADR 0020](../adrs/0020-deploy-into-ats-avm-jam.md). Generic
background: [deployment.md](../deployment.md).

Nothing here has been applied. Every command below is for **you** to run.

## What gets created (39 resources)

- 1 Cloud Run service `trident-val` (2 containers: nginx frontend + FastAPI backend)
- 1 Cloud SQL Postgres 16 instance (`db-f1-micro`) + database + user
- Artifact Registry repo `trident-val`; 4 Secret Manager secrets
- Runtime SA `trident-val-run`, deployer SA `trident-val-gha-deployer`, a WIF pool and provider for GitHub
- IAM: runtime SA gets `bigquery.jobUser` (project) and `bigquery.dataViewer` on dataset `listings_raw` only
- Enables 9 APIs (run, sqladmin, artifactregistry, secretmanager, iam, iamcredentials, sts, cloudresourcemanager, bigquery)

Estimated cost (list prices, my estimate): about **$12-15/month**. That is Cloud SQL
`db-f1-micro` (~$8-10) plus 10 GB SSD and backups (~$2-3). Cloud Run scales to zero
(about $0 idle); Artifact Registry and Secret Manager are under $1. The existing
project budget ($100/month) covers it; this stack creates no budget. The BigQuery
1 TiB/day cap protects the explorer's queries, but nothing caps Cloud Run or Cloud SQL
spend (a known gap in the ats_avm runbook); `max_instances = 2` bounds Cloud Run.

## Access model: NOT public (decision)

`allow_unauthenticated = false` is the default. The app contains PoC demo credentials
and shares a project with AVM data, so the Cloud Run URL requires a Google identity
with `roles/run.invoker` (the `invoker_members` list). The backend has no URL of its
own; it runs beside nginx in the same instance.

To use the app, run a local authenticated proxy and open http://localhost:8080:

```bash
gcloud run services proxy trident-val --region=us-central1 --project=ats-avm-jam --port=8080
```

Trade-off: no shareable link for people without gcloud. Options for later: (a) Cloud
Run native IAP (browser Google login; needs an OAuth consent screen; not set up here),
(b) load balancer plus IAP, (c) `allow_unauthenticated = true`, only after removing the
demo users. Safari rejects `Secure` cookies on localhost; use Chrome or Firefox.

## 1. Environment (PowerShell)

```powershell
$env:CLOUDSDK_CORE_PROJECT="ats-avm-jam"; $env:GOOGLE_CLOUD_PROJECT="ats-avm-jam"; $env:GOOGLE_PROJECT="ats-avm-jam"
gcloud auth application-default login   # only if ADC is missing or expired
```

Per-shell only, same approach as gcp-local-setup.md (no machine-wide changes).

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
already has run.admin, cloudsql.admin, secretmanager.admin,
workloadIdentityPoolAdmin, bigquery.admin, projectIamAdmin, serviceAccountAdmin,
serviceUsageAdmin, storage.admin. It lacks two roles this stack needs. Run as project owner:

```bash
gcloud projects add-iam-policy-binding ats-avm-jam --member="serviceAccount:terraform@ats-avm-jam.iam.gserviceaccount.com" --role="roles/artifactregistry.admin" --condition=None --format=none
```

```bash
gcloud projects add-iam-policy-binding ats-avm-jam --member="serviceAccount:terraform@ats-avm-jam.iam.gserviceaccount.com" --role="roles/iam.serviceAccountUser" --condition=None --format=none
```

`serviceAccountUser` lets Terraform create a Cloud Run service that runs as the new
runtime SA. This edits the shared `terraform@` SA outside any Terraform state, so update
the roles list in the ats_avm runbook afterwards.

## 4. Configure and init

```powershell
$env:GOOGLE_IMPERSONATE_SERVICE_ACCOUNT="terraform@ats-avm-jam.iam.gserviceaccount.com"
cd terraform
copy terraform.tfvars.example terraform.tfvars   # adjust invoker_members if needed
terraform init
```

## 5. Bootstrap: registry first, then real images

The service's backend sidecar has a startup probe, so the Google "hello" placeholder
image cannot be used (it never serves `/api/v1/health` on 8000) and the first revision
would fail. Create the registry, push real images by hand once, then do the full apply.
CI takes over for later deploys.

```powershell
terraform apply -target=google_project_service.apis -target=google_artifact_registry_repository.docker
gcloud auth configure-docker us-central1-docker.pkg.dev
cd ..
docker build -f backend/Dockerfile -t us-central1-docker.pkg.dev/ats-avm-jam/trident-val/backend:bootstrap .
docker build -f frontend/Dockerfile -t us-central1-docker.pkg.dev/ats-avm-jam/trident-val/frontend:bootstrap ./frontend
docker push us-central1-docker.pkg.dev/ats-avm-jam/trident-val/backend:bootstrap
docker push us-central1-docker.pkg.dev/ats-avm-jam/trident-val/frontend:bootstrap
cd terraform
```

Pushing needs `artifactregistry.writer` for your own account, which project Owner
includes. Then add to `terraform.tfvars`:

```
backend_image  = "us-central1-docker.pkg.dev/ats-avm-jam/trident-val/backend:bootstrap"
frontend_image = "us-central1-docker.pkg.dev/ats-avm-jam/trident-val/frontend:bootstrap"
```

## 6. Plan and apply

```powershell
terraform plan -out=tfplan
```

Expect `Plan: 39 to add` from a clean state (slightly fewer after step 5's targeted
apply). Check that the only BigQuery IAM changes are `jobUser` on the project and
`dataViewer` on `listings_raw`. Then:

```powershell
terraform apply tfplan
```

About 10 minutes (Cloud SQL). The first revision seeds the database on cold start.

## 7. Wire up GitHub Actions

```powershell
terraform output -raw workload_identity_provider
terraform output -raw deployer_service_account_email
```

In the GitHub repo (Settings > Secrets and variables > Actions > Variables) set
`GCP_PROJECT_ID=ats-avm-jam`, `GCP_REGION=us-central1`, `GCP_WORKLOAD_IDENTITY_PROVIDER`
and `GCP_DEPLOYER_SA` from the outputs. No secrets are stored in GitHub. Later pushes
to `main` build and deploy both containers with one `gcloud run deploy`.

## 8. Open the app

```bash
gcloud run services proxy trident-val --region=us-central1 --project=ats-avm-jam --port=8080
```

## Optional: LLM keys, teardown

```bash
echo -n "sk-..." | gcloud secrets versions add trident-val-copilot-provider-api-key --data-file=- --project=ats-avm-jam
```

Teardown: set `db_deletion_protection = false`, apply, then `terraform destroy`. The
`listings_raw` IAM binding is removed with it; nothing in the AVM stack changes.

## Boundaries with the ats_avm stack

- Separate state in its own bucket; nothing is imported from or shared with `env/dev`.
- `google_project_service` here may overlap API enablement the AVM stack adds later;
  enabling an enabled API is a no-op and `disable_on_destroy = false`.
- The `dataViewer` grant is additive (`google_bigquery_dataset_iam_member`). If the
  ats_avm stack ever manages `listings_raw` ACLs authoritatively, it will remove this
  grant, so tell that team.
