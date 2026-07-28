<!-- docs/plans/deployment/001-local-quickstart.md -->

# 001 — Local Quickstart: foolproof spin-up for a fresh clone

Status: Planned
Written: 2026-07-27
Depends on: nothing (this is the first deployment plan to execute)

## Goal

Someone who has never seen this repo clones it and has a working Praxis
Agents OS in their browser within a few minutes, with exactly one hard
prerequisite (Docker) and one piece of required input (an LLM API key).
Everything else — env files, keys, migrations, service ordering — is
generated and sequenced for them. Failure modes produce a clear message
naming the fix, not a stack trace.

Two audiences, two paths, both foolproof:

- **Try-it path** (`docker compose up` / `make quickstart`): Docker only.
  No uv, pnpm, Python, or Node on the host. This is what we hand to someone
  we're sharing the project with.
- **Contributor path** (`make bootstrap` + `make dev`): the existing local
  workflow with host toolchains and hot reload. Already works; this plan
  hardens its edges rather than changing it.

## Current state (grounded 2026-07-27)

- `make bootstrap` creates `.local/` env files (generating a real
  `CREDENTIAL_MASTER_KEYS` value via python3) and installs deps;
  `make dev` starts Postgres in Docker, waits, migrates, then runs API,
  worker, and web on the host. This flow is solid for contributors.
- `make compose-up` builds and runs the full stack in Docker, but:
  - **No migrations run.** The api container CMD is uvicorn only; nothing
    executes `alembic upgrade heads`, so a fresh volume gives a broken app.
  - `depends_on` uses `condition: service_started` even though Postgres has
    a healthcheck — the API can race the DB on first boot.
  - It uses the `dev` image targets with bind mounts and a node_modules
    volume — fine for development, heavier than needed for try-it.
  - It still requires `make local-env` first (and therefore make + python3
    on the host) to produce `.local/generated/*` env files.
- The API has no `/healthz` route; the production Dockerfile healthcheck is
  a TCP probe with a comment saying to upgrade once an endpoint exists.
- A working experience needs an LLM key: `DEFAULT_MODEL_PROVIDER=openai`
  with `OPENAI_API_KEY` empty by default. Nothing surfaces this until an
  agent conversation fails.
- Compose volume/network names still say `praxis-agents-template-*`.
- `README.md` documents the contributor path; there is no short "just try
  it" section.

## Design decisions

- **D1 — One-command entry is `docker compose up` semantics.** The try-it
  path must work with Docker alone. Env bootstrap moves into the compose
  stack itself (an `init` one-shot service that writes
  `.local/generated/*` if missing, generating `CREDENTIAL_MASTER_KEYS`
  with Python inside the container) so make/python3 on the host are not
  required. `make quickstart` remains as sugar over the same path.
- **D2 — Migrations are a first-class compose step.** Add a one-shot
  `migrate` service (same api image, command `alembic upgrade heads`) with
  `depends_on: postgres: condition: service_healthy`; `api` and `worker`
  depend on `migrate: condition: service_completed_successfully`. This
  also becomes the pattern every cloud target copies (a migrate job).
- **D3 — The LLM key is prompted, not discovered.** Try-it path: compose
  reads `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` from `.local/targets/local.secrets.env`
  (already wired in compose) or the host environment; the quickstart doc
  and `make quickstart` say so up front. Additionally, the web UI should
  degrade clearly when no provider key is configured (a settings hint, not
  a failed stream) — small backend/frontend task, not a redesign.
- **D4 — Try-it uses production image targets.** `docker compose` gets a
  `try` profile (or a `docker-compose.quickstart.yml` overlay) using the
  `production` targets: nginx-served web (with `VITE_API_BASE_URL` built
  for `http://localhost:8000/api/v1`), non-reload API. Faster, smaller,
  and it exercises the images we ship to clouds. The existing dev-target
  services stay for contributors.
- **D5 — `ENVIRONMENT=local` stays the only mode either path runs in.**
  No loosening of the settings validation; local-only providers
  (`local_fs`, `console`, `local` secrets) are exactly what quickstart
  uses.

## Tasks

### Stage 1 — Make the compose path correct

- [ ] Add a `migrate` one-shot service to `docker-compose.yml` per D2; flip
      `postgres` dependencies to `condition: service_healthy`.
- [ ] Set explicit Compose `stop_grace_period` values that cover graceful
      shutdown: at least 120 seconds for the API and 30 seconds for the
      worker, so Docker does not terminate either process mid-drain.
- [ ] Add `/healthz` (liveness, returns 200 with app version, no DB) and
      `/readyz` (checks DB connection) to the API; wire the production
      Dockerfile HEALTHCHECK and a compose healthcheck on `api` to it.
- [ ] Move env bootstrap into an `init` one-shot compose service per D1 so
      the stack self-provisions `.local/generated/*` on first run; keep
      `make local-env` delegating to the same logic so the two paths cannot
      drift.
- [ ] Rename `praxis-agents-template-*` volumes/networks to `praxis-*`
      (note: existing local volumes are orphaned by a rename — call this
      out in the changelog/README so contributors know to re-migrate or
      keep the old names locally).

### Stage 2 — The try-it profile

- [ ] Add production-target compose services (D4): `web` built with
      `target: production` and `VITE_API_BASE_URL=http://localhost:8000/api/v1`
      as a build arg (Vite env must be present at build time — add the
      `ARG`/`ENV` plumbing to `apps/web/Dockerfile` build stage), `api`
      with `target: production`.
- [ ] Harden the nginx-served document, including every cache-specific
      location: `Strict-Transport-Security` in HTTPS deployments,
      `Content-Security-Policy` with `default-src 'self'`,
      `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`,
      `form-action 'self'`, `script-src 'self'`,
      `style-src 'self' 'unsafe-inline'`, and `connect-src`/`frame-src`
      generated from the validated `VITE_API_BASE_URL`. Limit
      `img-src`/`media-src` to `'self'`, `data:`, `blob:`, and the validated
      public/signed-storage origins needed by Files, avatars, and previews;
      do not use a scheme or host wildcard. Emit the policy from the same
      per-environment build inputs as the Vite API URL so browser and nginx
      configuration cannot drift. Also set `X-Content-Type-Options: nosniff`,
      `X-Frame-Options: DENY`, and
      `Referrer-Policy: strict-origin-when-cross-origin`. Use `always` and
      account for nginx `add_header` inheritance so `/`, `/index.html`, and
      `/assets/*` all receive the policy. Add an nginx-config/container
      test that proves those three path classes and rejects a wildcard
      script or connect source. Local HTTP may omit HSTS; production must
      emit `max-age=31536000; includeSubDomains` after both sibling
      subdomains are HTTPS-only.
- [ ] `make quickstart`: one target that checks Docker is present, prompts
      for/validates an LLM key into `.local/targets/local.secrets.env` if
      absent, then `docker compose --profile try up`. Print the URL and
      first-run instructions (sign up, create workspace) on success.
- [ ] `make doctor`: check Docker, and for the contributor path uv, pnpm,
      Node 24, Python 3.12 — versioned, with install hints per platform.
      `bootstrap` and `dev` call it first.

### Stage 3 — First-run experience

- [ ] Graceful no-LLM-key state (D3): API surfaces "no provider key
      configured for the default model provider" as a typed error; web
      shows an actionable message instead of a dead stream.
- [ ] README: add a "Quickstart (Docker only)" section at the top — clone,
      set key, `make quickstart` (or the raw compose command for
      make-less/Windows users), open http://localhost:3000. Keep the
      contributor section below it.
- [ ] Walk through the flow on a machine (or pristine checkout + wiped
      Docker volumes) exactly as written: fresh clone → quickstart → sign
      up → create workspace → create agent → send a message that calls a
      tool → upload a file. Every rough edge found becomes a task here
      before this plan is marked done.

## Verification

- Fresh clone + wiped volumes: `make quickstart` reaches a usable app with
  only Docker installed; `docker compose --profile try up` alone also
  works after env init.
- `make dev` contributor path unchanged and green.
- `make check` passes; migration ordering verified by the compose `migrate`
  service logs on first boot.
- The production web container returns the required security headers on the
  SPA shell, fallback routes, and fingerprinted assets; the GCP staging smoke
  test in 002 confirms that Cloud Run/domain mapping preserves them.
- README quickstart followed verbatim by someone (or a clean-room agent
  session) who hasn't seen the repo.

## STOP conditions

- STOP if making the try-it path work requires weakening
  `validate_runtime_provider_config` or any CORS/cookie/CSRF setting —
  find a local-config route instead.
- STOP if the init-container approach requires committing generated env
  values or secrets to the repo.
- STOP before adding a seed-data/demo-content system — if first-run UX
  seems to need one, note it as a follow-up and finish the plan without it.

## Out of scope

- Windows-native (non-WSL/non-Docker) contributor tooling.
- Demo/seed data beyond the empty first-run flow.
- Any cloud concerns (002+).
