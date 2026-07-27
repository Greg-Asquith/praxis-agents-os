<!-- docs/plans/deployment/000_README.md -->

# Deployment Plans

Written 2026-07-27 from a survey of the working tree (compose file, Dockerfiles,
makefiles, `core/settings/`, `workers/main.py`, `.github/workflows/ci.yml`).
These plans cover how Praxis Agents OS gets run, in two flavours now and more
later:

| Plan | Target | Status |
| --- | --- | --- |
| [001-local-quickstart.md](001-local-quickstart.md) | Local — foolproof single-command spin-up for someone who just cloned the repo | Planned |
| [002-gcp-cloud-run.md](002-gcp-cloud-run.md) | GCP — Cloud Run services (API, web) + Cloud Run Jobs (worker, migrate), scale to zero | Planned |
| 003 (future) | Azure — Container Apps + Container Apps Jobs | Not started |
| 004 (future) | AWS — App Runner / ECS + EventBridge Scheduler | Not started |
| 005 (future) | Cloudflare — web on Pages/Workers; API/worker need a container-capable backend | Not started |

Future targets start from [TEMPLATE-provider-target.md](TEMPLATE-provider-target.md),
which is the GCP plan with the provider-specific column left blank.

Plans here follow the same rules as the numbered roadmap plans: read fully
before executing, honor STOP conditions, update the status row when done, and
do not cite plan files from implementation code.

## The deployment target contract

The codebase is already deliberately deployment-agnostic. Every cloud target
must supply the same nine capabilities; everything else is provider glue. This
contract is what makes the GCP plan copyable to Azure/AWS/Cloudflare.

| # | Capability | What the code expects | Where it's abstracted |
| --- | --- | --- | --- |
| 1 | Container runtime for the API | Runs `apps/api` `production` image; injects `PORT`; HTTP + long-lived SSE responses | `apps/api/Dockerfile` (non-root, `PORT`-aware) |
| 2 | Static hosting for the web SPA | Serves `apps/web` `production` image (nginx-unprivileged) or the raw `dist/` bundle; SPA fallback to `index.html` | `apps/web/Dockerfile`, `apps/web/nginx.conf` |
| 3 | Worker execution | Runs `python -m workers.main` — today a run-forever supervisor; plans add a run-to-completion drain mode for scale-to-zero job runners | `apps/api/workers/main.py` |
| 4 | Cron trigger | Something fires the worker (or a drain job) on a schedule | Provider scheduler (Cloud Scheduler, ACA cron jobs, EventBridge) |
| 5 | Managed Postgres 17 + pgvector | Async SQLAlchemy via `DATABASE_URL` (`postgresql+asyncpg://`); pgvector extension enabled by Alembic | `core/settings/database.py` |
| 6 | Secret store | `SECRET_PROVIDER` = `gcp_secret_manager` \| `azure_key_vault` \| `aws_secrets_manager`; resolves `CREDENTIAL_MASTER_KEY_SECRET_NAME` | `services/secrets/`, `core/settings/providers.py` |
| 7 | Object storage with signed URLs | `STORAGE_PROVIDER` = `gcs` \| `azure_blob` \| `s3`; public + private buckets | `services/storage/`, `services/assets/` |
| 8 | Email | `EMAIL_PROVIDER` = `ses` \| `smtp` \| `sendgrid` (console is local-only, enforced by settings validation) | `core/settings/providers.py` |
| 9 | DNS / TLS / same-site origins | Session cookies are `samesite="lax"` (`core/auth/sessions/cookies.py`), so web and API must be same-site: sibling subdomains with `COOKIE_DOMAIN` set to the parent domain, or same-origin behind path routing | `core/settings/urls.py`, CORS/CSRF middleware |

Settings validation (`core/settings/__init__.py::validate_runtime_provider_config`)
enforces the boundary: `local_fs` storage, `console` email, `local` secrets,
and inline `CREDENTIAL_MASTER_KEYS` are rejected outside `ENVIRONMENT=local`.
Do not weaken this to make a deployment easier — it is the guard rail that
keeps every cloud target honest.

## Cross-cutting work (shared by all targets)

These items are provider-independent and appear as prerequisites in both
plans; do each once:

- **Health endpoints** — `/healthz` (liveness, no dependencies) and
  `/readyz` (checks DB) on the API. The Dockerfile healthcheck comment
  already anticipates this.
- **Worker drain mode** — a run-to-completion entrypoint
  (`python -m workers.main --once` or `WORKER_MODE=drain`) that claims and
  processes due scheduled runs and pending jobs until queues are empty or a
  time budget expires, then exits 0. This is what makes "worker as a
  scale-to-zero job" possible on every provider.
- **Compose migrations** — the Docker Compose path must run
  `alembic upgrade heads` before the API starts (today only `make dev`
  migrates).
- **Web API base URL strategy** — `VITE_API_BASE_URL` is baked at build time
  (`apps/web/src/config/env.ts`). Either build per environment in CI or add
  runtime injection; each target plan states which it uses.

## Known constraint: API horizontal scaling

Agent runs execute in-process in the API (`run_task_registry` in
`services/agents/runtime`), and SSE resume must reach the instance that owns
the run. Until roadmap plan 060 (durable stream replay) lands, cloud targets
should cap the API at one instance (still scale-to-zero) and keep CPU
allocated while background runs drain. Both plans call this out where it
applies; do not silently raise max instances before 060.
