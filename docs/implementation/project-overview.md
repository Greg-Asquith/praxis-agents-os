# Project implementation overview

This reference describes the implemented product and deployment topology.
Paths are relative to the repository root.

## Processes and deployment

The following contracts apply in this area:

- `apps/api` is the FastAPI backend. Background work runs in a separate worker
  process (`python -m workers.main`) that supervises two loops: the
  scheduled-agent runner and the generic jobs runner. It polls continuously by
  default; `WORKER_MODE=drain` processes available work until both queues are
  empty or the drain budget expires, then exits for run-to-completion platforms.
  Terminal agent runs retain their existing lifecycle status and separately
  record a structured outcome plus bounded completion evidence. Terminal
  transitions serialise on the generic run row so the first verdict remains
  authoritative under cancellation/finalisation races. Schedules may also
  require a bounded completion report against operator-authored criteria;
  pass, fail, and missing-report verdicts remain separate from lifecycle status.
  AI usage is recorded in a forced-RLS, runtime-append-only ledger with one row
  per logical agent, helper, or embedding invocation, not per provider request.
  Successful and suspended agent invocations record atomically with their run
  transition; failure/cancellation and helper/embedding paths use best-effort
  durable recording through a distinct bounded runtime-role connection pool.
  Owner/admin usage routes apply effective-dated public prices to UTC daily
  buckets and expose estimated workspace cost, trends (one zero-filled point
  per UTC day in the requested range), attribution breakdowns, and explicit
  pricing coverage. Super admins can use a separately gated,
  database-read-only maintenance view to see the same measures across all
  workspaces, including workspace and cross-workspace user attribution.
  Image-generation events retain known output
  metadata so GPT Image 2 and Gemini 3.1 Flash Image estimates are added
  separately from the mainline helper model. This ledger is observability only:
  it does not enforce budgets or admission.
- `apps/web` is the Vite + React single-page frontend (TanStack Router +
  TanStack Query). It talks to the API over REST and consumes agent turns over
  SSE.
- `docker-compose.yml` defines local Postgres (pgvector image), the API, the
  worker, and the web app. The root `Makefile` wraps the local dev flow
  (`make bootstrap`, `make dev`, `make check`).
- `deploy/gcp/` contains the customer-independent GCP bootstrap, Cloud Run
  service/job templates, and the build/migrate/deploy path. Real environment
  files stay outside git (or under `.local/`); the GCP bootstrap and deploy
  Make targets require an explicit `ENV_FILE`, and bootstrap keeps
  API/IAM/billable mutations behind a typed interactive approval gate. It
  generates initial Cloud SQL credentials and core Secret Manager payloads in
  memory, redacts them from previews, and seeds them without writing them to
  disk. Operators manually enable each selected serverless partner model in
  Model Garden for the Vertex request's project before use, and verify
  inference after deployment. API enablement and IAM grants do not enable
  individual models; bootstrap does not accept partner terms.
  Deployments run manually from an authenticated operator machine; the
  bootstrap does not provision GitHub Actions deployment identity federation.

## Implemented domains

Domains wired end to end (service + route + UI): auth (password, OAuth, TOTP,
sessions), users, workspaces (memberships, invitations), agents, conversations
(SSE chat with tool calls and approvals), agent runs (durable approval resume,
configurable approval expiry, and staged-input cleanup), the
LLM model catalogue, AI usage and estimated public-rate costs, files and storage
(signed uploads, revisions, background
markdown extraction), skills, workspace classifiers, knowledge base, agent
memories, the context hub, schedules, integrations (OAuth, API-key, and
service-account connections, including bounded Notion page and data-source
reads plus approval-only page creation and content or property updates),
artifacts (dedicated immutable revisions, approval-gated agent
tools, agent list/read/update across conversations, workspace management UI,
append-only edit/restore flows, and
version-pinned anonymous share links with CSP-locked serving), the tool
catalogue, provider-native isolated code execution for computation, new document
generation, and append-only editing of existing workspace documents, and the
audit/security event viewers.

Notifications have a backend service; routes and UI are pending.
Knowledge Base chunks and agent memories use `HALFVEC` embeddings with HNSW
indexes provisioned by migrations. Keep
public behaviour explicit. If a capability is not wired end to end, document
it as pending instead of implying it works.
