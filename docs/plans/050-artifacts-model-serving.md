# Plan 050: Artifacts model, registry tools, and CSP-locked serving

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G3 pre-flight**: `docs/architecture/governance.md` exists (029 DONE
> 2026-07-06 at `0cbbb39`). Re-verify every governance citation below against
> the live note before coding — the note wins. When this plan ships, flip the
> governance cells it implements (§1 "Create artifacts via agents", §2
> artifact-creation approval default) to `[implemented: plan 050]` in the
> same PR.
>
> **Cross-plan pre-flight (run before Step 1)**: this plan was written while
> plans 030–032 were still TODO, against their dictated contracts. Verify at
> execution time that 031 (`File`/`FileRevision`/`FileReference` in
> `apps/api/models/files.py`, immutable revisions, exactly-one-actor
> provenance, `FileReference.target_type` including `artifact`) and 032
> (storage keys `workspaces/{workspace_id}/files/{file_id}/{revision_id}{ext}`,
> signed download URLs, revision-append service) are implemented. If either
> is missing or its contract diverges from those names, STOP.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/main.py apps/api/middleware/ apps/api/core/settings/ apps/api/core/dependencies.py apps/api/models/ apps/api/routes/ apps/api/services/agents/runtime/tools/ apps/api/services/storage/ apps/api/utils/security.py`
> Files WILL have changed (030–049 land first). Compare the "Current state"
> excerpts against live code before proceeding; treat a structural mismatch
> (middleware ordering comment, tool registry shape, exception layer,
> signed-URL helpers) as a STOP condition, not a formality.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH (new content-serving surface rendering agent-authored HTML;
  prompt-injected artifacts are assumed hostile — the three-layer defense is
  the point of this plan, not an add-on)
- **Depends on**: hard — 031 (FileRevisions), 032 (storage keys +
  revision-append), 025/026 (tool registry + dispatch choke point, DONE
  2026-07-03), Gate G3 (`docs/architecture/governance.md`, satisfied).
  Soft: none. Plan 051 depends on this plan.
- **Category**: Phase 6 artifacts (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 6 row 050; donor `DONOR_PORT_ROADMAP.md` §4.6 / §6 row F1)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Versions ARE FileRevisions — no parallel versioning.** Each artifact
   owns exactly one `File` (unique FK); its version history is that file's
   immutable revision chain (031), with agent-authored revisions carrying
   agent provenance via 031's actor columns (`created_by_agent_id`,
   exactly-one-actor CHECK; `revision_kind` `create`/`edit` — the donor's
   `agent_artifact` source vocabulary maps onto 031's landed actor columns,
   not a new revision kind) and a `FileReference(target_type="artifact")`
   row linking the file to the artifact. `update_artifact` appends a revision and bumps
   `current_version_id`; nothing ever mutates a stored revision. User edits
   (051) append to the same chain with user actor provenance — diff/restore
   falls out for free.
2. **Artifact creation defaults to `approval`** per `governance.md` §2:
   artifact creation is an `effect="write"` with external-ish consequences
   (content that can be served and later shared). Both tools register with
   `effect=TOOL_EFFECT_WRITE, default_policy=TOOL_POLICY_APPROVAL,
   supports_auto=True` — per-agent `tool_policies` may relax to `auto`
   (the §2 default stands for review, mechanics are 025/026 and cost this
   plan nothing). Dispatch-level audit rows come free via 026's choke point;
   no extra route-level audit is added here.
3. **Serving is a signed capability, not a cookie session.** The serving
   route takes `?expires=&sig=` (HMAC-SHA256 over
   `artifact-view:{artifact_id}:{version_id}:{expires}` with `SECRET_KEY`,
   via `utils/security.py:204` `create_hmac_signature` /
   `verify_hmac_signature`), minted by an authenticated API endpoint —
   mirroring `routes/storage/private_object.py:15-29`, which serves signed
   objects with no auth dependency. This is what makes a cookie-less
   separate origin possible: the credential travels in the URL, not in a
   cookie. Default TTL 300 s.
4. **Dedicated top-level serving router** (`routes/artifact_serving/`,
   mounted in `main.py` beside `api_router`, paths `/artifacts/view/...`
   and — in 051 — `/artifacts/shared/{token}`). Not under
   `API_V1_PREFIX`: share URLs must be clean, and the stable `/artifacts/`
   path prefix is what the middleware carve-outs (decision 6) and the
   production reverse-proxy rule key on. Production guidance (docs, not
   code): `ARTIFACT_ORIGIN` should be a **distinct registrable domain** (not
   a subdomain — cookie scoping and same-site CSRF), and the reverse proxy
   for that domain should forward ONLY `/artifacts/view` and
   `/artifacts/shared` paths to the API. Iframe `src` loads are not subject
   to CORS, so no CORS config changes are needed for cross-origin embeds.
5. **Local dev: srcdoc + sandbox only, no separate origin** — recording the
   decision already taken in `000_MASTER_ROADMAP.md` §4 Phase 6 row 050.
   `ARTIFACT_ORIGIN` defaults empty (view URLs are minted against
   `APP_BASE_URL`); the settings validator only checks shape in this plan.
   The hard "separate origin in production" rule binds when sharing is
   enabled and is implemented as a settings-validator rule in plan 051
   (see Maintenance notes).
6. **Cookie-freedom is enforced, not assumed.** Two deliberate middleware
   carve-outs, both keyed on the `/artifacts/` serving-path prefix:
   (a) `CSRFMiddleware` auto-refreshes the `csrf` cookie on every response
   when a `session` cookie is present (`middleware/csrf.py:200-212`) — the
   serving paths skip that refresh so an artifact response NEVER carries
   `Set-Cookie`; (b) `SecurityHeadersMiddleware` `setdefault`s
   `X-Frame-Options: DENY` and a deny-all CSP (`security_headers.py:57-73`)
   — serving paths get a branch mirroring the existing `_is_app_frame_path`
   special case (`middleware/utils.py:44-47`): no `X-Frame-Options` (CSP
   `frame-ancestors` is the framing control), and the route owns the full
   CSP. This does NOT touch the CSRF *enforcement* exempt list
   (`csrf.py:45-55`): the serving routes are GET-only and CSRF enforcement
   already applies only to POST/PUT/PATCH/DELETE (`csrf.py:64-69`), so no
   exemption is added — per AGENTS.md, exempt lists are not widened.
7. **CSP CDN whitelist**: exactly two hosts — `https://cdn.jsdelivr.net`
   and `https://unpkg.com` — for `script-src`/`style-src`/`font-src`. These
   cover the libraries models actually emit (Chart.js, mermaid, Tailwind
   play builds). `img-src` is deliberately limited to `data: blob:` — a
   remote `img-src` is an exfiltration channel (URL-encoded beacons), and
   `connect-src 'none'` would be theater with it open. `connect-src 'none'`
   is non-negotiable: a prompt-injected artifact cannot phone home. The
   whitelist lives as one module constant (`ARTIFACT_CSP_CDN_HOSTS` in
   `services/artifacts/domain.py`); growing it is a reviewed code change,
   not config.
8. **The CSP also carries the `sandbox allow-scripts` directive**, so a
   served HTML artifact is opaque-origin even when opened as a top-level
   tab (not just when iframed with the sandbox attribute). Belt and braces
   with layer 1; costs one token in the header.
9. **`Referrer-Policy: no-referrer` on every serving response.** Links
   inside an artifact navigate within the sandboxed frame; without this,
   the outbound request's `Referer` would leak the capability URL (and in
   051, the share token). `Cache-Control: no-store` for the same reason —
   secret-URL content must not land in shared caches.
10. **`image-ref` creation is deferred.** The `artifact_type` CHECK admits
    all five dictated types (`html`, `markdown`, `mermaid`, `csv`,
    `image-ref`), but `create_artifact`/`update_artifact` accept only the
    four text types in v1 — there is no agent-visible image producer until
    034/036 land. The serving route handles `image-ref` defensively
    (streams stored bytes only when the revision content type is `image/*`;
    otherwise 404). Recorded in Maintenance notes.
11. **Content limits**: `ARTIFACT_MAX_CONTENT_BYTES` default 1 MiB
    (UTF-8 encoded), title ≤ 255 chars. Oversize content raises
    `ModelRetry` from the tool (model-visible, like
    `tools/planning.py:49-50`), not an opaque failure.
12. **No new SSE event names.** The chat treatment (051's artifact cards)
    rides the existing `tool.call`/`tool.result` events — the frontend SSE
    parser throws on unknown event names
    (`apps/web/src/features/conversations/stream/sse.ts:73-75`), so a new
    server event would break stale clients. Nothing in this plan touches
    the stream protocol.
13. **This plan is backend-only.** Until 051, `create_artifact` results
    render through the generic tool row — per AGENTS.md, the pending UI is
    documented (051), not implied.

## Why this matters

Artifacts are the roadmap's "Surfaces" pillar for agent output: versioned,
diffable, visible documents instead of chat-scrollback HTML blobs. The donor
had no lightweight artifact path — a simple HTML report required its full
Apps machinery (59 route files); we build the missing middle tier and defer
interactive apps entirely (donor §4.6). The security posture is the actual
deliverable: agent-authored HTML is attacker-controlled input (prompt
injection is an assumption, not an edge case), and the three-layer defense —
opaque-origin sandbox, cookie-free dedicated origin, strict CSP with
`connect-src 'none'` — is the industry-standard answer. 051 then adds the
human surfaces (cards, versions, share links) on top of a serving pipeline
that is already safe for anonymous use.

## Current state

All anchors verified at `0cbbb39`. Nothing artifact-shaped exists
(`grep -ri artifact apps/api --include="*.py"` matches nothing).

- **Middleware** (`apps/api/main.py:75-89`): authoritative ordering comment —
  request entry `CORS → RequestID → SecurityHeaders → CSRF → BodySizeLimit →
  RequestLogging → DBSession → RateLimit → AuditContext → route`. Keep the
  comment accurate if anything moves (nothing should).
  `SecurityHeadersMiddleware` uses `setdefault` for every header
  (`middleware/security_headers.py:57-73`), so a route-set CSP already wins;
  only the unconditional `X-Frame-Options: DENY` default (line 58) needs a
  path branch, and the `_is_app_frame_path` special case
  (`middleware/utils.py:44-47`, `security_headers.py:54-67`) is the exact
  precedent. `CSRFMiddleware._should_enforce_csrf` only fires for unsafe
  methods (`middleware/csrf.py:64-69`); the csrf-cookie auto-refresh fires
  on ALL methods (`csrf.py:200-212`) — decision 6's target.
- **CORS**: `settings.cors_origins_list` from `ALLOWED_CORS_ORIGINS`
  (`core/settings/urls.py:14-52`, wildcards rejected); CORS middleware
  registered outermost with credentials (`main.py:92-109`).
- **Auth opt-out precedent**: `routes/storage/private_object.py:15-29` — a
  GET route with no auth dependency, guarded by
  `provider.require_valid_download_signature`
  (`services/storage/serve_private_object.py:26-34`). The CSRF exempt-list
  comment for signed uploads (`csrf.py:50-51`) documents the "HMAC-signed
  capability" rationale this plan reuses.
- **HMAC helpers**: `utils/security.py:204-230`
  `create_hmac_signature`/`verify_hmac_signature` (SHA-256, constant-time
  compare); `hash_token`/`verify_token_hash` at `utils/security.py:70-96`
  (051 uses these).
- **Tool registry**: `services/agents/runtime/tools/registry.py:33-91`
  `runtime_tool(...)` decorator with import-time uniqueness (line 86-88);
  provider modules register via the assembly-point import block at
  `registry.py:254-258`. Contract invariants in
  `tools/contract.py:109-176` — notably "Write runtime tools must support
  approval policy" (line 171-176). Write-tool precedent with `ctx.deps.db`
  writes: `tools/planning.py:29-78` (`write_todos`). `RuntimeDeps` carries
  `db/user/workspace/conversation/agent/run/sink/envelope`
  (`runtime/context.py:19-30`).
- **Dispatch choke point** (026): `runtime/dispatch.py:127-227` audits every
  invocation (pending/denied/failed/success) and enforces envelopes and
  output contracts — artifact tools inherit all of it by registration.
- **Settings**: mixins compose in `core/settings/__init__.py:30-46`; the
  production-safety `model_validator` at `__init__.py:51-123` is where the
  051 sharing/origin rule will live. `APP_BASE_URL`/`FRONTEND_URL` at
  `core/settings/urls.py:10-23`. `SECRET_KEY` at
  `core/settings/security.py:16`.
- **Models/migrations**: `BaseModel` (soft-delete) at `models/base.py:130`;
  new models must be imported in `models/__init__.py`. Core migration head
  at `0cbbb39` is `core_0008` (`alembic/versions/core/`) — 030/031/032 will
  have advanced it; generate against the live `core@head` (D5: core branch).
- **Storage**: `StorageProvider.get_object/stat_object/create_signed_download`
  (`services/storage/provider.py:31-64`); response helpers
  `storage_object_response`/`storage_object_headers`
  (`services/storage/utils.py:13-45`); key validation in
  `services/storage/paths.py:14-70`.
- **Frontend (disk state, includes uncommitted 020 follow-up work)**: the
  tool-row extension seam is
  `apps/web/src/features/conversations/components/tool-call-row-registry.tsx:29-56`
  (`TOOL_CALL_ROW_DEFINITIONS`); SSE parser throws on unknown event names
  (`features/conversations/stream/sse.ts:73-75`). Cited here for 051; this
  plan does not touch `apps/web`.
- **Will exist after 031/032 (dictated, verify at pre-flight)**:
  `models/files.py` with `File`/`FileRevision`/`FileReference`;
  a `services/files/` revision-append operation; storage keys
  `workspaces/{workspace_id}/files/{file_id}/{revision_id}{ext}`.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations after Step 2 |
| Apply migration | `uv run alembic upgrade heads` | `artifacts` table created |
| Registry check | `uv run python -c "from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG as c; print([n for n in sorted(c) if 'artifact' in n])"` | `['create_artifact', 'update_artifact']` |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/artifacts tests/routes/artifacts -q` | all pass |
| Serving smoke | `curl -si "http://localhost:8000/artifacts/view/<id>/<vid>?expires=...&sig=..."` | CSP + nosniff headers, no `Set-Cookie` |

## Scope

**In scope:**

- `apps/api/core/settings/artifacts.py` (create — `ArtifactSettingsMixin`) +
  `core/settings/__init__.py` (compose; shape-validate `ARTIFACT_ORIGIN`)
- `apps/api/models/artifacts.py` (create — `Artifact`) +
  `models/__init__.py` (register import)
- `apps/api/alembic/versions/core/<next>_add_artifacts.py` (core branch, D5)
- `apps/api/services/artifacts/` (create): `__init__.py`, `domain.py`,
  `schemas.py`, `utils.py`, `create_artifact.py`, `update_artifact.py`,
  `get_artifact.py`, `list_artifacts.py`, `create_view_url.py`,
  `serve_artifact_version.py`
- `apps/api/services/agents/runtime/tools/artifacts.py` (create — the two
  registry tools) + `tools/registry.py` (add to the assembly-point import)
- `apps/api/routes/artifacts/` (create): `__init__.py`, `list_artifacts.py`,
  `get_artifact.py`, `get_version_content.py`, `create_view_url.py`
- `apps/api/routes/artifact_serving/` (create): `__init__.py`,
  `view_artifact_version.py`; `routes/__init__.py` (export the serving
  router) + `apps/api/main.py` (include it — keep the middleware comment
  intact)
- `apps/api/middleware/csrf.py` (skip cookie auto-refresh on serving paths),
  `apps/api/middleware/security_headers.py` + `middleware/utils.py`
  (artifact-serving path branch)
- `apps/api/tests/services/artifacts/`, `apps/api/tests/routes/artifacts/`
  (create), plus a `tests/factories/` artifact helper

**Out of scope (do NOT touch):**

- Share links, share tokens, the `/artifacts/shared/{token}` route, sweep
  kinds, and ALL of `apps/web` — plan 051.
- User-edit / restore / delete routes for artifacts — 051 (delete rides the
  soft-delete column shipped here but gets no route yet).
- `image-ref` producers (decision 10) and any multimodal work (034/036).
- The interactive Apps system (donor §4.6 "Deferred") — stays deferred.
- 031/032 internals — consume their services; never write `File`/
  `FileRevision` rows directly if an append operation exists.
- The CSRF enforcement exempt list (`csrf.py:45-55`) — decision 6 touches
  only the cookie-refresh block.

## Git workflow

- Branch: `advisor/050-artifacts-model-serving`
- Commit style: `API - Artifacts Model & Serving`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Create `core/settings/artifacts.py` with `ArtifactSettingsMixin` (shape of
`core/settings/rate_limit.py`):

```python
ARTIFACT_ORIGIN: str = ""                      # empty = serve from APP_BASE_URL (local default)
ARTIFACT_VIEW_URL_TTL_SECONDS: int = 300       # signed view-URL lifetime
ARTIFACT_MAX_CONTENT_BYTES: int = 1_048_576    # 1 MiB per revision (decision 11)
```

Field validator on `ARTIFACT_ORIGIN`: when non-empty it must start with
`http(s)://`, contain no path/query/fragment, and is stored without a
trailing slash (mirror `urls.py:25-31`). Compose the mixin into `Settings`
(`core/settings/__init__.py:30-46`). No production validator change in this
plan — the sharing-gated origin rule is 051's (Maintenance notes).

**Verify**: `uv run python -c "from core.settings import settings; print(repr(settings.ARTIFACT_ORIGIN), settings.ARTIFACT_MAX_CONTENT_BYTES)"`
→ `'' 1048576`; ruff exit 0.

### Step 2: Model + core migration

Create `models/artifacts.py` with `Artifact(BaseModel)`
(`models/base.py:130` — soft-delete: artifacts are user-facing resources;
retention/hard-delete policy is deferred with the delete route to 051+,
consistent with `governance.md` §3 files treatment), `__tablename__ =
"artifacts"`:

- `workspace_id` UUID FK `workspaces.id` ondelete CASCADE, not null, indexed
- `agent_id` UUID FK `agents.id` ondelete SET NULL, nullable
- `conversation_id` UUID FK `conversations.id` ondelete SET NULL, nullable
- `run_id` UUID FK `agent_runs.id` ondelete SET NULL, nullable
- `file_id` UUID FK `files.id` ondelete RESTRICT, not null, **unique**
  (decision 1: one File per artifact)
- `current_version_id` UUID FK `file_revisions.id` ondelete RESTRICT,
  not null
- `artifact_type` String(16) not null, CHECK in
  `('html','markdown','mermaid','csv','image-ref')`
- `title` String(255) not null

Indexes: `(workspace_id, created_at)`, `(conversation_id)`. Import in
`models/__init__.py`. Generate on the core branch against the live head:
`uv run alembic revision --autogenerate --head core@head --version-path
alembic/versions/core -m "add artifacts table"`; hand-check FKs to
`files`/`file_revisions` resolved (they must exist — 031 landed) and the
CHECK constraint made it in.

**Verify**: `uv run alembic upgrade heads` applies; `uv run alembic check`
clean; downgrade round-trips
(`uv run alembic downgrade core@-1 && uv run alembic upgrade heads`).

### Step 3: Domain + services

`services/artifacts/domain.py`: `ARTIFACT_TYPES` frozenset,
`CREATABLE_ARTIFACT_TYPES` (the four text types, decision 10), extension map
(`html→.html, markdown→.md, mermaid→.mmd, csv→.csv`), served content types
(`html→text/html; charset=utf-8`, others→`text/plain; charset=utf-8`),
`ARTIFACT_CSP_CDN_HOSTS = ("https://cdn.jsdelivr.net", "https://unpkg.com")`
(decision 7), and the CSP builders (Step 5 values live here as the single
source of truth).

Service operations (one per file, AGENTS.md; raise typed exceptions from
`core/exceptions` — `NotFoundError` for missing/deleted/cross-workspace
artifacts, `AppValidationError` for bad types/oversize content):

- `create_artifact.py` — `create_artifact(db, *, workspace, title,
  artifact_type, content, agent=None, conversation=None, run=None,
  actor_user_id=None) -> tuple[Artifact, FileRevision]`. Validates type ∈
  `CREATABLE_ARTIFACT_TYPES` and encoded size ≤
  `ARTIFACT_MAX_CONTENT_BYTES`; creates the backing `File` + first
  `FileRevision` **through the 032 revision service** (`revision_kind=
  'create'` with `created_by_agent_id` provenance for agent actors;
  031's exactly-one-actor rule decides the provenance columns), storing
  bytes at the 032 key
  `workspaces/{workspace_id}/files/{file_id}/{revision_id}{ext}`; creates
  the `FileReference(target_type="artifact", target_id=artifact.id)`; then
  the `Artifact` row with `current_version_id`.
- `update_artifact.py` — `update_artifact(db, *, workspace, artifact_id,
  content, title=None, ...actor args) -> tuple[Artifact, FileRevision]`.
  Appends a revision to the existing chain (same seam), bumps
  `current_version_id`, optionally retitles. Type is immutable.
- `get_artifact.py` — artifact + its version list (id, created_at, actor
  summary, size) read off the revision chain, workspace-scoped,
  `deleted == False`.
- `list_artifacts.py` — workspace-scoped page (limit/offset, newest first),
  optional `conversation_id` filter.

`services/artifacts/__init__.py` re-exports operations only.

**Verify**: `uv run ruff check .` exit 0; unit smoke via Step 7 tests.

### Step 4: Registry tools

Create `services/agents/runtime/tools/artifacts.py`; register both tools via
`runtime_tool` and add the module to the assembly-point import block at
`tools/registry.py:254-258`. Per decision 2:

```python
class ArtifactToolResult(BaseModel):
    artifact_id: str
    version_id: str
    title: str
    artifact_type: str

@runtime_tool(
    name="create_artifact",
    provider="core",
    label="Create artifact",
    description=(
        "Create a titled, versioned artifact (html, markdown, mermaid, or csv) "
        "the user can view, share, and edit. Use for reports and documents, "
        "not for short chat answers."
    ),
    effect=TOOL_EFFECT_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,   # governance.md §2 external-ish write
    takes_ctx=True,
    timeout=30,
    output_model=ArtifactToolResult,
)
async def create_artifact(ctx: RunContext[RuntimeDeps], title: str,
                          artifact_type: Literal["html","markdown","mermaid","csv"],
                          content: str) -> dict[str, object]: ...
```

`update_artifact(ctx, artifact_id: str, content: str, title: str | None)`
mirrors it (same effect/policy/output model). Both delegate to the Step 3
services with `agent=ctx.deps.agent, conversation=ctx.deps.conversation,
run=ctx.deps.run`, and translate oversize/bad-type validation into
`ModelRetry` (the `planning.py:49-50` pattern). `update_artifact` must
reject artifacts outside `ctx.deps.workspace.id` (NotFound, surfaced as
`ModelRetry("Unknown artifact id")` — do not leak cross-workspace
existence to the model).

**Verify**: the registry command from the Commands table prints
`['create_artifact', 'update_artifact']`; a REPL check shows
`RUNTIME_TOOL_CATALOG['create_artifact'].default_policy == 'approval'` and
`.effect == 'write'`.

### Step 5: Serving pipeline + middleware carve-outs

`services/artifacts/create_view_url.py` — `create_view_url(*, artifact,
version_id) -> ArtifactViewUrl`: base = `settings.ARTIFACT_ORIGIN or
settings.APP_BASE_URL`; `expires = now + ARTIFACT_VIEW_URL_TTL_SECONDS`
(unix seconds); `sig = create_hmac_signature(
f"artifact-view:{artifact.id}:{version_id}:{expires}", SECRET_KEY)`;
returns `{base}/artifacts/view/{artifact.id}/{version_id}?expires=...&sig=...`.

`services/artifacts/serve_artifact_version.py` — the anonymous core:
verify expiry then signature (`verify_hmac_signature`, constant-time); load
artifact (not deleted) and confirm the revision belongs to the artifact's
file chain; read bytes via `provider.get_object`; return a `Response` with
exactly these headers (built in `domain.py`, `{app_origins}` =
`'self'` + `FRONTEND_URL` + `cors_origins_list`, the
`security_headers.py:28-41` recipe):

For `html`:

```
Content-Type: text/html; charset=utf-8
Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; style-src 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; img-src data: blob:; font-src data: https://cdn.jsdelivr.net https://unpkg.com; connect-src 'none'; frame-ancestors {app_origins}; base-uri 'none'; form-action 'none'; object-src 'none'; sandbox allow-scripts
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Cache-Control: no-store
```

For `markdown`/`mermaid`/`csv` (served as plain text, decision — donor §4.6
"non-HTML types served as attachment/plain"): `Content-Type: text/plain;
charset=utf-8`, CSP `default-src 'none'; frame-ancestors {app_origins};
base-uri 'none'; form-action 'none'; sandbox`, same
nosniff/no-referrer/no-store; with `?download=1`,
`Content-Disposition: attachment; filename=...` via
`build_content_disposition` (`services/storage/paths.py:78-91`). For
`image-ref`: stream only when the stored content type is `image/*`
(decision 10), CSP as for plain text. Any signature/expiry/lookup failure →
uniform `NotFoundError` (404 problem+json) — do not distinguish causes.

Routes: `routes/artifact_serving/view_artifact_version.py` — `GET
/artifacts/view/{artifact_id}/{version_id}` with `expires`/`sig` query
params, **no auth dependency** (decision 3; precedent
`routes/storage/private_object.py`). Compose in
`routes/artifact_serving/__init__.py` (router prefix `/artifacts`), export
`artifact_serving_router` from `routes/__init__.py`, and include it in
`main.py` next to `api_router` (`main.py:115`) with a one-line comment
noting it is the cookie-free serving surface. Do not alter middleware
registration order — the `main.py:75-81` comment stays authoritative and
unchanged.

Middleware carve-outs (decision 6):

- `middleware/utils.py`: add
  `_is_artifact_serving_path(path) -> bool` → `path.startswith("/artifacts/view") or path.startswith("/artifacts/shared")`
  (the second prefix is claimed now so 051 does not touch middleware).
- `middleware/security_headers.py`: for artifact-serving paths, skip the
  `X-Frame-Options` default and skip the fallback CSP `setdefault` (the
  route always sets its own; if a non-route 404 escapes, `setdefault`
  applying the deny-all CSP is fine — so only XFO strictly needs the
  branch; implement exactly that and leave the CSP `setdefault` in place as
  the fail-closed backstop).
- `middleware/csrf.py`: guard the cookie auto-refresh block
  (`csrf.py:200-212`) with `not _is_artifact_serving_path(request.url.path)`
  so serving responses never carry `Set-Cookie`.

**Verify**: with the dev server running and a seeded artifact, `curl -si`
a minted view URL → 200 with the exact HTML CSP above, `nosniff`,
`no-referrer`, `no-store`, no `Set-Cookie`, no `X-Frame-Options`; the same
URL with a flipped signature character → 404 problem+json; after TTL → 404.

### Step 6: Management routes

`routes/artifacts/` under `api_router` (prefix `/artifacts`, so
`/api/v1/artifacts/...`), route-per-file, following
`routes/skills/list_skills.py` (workspace read access via
`CurrentWorkspaceDep`; membership implies read — the `governance.md` §1
matrix row "View … artifacts: all roles"):

- `list_artifacts.py` — `GET /` (limit/offset, optional `conversation_id`)
- `get_artifact.py` — `GET /{artifact_id}` (artifact + versions)
- `get_version_content.py` — `GET /{artifact_id}/versions/{version_id}/content`
  → JSON `{content, content_type, size_bytes}` for 051's srcdoc previews
  (safe to inline: revisions are capped at `ARTIFACT_MAX_CONTENT_BYTES`).
  `image-ref` returns a signed storage download URL instead of inline bytes.
- `create_view_url.py` — `GET /{artifact_id}/versions/{version_id}/view-url`
  → JSON `{url, expires_at}` (Step 5 service).

Pydantic response schemas in `services/artifacts/schemas.py`. No
create/update/delete routes — creation is tool-only in this plan; user
edits are 051.

**Verify**: authenticated `curl` list/get/content/view-url round-trip works;
a request against another workspace's artifact id → 404; ruff exit 0.

### Step 7: Tests

`tests/services/artifacts/` and `tests/routes/artifacts/` (all modules set
`pytestmark = pytest.mark.asyncio`; DB-backed tests use `conftest.py`
fixtures and skip without `TEST_DATABASE_URL`; live LLM calls are already
blocked in tests):

- `test_artifact_registry_tools.py` (no DB): both tools registered;
  `effect == "write"`, `default_policy == "approval"`,
  `supports_approval` true (pinning governance §2); output model declared;
  `CREATABLE_ARTIFACT_TYPES` excludes `image-ref`.
- `test_create_update_artifact.py`: create writes File + revision +
  reference + artifact with matching `current_version_id`; update appends a
  second revision (chain length 2, first revision bytes unchanged in
  storage — immutability observed end to end); oversize content →
  validation error; bad type → validation error; cross-workspace update →
  NotFound.
- `test_serve_artifact_version.py` (route-level, the pinned invariants):
  - **CSP exact-match**: the HTML response's `Content-Security-Policy`
    equals the Step 5 string byte-for-byte (single source in `domain.py`;
    the test builds the expected value from the same constants — a drifted
    header fails review, not silently).
  - `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
    `Cache-Control: no-store` present; `X-Frame-Options` ABSENT.
  - **No-cookie assertion**: response has no `Set-Cookie`, including when
    the request carries a valid `session` cookie (the csrf auto-refresh
    carve-out).
  - Signature tampering, expired `expires`, unknown artifact, unknown
    version, version from a different artifact's chain, soft-deleted
    artifact → all uniform 404 problem+json.
  - Non-HTML types: `text/plain`, minimal CSP with `sandbox`;
    `?download=1` → `Content-Disposition: attachment`.
- `test_artifact_routes.py`: list/get/content shapes; workspace scoping;
  `view-url` returns a URL that the serving route then accepts (round-trip);
  content endpoint returns the exact stored string.
- Factory helper in `tests/factories/` building an artifact over a real
  File/FileRevision chain (reuse 031/032 factories — do not hand-roll
  files rows).

**Verify**: `TEST_DATABASE_URL=... uv run pytest tests/services/artifacts
tests/routes/artifacts -q` all pass; without the env var, DB tests skip.

## Test plan

Covered by Step 7 (~20–24 tests). Pinned invariants: **the serving response
headers are exact and cookie-free** (CSP byte-match, nosniff, no-referrer,
no-store, no Set-Cookie even with a session cookie present), **capability
URLs fail closed** (tamper/expiry/cross-chain/deleted → uniform 404),
**versions ride the 031 chain immutably** (update appends, never mutates),
and **both tools are write-classified with approval default** (governance
§2 pinned in a test so a policy regression is loud).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` clean; migration on the **core** branch (D5);
      downgrade round-trips
- [ ] Registry lists exactly `create_artifact` and `update_artifact` as the
      artifact tools, `effect=write`, `default_policy=approval`
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/artifacts tests/routes/artifacts -q` exits 0
- [ ] Serving route returns the exact Step 5 headers; no `Set-Cookie` under
      any request shape; GET-only; no auth dependency; no CSRF exempt-list
      change (`git diff apps/api/middleware/csrf.py` touches only the
      refresh block)
- [ ] `main.py` middleware ordering comment unchanged and still accurate
- [ ] No `apps/web` changes; no share/token/sweep code (051)
- [ ] `docs/architecture/governance.md` §1/§2 artifact cells flipped to
      `[implemented: plan 050]` in the same PR
- [ ] `git status` clean outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated (add the 050 row)

## STOP conditions

Stop and report back (do not improvise) if:

- The cross-plan pre-flight fails: 031 or 032 is not implemented, or their
  landed contract diverges from the dictated names
  (`File`/`FileRevision`/`FileReference`, `target_type="artifact"`, the
  storage key scheme, a revision-append service).
- An `artifacts` table, `models/artifacts.py`, or `services/artifacts/`
  already exists.
- The `main.py:75-89` middleware ordering comment no longer matches the
  registered middleware, or the ordering conflicts with the serving route's
  needs (e.g. a new middleware sets cookies or rewrites headers after
  SecurityHeaders) — reconcile the comment and design first.
- CSRF/session behavior would still leak onto artifact serving responses
  after decision 6's carve-out (e.g. `session_manager` or another
  middleware sets cookies on arbitrary responses) — the no-cookie invariant
  is non-negotiable.
- `SecurityHeadersMiddleware` no longer uses `setdefault` (route-owned CSP
  would be silently overwritten).
- The governance note's §2 default for artifact creation has changed from
  `approval` — reconcile before registering the tools.
- You feel the need to add share tokens, anonymous non-signed access, new
  SSE event names, or frontend code — scope leaking into 051.

## Maintenance notes

- **051 consumes**: the serving pipeline (`serve_artifact_version.py`) is
  reused verbatim by the share route — keep it free of signature-specific
  logic (signature checking stays in the route/service seam so a
  token-resolved share can call the same renderer). The
  `/artifacts/shared` middleware prefix is already carved out here.
- **Separate-origin enforcement is 051's validator rule**: when
  `ARTIFACT_SHARING_ENABLED` ships, the production validator must require a
  non-empty `ARTIFACT_ORIGIN` on a distinct registrable domain. Until then
  `ARTIFACT_ORIGIN` is optional everywhere (local decision recorded:
  srcdoc + sandbox only, no separate origin in dev).
- **CDN whitelist growth** (`ARTIFACT_CSP_CDN_HOSTS`) is a reviewed code
  change. Reviewers should reject any host that serves user-controllable
  paths (that would reopen exfil via `script-src`), and must never admit a
  remote `img-src` or any `connect-src`.
- **`image-ref` producers**: when 034/036 give agents image handles, lift
  the `CREATABLE_ARTIFACT_TYPES` restriction and route creation through the
  same revision chain; the CHECK constraint and serving path are already in
  place.
- **Deferred interactive Apps** (donor §4.6 "Deferred") stay deferred; if
  they return, the donor security kernel is the reference — but this plan's
  serving discipline (server-served documents, real CSP, no cookies) is the
  baseline they must meet.
- Reviewers should scrutinize: the uniform-404 discipline in
  `serve_artifact_version.py` (no oracle for existence), constant-time
  signature comparison, that tool errors surface as `ModelRetry` without
  leaking cross-workspace ids, and that no code path calls
  `dangerouslySetInnerHTML`-equivalent HTML injection on the API side
  (responses are byte streams, never templated).
