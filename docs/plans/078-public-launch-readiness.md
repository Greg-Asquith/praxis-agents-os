# Plan 078: Public launch readiness — README, community health, supply chain, and first release

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6be5491..HEAD -- README.md LICENSE CHANGELOG.md .github/ apps/api/main.py apps/api/core/settings/app.py apps/api/pyproject.toml apps/web/package.json docs/plans/complete/C05-production-readiness-gaps.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live files before proceeding. C05 is
> DONE as of 2026-07-09; preserve its README/license corrections when rewriting
> the public launch README.

## Status

- **Priority**: P1
- **Effort**: L (many small artifacts, no product code)
- **Risk**: LOW (docs/CI only; the release workflow is the only executable
  risk, and pushing the tag that triggers it is operator-gated)
- **Depends on**: C05 (DONE — see decision 1), C01 (DONE — CI exists). No product-plan
  dependencies; this plan can interleave at any time.
- **Category**: Lane P — public launch & adoption (new lane, added
  2026-07-07)
- **Planned at**: working tree at commit `6be5491`, 2026-07-07

## Product intent

The repository is engineered to be good — CI, a trustworthy local gate,
governance docs, an audited tool runtime — but nothing in the roadmap
makes it *visible*. Lanes R/O/C/H/Q all improve the product; no lane
covers adoption. C05 added the Apache-2.0 license and fixed the most obvious
README inaccuracies, but there is still no security policy, contributing
guide, issue template, dependency-update or code-scanning automation,
changelog, tagged release, or readable API spec. For a project whose
differentiator is governance and auditability, a missing SECURITY.md and
unpinned CI actions actively contradict the pitch. This plan opens Lane P
and ships the minimum credible public storefront: an accurate README, the
community health pack, supply chain hygiene, a `v0.1.0` release with a
published API image, and an exported OpenAPI spec.

## Decisions taken

1. **C05 precedence on the README.** C05
   (`docs/plans/complete/C05-production-readiness-gaps.md`, DONE
   2026-07-09) owns license/metrics/403-bodies plus *surgical* README
   corrections (its Step 4). This plan rewrites the README wholesale and
   must preserve every correction C05 made: the line-6 typo/comma fixes,
   Node.js 24, `make bootstrap` / `make dev` as the supported local flow,
   and the Apache-2.0 license note. C05's metrics and 403-body steps are
   complete and untouched here.
2. **OpenAPI export is a CI artifact, not a served route.** `main.py`
   disables `docs_url`/`redoc_url`/`openapi_url` deliberately (attack
   surface: the API serves credentialed browser clients, not anonymous
   spec readers). Keep that. `app.openapi()` still generates the schema
   regardless of `openapi_url=None`, so CI exports `openapi.json` as a
   build artifact. A settings-gated `/docs` in non-production would be
   product code and is rejected here; committing the file is rejected too
   (per-PR churn, no consumer yet). Revisit when a docs site exists.
3. **Dependency audit is non-blocking initially.** `pip-audit` and
   `pnpm audit` run as a CI job with `continue-on-error: true` until the
   first triage pass establishes a clean baseline; the flip to blocking
   is a maintenance-note rule, not a later plan.
4. **Semver 0.x posture.** While the major version is 0, breaking changes
   to APIs, schemas, and config are allowed in minor releases; patches
   are fixes only. Recorded in the CHANGELOG header and CONTRIBUTING.md —
   no compatibility promise is implied before 1.0.
5. **All third-party actions get SHA-pinned**, version as a trailing
   comment, with `dependabot.yml`'s `github-actions` ecosystem keeping
   the pins current. Resolve the SHAs at execution time (e.g.
   `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`) — this plan does not
   guess them.
6. **Release images: API only in v1.** The API image is
   deployment-portable (config via env). The web production image bakes
   `VITE_API_BASE_URL` into the bundle at build time
   (`apps/web/src/config/env.ts:4`; every `VITE_*` value is inlined), so
   a generic published web image cannot be retargeted at another API
   origin. Publish `ghcr.io/greg-asquith/praxis-agents-os-api` on tag;
   web runtime-config (then web image publication) is a Lane P follow-up.
7. **Versions align at `0.1.0`.** `apps/api/pyproject.toml` already says
   `0.1.0`; set `apps/web/package.json` (`0.0.0`) and the `APP_VERSION`
   settings default (`core/settings/app.py:13`, currently `"1.0.0"`) to
   match. The settings default — a constant — is the single code-adjacent
   touch in this plan.
8. **Positioning is honest, not aspirational.** The README compares
   against LangGraph/dify/n8n-class tools by *kind*: Praxis is not an
   orchestration framework or a visual workflow builder — it is a
   self-hosted, workspace-governed agent platform where audited tool
   dispatch, approval-gated side effects, and RBAC are the point. Claims
   are limited to what AGENTS.md lists as wired end to end; pending
   surfaces stay documented as pending.

## Why this matters

Every future adoption artifact (docs site, demo, launch post) builds on
this substrate, and none of it requires product code — so it can
interleave with Lane H and Phase 4a at any time. The cost of *not* doing
it compounds: evaluators bounce off a README that says the project is
unlicensed (it is Apache-2.0), security researchers have no disclosure
channel, and a governance-positioned project running tag-pinned actions
with no dependency updates is an easy dismissal.

## Current state

All anchors verified on the working tree at `6be5491` (2026-07-07).

- **README.md** remains a porting-era front door after C05's surgical fixes:
  - Line 10: "This repository is in an early porting stage." — stale; the
    index records ~50 executed plans across the product and quality lanes.
  - C05 corrected the line-6 typo/comma issue, the distrusted Docker/Compose
    copy, the Node.js 24 prerequisite, and the license note. Preserve those
    corrections in the rewrite.
  - Lines 191–195: frontend checks listed as `pnpm lint` + `pnpm build`;
    the actual gate is `pnpm check` (`makefiles/checks.mk:18-19`).
  - Line 232: "Add focused tests and CI as each surface becomes real" —
    CI exists (`.github/workflows/ci.yml`, since C01). `LICENSE` (Apache
    License 2.0) exists at the repo root.
  - No badges, screenshots, feature overview, positioning, or pointer to
    `docs/architecture/`.
- **.github/** contains only `workflows/ci.yml`. No `dependabot.yml`, no
  CodeQL workflow, no release workflow, no `ISSUE_TEMPLATE/`, no
  `PULL_REQUEST_TEMPLATE.md`.
- **ci.yml** pins actions by tag, not SHA: `actions/checkout@v7` (lines
  38, 78), `astral-sh/setup-uv@v8.2.0` (39), `pnpm/action-setup@v6.0.9`
  (79), `actions/setup-node@v6.4.0` (82). It has api and web jobs only —
  no audit, no CodeQL, no spec export.
- **Repo root** has no `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, or `CHANGELOG.md`.
- **main.py:68-75** constructs `FastAPI(... docs_url=None,
  redoc_url=None, openapi_url=None ...)` — no served spec;
  `app.openapi()` remains callable. **Versions disagree**:
  `apps/api/pyproject.toml:3` → `0.1.0`; `apps/web/package.json` →
  `0.0.0`; `core/settings/app.py:13` → `APP_VERSION` default `"1.0.0"`.
  `git tag` returns nothing.
- **Dockerfiles are production-shaped**: API runs non-root (`USER
  1001:1001`, `apps/api/Dockerfile:45`) on `python:3.12.10-slim` with a
  `production` target; web serves the built SPA from
  `nginxinc/nginx-unprivileged:1.27-alpine` (`apps/web/Dockerfile:36`).
  Compose defines postgres/api/worker/web. Nothing builds or publishes
  images (the deploy pipeline remains the deferred maintainer decision in
  C05's maintenance notes — untouched here).
- **docs/architecture/** holds `agent-runtime.md`, `governance.md`,
  `integration-packaging.md`, `agent-turn-streaming-plan.md`.
- **Roadmap lanes** R/O/C/H/Q cover hardening, ops surfaces, cleanup,
  harness, and quality; no lane or plan anywhere covers
  adoption/community/release. Remote: `github.com/Greg-Asquith/praxis-agents-os`.

## Commands you will need

| Purpose | Command (repo root unless noted) | Expected on success |
|---------|----------------------------------|---------------------|
| Workflow syntax | `cd apps/api && for f in ../../.github/workflows/*.yml ../../.github/dependabot.yml; do uv run python -c "import sys,yaml; yaml.safe_load(open(sys.argv[1]))" "$f" || exit 1; done` | exit 0 |
| README local links | `cd apps/api && uv run python -c "import re,pathlib; md=pathlib.Path('../../README.md').read_text(); missing=[t for t in re.findall(r'\]\((?!http)([^)#]+)\)', md) if not (pathlib.Path('../..')/t).exists()]; print(missing); raise SystemExit(1 if missing else 0)"` | `[]`, exit 0 |
| Stale-claim grep | `grep -n "focus i \|Node.js 22\|still being normalized\|No license file\|early porting stage\|auditability notifications" README.md` | no matches |
| OpenAPI export (local) | from `apps/api`, with a valid local `.env`: `uv run python -c "import json; from main import app; print(json.dumps(app.openapi()))" > /tmp/openapi.json && uv run python -m json.tool /tmp/openapi.json > /dev/null` | exit 0 |
| Focused tests (APP_VERSION touch) | `cd apps/api && uv run pytest tests/contract -q` | all pass |
| Full gate | `make check` | exit 0 |

## Scope

**In scope:**

- `README.md` (full rewrite)
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`
  (create, repo root)
- `.github/ISSUE_TEMPLATE/` (bug + feature forms, `config.yml`) and
  `.github/PULL_REQUEST_TEMPLATE.md` (create)
- `.github/dependabot.yml`, `.github/workflows/codeql.yml`,
  `.github/workflows/release.yml` (create)
- `.github/workflows/ci.yml` (SHA pins, audit job, spec-export step only)
- `apps/web/package.json` (`version` field only) and
  `apps/api/core/settings/app.py` (`APP_VERSION` default only)
- The `v0.1.0` git tag (local; pushing is operator-gated)
- `docs/plans/000_MASTER_ROADMAP.md` (Lane P section) and
  `docs/plans/000_README.md` (status row + Lane P note)

**Out of scope (do NOT touch):**

- A docs site, demo video/GIF capture, deployment guides — recorded as
  Lane P follow-ups, not executed here.
- MCP support, any product code, routes, models, or runtime behavior.
- A marketing site or marketing copy in the repo.
- C05's metrics endpoint, 403-body filtering, and `LICENSE` itself.
- The hosting/deploy pipeline decision (still deferred to the
  maintainer); `docker-compose.yml` and both Dockerfiles.

## Git workflow

- Branch: `advisor/078-public-launch-readiness`
- Commit: `Cross - Public Launch Readiness`
- Tag `v0.1.0` locally in Step 4. Do NOT push the branch, open a PR, or
  push the tag unless the operator instructed it — the tag push is what
  triggers image publication.

## Steps

### Step 1: README rewrite

Rewrite `README.md` as the storefront, in this order:

1. Title + one-paragraph 30-second pitch: a workspace-governed agent
   platform — audited tool dispatch, approval-gated side effects,
   agent-to-agent delegation, schedules, skills, files, SSE chat —
   Postgres-only, self-hostable, Apache-2.0.
2. Badges: CI
   (`https://github.com/Greg-Asquith/praxis-agents-os/actions/workflows/ci.yml/badge.svg`),
   License (Apache-2.0), Python 3.12, Node 24.
3. Screenshot/demo-GIF placeholders as HTML comments (capture needs a
   running seeded instance — see Maintenance notes); do not ship broken
   image links.
4. Features section grounded in AGENTS.md's wired-end-to-end list: auth
   (password, OAuth, TOTP, sessions), workspaces with RBAC and
   invitations, agents, conversations (SSE chat, tool calls, approvals,
   approval-resume), delegation, model catalog, skills, schedules
   (worker-driven; HTTP surface pending — say so), files, audit/security
   logs.
5. Honest positioning paragraph vs LangGraph/dify/n8n-class tools per
   decision 8.
6. Quickstart: prerequisites (Python 3.12, uv, **Node.js 24**, pnpm,
   Docker), then `make bootstrap` / `make dev` / `make check` as the
   supported flow, with per-app manual commands as the alternative. Preserve
   the C05 quickstart corrections.
7. Keep (corrected) sections: repository layout, technology, backend and
   frontend development, migrations, Compose env files. Frontend checks
   become `pnpm check`.
8. Architecture pointer to `docs/architecture/` (name the four docs) and
   plans pointer to `docs/plans/000_README.md`; license section says
   Apache-2.0 and points at `LICENSE` — the "no license file" claim goes.

**Verify**: the stale-claim grep from the commands table → no matches;
`grep -n "pnpm lint" README.md` → no matches; the local-link check → `[]`.

### Step 2: Community health pack

- `SECURITY.md`: coordinated disclosure via GitHub private vulnerability
  reporting (Security → Report a vulnerability); no public issues for
  vulnerabilities; supported versions table (latest 0.x minor only);
  response expectation stated honestly (acknowledgement target, no SLA).
  The repo-settings toggle for private reporting is a maintainer click —
  record it in your report.
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

**Verify**: `for f in SECURITY.md CONTRIBUTING.md CODE_OF_CONDUCT.md .github/PULL_REQUEST_TEMPLATE.md .github/ISSUE_TEMPLATE/bug_report.yml .github/ISSUE_TEMPLATE/feature_request.yml .github/ISSUE_TEMPLATE/config.yml; do test -s "$f" || echo "MISSING $f"; done`
→ no output; the two issue forms YAML-parse.

### Step 3: Supply chain & CI hardening

1. `.github/dependabot.yml`: ecosystems `uv` (directory `/apps/api`),
   `npm` (`/apps/web`), `github-actions` (`/`); weekly schedule; group
   minor/patch updates per ecosystem to bound PR noise.
2. `.github/workflows/codeql.yml`: languages `python` and
   `javascript-typescript`, on push/PR to `main` plus a weekly cron,
   `security-events: write` permission only.
3. Audit job in `ci.yml` (`continue-on-error: true` per decision 3):
   `uv export --format requirements-txt` piped to `uvx pip-audit -r -`
   for the API; `pnpm audit --prod` for the web.
4. SHA-pin every third-party action in all workflows (the existing four
   in `ci.yml` plus any introduced by this step and Steps 4–5) per
   decision 5, with `# vX.Y.Z` trailing comments.

**Verify**: all workflow files + `dependabot.yml` YAML-parse;
`grep -En 'uses: .+@(v?[0-9.]+|main|master)\s*(#.*)?$' .github/workflows/*.yml | grep -v '@[0-9a-f]\{40\}'`
→ no matches.

### Step 4: First tagged release

1. `CHANGELOG.md` in Keep a Changelog format with the decision-4 semver
   note in the header. Seed `## [0.1.0] - 2026-07-07` from the completed
   work recorded in `docs/plans/000_README.md`, written as user-facing
   feature groups (auth/workspaces, agent runtime + approvals +
   delegation, conversations/SSE, skills, schedules, files, storage,
   audit, CI/DX) — do not cite plan numbers.
2. Align versions per decision 7: `apps/web/package.json` → `0.1.0`;
   `APP_VERSION` default → `"0.1.0"`. Grep tests for a pinned `"1.0.0"`
   first and update any assertion you find.
3. `.github/workflows/release.yml`: trigger `push: tags: ["v*"]`;
   `permissions: contents: read, packages: write`; checkout (SHA-pinned),
   `docker login ghcr.io` with `GITHUB_TOKEN`, shell `docker build` of
   the `apps/api` `production` target, pushed as
   `ghcr.io/greg-asquith/praxis-agents-os-api:<version>` and `:latest`.
   API image only (decision 6); prefer shell over more third-party
   actions.
4. `git tag -a v0.1.0 -m "Praxis Agents OS 0.1.0"` on the release commit.
   Do not push it (Git workflow rule).

**Verify**: `grep -n '\[0.1.0\]' CHANGELOG.md` → match;
`grep -n '"version": "0.1.0"' apps/web/package.json` and
`grep -n '0.1.0' apps/api/core/settings/app.py` → match each;
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

### Step 6: Record Lane P in the roadmap

Add a short "Lane P — Public Launch & Adoption (added 2026-07-07; plan
078)" section to `docs/plans/000_MASTER_ROADMAP.md`: what 078 ships, plus
the Maintenance-notes follow-ups as *future* Lane P plans (not numbered
yet). Add the 078 row and a one-paragraph provenance note to
`docs/plans/000_README.md`; cross-reference decision 1 in its C05
dependency note so whoever executes C05 sees the README precedence rule.

**Verify**: `grep -n "Lane P" docs/plans/000_MASTER_ROADMAP.md docs/plans/000_README.md`
→ matches in both; `grep -n "| 078 |" docs/plans/000_README.md` → match.

## Test plan

Honest: this plan is almost entirely static artifacts, so verification is
static — the stale-claim and version greps, README local links resolving,
every workflow and template YAML-parsing, and `make check` staying green.
The one code-adjacent touch (`APP_VERSION` default) is covered by the
contract suite plus the full gate. Two things cannot be verified before a
push and must be called out in the report instead: badge URLs returning
200 (they 404 until the workflow exists on the GitHub default branch) and
the release workflow actually publishing (it runs only on a pushed tag).
Do not push to test them.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "focus i \|Node.js 22\|still being normalized\|No license file\|early porting stage\|auditability notifications" README.md`
      → no matches, and the README local-link check prints `[]`
- [ ] Community profile set complete: `LICENSE`, `README.md`,
      `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, both issue
      forms + `config.yml`, and `.github/PULL_REQUEST_TEMPLATE.md` all
      exist and are non-empty
- [ ] `.github/dependabot.yml`, `codeql.yml`, `release.yml` exist; every
      workflow file YAML-parses; the `audit` job exists with
      `continue-on-error: true`
- [ ] No third-party action pinned by tag: the Step 3 grep returns nothing
- [ ] `CHANGELOG.md` contains `[0.1.0]`; `0.1.0` appears in
      `apps/api/pyproject.toml`, `apps/web/package.json`, and the
      `APP_VERSION` default; `git tag --list v0.1.0` → `v0.1.0`
- [ ] `ci.yml` exports and uploads `openapi.json`; the local export
      command produces valid JSON
- [ ] `make check` exits 0
- [ ] Lane P recorded in `000_MASTER_ROADMAP.md`; the 078 row and the C05
      cross-reference updated in `docs/plans/000_README.md`

## STOP conditions

Stop and report back (do not improvise) if:

- Any license question arises beyond pointing at the existing Apache-2.0
  `LICENSE` — relicensing, a NOTICE file, CLA/DCO policy, or third-party
  license auditing are maintainer decisions.
- C05's completed README corrections are not present in the working tree —
  reconcile before rewriting instead of reintroducing stale claims.
- A `SECURITY.md`/`CODE_OF_CONDUCT.md` contact needs a real email address
  or GitHub private vulnerability reporting is unavailable for the repo —
  the disclosure channel is a maintainer decision; do not invent one.
- Anything would enable a billed service — paid CI, external scanning
  SaaS, docs hosting, registries beyond GHCR's free tier. CodeQL and
  Dependabot are free for public repos; if the repo is private when you
  execute, stop before adding CodeQL.
- Dependabot rejects the `uv` ecosystem — fall back to `pip` and record
  the substitution.
- You are tempted to push the branch or the `v0.1.0` tag to "test" the
  badges or the release workflow — that is the operator's call.

## Maintenance notes

- **Release cadence rule**: tag a minor release per meaningful feature
  batch; the CHANGELOG entry, the three version fields, and the tag move
  together in one commit. Breaking changes are allowed in 0.x minors
  (decision 4) but must be listed under a `Changed`/`Removed` heading.
- **README screenshots rule**: the placeholders become real captures once
  a seeded instance exists; recapture whenever the chat, agent form, or
  schedules surfaces change materially. Stale screenshots are worse than
  placeholders.
- **Audit job flip**: after the first triage pass over `pip-audit`/
  `pnpm audit` findings, remove `continue-on-error` so the job blocks.
- **Future Lane P plans (recorded, not executed here)**: a docs site
  seeded from `docs/architecture/`; a one-command seeded demo
  (`make demo`); a demo video/GIF; publishing eval results once plan 055
  lands; deployment guides (pairs with the deferred hosting decision in
  C05's maintenance notes); web runtime configuration so the web image
  can be published per decision 6.
- Reviewers should scrutinize: `release.yml` permissions staying minimal,
  the README making no claim beyond what is wired end to end, and that
  no artifact cites plan numbers.
