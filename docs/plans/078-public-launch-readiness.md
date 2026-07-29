# Plan 078: Public launch readiness — README, community health, supply chain, hardening, and first release

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 9d83f9d..HEAD -- README.md AGENTS.md LICENSE CHANGELOG.md .github/ apps/api/main.py apps/api/core/settings/ apps/api/.dockerignore apps/api/.env.example apps/api/pyproject.toml apps/web/package.json apps/web/nginx.conf docs/plans/deployment/ docs/guides/`
> If any in-scope file changed since this revision was written, compare the
> "Current state" excerpts against the live files before proceeding.

## Status

- **Priority**: P0 for launch week (raised from P1 on 2026-07-28)
- **Effort**: XL (many small artifacts plus a handful of small code touches)
- **Risk**: MEDIUM (mostly docs/CI; the code touches are a settings
  validator, two ignore/manifest lines, and a version constant; the release
  workflow is executable but pushing the tag that triggers it is
  operator-gated)
- **Depends on**: C05 (DONE), C01 (DONE — CI exists), 082 (DONE — see
  decision 2), and deployment plan 001 (DONE — see
  `docs/plans/complete/deployment-001-local-quickstart.md`). See launch
  gate G1.
- **Category**: Lane P — public launch & adoption
- **Planned at**: working tree at commit `6be5491`, 2026-07-07.
  **Revised 2026-07-28 against working tree `9d83f9d`** after a four-track
  verification pass (plan-anchor audit, product-surface inventory, pre-launch
  security sweep, launch gap analysis). Launch target: week of 2026-08-03.

## Product intent

The repository is engineered to be good — CI, a trustworthy local gate,
governance docs, an audited tool runtime, and (since this plan was first
written) a knowledge base, agent memory, artifacts with public share links,
four shipped integrations, and a behavior eval harness. What is still missing
is everything that makes it *publishable*: community health files, supply
chain hygiene, a changelog, a tagged release, a published image — and, found
by the 2026-07-28 security sweep, two publication-mechanics fixes without
which going public is actively unsafe (see decision 11). For a project whose
differentiator is governance and auditability, a missing SECURITY.md and
unpinned CI actions actively contradict the pitch. This plan ships the
minimum credible public storefront and makes the act of publishing safe.

## Decisions taken

1. **C05 precedence on the README — now historical.** C05's corrections
   (Node.js 24, `make bootstrap`/`make dev` flow, Apache-2.0 note) are
   present in the current README, which was substantially rewritten after
   this plan was first written. Step 1 is therefore a **targeted upgrade**,
   not a wholesale rewrite; do not regress any existing correction.
2. **OpenAPI: anonymous docs stay disabled; CI exports the spec; an
   authenticated route already exists.** `main.py:75-77` still sets
   `docs_url`/`redoc_url`/`openapi_url` to `None` — keep that. Plan 082
   (DONE 2026-07-22) shipped `GET /api/v1/meta/openapi.json` (session-auth,
   `routes/meta/get_openapi_schema.py`), superseding the old "no consumer
   yet" rationale but not the attack-surface one. Step 5's CI artifact
   export still ships: docs tooling should not need credentials. The README
   claim at `README.md:183` ("disables OpenAPI, Swagger, and ReDoc routes")
   is now only half true and gets corrected in Step 1.
3. **Dependency audit is non-blocking initially.** `pip-audit` and
   `pnpm audit` run as a CI job with `continue-on-error: true` until the
   first triage pass establishes a clean baseline; the flip to blocking is a
   maintenance-note rule, not a later plan. Note: the 2026-07-28 sweep found
   `pnpm audit --prod` reports 4 vulnerabilities, all via `shadcn` sitting
   in `dependencies`; Step 0 moves it to `devDependencies`, which should
   take the prod audit to zero before the job ever runs.
4. **Semver 0.x posture.** While the major version is 0, breaking changes to
   APIs, schemas, and config are allowed in minor releases; patches are
   fixes only. Recorded in the CHANGELOG header and CONTRIBUTING.md — no
   compatibility promise is implied before 1.0.
5. **All third-party actions get SHA-pinned**, version as a trailing
   comment, with `dependabot.yml`'s `github-actions` ecosystem keeping the
   pins current. Resolve the SHAs at execution time (e.g.
   `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`) — this plan does not
   guess them. **Ownership note**: `docs/plans/complete/deployment-000-security-review.md`
   lists "pin third-party Actions by SHA" under CI/CD hardening — this plan
   owns that task; Step 6 ticks it there so the two plans do not collide.
6. **Release images: API only in v1; web is a per-environment build.** The
   API image is deployment-portable (config via env). The web bundle bakes
   `VITE_API_BASE_URL` at build time (`apps/web/src/config/env.ts:4`), so a
   generic published web image cannot be retargeted. Deployment plan 002
   (D6) has since settled the direction: **per-environment image builds
   with a build arg**, with runtime env injection explicitly rejected for
   now; the `ARG VITE_API_BASE_URL` Dockerfile plumbing is owned by
   deployment plan 001 Stage 2, not here. Publish
   `ghcr.io/greg-asquith/praxis-agents-os-api` on tag; revisit a published
   web image only if runtime config is ever adopted.
7. **Versions align at `0.1.0` — in four places, not three.**
   `apps/api/pyproject.toml:3` already says `0.1.0`; set
   `apps/web/package.json:4` (`0.0.0`), the `APP_VERSION` settings default
   (`core/settings/app.py:13`, currently `"1.0.0"`), **and
   `apps/api/.env.example:12` (`APP_VERSION=1.0.0`)** — the fourth site was
   outside the original scope list and would have left every bootstrapped
   local env reporting the wrong version. Verified 2026-07-28: no test
   asserts `"1.0.0"`, so the change is assertion-free. Note the planned
   `/healthz` endpoint (deployment plan 001) will expose `APP_VERSION`
   publicly — another reason it must be right.
8. **Positioning is honest, not aspirational.** The README compares against
   LangGraph/dify/n8n-class tools by *kind*: Praxis is not an orchestration
   framework or a visual workflow builder — it is a self-hosted,
   workspace-governed agent platform where audited tool dispatch,
   approval-gated side effects, and RBAC are the point. Claims are limited
   to what is wired end to end; pending surfaces stay documented as pending.
   Two honesty constraints added 2026-07-28: the README must **not** claim
   `docker compose up` works from a fresh clone until deployment plan 001
   Stage 1 lands (today it fails on missing env files and runs no
   migrations), and it must state the production self-hosting constraints
   plainly (gate G2: cloud storage + cloud secret manager required outside
   `ENVIRONMENT=local`; no email transport is implemented yet).
9. **Launch is gated, not just planned.** This plan alone does not make
   launch safe. The "Launch gates" section lists the blockers found on
   2026-07-28, each with an owner. The `v0.1.0` tag is not pushed until
   gates G0–G1 are done and the maintainer has recorded decisions on G2–G5.
10. **Two image pipelines coexist.** `release.yml` (this plan) publishes
    public, version-tagged release artifacts to GHCR on `v*` tags.
    Deployment plan 002 Stage 3 separately builds SHA-tagged deploy
    artifacts to Artifact Registry for its own environments. Different
    purpose, registry, and tagging scheme — neither replaces the other, and
    002's executor should not duplicate `release.yml`.
11. **Pre-flight hardening moves into scope.** The original plan was
    "docs/CI only". The 2026-07-28 security sweep found publication itself
    is unsafe without four small fixes, so they are now Step 0 of this plan:
    (a) `apps/api/.dockerignore` does not exclude `.local/` — a production
    image built from a dev working tree ships the encrypted local secret
    store and ~13MB of real user storage (the root `.dockerignore` never
    applies because the build context is `apps/api`); (b) the publicly-known
    `.env.example` placeholder `SECRET_KEY`/`ENCRYPTION_KEY` values pass
    validation outside local (they satisfy the only checks: min-length and
    Fernet-parseable) — the moment the repo is public those strings are
    globally known; (c) `SECURE_COOKIES=false` from the example env is
    likewise accepted outside local; (d) a tracked doc leaks a local
    developer-home path. Larger product gaps (email transport, password
    reset, email verification, single-box production mode) are explicitly
    **not** pulled into this plan — they are gates or follow-ups.
12. **README quickstart ownership.** Deployment plan 001 Stage 3 owns the
    future "Quickstart (Docker only)" README section; this plan must not
    write one (see decision 8). Step 1 keeps the contributor flow
    (`make bootstrap` / `make dev`) as the documented path and leaves a
    placeholder comment where 001's section will land.

## Launch gates

The tag push (and any launch announcement) is gated on the following. G0 is
this plan. G1 is a sibling plan. G2–G5 are maintainer decisions to record
this week — each has a cheap "document honestly" fallback that unblocks
launch without code.

| Gate | What | Owner | Launch-blocking action |
|------|------|-------|------------------------|
| G0 | This plan's Steps 0–6 | this plan | Execute. |
| G1 | Fresh-clone experience: compose `migrate` one-shot service, `service_healthy` dependencies, `/healthz` + `/readyz`, env-init in compose, `make quickstart` | `docs/plans/complete/deployment-001-local-quickstart.md` | **Resolved 2026-07-28:** the complete plan includes the fresh-volume walkthrough, 120-second API and 30-second worker shutdown windows, health routes, ordered migrations, and Docker-only bootstrap. |
| G2 | **Production self-hosting posture.** Outside `ENVIRONMENT=local`, settings validation (`core/settings/__init__.py:79-101`) rejects `local_fs` storage, `local` secrets, and `console` email — and no email transport is implemented at all (`ses`/`smtp`/`sendgrid` are accepted literals with zero implementation; `.env.example:195-202` documents dead SES config). So "self-hosted production" today requires cloud storage + a cloud secret manager and still has no working email. | Maintainer | Decide: (a) ship an SMTP transport and/or allow `EMAIL_PROVIDER=disabled` plus an S3-compatible endpoint override as a fast-follow plan, or (b) launch with README/deployment docs stating plainly that production deployment targets cloud providers (the GCP plan) and email delivery is pending. Either is honest; silence is not. Do NOT weaken `validate_runtime_provider_config` ad hoc. |
| G3 | **No password reset exists.** Only `change_password` is implemented; `PASSWORD_RESET_TOKEN_TTL_MINUTES` and its rate limit are dead settings. A self-hoster who forgets their password is stuck at the SQL prompt. | Maintainer | Decide: fast-follow plan (needs G2's email decision), or document the limitation and a recovery runbook (super-admin `PUT /users/{id}/password` via `SUPER_ADMIN_EMAILS`) in the README/FAQ before launch. |
| G4 | **Super-admin claim window.** Super-admin is granted by email-string match (`core/dependencies.py:155-157`) with open registration (`ALLOW_SIGNUP` default true) and no email verification anywhere (`user.email_verified` exists but nothing reads it). An attacker who registers the operator's intended admin email first owns the instance. | Maintainer (docs now; code later) | Before launch: document the safe ordering prominently (deploy with `ALLOW_SIGNUP=false` → register admin → set `SUPER_ADMIN_EMAILS`) in SECURITY.md's deployment-hardening note and the deployment docs. Real fix (email verification, or refusing super-admin elevation for unverified emails) is a recorded follow-up plan. |
| G5 | Public-record source notes, `NOTICE`/third-party attribution posture, and an unused branded support-address constant baked into self-hosted instances. | Maintainer | **Resolved 2026-07-28:** the retired source codebase was owned by the same maintainer, so remove its notes, remove the unused constant, and do not add a `NOTICE` file for that material. |

## Current state

Verified 2026-07-28 on working tree `9d83f9d` (clean). Full detail lives in
the revision-pass reports; the anchors below are what the steps rely on.

**Already done since this plan was first written (do not redo):**

- **README.md** (322 lines) was rewritten: the stale-claim greps and the
  `pnpm lint` grep already pass, local links resolve, C05's corrections are
  present, and a real feature overview exists (`README.md:11-37`) including
  the honest notifications caveat. Still missing: badges, screenshots,
  positioning (zero mentions of LangGraph/dify/n8n), any pointer to
  `docs/architecture/` or `docs/plans/000_README.md`, and mentions of the
  named integrations (Gmail, Airtable, BigQuery, Google Ads), service
  accounts, the context hub, and the eval harness. One new inaccuracy:
  `README.md:183` (see decision 2).
- **Lane P is already recorded**: `000_MASTER_ROADMAP.md:901` and
  `000_README.md:103-104`. Old Step 6 shrinks to bookkeeping.
- **Plan 082** shipped the authenticated schema route; **plan 055** shipped
  the eval harness (`apps/api/evals/`, `make evals` at
  `makefiles/checks.mk:17-19` — deliberately outside `make check`); plans
  079–081, 089, 090 are DONE; 083–088 are DEFERRED (2026-07-28).
- **`docs/architecture/` now holds eight docs** (was four):
  `agent-context.md`, `agent-runtime.md`, `agent-turn-streaming-plan.md`,
  `governance.md`, `integration-events.md`, `integration-packaging.md`,
  `internal-applications.md`, `threat-model.md`. Two need care in a public
  pointer: `agent-turn-streaming-plan.md` is plan-shaped and
  `internal-applications.md` describes deferred work.
- **`docs/plans/deployment/`** (five files, written 2026-07-27/28) owns
  quickstart, GCP, and the InfoSec hardening checklist. The master roadmap
  does not mention it — fixed in Step 6.

**Still missing, unchanged from the original plan:**

- `.github/` contains exactly one file, `workflows/ci.yml`: jobs `api` and
  `web` only; actions tag-pinned at lines 38, 39, 78, 79, 82
  (`actions/checkout@v7`, `astral-sh/setup-uv@v8.2.0`,
  `pnpm/action-setup@v6.0.9`, `actions/setup-node@v6.4.0`); no
  `permissions:` block; no audit job, CodeQL, release workflow, issue
  templates, or PR template. The api job env (lines 27–36) already supplies
  valid settings for the Step 5 export. CI never builds either Docker
  image — the release workflow would be the first-ever build of the
  production image (Step 3 fixes this before the tag).
- No `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `CHANGELOG.md`, or `NOTICE` at root. `git tag` is empty.
- Versions disagree across **four** sites (decision 7).

**New blockers found by the 2026-07-28 sweep (Step 0 and gates):**

- `apps/api/.dockerignore` has no `.local/` entry; `apps/api/.local/` on a
  bootstrapped machine holds `secrets.enc.json` (12K Fernet ciphertext) and
  ~13MB of storage including a real user avatar. Its header says "keep in
  sync with `.gcloudignore`" — a file that does not exist.
- Placeholder `SECRET_KEY`/`ENCRYPTION_KEY` (`.env.example:43,47`) and
  `SECURE_COOKIES=false` (`.env.example:51`) pass validation outside local
  (`core/settings/security.py:16,19,25,85-94`); `make bootstrap` copies
  them verbatim, regenerating only `CREDENTIAL_MASTER_KEYS`
  (`makefiles/local.mk:15-26`). Independently flagged by
  `docs/plans/complete/deployment-000-security-review.md:50-57`.
- `pnpm audit --prod`: 4 vulnerabilities (3 high), all reached via `shadcn`
  in `dependencies` (`apps/web/package.json:39`) — a scaffolding CLI that
  never enters the browser bundle.
- Tracked planning documents contained private-source references and one
  absolute developer-home path. Step 0 removes the dedicated source roadmap
  and source-specific notes while retaining durable technical decisions.
- Doc drift to fix while touching docs: AGENTS.md still says "pgvector is
  provisioned by migrations but no vector columns exist yet" — false since
  the KB and agent-memory `HALFVEC` columns with HNSW indexes landed
  (`models/kb.py`, `models/agent_memories.py`); AGENTS.md's end-to-end list
  omits knowledge base, memories, and the context hub; and the single user
  guide (`docs/guides/skills-files-knowledge-memories.md`) labels Memories
  "(coming soon)" although they shipped.
- History and posture verified clean, for the record: a full 249-commit
  scan found zero real secrets ever committed; no `.env`/key file was ever
  added; CORS/CSRF/rate-limiting/security-header middleware is strong;
  compose binds `127.0.0.1` only; there is **no telemetry or phone-home
  anywhere** — a differentiator the README should state (Step 1).

## Commands you will need

| Purpose | Command (repo root unless noted) | Expected on success |
|---------|----------------------------------|---------------------|
| Workflow syntax | `cd apps/api && for f in ../../.github/workflows/*.yml ../../.github/dependabot.yml; do uv run python -c "import sys,yaml; yaml.safe_load(open(sys.argv[1]))" "$f" || exit 1; done` | exit 0 |
| README local links | `cd apps/api && uv run python -c "import re,pathlib; md=pathlib.Path('../../README.md').read_text(); missing=[t for t in re.findall(r'\]\((?!http)([^)#]+)\)', md) if not (pathlib.Path('../..')/t).exists()]; print(missing); raise SystemExit(1 if missing else 0)"` | `[]`, exit 0 |
| Stale-claim regression grep | `grep -n "focus i \|Node.js 22\|still being normalized\|No license file\|early porting stage\|auditability notifications\|pnpm lint" README.md` | no matches |
| Image contains no `.local` | `docker build -t praxis-api-check --target production apps/api && docker run --rm --entrypoint sh praxis-api-check -c 'ls /app/.local 2>&1'` | `ls: /app/.local: No such file or directory` |
| Prod audit clean after Step 0 | `cd apps/web && pnpm audit --prod` | 0 vulnerabilities |
| OpenAPI export (local) | from `apps/api`, with a valid local `.env`: `uv run python -c "import json; from main import app; print(json.dumps(app.openapi()))" > /tmp/openapi.json && uv run python -m json.tool /tmp/openapi.json > /dev/null` | exit 0 |
| Focused tests (settings touches) | `cd apps/api && uv run pytest tests/contract tests/core -q` | all pass |
| Full gate | `make check` | exit 0 |

## Scope

**In scope:**

- Step 0 hardening: `apps/api/.dockerignore`, the placeholder-secret /
  `SECURE_COOKIES` validator in `apps/api/core/settings/` (+ tests),
  `apps/web/package.json` (`shadcn` → devDependencies), the path redaction
  in `docs/plans/complete/003-cloud-storage-providers.md`, declaring
  `logfire` as a direct dependency in `apps/api/pyproject.toml`, and the
  doc-drift fixes in `AGENTS.md` and
  `docs/guides/skills-files-knowledge-memories.md`
- `README.md` (targeted upgrade, not a rewrite)
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`
  (create, repo root)
- `.github/ISSUE_TEMPLATE/` (bug + feature forms, `config.yml`),
  `.github/PULL_REQUEST_TEMPLATE.md`, optional `CODEOWNERS`
- `.github/dependabot.yml`, `.github/workflows/codeql.yml`,
  `.github/workflows/release.yml` (create)
- `.github/workflows/ci.yml` (SHA pins, `permissions:` block, audit job,
  Docker-build job, spec-export step)
- Version alignment: `apps/web/package.json`, `core/settings/app.py`,
  `apps/api/.env.example` (decision 7)
- The `v0.1.0` git tag (local; pushing is operator-gated)
- Roadmap bookkeeping per Step 6

**Out of scope (do NOT touch):**

- Everything gate G1 owns: compose migrations, health endpoints, env-init,
  quickstart, `stop_grace_period` — that is deployment plan 001 (amended
  per G1), executed separately.
- Everything gates G2–G4 defer: email transport, S3-compatible storage,
  password reset, email verification, `ENVIRONMENT` default semantics.
- MCP support, routes, models, or runtime behavior beyond the Step 0
  validator.
- A docs site, demo video/GIF capture, marketing copy.
- C05's metrics endpoint, 403-body filtering, and `LICENSE` itself.
- `docker-compose.yml`, both Dockerfiles, and `apps/web/nginx.conf`
  (security headers there are a G1/002 concern).
- Relicensing, `NOTICE`, CLA/DCO (STOP conditions).

## Git workflow

- Branch: `advisor/078-public-launch-readiness`
- Commit: `Cross - Public Launch Readiness` (Step 0 may land as its own
  commit `Cross - Pre-Launch Hardening` if the operator prefers)
- Tag `v0.1.0` locally in Step 4. Do NOT push the branch, open a PR, or
  push the tag unless the operator instructed it — the tag push is what
  triggers image publication, and decision 9 gates it on G0–G5.

## Steps

### Step 0: Pre-flight hardening (gates the tag; do first)

1. **`.dockerignore`**: add `.local/` (and `.local`) to
   `apps/api/.dockerignore`. Resolve the "keep in sync with
   `.gcloudignore`" header: either create `apps/api/.gcloudignore` to match
   or correct the comment — do not leave it pointing at a missing file.
2. **Placeholder-secret rejection**: extend settings validation (same
   guard-rail pattern as `validate_runtime_provider_config` in
   `core/settings/__init__.py`) so that when `ENVIRONMENT != "local"`:
   the known `.env.example` placeholder values of `SECRET_KEY`
   (`not-a-secret-local-development-secret-key-change-me`) and
   `ENCRYPTION_KEY` (`bm90LWEtc2VjcmV0LWxvY2FsLWRldi1rZXktMDAwMDA=`) are
   rejected by exact match, and `SECURE_COOKIES=false` is rejected. Error
   messages must name the env var and the fix. Add focused tests beside the
   existing settings-validation tests (auth/session handling is a
   high-risk area — test both rejection and the local-environment pass).
   This executes the first high-priority task in
   `docs/plans/complete/deployment-000-security-review.md`; tick it there with a
   note that it landed via Lane P (Step 6).
3. **`shadcn` → `devDependencies`** in `apps/web/package.json`; run
   `pnpm install` to refresh the lockfile.
4. **Remove private-source notes**: delete the dedicated source roadmap and
   remove source-specific attributions and critiques from tracked planning
   and architecture documents while retaining durable technical decisions.
   Grep the tracked tree for absolute developer-home paths and the retired
   source identifiers to confirm there are no remaining references.
5. **Declare `logfire`**: `core/observability.py:5` imports `logfire`,
   which resolves only transitively via `pydantic-ai-slim[logfire]`. Add it
   as a direct dependency in `apps/api/pyproject.toml` (`uv add logfire`)
   so a pydantic-ai extras change cannot silently break startup.
6. **Doc drift**: in `AGENTS.md`, replace the stale "no vector columns
   exist yet" sentence with the truth (KB chunks and agent memories carry
   `HALFVEC` embeddings with HNSW indexes) and add knowledge base,
   memories, and the context hub to the wired-end-to-end list. In
   `docs/guides/skills-files-knowledge-memories.md`, remove
   "(coming soon)" from Memories and check the rest of the guide against
   the shipped UI.

**Verify**: the image-contents check from the commands table → no `.local`;
`cd apps/api && uv run pytest tests/contract tests/core -q` → pass (with the
new validator tests); `cd apps/web && pnpm audit --prod` → 0
vulnerabilities; `git grep -n '/''Users/' -- ':!*.local*'` → no
tracked hits; `make check` → exit 0.

### Step 1: README upgrade

Targeted changes to the existing (already good) README — preserve
everything C05 and later plans fixed:

1. Badges after the title: CI
   (`https://github.com/Greg-Asquith/praxis-agents-os/actions/workflows/ci.yml/badge.svg`),
   License (Apache-2.0), Python 3.12, Node 24. (They 404 until the workflow
   exists on the GitHub default branch — note this in the report, do not
   push to test.)
2. Screenshot/demo-GIF placeholders as HTML comments (capture needs a
   running seeded instance — see Maintenance notes); do not ship broken
   image links.
3. Feature list refresh (`README.md:11-37`): add the named integrations
   (Gmail, Airtable, Google BigQuery, Google Ads) with their auth modes
   (OAuth / API key / service account), service-account connections, the
   knowledge base with hybrid keyword+semantic search, agent memory with
   operator review, the context hub, and the behavior eval harness
   (`make evals`, deliberately outside `make check`). Keep the honest
   notifications caveat. Do not name a capability the inventory did not
   verify as wired end to end.
4. Honest positioning paragraph vs LangGraph/dify/n8n-class tools per
   decision 8.
5. Correct `README.md:183`: anonymous docs/Swagger/ReDoc stay disabled;
   authenticated users can fetch the schema at
   `GET /api/v1/meta/openapi.json`; CI publishes `openapi.json` as a build
   artifact (after Step 5).
6. Add a short **"No telemetry"** statement: the platform sends nothing
   home — no analytics, no phone-home; observability is opt-in and
   self-hosted. (Verified true 2026-07-28; it is a selling point.)
7. Add a short **"Operations"** section: back up the Postgres volume
   (`pg_dump` for the compose path — the audit trail lives there); upgrade
   ordering (stop worker → `alembic upgrade heads` → start API; migrations
   are never auto-applied); pointer to `docs/plans/deployment/` for the
   deployment plans, with the G2 posture stated per the maintainer's
   recorded decision.
8. Repository layout: add `docs/architecture/`, `makefiles/`, `LICENSE`.
9. Architecture pointer: link `docs/architecture/` naming the stable
   references (`agent-runtime.md`, `governance.md`, `threat-model.md`,
   `agent-context.md`, `integration-packaging.md`,
   `integration-events.md`); do not enumerate the plan-shaped or
   deferred-scope docs. Plans pointer to `docs/plans/000_README.md`.
10. Leave an HTML comment placeholder where deployment plan 001's
    "Quickstart (Docker only)" section will land (decision 12); make no
    compose-quickstart claim yourself.

**Verify**: the regression grep from the commands table → no matches; the
local-link check → `[]`; `grep -n "meta/openapi.json" README.md` → match;
`grep -ni "telemetry" README.md` → match.

### Step 2: Community health pack

- `SECURITY.md`: coordinated disclosure via GitHub private vulnerability
  reporting (Security → Report a vulnerability); no public issues for
  vulnerabilities; supported versions table (latest 0.x minor only);
  response expectation stated honestly (acknowledgement target, no SLA);
  plus a short **deployment hardening** note covering the G4 safe ordering
  (`ALLOW_SIGNUP=false` → register admin → set `SUPER_ADMIN_EMAILS`) and a
  pointer to the deployment security review. The repo-settings toggle for
  private reporting is a maintainer click — record it in your report.
- `CONTRIBUTING.md`: dev setup (`make bootstrap` / `make dev` /
  `make check`), the plan-driven workflow (`docs/plans/000_README.md`;
  AGENTS.md is the standards document), PR expectations (focused changes,
  tests in proportion to risk, run the gate, commit message style), and
  the 0.x posture from decision 4.
- `CODE_OF_CONDUCT.md`: Contributor Covenant 2.1 verbatim; enforcement
  contact is the maintainer via GitHub (see STOP conditions before
  inventing an email).
- `.github/ISSUE_TEMPLATE/bug_report.yml` and `feature_request.yml`
  (issue forms: environment, reproduction, expected/actual; problem,
  proposal, alternatives) plus `config.yml` with
  `blank_issues_enabled: true` and a security link to `SECURITY.md`.
- `.github/PULL_REQUEST_TEMPLATE.md`: summary, linked issue/plan, checks
  run, risk areas touched (mirrors AGENTS.md's high-risk list).
- Optional: `.github/CODEOWNERS` with `* @Greg-Asquith`.

**Verify**: `for f in SECURITY.md CONTRIBUTING.md CODE_OF_CONDUCT.md .github/PULL_REQUEST_TEMPLATE.md .github/ISSUE_TEMPLATE/bug_report.yml .github/ISSUE_TEMPLATE/feature_request.yml .github/ISSUE_TEMPLATE/config.yml; do test -s "$f" || echo "MISSING $f"; done`
→ no output; the issue forms YAML-parse;
`grep -n "ALLOW_SIGNUP" SECURITY.md` → match.

### Step 3: Supply chain & CI hardening

1. `.github/dependabot.yml`: ecosystems `uv` (directory `/apps/api`),
   `npm` (`/apps/web`), `github-actions` (`/`); weekly schedule; group
   minor/patch updates per ecosystem to bound PR noise.
2. `.github/workflows/codeql.yml`: languages `python` and
   `javascript-typescript`, on push/PR to `main` plus a weekly cron,
   `security-events: write` permission only.
3. Audit job in `ci.yml` (`continue-on-error: true` per decision 3):
   `uv export --format requirements-txt` piped to `uvx pip-audit -r -`
   for the API (verified working, 154 hash-pinned requirements);
   `pnpm audit --prod` for the web (zero expected after Step 0.3).
4. **Docker-build job in `ci.yml`**: build both production images
   (`docker build --target production apps/api` and
   `docker build --target production apps/web` with a placeholder
   `VITE_API_BASE_URL` once the ARG plumbing exists — until then build the
   web dev target or skip web with a comment). Build only, no push, no
   registry login. Rationale: today nothing ever builds these images in CI,
   so the tag-triggered release would be the first-ever build of the
   artifact being announced.
5. Add an explicit least-privilege `permissions:` block to every workflow
   (`contents: read` baseline; job-level additions only where needed).
6. SHA-pin every third-party action in all workflows (the existing five
   tag-pinned uses in `ci.yml` plus any introduced by Steps 3–5) per
   decision 5, with `# vX.Y.Z` trailing comments.

**Verify**: all workflow files + `dependabot.yml` YAML-parse;
`grep -En 'uses: .+@(v?[0-9.]+|main|master)\s*(#.*)?$' .github/workflows/*.yml | grep -v '@[0-9a-f]\{40\}'`
→ no matches; `grep -Ln 'permissions:' .github/workflows/*.yml` → no files
listed; the api image builds locally with
`docker build --target production apps/api`.

### Step 4: First tagged release

1. `CHANGELOG.md` in Keep a Changelog format with the decision-4 semver
   note in the header. Seed `## [0.1.0] - <tag date>` from the completed
   work in `docs/plans/000_README.md` (now ~100 completed plans), written
   as user-facing feature groups — auth/workspaces; agent runtime with
   approvals, delegation, cancellation, and memory; conversations/SSE with
   compaction and summarisation; skills; knowledge base with hybrid
   search; schedules; files and storage; artifacts and share links;
   integrations (Gmail, Airtable, BigQuery, Google Ads) and service
   accounts; tool catalog and governance; audit/security events; eval
   harness; CI/DX. Do not cite plan numbers.
2. Align versions per decision 7 (all four sites): `apps/web/package.json`
   → `0.1.0`; `APP_VERSION` default → `"0.1.0"`;
   `apps/api/.env.example:12` → `APP_VERSION=0.1.0`. (Verified: no test
   pins `"1.0.0"`.)
3. `.github/workflows/release.yml`: trigger `push: tags: ["v*"]`;
   `permissions: contents: read, packages: write`; checkout (SHA-pinned —
   an Actions checkout is clean by construction, and Step 0.1 protects
   local builds too), `docker login ghcr.io` with `GITHUB_TOKEN`, shell
   `docker build` of the `apps/api` `production` target, pushed as
   `ghcr.io/greg-asquith/praxis-agents-os-api:<version>` and `:latest`.
   API image only (decision 6); prefer shell over more third-party
   actions. Add a post-build guard step in the workflow:
   `docker run --rm --entrypoint sh IMAGE -c '! test -d /app/.local'`.
4. `git tag -a v0.1.0 -m "Praxis Agents OS 0.1.0"` on the release commit.
   Do not push it (Git workflow rule; decision 9 gates).

**Verify**: `grep -n '\[0.1.0\]' CHANGELOG.md` → match;
`grep -rn '0.1.0' apps/web/package.json apps/api/core/settings/app.py apps/api/.env.example` → match in each;
`git tag --list v0.1.0` → `v0.1.0`; `release.yml` YAML-parses;
`cd apps/api && uv run pytest tests/contract -q` → pass.

### Step 5: OpenAPI spec export in CI

In the `ci.yml` api job (after `uv sync`), add: export the schema with
`uv run --locked python -c "import json; from main import app; print(json.dumps(app.openapi()))" > openapi.json`
(the job env already provides valid settings) and upload it with
`actions/upload-artifact` (SHA-pinned) as `openapi-spec`. Per decision 2,
`main.py` is not modified and the file is not committed.

**Verify**: the local OpenAPI export command from the commands table
produces valid JSON; `ci.yml` YAML-parses.

### Step 6: Roadmap and cross-plan bookkeeping

Lane P already exists in both index docs, so this step is reconciliation:

1. `docs/plans/000_README.md`: flip the 078 status row; note the revision
   date and that Step 0 absorbed the placeholder-secret task.
2. `docs/plans/000_MASTER_ROADMAP.md`: the roadmap never mentions
   `docs/plans/deployment/` — add one sentence to the Lane P section
   pointing at it and at the launch gates in this plan.
3. `docs/plans/complete/deployment-000-security-review.md`: tick the
   placeholder-secret task (landed via Step 0) and annotate the "pin
   third-party Actions by SHA" bullet as owned/done by Lane P (decision 5)
   so 002 Stage 3 does not redo it.
4. `docs/plans/complete/deployment-001-local-quickstart.md`: completed
   2026-07-28 with the `stop_grace_period` requirement implemented.
5. Record the maintainer's G2–G5 decisions wherever they land (roadmap
   note, README wording, or new follow-up plan stubs) so the next plan
   does not re-litigate them.

**Verify**: `grep -n "| 078 |" docs/plans/000_README.md` shows the updated
status; `grep -n "deployment/" docs/plans/000_MASTER_ROADMAP.md` → match;
`grep -n "stop_grace_period" docs/plans/complete/deployment-001-local-quickstart.md`
→ match.

## Test plan

Mostly static artifacts, so verification is mostly static — the regression
greps, README links resolving, every workflow and template YAML-parsing,
and `make check` staying green. The code touches are covered by: new
settings-validator tests (rejection outside local + pass inside local),
the contract suite for the `APP_VERSION` default, `pnpm check` +
`pnpm audit --prod` for the dependency move, and local
`docker build --target production` runs for both the dockerignore fix and
the new CI build job. Three things cannot be verified before a push and
must be called out in the report instead: badge URLs returning 200, CodeQL
completing on the default branch, and the release workflow actually
publishing (it runs only on a pushed tag). Do not push to test them.

## Execution notes (2026-07-28)

- The GitHub repository is public, so the CodeQL STOP condition does not
  apply. GitHub private vulnerability reporting is available but currently
  disabled; the maintainer must enable it in repository settings before
  launch.
- G2's honest-documentation fallback is recorded in the README: production
  currently requires cloud-backed storage and secrets, and email delivery is
  pending. G3 is also documented: there is no self-service password reset,
  and operators need a tested super-admin recovery path. G4's safe
  super-admin claim ordering is in `SECURITY.md`.
- G5 was resolved by the maintainer on 2026-07-28: source-specific notes were
  removed, the unused branded support-address constant was removed, and no
  `NOTICE` file is needed for the retired codebase because it was owned by the
  same maintainer. Static verification found no remaining retired source
  identifiers, support-address references, or absolute developer-home paths.
- The current `pip-audit` rejects the drafted `-r -` stdin form. CI exports a
  fully hashed requirements file and audits it with `--disable-pip
  --require-hashes`; the first run found three 2026 advisories in transitive
  `pyasn1` and the lock was advanced from 0.6.3 to the fixed 0.6.4.
- After `shadcn` moved to development dependencies, a new PostCSS advisory
  still entered the production audit through the build-only
  `@tailwindcss/vite` plugin. It was also reclassified as a development
  dependency, taking `pnpm audit --prod` to zero without changing the browser
  bundle.
- Importing `main` emits an informational setup log on stdout, so the CI
  OpenAPI export disables Python logging before the import. The resulting
  artifact is valid JSON without changing application logging behavior.
- The final repository gate passed twice on 2026-07-28, including after the G5
  cleanup: `make check` completed with 1,302 backend tests and 410 frontend
  tests passing. The concurrent home-route loader cleanup made three
  query-option factories module-private; their stale `export` modifiers were
  removed so the frontend dead-code gate reflects the new route boundary.

## Done criteria

Machine-checkable. ALL must hold:

- [x] Step 0 verifications all pass: production image contains no
      `/app/.local`; placeholder `SECRET_KEY`/`ENCRYPTION_KEY` and
      `SECURE_COOKIES=false` are rejected outside `ENVIRONMENT=local`
      (tests prove it); `pnpm audit --prod` → 0; no tracked
      absolute developer-home path; `logfire` is a declared dependency;
      AGENTS.md and the user guide no longer contradict shipped features
- [x] README regression grep → no matches; local-link check prints `[]`;
      README has badges, positioning, the corrected OpenAPI claim, the
      no-telemetry statement, the Operations section, and architecture +
      plans pointers
- [x] Community profile complete: `LICENSE`, `README.md`,
      `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` (with the G4
      hardening note), both issue forms + `config.yml`, and
      `.github/PULL_REQUEST_TEMPLATE.md` all exist and are non-empty
- [x] `.github/dependabot.yml`, `codeql.yml`, `release.yml` exist; every
      workflow YAML-parses, has a `permissions:` block, and no third-party
      action is tag-pinned (Step 3 grep returns nothing); the `audit` job
      exists with `continue-on-error: true`; CI builds the API production
      image; `release.yml` contains the no-`.local` guard step
- [ ] `CHANGELOG.md` contains `[0.1.0]`; `0.1.0` appears in
      `apps/api/pyproject.toml`, `apps/web/package.json`, the
      `APP_VERSION` settings default, and `apps/api/.env.example`;
      `git tag --list v0.1.0` → `v0.1.0`
- [x] `ci.yml` exports and uploads `openapi.json`; the local export
      command produces valid JSON
- [x] `make check` exits 0
- [ ] Step 6 bookkeeping done in all four target docs; G2–G5 decisions
      recorded (or explicitly listed as outstanding in the report — they
      block the tag push, not this plan's completion)

## STOP conditions

Stop and report back (do not improvise) if:

- Any license question arises beyond pointing at the existing Apache-2.0
  `LICENSE` — relicensing, a NOTICE file, CLA/DCO policy, or third-party
  license auditing are maintainer decisions (gate G5).
- A `SECURITY.md`/`CODE_OF_CONDUCT.md` contact needs a real email address
  or GitHub private vulnerability reporting is unavailable for the repo —
  the disclosure channel is a maintainer decision; do not invent one.
- You are tempted to solve gate G2 by weakening
  `validate_runtime_provider_config` or any CORS/cookie/CSRF/rate-limit
  setting — that guard rail stays; G2 is a maintainer decision.
- The Step 0 validator would reject a value the maintainer actually uses
  in a non-local environment — surface it; do not special-case silently.
- Any future source-attribution or support-contact policy change needs a
  maintainer judgement call.
- Anything would enable a billed service — paid CI, external scanning
  SaaS, docs hosting, registries beyond GHCR's free tier. CodeQL and
  Dependabot are free for public repos; if the repo is private when you
  execute, stop before adding CodeQL.
- Dependabot rejects the `uv` ecosystem — fall back to `pip` and record
  the substitution.
- You are tempted to push the branch or the `v0.1.0` tag to "test" the
  badges or the release workflow — that is the operator's call, and
  decision 9 gates the tag on G0–G5 regardless.

## Maintenance notes

- **Release cadence rule**: tag a minor release per meaningful feature
  batch; the CHANGELOG entry, the four version fields, and the tag move
  together in one commit. Breaking changes are allowed in 0.x minors
  (decision 4) but must be listed under a `Changed`/`Removed` heading.
- **Release build rule**: release images are built by the workflow from a
  clean checkout, never pushed from a developer machine; the no-`.local`
  guard step stays in `release.yml` permanently.
- **README screenshots rule**: the placeholders become real captures once
  a seeded instance exists (gate G1 makes this easy); recapture whenever
  the chat, agent form, context hub, or schedules surfaces change
  materially. Stale screenshots are worse than placeholders.
- **Audit job flip**: after the first triage pass over `pip-audit`/
  `pnpm audit` findings, remove `continue-on-error` so the job blocks.
- **Eval results**: plan 055 is DONE and `make evals` exists — publishing
  eval results is now unblocked and becomes a strong Lane P follow-up
  (methodology + results page), no longer contingent.
- **Future Lane P plans (recorded, not executed here)**: a docs site
  seeded from `docs/architecture/`; a self-hoster configuration guide
  (the settings audit found 114 of 256 settings fields undocumented,
  including `METRICS_ENABLED`/`METRICS_TOKEN` and all `KB_*`/`MEMORY_*`/
  `JOBS_*`/`DB_POOL_*` knobs — the metrics endpoint C05 shipped is
  currently undiscoverable); a reverse-proxy/TLS example for the compose
  path (same-site cookie constraint + SSE `proxy_buffering off`); a
  one-command seeded demo (`make demo`); a demo video/GIF; error
  aggregation guidance (no Sentry-class integration exists); publishing
  eval results; deployment guides beyond GCP (deployment plan templates
  exist); web `.env.example` + meta/OG tags; a real `alembic downgrade`
  for `core_0011` (its downgrade body is a no-op docstring); and the G3/G4
  product fixes (password reset, email verification) once G2's email
  decision lands.
- Reviewers should scrutinize: `release.yml` permissions staying minimal,
  the README making no claim beyond what is wired end to end (especially
  around compose quickstart and production self-hosting until G1/G2
  resolve), the Step 0 validator not breaking `ENVIRONMENT=local`
  bootstraps, and that no artifact cites plan numbers.
