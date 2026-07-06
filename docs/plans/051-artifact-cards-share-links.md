# Plan 051: Chat artifact cards, versions UI, and share links

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G3 pre-flight**: `docs/architecture/governance.md` exists (029 DONE
> 2026-07-06). Re-verify every governance citation below (§1 share-link
> roles, §3 share retention, §4 share rate limit) — the note wins. When this
> plan ships, flip those cells to `[implemented: plan 051]` in the same PR.
>
> **Cross-plan pre-flight (run before Step 1)**: plan 050 must be
> implemented (the `artifacts` table, `services/artifacts/`
> `serve_artifact_version.py`, the `/artifacts/view` serving route, and the
> middleware carve-outs — including the reserved `/artifacts/shared` path
> prefix in `_is_artifact_serving_path`). Plans 030 (jobs harness) and 031
> (File/FileRevision) are implemented at `a0eea1c`; 032's upload/edit
> services are in flight on disk — verify the file-service seams cited below
> against the landed code. If 050 is not implemented, STOP.
>
> **Security review (mandatory)**: the share slice is the platform's FIRST
> anonymous-access surface. Before merge, request a dedicated
> security-auditor review of Steps 2–5 and the Step 8 invariants (token
> handling, uniform 404s, header set, log redaction, rate limits). Record
> the review outcome in the PR description.
>
> **Drift check (run first)**:
> `git diff --stat a0eea1c..HEAD -- apps/api/main.py apps/api/middleware/ apps/api/core/rate_limiting.py apps/api/core/settings/ apps/api/models/ apps/api/routes/ apps/api/services/artifacts/ apps/api/services/files/ apps/api/services/jobs/ apps/api/workers/job_runner.py apps/api/utils/security.py apps/web/src/features/conversations/ apps/web/src/app/router.tsx apps/web/src/config/navigation.ts`
> Files WILL have changed (050 and the remaining Phase 3 plans land first).
> Compare the "Current state" excerpts against live code before proceeding;
> treat a structural mismatch (rate limiter keying, serving pipeline shape,
> tool-row registry seam, jobs handler assembly) as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH (first anonymous-access surface; unguessable-token
  authorization; donor §4.6 rule: "treat as high-risk, small, and explicit")
- **Depends on**: hard — 050 (artifacts model + CSP-locked serving), 030
  (jobs harness, DONE — sweep kind registration), 031 (FileRevisions, DONE —
  version chain), Gate G3 (satisfied). Soft: 035 (files UI revision-diff
  component — reuse if landed, decision 10).
- **Category**: Phase 6 artifacts (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 6 row 051; donor `DONOR_PORT_ROADMAP.md` §4.6 / §6 row F2)
- **Planned at**: commit `a0eea1c`, 2026-07-06

## Decisions taken

1. **Token scheme**: `secrets.token_urlsafe(32)` — 256 bits of entropy,
   ~43 URL-safe chars, comfortably above the dictated ≥128-bit floor. The
   token is returned exactly once (share-creation response) and never
   stored: the row keeps `token_hash = hash_token(token)` (plain SHA-256
   hex, `utils/security.py:70-82`) plus an 8-char `token_prefix` for admin
   display. Plain SHA-256 (not a slow KDF) is correct here: the input is
   256-bit random, so offline brute force is infeasible and a slow hash
   would only tax the anonymous hot path. Lookup is a unique-index SELECT
   by `token_hash` — the comparison happens on the digest, so response
   timing does not vary with stored-token similarity ("constant-time-ish");
   uniform 404s (decision 3) close the rest of the enumeration surface.
2. **Version-pinned, always, in v1.** `version_id` is non-nullable and
   stamped with the artifact's `current_version_id` at share creation
   (dictated: pinned by default). A "follow latest" mode is deferred — it
   is a one-column relaxation later, and shipping it now would silently
   publish future revisions through old links. Recorded here so the
   deferral is deliberate.
3. **Enumeration resistance = uniform 404.** Unknown token, expired,
   revoked, artifact soft-deleted — all return the identical problem+json
   404 (typed `NotFoundError`) with no differentiating detail, body, or
   header. Expired/revoked shares are indistinguishable from tokens that
   never existed.
4. **Share-creation rate limit (governance §4: 10/hour/workspace)** rides
   the existing Postgres limiter unchanged. The limiter keys on
   `(ip, endpoint, limit_type, window)` and validates `ip` as an IP literal
   (`core/rate_limiting.py:96-109`), so a per-workspace (not per-IP) limit
   uses a documented sentinel: `check_rate_limit(ip="0.0.0.0",
   endpoint=f"artifact_share_create:{workspace_id}",
   limit_type="artifact_share_creation", custom_limit=10,
   custom_window=3600)`, wrapped in
   `services/artifacts/utils.py::check_workspace_share_rate_limit(db, workspace_id)`
   with a comment explaining the sentinel. No limiter schema or API change;
   if the limiter later grows a first-class subject key, migrate the
   wrapper. Blocked requests raise the existing `RateLimitError`
   (`core/rate_limiting.py:390-411` — RFC 7807 + `X-RateLimit-*`/
   `Retry-After` headers).
5. **Share-access rate limit (defense in depth, not governance-mandated)**:
   the anonymous route also applies
   `require_rate_limit(custom_limit=120, custom_window=3600)`
   (`core/rate_limiting.py:414-445`, per-IP) so token guessing and
   scraping are throttled beyond the global middleware limits. Recorded as
   a deviation-free addition (governance §4 names only the creation limit).
6. **Access audit is throttled by `last_accessed_at`**: every successful
   access does one atomic
   `UPDATE ... SET access_count = access_count + 1, last_accessed_at = now()`
   returning the previous `last_accessed_at`; an audit row (action `READ`,
   resource `artifact_share`, actor_type `SYSTEM`, actor_display
   `"anonymous"`, details = ip/user_agent/artifact_id) is written only when
   the previous value is NULL or older than 1 hour. Bounded audit volume
   (≤ 24 rows/share/day), zero extra state. Create and revoke are audited
   unconditionally (actor = the acting user). New enum:
   `AuditResourceType.ARTIFACT_SHARE = "artifact_share"`
   (`services/audit_events/enums.py:25-40`).
7. **Share tokens must never reach logs.** The token travels in the URL
   path (clean shareable link), but
   `middleware/request_logging.py:74` logs the raw `request.url.path`.
   This plan changes `_record_request` to log the matched route template
   (the `_endpoint_template_for_metrics` value, `request_logging.py:19-25`)
   instead of the raw path when the path starts with `/artifacts/shared` —
   a two-line, path-scoped redaction, pinned by a caplog test. Referer
   leakage is already closed by 050's `Referrer-Policy: no-referrer`;
   cache leakage by `Cache-Control: no-store`.
8. **Sweep kind `artifacts.sweep_expired_shares`** (governance §3: shares
   hard-deleted at `expires_at`, default 7 d). Registered exactly like the
   landed precedent `services/jobs/handlers/sweep_deleted_files.py:20-56`
   (`@job_handler` + self-reschedule + `ensure_*` called from
   `workers/job_runner.py:28-48`). Hard-deletes rows where
   `expires_at < now()` — revoked rows included (they stay visible in the
   admin list as "revoked" until expiry, then vanish; audit rows survive
   per governance §3 law 2). Shares are NOT soft-deleted rows: revocation
   is the explicit `revoked_at` column, so the model composes
   `Base + UUIDMixin + TimestampMixin` (the `models/jobs.py` precedent),
   not `BaseModel`.
9. **Sharing is feature-gated and forces the separate origin in
   production.** New setting `ARTIFACT_SHARING_ENABLED` (default `False`).
   The production-safety validator (`core/settings/__init__.py:51`) gains:
   when `ARTIFACT_SHARING_ENABLED` and `ENVIRONMENT != "local"`,
   `ARTIFACT_ORIGIN` must be non-empty AND its host must differ from — and
   not be a subdomain of — the `APP_BASE_URL` and `FRONTEND_URL` hosts
   (pragmatic registrable-domain check via suffix comparison, documented
   as an approximation in the validator; no public-suffix dependency).
   This implements the roadmap decision "separate origin required only when
   share links ship" and 050's maintenance note. Share-creation requests
   while disabled fail with a typed validation error; the anonymous route
   404s (uniform).
10. **Roles**: share create/list/revoke are admin+ (`require_owner`, which
    is `MANAGER_ROLES` = owner+admin, `core/dependencies.py:267`) per
    governance §1 "Create/revoke artifact share links (051)". User artifact
    edits and restores are member+ (`require_editor`), matching the §1
    files row ("Upload/edit/delete files: member+") — artifacts are files
    underneath. Frontend gating mirrors
    `workspace-settings-route.tsx:14` (`current_user_role === "owner" ||
    "admin"`).
11. **Diff/restore ride the landed revision chain.** Restore appends a NEW
    revision with `revision_kind="restore"` and
    `restored_from_revision_id` set (the 031 CHECK at
    `models/files.py:126-129` requires exactly that pairing), then bumps
    `Artifact.current_version_id` — never mutates history (immutability
    listener, `models/files.py:201-217`). Diff is client-side: if 035 has
    landed a revision-diff component in `features/files/`, reuse it;
    otherwise ship a minimal unified line-diff helper in
    `features/artifacts/lib-diff.ts` (no new dependency — hand-rolled LCS
    is ~60 lines and knip-clean). Record which path was taken in the PR.
12. **User edits append revisions too** (dictated): `PATCH
    /api/v1/artifacts/{artifact_id}` takes `{content, title?}` and calls
    050's `update_artifact` service with user actor provenance
    (`created_by_user_id`, exactly-one-actor check
    `models/files.py:120-125`). v1 edit UI is a plain textarea dialog for
    the text types (html/markdown/mermaid/csv); no rich editor.
13. **The share link serves the raw document — no viewer wrapper page.**
    The anonymous URL IS 050's CSP-locked serving pipeline with a
    token-resolved version. A wrapper viewer on the app origin was
    rejected: it would need an anonymous app route plus a second
    anonymous content fetch — twice the surface for cosmetics. The share
    dialog copy says links open the document directly.
14. **An artifacts page ships** (`/artifacts`): decision recorded as YES.
    Rationale: share management is admin-facing and needs a home outside
    any one conversation; the roadmap's Surfaces pillar names artifacts a
    first-class screen ("versioned and diffable"); and orphaned artifacts
    (conversation deleted) would otherwise be unreachable. Kept dense and
    small: a table + a detail view; no gallery, no search in v1.
15. **Chat cards reuse `tool.call`/`tool.result` — no new SSE events.**
    The parser throws on unknown event names
    (`features/conversations/stream/sse.ts:73-75`). Artifact cards key off
    the tool activity (`name === "create_artifact" | "update_artifact"`)
    through the existing custom-row registry
    (`tool-call-row-registry.tsx:29-56`) — the same seam skills used in
    020. Previews are `<iframe sandbox="allow-scripts" srcDoc={...}>` —
    never `allow-same-origin`, never `dangerouslySetInnerHTML`, matching
    the roadmap's local-dev decision (srcdoc + sandbox; no separate origin
    needed for previews).

## Why this matters

050 makes artifacts exist; this plan makes them usable and — carefully —
shareable. Cards in chat close the loop for the person driving the agent
(see the report, flip versions, restore); the artifacts page closes it for
the workspace (find, audit, manage). Share links are the deliberate
high-stakes slice: the platform has never served anything to an
unauthenticated caller except HMAC-signed storage capabilities, and the
donor's history shows anonymous surfaces grown casually become incident
surfaces. Hence the posture: one route, opaque high-entropy capability
tokens stored hashed, version-pinned, expiring by default, revocable,
audited, rate-limited, swept — and served only through the CSP-locked
pipeline that already assumes its content is hostile.

## Current state

All anchors verified at `a0eea1c` unless marked. 050 is not yet implemented
— its deliverables are cited from `docs/plans/050-artifacts-model-serving.md`
and re-verified at the pre-flight.

- **Revision chain (031, landed)**: `models/files.py:83-132` `FileRevision`
  — `revision_kind` CHECK over `('create','edit','replace','restore',
  'import')` (lines 27, 115-118), exactly-one-actor CHECK (120-125),
  restore-source CHECK (126-129), append-only enforcement via the
  `before_update` listener (201-217). `FileReference.target_type` CHECK
  includes `'artifact'` (lines 28, 155-159).
  `services/files/list_file_revisions.py:14` and
  `services/files/restore_file_revision.py:19` exist (032 slice in flight
  on disk — verify signatures at execution).
- **Jobs harness (030, landed)**: `services/jobs/registry.py:32-61`
  `job_handler` (duplicate kind → error at import, line 41); handlers
  auto-register via `from services.jobs import handlers` at
  `registry.py:68`; the consumer sweep precedent is
  `services/jobs/handlers/sweep_deleted_files.py:20-56`
  (`@job_handler(kind=..., timeout=300.0)`, self-reschedule via
  `enqueue_job`, `ensure_files_sweep_job` with a fixed `content_hash` for
  dedup); the worker calls each `ensure_*` per pass
  (`workers/job_runner.py:28-48`).
- **Rate limiter**: Postgres-backed upsert counter
  (`core/rate_limiting.py:138-188`), keyed `(ip_address, endpoint,
  limit_type, window_seconds, window_start)`; IP literal validated at
  `:96-109` (decision 4's sentinel constraint); dependency factory
  `require_rate_limit(limit_type, custom_limit, custom_window)` at
  `:414-445`; `get_client_ip` trusted-proxy resolution at `:356-384`.
- **Anonymous route precedent**: `routes/storage/private_object.py:15-29`
  (no auth dependency); CSRF enforcement is unsafe-methods-only
  (`middleware/csrf.py:64-69`) so a GET share route needs **no exempt-list
  change**; 050 already suppresses the csrf-cookie auto-refresh and
  X-Frame-Options default for the `/artifacts/shared` prefix
  (reserved in `_is_artifact_serving_path`).
- **Raw-path logging**: `middleware/request_logging.py:74` logs
  `request.url.path`; route template helper at `:19-25` (decision 7).
- **Token helpers**: `utils/security.py:70-96` `hash_token` /
  `verify_token_hash` (SHA-256 + `secrets.compare_digest`).
- **Audit**: writer `services/audit_events/operations.py:27-81`
  (workspace-scoped, actor typed, `safe_` wrapper);
  enums at `services/audit_events/enums.py:13-58` (no artifact resource
  types yet — this plan adds `ARTIFACT_SHARE`).
- **RBAC**: `require_owner` = MANAGER_ROLES (owner+admin),
  `require_editor` = +member (`core/dependencies.py:243-269`).
- **Settings validator**: production-safety `model_validator` at
  `core/settings/__init__.py:51-123` (decision 9's insertion point);
  local-only provider rejections at `:60-64` are the pattern to follow.
- **Frontend (disk state at `a0eea1c`)**:
  - Custom tool-row seam: `tool-call-row-registry.tsx:29-56`
    (`TOOL_CALL_ROW_DEFINITIONS`, matched in `renderCustomToolCallRow`);
    rows render from `message-row.tsx` via `ToolCallRow`; assistant turns
    group via `message-parts/group-render-items.ts:33-65`.
  - SSE parser throws on unknown events (`stream/sse.ts:73-75`);
    tool activities parse in `message-parts/parse.ts:179-227` — result
    content for a completed tool call lands in `activity.result`.
  - Routing is code-based (`src/app/router.tsx`, `lazyRouteComponent`,
    auth in `beforeLoad`); primary nav items live in
    `src/config/navigation.ts` (skills entry at line 44); admin gating
    precedent `features/workspaces/routes/workspace-settings-route.tsx:14`.
  - Data layer: one operation per `features/*/api/*.ts` file
    (`features/skills/api/` is the model); all requests via
    `src/lib/api/client.ts`; workspace-scoped query keys include the slug.
  - shadcn primitives available: `dialog`, `select`, `table`, `badge`,
    `alert`, `tabs`, `empty-state` (`src/components/ui/`).
- **Will exist after 050 (verify at pre-flight)**: `models/artifacts.py`
  (`Artifact` with `file_id`/`current_version_id`), `services/artifacts/`
  (`serve_artifact_version.py`, `update_artifact.py`, schemas, CSP
  constants in `domain.py`), `routes/artifacts/` +
  `routes/artifact_serving/` (`/artifacts/view/...`),
  `GET /api/v1/artifacts/{id}/versions/{vid}/content`, and settings
  `ARTIFACT_ORIGIN` / `ARTIFACT_MAX_CONTENT_BYTES`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint (API) | `cd apps/api && uv run ruff check .` | exit 0 |
| Migration sanity | `cd apps/api && uv run alembic check` | clean after Step 1 |
| Apply migration | `cd apps/api && uv run alembic upgrade heads` | `artifact_shares` created |
| Sweep registered | `cd apps/api && uv run python -c "from services.jobs.registry import JOB_HANDLERS; print('artifacts.sweep_expired_shares' in JOB_HANDLERS)"` | `True` |
| API tests | `TEST_DATABASE_URL=... uv run pytest tests/services/artifacts tests/routes/artifacts tests/middleware -q` | all pass |
| Worker smoke | `cd apps/api && uv run python -m workers.job_runner --once` | exit 0, shares sweep enqueued |
| Frontend gate | `cd apps/web && pnpm check` | typecheck, eslint (0 warnings), prettier, knip, depcruise, build all pass |

## Scope

**In scope (API):**

- `apps/api/models/artifacts.py` (extend — add `ArtifactShare`) +
  `models/__init__.py` if the class needs registering
- `apps/api/alembic/versions/core/<next>_add_artifact_shares.py` (core, D5)
- `apps/api/core/settings/artifacts.py` (add `ARTIFACT_SHARING_ENABLED`,
  `ARTIFACT_SHARE_DEFAULT_TTL_DAYS=7`, `ARTIFACT_SHARE_MAX_TTL_DAYS=30`) +
  `core/settings/__init__.py` (decision 9 validator rule)
- `apps/api/services/artifacts/` (add): `create_share.py`,
  `list_shares.py`, `revoke_share.py`, `resolve_share.py`,
  `restore_artifact_version.py`, share bits in `schemas.py`/`utils.py`
- `apps/api/services/jobs/handlers/sweep_expired_artifact_shares.py`
  (create) + `workers/job_runner.py` (call its `ensure_*`)
- `apps/api/services/audit_events/enums.py` (add `ARTIFACT_SHARE`)
- `apps/api/routes/artifacts/` (add): `create_share.py`, `list_shares.py`,
  `revoke_share.py`, `update_artifact.py`, `restore_version.py`
- `apps/api/routes/artifact_serving/serve_shared_artifact.py` (create)
- `apps/api/middleware/request_logging.py` (decision 7 redaction)
- `apps/api/tests/`: `tests/services/artifacts/`, `tests/routes/artifacts/`,
  a middleware log-redaction test, factory helpers

**In scope (Web):**

- `apps/web/src/features/artifacts/` (create): `types.ts`;
  `api/list-artifacts.ts`, `api/get-artifact.ts`,
  `api/get-artifact-version-content.ts`, `api/update-artifact.ts`,
  `api/restore-artifact-version.ts`, `api/create-artifact-share.ts`,
  `api/list-artifact-shares.ts`, `api/revoke-artifact-share.ts`;
  `components/artifact-preview-frame.tsx`,
  `components/artifact-version-selector.tsx`,
  `components/artifact-diff.tsx`, `components/artifact-edit-dialog.tsx`,
  `components/artifact-share-dialog.tsx`,
  `components/artifact-shares-list.tsx`,
  `components/artifacts-table.tsx`,
  `components/artifact-detail.tsx`; `routes/artifacts-route.tsx`,
  `routes/artifact-detail-route.tsx`; `lib-diff.ts` (only if 035's diff is
  absent, decision 11)
- `apps/web/src/features/conversations/components/artifact-tool-row.tsx`
  (create) + `tool-call-row-registry.tsx` (one registry entry)
- `apps/web/src/app/router.tsx` (`/artifacts`, `/artifacts/$artifactId`),
  `src/config/navigation.ts` (nav entry)

**Out of scope (do NOT touch):**

- The serving pipeline's headers/CSP (owned by 050 — the share route calls
  it, never re-implements it); `ARTIFACT_CSP_CDN_HOSTS`.
- "Follow latest" shares, share passwords, per-share allowlists,
  download-count limits — all deferred until demanded.
- Public artifact discovery/indexing of any kind; `robots.txt` work.
- Artifact deletion routes and retention sweep for artifacts themselves
  (only *shares* are swept here; artifact lifecycle follows the files
  policy in a later slice).
- The interactive Apps system (donor §4.6 "Deferred").
- The CSRF enforcement exempt list, CORS config, cookie settings.
- Rich text/code editors, mermaid client-side rendering libraries.

## Git workflow

- Branch: `advisor/051-artifact-cards-share-links`
- Commit style: `API - Artifact Share Links` / `Web - Artifact Cards & Share Management`
  (two commits; API first so the web slice always has its backend)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Model, migration, settings

Add `ArtifactShare(Base, UUIDMixin, TimestampMixin)` to
`models/artifacts.py` (decision 8 — no soft-delete), `__tablename__ =
"artifact_shares"`:

- `workspace_id` UUID FK `workspaces.id` ondelete CASCADE, not null, indexed
- `artifact_id` UUID FK `artifacts.id` ondelete CASCADE, not null, indexed
- `version_id` UUID FK `file_revisions.id` ondelete CASCADE, **not null**
  (decision 2)
- `token_hash` String(64) not null, **unique** (the lookup index)
- `token_prefix` String(8) not null
- `expires_at` DateTime(tz) not null; `revoked_at` DateTime(tz) nullable
- `created_by_user_id` UUID FK `users.id` ondelete SET NULL, nullable-on-
  delete but required at insert; `revoked_by_user_id` same shape, nullable
- `last_accessed_at` DateTime(tz) nullable; `access_count` Integer not
  null server_default `0`, CHECK `access_count >= 0`

Indexes: unique `token_hash`; `(expires_at)` (sweep);
`(workspace_id, created_at)`. Core-branch migration against the live
`core@head` (D5); hand-check the unique index landed.

Settings (`core/settings/artifacts.py`): `ARTIFACT_SHARING_ENABLED: bool =
False`, `ARTIFACT_SHARE_DEFAULT_TTL_DAYS: int = 7` (governance §3),
`ARTIFACT_SHARE_MAX_TTL_DAYS: int = 30`. Add the decision 9 rule to the
production validator (`core/settings/__init__.py:51`): sharing enabled
outside `local` requires a non-empty `ARTIFACT_ORIGIN` whose host is
neither equal to nor a dot-suffix subdomain of the `APP_BASE_URL` /
`FRONTEND_URL` hosts.

**Verify**: `uv run alembic upgrade heads` + `alembic check` clean +
downgrade round-trip; `ARTIFACT_SHARING_ENABLED=true ENVIRONMENT=production
ARTIFACT_ORIGIN= uv run python -c "from core.settings import Settings; Settings()"`
→ raises the validator error (with the other prod-required env set);
same command with `ARTIFACT_ORIGIN=https://example-artifacts.com` and a
distinct app domain → constructs.

### Step 2: Share services

One operation per file in `services/artifacts/` (typed exceptions only):

- `create_share.py` — `create_artifact_share(db, *, request, workspace,
  membership, artifact_id, expires_in_days=None) -> tuple[ArtifactShare, str]`.
  Order matters: (1) reject when `not settings.ARTIFACT_SHARING_ENABLED`
  (`AppValidationError`); (2) load artifact workspace-scoped, not deleted
  (`NotFoundError`); (3) `check_workspace_share_rate_limit` (decision 4 —
  BEFORE token generation so blocked attempts burn nothing); (4) clamp TTL
  to `[1, ARTIFACT_SHARE_MAX_TTL_DAYS]`, default
  `ARTIFACT_SHARE_DEFAULT_TTL_DAYS`; (5) `token = secrets.token_urlsafe(32)`,
  insert row (`token_hash`, `token_prefix=token[:8]`,
  `version_id=artifact.current_version_id`); (6) audit (action `CREATE`,
  resource `ARTIFACT_SHARE`, actor user, details: artifact_id, version_id,
  expires_at, token_prefix — **never the token**). Returns the row and the
  plain token; only the route composes the URL:
  `{ARTIFACT_ORIGIN or APP_BASE_URL}/artifacts/shared/{token}`.
- `list_shares.py` — active + revoked-unexpired shares for an artifact
  (prefix, expiry, creator, access_count, revoked state). Never exposes
  `token_hash`.
- `revoke_share.py` — sets `revoked_at`/`revoked_by_user_id` (idempotent:
  revoking twice is a no-op success); audit (action `DELETE`, resource
  `ARTIFACT_SHARE`).
- `resolve_share.py` — `resolve_artifact_share(db, *, token) ->
  tuple[ArtifactShare, Artifact]`: `hash_token(token)` → unique-index
  lookup → reject when `revoked_at IS NOT NULL` or `expires_at <= now()`
  or the artifact is soft-deleted — every rejection raises the SAME
  `NotFoundError("Share not found")` (decision 3). On success, perform the
  decision 6 atomic access-count UPDATE and (throttled) audit write.
- `restore_artifact_version.py` — appends a `revision_kind="restore"`
  revision with `restored_from_revision_id` (031 CHECK,
  `models/files.py:126-129`), preferring the landed
  `services/files/restore_file_revision.py` seam if its signature composes;
  bumps `Artifact.current_version_id`. User actor provenance.

Add `AuditResourceType.ARTIFACT_SHARE = "artifact_share"` to
`services/audit_events/enums.py`.

**Verify**: ruff exit 0; service tests in Step 8 cover behavior.

### Step 3: Routes

Management (under `/api/v1/artifacts`, route-per-file; roles per
decision 10):

- `create_share.py` — `POST /{artifact_id}/shares`
  (`Depends(require_owner)`) → 201 `{id, share_url, token_prefix,
  expires_at, version_id}`. `share_url` contains the token — the ONLY
  response that ever does.
- `list_shares.py` — `GET /{artifact_id}/shares` (`require_owner`)
- `revoke_share.py` — `DELETE /{artifact_id}/shares/{share_id}`
  (`require_owner`) → 204
- `update_artifact.py` — `PATCH /{artifact_id}` (`require_editor`) body
  `{content, title?}` → 050's `update_artifact` service, user actor
- `restore_version.py` — `POST /{artifact_id}/versions/{version_id}/restore`
  (`require_editor`) → Step 2 restore service

Anonymous serving: `routes/artifact_serving/serve_shared_artifact.py` —

```python
@router.get("/shared/{token}")
async def serve_shared_artifact(
    token: Annotated[str, Path(min_length=32, max_length=64)],
    db: AsyncDbSessionDep,
    download: Annotated[str | None, Query()] = None,
    _: None = Depends(require_rate_limit(custom_limit=120, custom_window=3600)),
) -> Response: ...
```

No auth dependency (precedent `routes/storage/private_object.py:15`).
Resolves via `resolve_share.py`, then serves the **pinned** `version_id`
through 050's `serve_artifact_version` pipeline — identical CSP/nosniff/
no-referrer/no-store headers, no `Set-Cookie` (the `/artifacts/shared`
prefix is already inside 050's middleware carve-outs). The route adds
nothing header-wise; it only swaps signature-auth for token-auth.

Apply the decision 7 log redaction in
`middleware/request_logging.py::_record_request`.

**Verify**: manual curl round-trip — create share as admin (with
`ARTIFACT_SHARING_ENABLED=true` locally), open `share_url` with NO cookies
→ 200 + 050's exact headers; revoke → same URL 404; member role creating a
share → 403; 11th create in an hour → 429 with `Retry-After`.

### Step 4: Sweep

`services/jobs/handlers/sweep_expired_artifact_shares.py`, cloning the
`sweep_deleted_files.py:20-56` shape:

```python
SWEEP_EXPIRED_ARTIFACT_SHARES_KIND = "artifacts.sweep_expired_shares"

@job_handler(kind=SWEEP_EXPIRED_ARTIFACT_SHARES_KIND, timeout=120.0)
async def sweep_expired_artifact_shares(db, job):
    # DELETE FROM artifact_shares WHERE expires_at < now()  (revoked included)
    # then self-reschedule via enqueue_job(run_after=now + interval)

async def ensure_artifact_shares_sweep_job(db): ...  # fixed content_hash dedup
```

Wire `ensure_artifact_shares_sweep_job` into the worker pass beside
`ensure_files_sweep_job` (`workers/job_runner.py:28-48`). Idempotent by
design (at-least-once execution — 030's rule for all handlers).

**Verify**: the Commands-table registry check prints `True`;
`uv run python -m workers.job_runner --once` exits 0 and logs the shares
sweep; expired rows (incl. revoked) deleted, live rows kept (Step 8 test).

### Step 5: Frontend — artifacts feature core

`features/artifacts/types.ts`: `Artifact`, `ArtifactVersion`,
`ArtifactShare` (with `token_prefix`, never a token field),
`ArtifactContent` — `type` aliases only (lint rule).

API modules (one operation each, `queryOptions` + `useSuspenseQuery` for
reads, `useMutation` + invalidation for writes, workspace slug in every
query key, all through `lib/api/client.ts`): the eight files listed in
Scope. `create-artifact-share.ts` holds the returned `share_url` in
component state only — it must never be written into the query cache
(it cannot be re-fetched, and cached copies outlive the dialog).

Components:

- `artifact-preview-frame.tsx` — THE sandbox chokepoint, used by chat cards
  and the detail view: html → `<iframe sandbox="allow-scripts"
  srcDoc={content} title={title} />` (no `allow-same-origin`, no
  `allow-popups`, no `allow-forms`, no `allow-top-navigation`); markdown →
  the existing `MessageMarkdown` renderer; csv → parse-and-render via the
  existing `markdown-table.tsx` treatment; mermaid → read-only code block
  (client-side mermaid rendering is out of scope); image-ref → `<img>`
  from the signed URL. A lint-greppable comment forbids
  `dangerouslySetInnerHTML` in this feature.
- `artifact-version-selector.tsx` (shadcn `select`, newest first, current
  badge), `artifact-diff.tsx` (decision 11), `artifact-edit-dialog.tsx`
  (decision 12 textarea), `artifacts-table.tsx`, `artifact-detail.tsx`
  (preview + version selector + diff/restore + shares section).

Routes/nav: `/artifacts` + `/artifacts/$artifactId` in
`src/app/router.tsx` (`lazyRouteComponent`, auth `beforeLoad` like the
skills routes); nav entry in `src/config/navigation.ts` beside Skills.

**Verify**: `pnpm check` passes; manual: artifacts page lists a seeded
artifact; detail shows versions; restore creates a new head version; edit
appends a revision.

### Step 6: Frontend — chat artifact cards

`features/conversations/components/artifact-tool-row.tsx`: renders a card
for `create_artifact`/`update_artifact` tool activities — status shell via
the existing `tool-activity-row-shell.tsx`, then (when
`activity.status === "completed"` and `activity.result` carries
`artifact_id`/`version_id`) title, type badge, an inline
`ArtifactPreviewFrame` fed by `get-artifact-version-content.ts`, a version
selector, and an "Open" link to `/artifacts/$artifactId`. Pending-approval
and denied states keep the standard tool-row treatment (the approval
controls already render for approval-required tools — do not fork that
path). Guard result parsing with `lib/guards.ts` helpers — tool results
are untrusted JSON.

Register it in `tool-call-row-registry.tsx` (`TOOL_CALL_ROW_DEFINITIONS`,
the 020 seam):

```ts
{
  key: "artifact",
  matches: (activity) =>
    activity.name === "create_artifact" || activity.name === "update_artifact",
  render: ({ activity, compact, defaultOpen }) => (
    <ArtifactToolRow activity={activity} compact={compact} defaultOpen={defaultOpen} />
  ),
}
```

No SSE protocol changes of any kind (decision 15).

**Verify**: `pnpm check` passes (dependency-cruiser: conversations →
artifacts feature import must not create a cycle — artifacts must not
import from conversations); manual: asking an agent with the tool enabled
to create an HTML artifact yields an approval row, then a rendered
sandboxed card; the iframe element in devtools shows
`sandbox="allow-scripts"` only.

### Step 7: Frontend — share management

`artifact-share-dialog.tsx` (create: expiry select 1/7/30 d capped by the
API, then a one-time copy-URL state with an explicit "you won't see this
again" note) and `artifact-shares-list.tsx` (prefix, expiry, creator,
access count, revoked badge, revoke button with confirm). Mounted in
`artifact-detail.tsx`, rendered only when
`workspace.current_user_role` is `owner`/`admin` (decision 10 gating,
`workspace-settings-route.tsx:14` pattern); the API remains the real
enforcement. When share creation returns the sharing-disabled validation
error, show it verbatim (no client-side feature flag — the API is the
source of truth).

**Verify**: `pnpm check`; manual: admin creates a share, copies the URL,
opens it in a private window (no session) → document renders; revoke →
private window reload → 404; member account sees no shares section.

### Step 8: Tests (API)

`tests/services/artifacts/` + `tests/routes/artifacts/` + one middleware
test (async modules set `pytestmark = pytest.mark.asyncio`; DB tests skip
without `TEST_DATABASE_URL`):

- `test_create_share.py`: token ≥ 32 chars URL-safe; row stores
  `hash_token(token)`, never the token (grep the row + audit details);
  version pinned to `current_version_id`; TTL default 7 d and clamped at
  max; sharing disabled → validation error; member → 403, admin/owner →
  201; **rate limit**: 10 creates succeed, the 11th → 429 with
  `X-RateLimit-*`/`Retry-After`, and a second workspace is unaffected
  (the sentinel key is workspace-scoped).
- `test_serve_shared_artifact.py` (the anonymous surface — pinned
  invariants):
  - valid token, no cookies → 200; headers equal 050's serving header set
    **exactly** (CSP byte-match against the `domain.py` constants,
    `nosniff`, `no-referrer`, `no-store`); **no `Set-Cookie`** even when a
    valid `session` cookie is sent.
  - revoked → 404; expired → 404; unknown token → 404; artifact
    soft-deleted → 404 — and all four response bodies are **identical**
    (uniform problem+json, decision 3).
  - version pinning: `update_artifact` after share creation; the share
    still serves the old revision's bytes.
  - access accounting: two accesses within an hour → `access_count == 2`,
    exactly ONE `artifact_share` READ audit row (decision 6); a third
    access with `last_accessed_at` backdated > 1 h → second audit row.
- `test_share_lifecycle.py`: revoke idempotent; revoke audited; list
  excludes swept rows and never leaks `token_hash`.
- `test_sweep_expired_artifact_shares.py`: expired live + expired revoked
  rows deleted, unexpired kept; handler re-enqueues itself; `ensure_*`
  idempotent (dedup index).
- `test_restore_and_edit.py`: user edit appends a user-actor revision
  (exactly-one-actor satisfied); restore appends `revision_kind="restore"`
  with `restored_from_revision_id`, bumps `current_version_id`, and the
  restored-from revision is byte-identical in storage; editor role
  required (read_only → 403).
- `tests/middleware/test_request_log_redaction.py`: caplog on a
  `/artifacts/shared/<token>` request never contains the token; the
  logged `url` is the route template.

**Verify**: `TEST_DATABASE_URL=... uv run pytest tests/services/artifacts
tests/routes/artifacts tests/middleware -q` all pass;
`cd apps/web && pnpm check` exits 0.

## Test plan

Covered by Step 8 (~26–30 API tests; the frontend gate is `pnpm check` —
no test framework exists). Pinned invariants: **tokens exist in exactly
one response and nowhere else** (not rows, not audits, not logs, not query
cache), **anonymous responses are uniform and cookie-free** (identical
404s; 050 header set byte-matched; no Set-Cookie), **shares are pinned,
expiring, revocable, and swept** (pin survives edits; revoke/expiry →
404; sweeper hard-deletes per governance §3 while audit rows survive),
**limits hold per workspace** (10/h creation via the sentinel key; per-IP
access throttle), and **the revision chain stays append-only** (edits and
restores add revisions; nothing mutates).

## Done criteria

- [ ] `uv run ruff check .` exits 0; `uv run alembic check` clean;
      migration on the **core** branch (D5); downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/artifacts tests/routes/artifacts tests/middleware -q` exits 0
- [ ] `artifacts.sweep_expired_shares` registered; `workers.job_runner
      --once` runs it; sweep test green
- [ ] Share create/list/revoke are admin+; edit/restore are member+;
      the anonymous route has no auth dependency and required no CSRF
      exempt-list change (`git diff apps/api/middleware/csrf.py` empty)
- [ ] The share URL token appears only in the 201 response; log-redaction
      test green
- [ ] Production validator rejects sharing without a distinct-origin
      `ARTIFACT_ORIGIN`
- [ ] `cd apps/web && pnpm check` exits 0 (typecheck, eslint 0 warnings,
      prettier, knip, depcruise, build)
- [ ] `grep -rn "dangerouslySetInnerHTML" apps/web/src/features/artifacts apps/web/src/features/conversations` → no matches;
      every artifact iframe sets `sandbox="allow-scripts"` and nothing more
- [ ] No new SSE event names (`stream/protocol.ts` untouched)
- [ ] Security-auditor review of the share slice completed and recorded in
      the PR description
- [ ] `docs/architecture/governance.md` §1 (share links), §3 (shares row),
      §4 (share rate limit) flipped to `[implemented: plan 051]`
- [ ] `git status` clean outside the in-scope list;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 050 is not implemented, or its landed shape diverges from the
  pre-flight expectations (no `serve_artifact_version` seam reusable by a
  token-resolved caller; `/artifacts/shared` prefix not carved out in the
  middleware; CSP constants not centralized in `domain.py`).
- An `artifact_shares` table or any share/token code already exists.
- `core/rate_limiting.py` no longer accepts the decision 4 sentinel
  pattern (e.g. IP validation tightened, keying changed) — do not fork the
  limiter; report.
- The jobs harness handler assembly (`services/jobs/registry.py:68`,
  `workers/job_runner.py` ensure-calls) has changed shape since `a0eea1c`.
- The uniform-404 requirement cannot be met (e.g. an exception handler
  decorates 404s with resource-specific detail) — fix the leak first.
- Serving a share response emits `Set-Cookie` or non-050 headers under any
  request shape — the cookie-freedom invariant is non-negotiable.
- The governance note's §1/§3/§4 share defaults changed (roles, 7 d expiry,
  10/hour) — reconcile before coding.
- Implementing log redaction requires touching more than
  `_record_request` — a broader logging refactor is not this plan.
- You feel the need to add a viewer wrapper page, "follow latest" shares,
  a new SSE event, or client-side mermaid rendering — scope creep; record
  a follow-up instead.

## Maintenance notes

- **First-anonymous-surface precedent**: any future anonymous route must
  match this bar — capability tokens stored hashed, uniform 404s, no
  cookies, rate-limited, swept, audited, log-redacted. Cite this plan's
  Step 8 invariants as the checklist.
- **Sentinel rate-limit key**: if a second per-workspace limit appears
  (e.g. 032's storage quota enforcement or a future API budget), promote
  the decision 4 wrapper into a first-class `subject`-keyed limiter API in
  `core/rate_limiting.py` and migrate both callers — do not copy the
  sentinel a third time.
- **Access-audit throttle** (1 row/share/hour) is a tunable, not a law; if
  ops need finer grain, drop the throttle behind a setting rather than
  widening audit writes silently. `access_count` remains exact regardless.
- **"Follow latest" shares** (nullable `version_id`) are the only
  anticipated schema relaxation; they must NOT ship without an explicit
  UI affordance showing share consumers see future edits.
- **Deferred interactive Apps** (donor §4.6) stay deferred; share links do
  not grow postMessage bridges, embed SDKs, or iframe APIs.
- **Separate-origin enforcement** now lives in the settings validator
  (decision 9). If deployment later terminates the artifact origin at a
  CDN or separate service, the validator rule and 050's reverse-proxy
  guidance must be updated together.
- Reviewers should scrutinize: `resolve_share.py`'s single-exception
  discipline (one `NotFoundError` for all rejection causes), the atomic
  access-count UPDATE (no read-modify-write race), that `share_url` never
  enters the TanStack Query cache, that the registry card matcher cannot
  shadow the delegation/skill rows (registry order in
  `tool-call-row-registry.tsx` is first-match-wins), and that the sweep
  deletes revoked-but-unexpired rows only after `expires_at`.
