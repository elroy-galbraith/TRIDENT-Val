# ADR 0001: Postgres primary with SQLite zero-config fallback

**Status:** Accepted · **Date:** 2026-07

## Context
The PoC must run in two modes: a stack that mirrors the PRD (PostgreSQL, Docker) for
demos, and a zero-friction local dev loop on a Windows workstation without Docker
running. Requiring Postgres for every code change slows iteration; requiring SQLite
everywhere misrepresents the production stack.

## Decision
`DATABASE_URL` env var selects the engine. Docker Compose provisions Postgres 16 and
injects the URL; when unset, the app falls back to a SQLite file whose path is anchored
to the repository root (absolute, not cwd-relative) so the API and seed scripts always
resolve the same file regardless of working directory.

## Consequences
- One-command dev startup with no services; PRD-faithful stack under Compose.
- All schema and query code must remain dual-dialect (SQLAlchemy core types only;
  no Postgres-specific features without a fallback).
- A cwd-relative SQLite default caused a silent empty-database bug during initial
  smoke testing; the absolute-path anchor is the fix and the lesson.

## Alternatives considered
- **Postgres-only:** rejected; Docker dependency for every dev task.
- **SQLite-only:** rejected; demo must show the stack a bank would deploy.
