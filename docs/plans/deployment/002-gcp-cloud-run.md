<!-- docs/plans/deployment/002-gcp-cloud-run.md -->

# 002 — GCP: Cloud Run services + Cloud Run Jobs, scale to zero

Status: Planned
Written: 2026-07-27
Depends on: 001 Stage 1 (health endpoints, migrate-before-serve pattern);
the worker drain mode below is shared cross-cutting work from `000_README.md`.

## Goal

First cloud target. API and web run as Cloud Run **services**; the worker
and migrations run as Cloud Run **jobs**; everything scales to zero when
idle. Deploys happen from the existing GitHub Actions CI via Workload
Identity Federation (no long-lived keys). The provider-specific choices are
isolated so this plan can be copied for Azure/AWS with only the right-hand
column changed (see `TEMPLATE-provider-target.md`).

## Current state (grounded 2026-07-27)

The codebase already anticipates this target:

- `apps/api/Dockerfile` has a `production` stage: non-root, respects
  Cloud Run's `PORT`, and takes `--build-arg CLOUD_EXTRA=gcp` to bundle
  `google-cloud-secret-manager` + `google-cloud-storage` (pyproject `gcp`
  extra).
- `apps/web/Dockerfile` `production` stage serves the built SPA from
  nginx-unprivileged on `PORT=8080` with correct caching and SPA fallback.
- Settings support `SECRET_PROVIDER=gcp_secret_manager` (requires
  `GCP_PROJECT_ID`), `STORAGE_PROVIDER=gcs` (public/private buckets,
  `PUBLIC_ASSETS_BASE_URL`), and validation forces non-local providers
  once `ENVIRONMENT != local`. `CREDENTIAL_MASTER_KEY_SECRET_NAME`
  resolves the credential master key from the secret store.
- Logging is already structured JSON outside dev
  (`core/logging.py::StructuredFormatter`) — Cloud Logging ingests it
  as-is. `/api/metrics` exposes Prometheus metrics behind `METRICS_TOKEN`.
- CI (`.github/workflows/ci.yml`) runs lint/format/migration-drift/tests +
  web checks on push/PR; there is **no build or deploy pipeline yet**.

What does not fit Cloud Run yet:

- `workers/main.py` only runs forever (two polling loops under one
  supervisor). Cloud Run Jobs are run-to-completion; there is no drain
  mode.
- No `/healthz` (001 Stage 1 adds it) — needed for Cloud Run startup
  probes.
- `VITE_API_BASE_URL` is baked at build time, so the web image is
  per-environment.
- Session cookies are `samesite="lax"`, so web and API origins must be
  same-site (decision D1 below).
- Agent runs are in-process (`run_task_registry`); SSE resume must reach
  the owning instance. Until roadmap plan 060 (durable stream replay), the
  API must run at most one instance.

## Design decisions

- **D1 — Origins: sibling subdomains, no load balancer (v1).**
  `app.<domain>` → web service, `api.<domain>` → API service, via Cloud Run
  custom domain mappings (zero fixed cost, automatic TLS). Set
  `COOKIE_DOMAIN=.<domain>` so lax cookies flow between the same-site
  origins; `ALLOWED_CORS_ORIGINS=https://app.<domain>`;
  `FRONTEND_URL=https://app.<domain>`; `SECURE_COOKIES=true`.
  Growth path (recorded, not built now): a global external HTTPS LB with
  path routing (`/api/*` → API) collapses to one origin and removes CORS
  entirely, at ~$18+/month fixed — adopt when adding CDN or multi-region.
  Check domain-mapping availability in the chosen region before committing;
  if unavailable, fall back to the LB option.
- **D2 — Database: Cloud SQL for PostgreSQL 17 with pgvector, connected
  via the built-in Cloud SQL connection (unix socket).** No VPC connector
  needed. `DATABASE_URL=postgresql+asyncpg://praxis:<pw>@/praxis?host=/cloudsql/<project>:<region>:<instance>`
  with the password in Secret Manager. Smallest viable tier to start
  (e.g. `db-g1-small` or sandbox/Enterprise smallest); pgvector is a
  supported flag-on extension and the existing Alembic migration enables
  it. Note: Cloud SQL does not scale to zero — it is the one always-on
  cost (~$10–30/month at the small end). Accept this for v1; revisit
  (e.g. scheduled stop for staging) only if it matters.
- **D3 — Worker: drain-mode Cloud Run Job on a Cloud Scheduler cadence.**
  Add `WORKER_MODE=drain` (or `--once`) to `workers/main.py`: run both
  loops until the schedule queue and jobs queue report empty (or a
  `WORKER_DRAIN_MAX_SECONDS` budget expires), then exit 0. Cloud Scheduler
  triggers the job every 1 minute (Scheduler's floor). Consequences to
  accept and document: scheduled-agent latency becomes "cadence + cold
  start" instead of the 5s poll; background jobs (file markdown
  extraction, KB ingest/embedding) enqueued by user actions wait up to a
  minute. **Fast-follow (same plan, Stage 4):** the API fire-and-forgets a
  `jobs.run()` via the Cloud Run Admin API when it enqueues work, making
  Scheduler the safety net rather than the primary trigger. The existing
  lease/claim semantics (`AGENT_SCHEDULE_RUN_CLAIM_TTL_SECONDS`, stale-job
  reclaim) already make overlapping drain executions safe — verify, don't
  assume.
- **D4 — Migrations: a dedicated Cloud Run Job (`praxis-migrate`), run by
  the deploy pipeline before new revisions go live.** Same API image,
  command `alembic upgrade heads`. Deploy order: build → run migrate job →
  deploy api/worker/web. Mirrors the compose `migrate` service from 001.
- **D5 — API service shape (until roadmap 060):** min instances 0, **max
  instances 1**, CPU always allocated (instance-based billing) so
  in-flight agent runs and SSE streams aren't throttled between request
  chunks, request timeout 3600s for SSE, concurrency default (80).
  Scale-to-zero still applies — instance-based billing only bills while an
  instance exists. Revisit max-instances only after plan 060 lands.
- **D6 — Web service shape:** min 0, request-based billing, tiny CPU/mem;
  it's nginx serving static files. Per-environment image build with
  `VITE_API_BASE_URL=https://api.<domain>/api/v1` as a build arg (added in
  001 Stage 2). Runtime env injection is rejected for now — one extra
  image build per env is cheaper than a config-serving mechanism.
- **D7 — Secrets & config:** `ENVIRONMENT=production` (or `staging`),
  `SECRET_PROVIDER=gcp_secret_manager`. Secret Manager holds: `SECRET_KEY`,
  `ENCRYPTION_KEY`, DB password, `INTERNAL_SCHEDULE_TRIGGER_SECRET`,
  `METRICS_TOKEN`, LLM provider keys, OAuth client secrets, and the
  `credential-master-key` (name from `CREDENTIAL_MASTER_KEY_SECRET_NAME`).
  Non-secret config rides as plain Cloud Run env vars, declared in the
  deploy config (see D9). Settings validation already refuses
  `CREDENTIAL_MASTER_KEYS` inline outside local — good.
- **D8 — IAM: one service account per runtime** (`praxis-api`,
  `praxis-worker`, `praxis-migrate`, deploy SA for CI), least privilege:
  `roles/cloudsql.client`, `roles/secretmanager.secretAccessor` (scoped to
  the praxis secrets), storage `objectAdmin` on the two buckets only.
  Never the default compute SA. CI authenticates via Workload Identity
  Federation from GitHub Actions.
- **D9 — IaC: start with declarative `gcloud`-driven config committed to
  the repo** (`deploy/gcp/` — service YAMLs via
  `gcloud run services replace`, plus a small bootstrap doc/script for the
  one-time resources: project, SQL instance, buckets, secrets, scheduler,
  domain mappings). Terraform is deliberately deferred: one target, small
  team, and the service YAML is the part that changes often. Record this
  as reversible; if/when Azure/AWS land, revisit IaC once across targets.
- **D10 — Email: SendGrid or SES over SMTP — pick at execution time.**
  GCP has no first-party transactional email. Both `ses` and `sendgrid`
  providers exist in settings; whichever account is easiest to provision
  wins, and the choice is one env var. Not a blocker for a staging deploy
  (`EMAIL_PROVIDER=disabled` exists for pre-DNS smoke tests — confirm
  invitation/reset flows degrade acceptably before relying on it).

## Tasks

### Stage 0 — Code prerequisites (in-repo, provider-agnostic)

- [ ] Health endpoints from 001 Stage 1 (`/healthz`, `/readyz`); point Cloud
      Run startup/liveness probes at `/healthz` and keep `/readyz` out of
      probes (DB hiccups shouldn't kill instances).
- [ ] Worker drain mode (D3): `WORKER_MODE=drain` + `WORKER_DRAIN_MAX_SECONDS`
      in `workers/main.py` and both runners; exit non-zero on unexpected
      loop failure so Cloud Run Job retries/alerting fire. Tests for both
      modes (empty queue exits promptly; budget expiry exits cleanly
      mid-queue; leases prevent double-processing across overlapping runs).
- [ ] Web Dockerfile build-arg plumbing for `VITE_API_BASE_URL`
      (shared with 001 Stage 2).
- [ ] Verify SSE behaves through Cloud Run (heartbeats exist? if streams
      can idle > idle-timeout without frames, add a keepalive comment
      frame) — check `services/agents/runtime/events` before assuming.

### Stage 1 — GCP foundation (one-time, per environment)

- [ ] Project(s): decide single project with env-suffixed resources vs
      project-per-env (recommend project-per-env: `praxis-staging`,
      `praxis-prod`; staging first). Pick one region (e.g. `europe-west2`
      given the team's UK base; confirm domain-mapping support per D1).
- [ ] Artifact Registry repo for images.
- [ ] Cloud SQL Postgres 17 instance per D2; create `praxis` DB + user;
      enable pgvector flag; automated backups + PITR on for prod.
- [ ] GCS buckets: `praxis-<env>-public-assets` (public read via
      `PUBLIC_ASSETS_BASE_URL`), `praxis-<env>-private-assets` (signed URLs
      only, uniform access, no public access).
- [ ] Secret Manager secrets per D7, values generated per `.env.example`
      instructions.
- [ ] Service accounts + IAM bindings per D8; WIF pool/provider for GitHub
      Actions.

### Stage 2 — Services and jobs

- [ ] `deploy/gcp/` in-repo config per D9: service YAML for `praxis-api`
      (D5 shape, Cloud SQL connection, secret refs, full env from
      `.env.example` cloud values), `praxis-web` (D6), job specs for
      `praxis-migrate` (D4) and `praxis-worker` (D3), Scheduler job
      (1-minute cadence, OIDC-authenticated `jobs.run` call).
- [ ] First manual deploy to staging: build both images
      (`CLOUD_EXTRA=gcp` for api), push, run migrate job, deploy services,
      run worker job once by hand; smoke-test sign-up → agent chat (SSE) →
      file upload (GCS signed URL) → schedule fires within cadence.
- [ ] Domain mappings + DNS for `app.` and `api.`; flip
      `SECURE_COOKIES=true`, `COOKIE_DOMAIN`, CORS, OAuth redirect URIs
      (Google/GitHub/Microsoft consoles) to the real origins.
- [ ] Observability floor: log-based alert on worker job failures and API
      5xx rate; uptime check on `/healthz`. Decide whether `/api/metrics`
      gets scraped (Managed Prometheus) or stays dormant for v1.

### Stage 3 — CI/CD

- [ ] Extend GitHub Actions: on main, after the existing checks pass —
      build+push images (tag = git SHA), run `praxis-migrate` and wait for
      success, then deploy api/worker/web to staging. Manual
      approval/workflow-dispatch promotes the same SHA to prod. Auth via
      WIF; no JSON keys anywhere.
- [ ] Rollback procedure documented and rehearsed once: Cloud Run revision
      pinning for services; migrations are roll-forward-only (note this in
      the deploy doc).

### Stage 4 — Fast-follows

- [ ] Event-driven job trigger per D3: API enqueue path fire-and-forgets a
      worker-job execution via the Cloud Run Admin API (`praxis-api` SA
      gets `roles/run.developer` on the worker job only); Scheduler remains
      the safety net. Measure enqueue→completion latency before/after.
- [ ] Cost review after 2–4 weeks of staging: confirm the always-on floor
      is Cloud SQL only, and everything else bills near zero at idle.
- [ ] Record in this file the decisions actually taken (region, tiers,
      email provider, single-vs-multi project) for the Azure/AWS copies.

## Verification

- Staging smoke test (Stage 2) passes end to end, including an SSE
  conversation with a tool-call approval and a scheduled agent run landing
  within one cadence interval.
- Kill/redeploy during an active conversation: instance drains within
  `AGENT_RUN_SHUTDOWN_DRAIN_SECONDS`, no orphaned runs after the startup
  sweep.
- Deliberately failing migration in staging blocks the deploy (migrate job
  non-zero → pipeline stops, old revisions keep serving).
- Overlapping worker executions (run the job manually while Scheduler
  fires) process each item exactly once.
- `make check` green; settings validation exercised with the production
  env shape in a test (non-local env + gcp providers boots).

## STOP conditions

- STOP if same-site cookies can't be made to work on the chosen domains
  without changing `samesite="lax"` — escalate rather than loosening
  cookie policy.
- STOP if scale-to-zero for the API conflicts with in-flight agent-run
  guarantees in a way instance-based billing doesn't solve — that's a
  signal to pull roadmap plan 060 forward, not to hack around the
  registry.
- STOP before granting any service account project-level Editor/Owner or
  reusing the default compute SA.
- STOP if the drain-mode worker requires changing lease/claim semantics —
  those are load-bearing for correctness; redesign the trigger instead.

## Out of scope

- Load balancer / CDN / multi-region (recorded as growth path in D1).
- Terraform (D9 records the revisit trigger).
- Horizontal API scaling (blocked on roadmap plan 060).
- Notifications routes/UI, and any product feature work.
