# Changelog

All notable changes to Praxis Agents OS are documented in this file.

The format follows [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the major
version is `0`, breaking API, schema, and configuration changes may ship in a
minor release. Patch releases contain backward-compatible fixes only.

## [0.1.0] - 2026-07-28

### Added

- Password, OAuth, and TOTP authentication; secure sessions; users,
  workspaces, memberships, invitations, and role-based access.
- A Pydantic AI agent runtime with streamed conversations, typed tools,
  approval pause and resume, bounded results, cooperative cancellation,
  single-level delegation, run envelopes, and deterministic behavior
  scenarios.
- Persistent conversation history with file attachments, multimodal image
  input, token-aware trimming, and background summaries.
- Workspace skills with progressive disclosure and supporting documents.
- A knowledge base with manual, URL, and uploaded sources; background
  ingestion; hybrid keyword and semantic retrieval; citations; agent tools;
  and operator management.
- Provenance-tracked agent memories with hybrid retrieval, prompt injection,
  deduplication, version-preserving correction, archive, purge, and operator
  review.
- Agent schedules, leased execution, a generic jobs worker, and visible
  failure and approval states.
- Signed file uploads, immutable revisions, background markdown extraction,
  cloud-storage provider seams, and agent file tools.
- Immutable artifacts with approval-gated agent tools, workspace management,
  append-only edit and restore flows, sandboxed previews, and version-pinned
  anonymous share links.
- Gmail, Google Ads, Airtable, Google BigQuery, and Google Analytics
  integration packages with OAuth, API-key, and service-account connections;
  resource discovery;
  context groups; approval-aware writes; and guarded rich results.
- A typed, versioned tool catalog with workspace grants, one audited
  dispatch choke point, runtime policy enforcement, and per-call audit data.
- Audit and security event viewers, opt-in self-hosted observability, and
  explicit security middleware for CORS, CSRF, cookies, rate limiting,
  request bounds, and response headers.
- An opt-in live-model evaluation harness alongside deterministic,
  database-backed runtime scenarios.
- Reproducible local development, database-backed verification, CI,
  dependency auditing, CodeQL analysis, Dependabot updates, SHA-pinned GitHub
  Actions, OpenAPI artifact export, and API image publication to GHCR.
- A Docker-only quickstart with self-provisioned local configuration,
  migration-gated service startup, production-image smoke coverage, health
  probes, and automatic support for both Compose command styles.

### Changed

- Compose resource names changed from `praxis-agents-template-*` to
  `praxis-*`. Existing legacy-named local volumes are left intact and can be
  inspected or migrated manually; the new stack starts with a fresh database.

[0.1.0]: https://github.com/Greg-Asquith/praxis-agents-os/releases/tag/v0.1.0
