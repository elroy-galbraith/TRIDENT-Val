# ADR 0017: GCP (Cloud Run + Cloud SQL) via Terraform, replacing Render

**Status:** Accepted · **Date:** 2026-07

## Context
The PoC has run on Render (`render.yaml`): a free-tier managed Postgres, a Docker web
service for the backend, and a static site for the frontend with a server-side rewrite
of `/api/*` to the backend. That's cheap and simple, but unmanaged (config lives only
in the Render dashboard beyond `render.yaml`), free-tier services spin down after 15
minutes idle, and there's no CI/CD — deploys are whatever Render's GitHub integration
does on push, with no build/test gate.

Moving off Render, the app itself doesn't need to change shape: same Docker backend,
same static-frontend-with-reverse-proxy pattern (`frontend/default.conf.template`),
same Postgres. What's needed is a cloud target the team can run infra-as-code against,
with real CI/CD.

## Decision
Google Cloud Run for both the backend and frontend containers, Cloud SQL for Postgres,
all provisioned by Terraform (`terraform/`):

- **Cloud Run** over GKE/Compute Engine: same request-driven, scale-to-zero model the
  Render free tier already had, without cluster or VM operations. Matches the modular
  monolith's current scale (ADR 0015) — nothing here needs orchestration yet.
- **Cloud SQL (Postgres)** over Cloud Spanner/AlloyDB: cheapest managed Postgres that's
  a drop-in for the existing SQLAlchemy models; connects to Cloud Run over the built-in
  Cloud SQL Auth Proxy socket, no VPC connector needed.
- **Artifact Registry + Secret Manager**: image storage and secret storage that Cloud
  Run reads from natively, no extra glue.
- **Workload Identity Federation** for GitHub Actions: the deploy pipeline
  authenticates to GCP via short-lived OIDC tokens scoped to this repo, not an
  exported service-account JSON key sitting in GitHub secrets.
- **Terraform owns infra, GitHub Actions owns images**: Terraform creates each Cloud
  Run service once (with a placeholder image) and is told to ignore drift on the image
  field; CI/CD's job is purely `docker build && gcloud run deploy --image=...` on every
  push to `main`. Keeps "what's the infra" and "what's currently deployed" as separate,
  non-conflicting concerns.
- **Public backend, same-origin frontend proxy**: preserved as-is from the Render setup
  (`render.yaml`'s rewrite rule) rather than re-architected into private
  ingress + service-to-service auth. The frontend's nginx still does the
  `/api/*` reverse proxy server-side, so the browser only ever sees one origin and the
  session cookie stays same-origin; the backend's own URL being publicly reachable is
  no less exposed than it was on Render.

## Consequences
- One `terraform apply` reproduces the whole environment (Cloud Run, Cloud SQL,
  registry, secrets, IAM, WIF) from source, instead of Render dashboard clicks.
- CI/CD gives every push to `main` an automatic build + deploy, with the deploy step
  cleanly separated from infra changes.
- Cloud SQL's cheapest tier (`db-f1-micro`, shared-core) is not production-grade — an
  intentional carry-over of the PoC's Render-free-tier posture, sized for now, not for
  real traffic (see `variables.tf`'s `db_tier` for the upgrade path).
- Terraform state (in a GCS bucket, per `terraform/versions.tf`) becomes a new piece of
  infra to bootstrap once and protect — it holds the DB password and session secret in
  plaintext, same as any Terraform state managing secrets.
- The frontend's nginx config had to become a runtime template
  (`frontend/default.conf.template`, rendered at container start by the nginx base
  image's own entrypoint) instead of a static file, since Cloud Run only assigns the
  backend's URL and the frontend's listen port after Terraform creates them — this is
  the one code-level change this migration required.

## Alternatives considered
- **GKE Autopilot:** rejected; no workload here needs pod-level control or
  multi-service orchestration Cloud Run doesn't already give for free.
- **Cloud Run + Firebase Hosting for the frontend:** rejected; would drop the
  same-origin `/api/*` reverse proxy and reopen the CORS/cookie question ADR-adjacent
  decisions elsewhere in this repo have deliberately avoided.
- **Static service-account JSON key in GitHub Secrets:** rejected in favor of Workload
  Identity Federation — no long-lived credential to leak or rotate.
- **Stay on Render, add IaC on top:** rejected; Render has no official Terraform
  provider with the coverage this needs, and the ask was explicitly to move off it.
