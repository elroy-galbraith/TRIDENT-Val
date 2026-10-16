# ADR 0020: Deploy into the shared `ats-avm-jam` project, gated, single service

**Status:** Proposed · **Date:** 2026-10 · Amends [ADR 0017](0017-gcp-cloud-run-terraform-infrastructure.md)

## Context
ADR 0017 provisioned a standalone GCP project. TRIDENT-Val now deploys beside the ATS AVM
platform in `ats-avm-jam`, and the new `/listings` explorer reads BigQuery
`listings_raw.listing_observation_raw`. The app ships PoC demo credentials.

## Decision
- **Own state, own bucket** (`ats-avm-jam-trident-val-tfstate`), applied by impersonating
  `terraform@ats-avm-jam`, per the ats_avm access model. No shared state.
- **Not public by default.** Cloud Run IAM (`run.invoker` for named users), no `allUsers`.
- **One Cloud Run service with two containers** (nginx ingress + FastAPI sidecar) instead
  of two services. A gated backend service cannot be called by nginx without ID-token
  plumbing; co-locating keeps a single IAM gate and the same-origin `/api/*` proxy, with
  no backend URL exposed. CI deploys both images with one `gcloud run deploy`.
- **Least privilege in a shared project:** one runtime SA with `cloudsql.client`,
  `bigquery.jobUser` (project) and `bigquery.dataViewer` on `listings_raw` only. Deployer
  roles are scoped to this stack's repo, service and runtime SA.
- **No billing module.** The project already has a budget; this stack adds none.
- Fixed a latent bug: `secret_version_keys` was derived from resource attributes, which
  made `for_each` unknown and fails a first apply from empty state.

## Consequences
- Access needs gcloud (`run services proxy`) until IAP or a load balancer is added.
- Frontend and backend scale together; backend cold start gates frontend readiness.
- The first deploy needs real images pushed by hand (the sidecar probe rejects the
  placeholder image); CI handles later deploys.
- The `gcloud run deploy --container` CI flow is not yet exercised end to end.
