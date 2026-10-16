# ADR 0020: Deploy into the shared `ats-avm-jam` project

**Status:** Accepted · **Date:** 2026-10 · Amends [ADR 0017](0017-gcp-cloud-run-terraform-infrastructure.md)

## Context
ADR 0017 provisioned a standalone GCP project. TRIDENT-Val now deploys beside the ATS AVM
platform in `ats-avm-jam`, and the new `/listings` explorer reads BigQuery
`listings_raw.listing_observation_raw`. The app ships PoC demo credentials.

## Decision
- **Own state, own bucket** (`ats-avm-jam-trident-val-tfstate`), applied by impersonating
  `terraform@ats-avm-jam`, per the ats_avm access model. No shared state.
- **Same layout and access model as ADR 0017:** two Cloud Run services, both public
  (`allUsers` invoker), demo logins as shipped. **This is an explicit decision by the
  owner** (Elroy Galbraith): keep the existing access model, just in the new project.
- **Least privilege in a shared project:** the backend runtime SA gets `cloudsql.client`,
  `bigquery.jobUser` (project) and `bigquery.dataViewer` on `listings_raw` only; the
  frontend SA has no roles. Deployer roles are scoped to this stack's repo, services and
  runtime SAs instead of project-wide.
- **No billing module.** The project already has a budget; this stack adds none.
- Fixed a latent bug: `secret_version_keys` was derived from resource attributes, which
  made `for_each` unknown and fails a first apply from empty state.
- CI (`deploy.yml`) is unchanged, so it keeps working against the old project until the
  repo variables are flipped after the first apply.

## Risk accepted
The project also holds AVM data. The public app's backend can read `listings_raw`
(read-only, that dataset only), and the demo credentials are public knowledge. So anyone
on the internet who logs in with them can read listing data through the explorer, and
can reach the app's own demo data. Mitigations in place: read-only, one dataset, no write
roles, a 1 TiB/day BigQuery query cap and the $100 budget. Not mitigated: Cloud Run and
Cloud SQL spend are uncapped apart from `max_instances`. Revisit by removing the demo
users, gating access (IAP or service-to-service auth) or dropping
`grant_listings_access` before the listings data is sensitive.

## Consequences
- The shared project's attack surface grows by one public web app.
- The `terraform@` SA needs two added roles (artifactregistry.admin, serviceAccountUser).
- The listings grant is additive and would be removed by any authoritative ACL on the
  dataset in the ats_avm stack.
