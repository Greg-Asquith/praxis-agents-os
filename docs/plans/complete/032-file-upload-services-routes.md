# Plan 032: File upload, edit, restore, and deletion services + routes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G3**: `docs/architecture/governance.md` EXISTS and is DONE
> (written 2026-07-06 at `0cbbb39`, plan 029). This plan cites its sections
> directly — no pre-flight confirmation is needed. If a cited default has
> been flipped since, the note wins; reconcile before coding.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/services/files/ apps/api/routes/files/ apps/api/routes/__init__.py apps/api/services/assets/ apps/api/services/storage/ apps/api/services/jobs/ apps/api/services/audit_events/enums.py apps/api/core/settings/files.py apps/api/workers/ apps/api/models/files.py`
> Changes under `services/files/` and `models/files.py` from plan 031 and
> under `services/jobs/`/`workers/` from plan 030 are EXPECTED — verify
> they match those plans' deliverables (Current state below). Any other
> in-scope drift the excerpts do not describe is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (first write surface over workspace blobs: RBAC on a
  new resource type, symmetric deletion that destroys storage objects,
  and optimistic concurrency — all governance high-risk areas)
- **Depends on**: 031 (hard — models, contract, staging table, key
  builders), 030 (hard for Step 7's sweeper — `enqueue_job`,
  `@job_handler`, the sweep-kind pattern; the rest of the plan does not
  touch jobs). Soft: `docs/architecture/governance.md` (Gate G3).
- **Category**: Phase 3 files substrate (roadmap `000_MASTER_ROADMAP.md`
  §4 Phase 3 row 032; donor `DONOR_PORT_ROADMAP.md` §4.3 / §6 row B3)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Reuse the assets token seam, not a parallel one.** Upload grants ride
   `services/assets/tokens.py` (`create_asset_upload_token:21-49`,
   `verify_asset_upload_token:52-81`) with one new
   `AssetKind.WORKSPACE_FILE` member
   (`services/assets/domain.py:15-20`). The token already binds actor,
   workspace, bucket, object key, content type, and max size with a
   10-minute TTL — exactly what file uploads need. A second token module
   would be the donor's parallel-frameworks mistake.
2. **Confirm computes the real sha256.** The client-declared
   `content_hash` powers only the request-time dedup fast path; at
   confirm the service reads the stored bytes (`get_object`) and hashes
   them itself — the stored hash is never client-controlled (it feeds
   044 provenance and dedup forever). The skills confirm already pulls
   full bytes for conversion
   (`services/skills/documents/confirm_document_upload.py:74`), so the
   memory profile (bounded by the 100 MB max) is accepted precedent.
3. **Dedup returns, never blocks.** Request-time dedup (dictated) looks
   up `(workspace_id, content_hash)` against live files' current
   revisions; on a hit the response carries `deduplicated: true` plus the
   existing file instead of an upload grant. An
   `allow_duplicate_content: true` flag opts out (two files may
   legitimately share bytes under different names). Confirm-time recheck
   only short-circuits when the same *file* already has an identical
   current revision (idempotent re-confirm); it never silently merges
   distinct files.
4. **Edit/restore concurrency is a row lock plus a typed 409.** Edit and
   restore `SELECT ... FOR UPDATE` the `File` row, compare
   `expected_current_revision_id`, and raise `ConflictError`
   (`core/exceptions/general.py:91-122`, RFC 7807 → 409) with
   `details={"current_revision_id": ...}` on mismatch. Revision numbers
   are assigned under the same lock (`revision_count + 1`), so concurrent
   confirms/edits serialize instead of colliding on the unique
   constraint.
5. **Restore is roll-forward and non-copying**, per 031 decision 8: a
   `restore` revision reuses the source revision's `object_key` — no
   byte copy (the `StorageProvider` protocol has no copy op,
   `services/storage/provider.py:14-89`). History is never rewritten;
   restoring an old revision only appends.
6. **Deletion is symmetric, in two stages** (governance §3 law 1 +
   Files row: soft ✓, hard 30 d, "tombstone blob; sweeper deletes both").
   Soft delete (EDITOR) marks the row; blobs stay untouched so a purge
   decision remains reversible by an operator at the DB level during the
   window. Hard deletion happens in exactly two places: the sweeper
   (30 d after `deleted_at`) and MANAGER purge — both delete the file's
   **distinct** revision `object_key`s plus any `markdown_object_key`s
   first (best-effort, logged), then hard-delete the `files` row
   (revisions/references cascade, verified 031). Distinct-key handling
   matters because restore revisions share keys (decision 5).
7. **One sweep kind, two passes.** `files.sweep_deleted` (registered
   here, per 030 decision 6's owning-plan rule) hard-deletes expired
   soft-deleted files AND expires abandoned `FileUpload` rows
   (`consumed_at IS NULL AND expires_at < now`), deleting their staged
   blob best-effort. One kind keeps the worker's ensure-bootstrap wiring
   to a single line; the two passes are independent inside the handler.
   The handler self-reschedules exactly like `jobs.sweep_terminal`
   (030 Step 5), and `workers/job_runner.py` gains one
   `ensure_files_sweep_job(db)` call beside 030's `ensure_sweep_job` —
   the minimal bootstrap, recorded as the pattern later resource
   sweepers (044, 051) follow.
8. **Storage quota is a counter, not a wall** (governance §4 law:
   "counters + admin visibility first, hard enforcement second";
   per-workspace storage default 10 GB, counter named for 032). Usage =
   `SUM(size_bytes)` over **distinct object keys** of live files'
   revisions (shared restore keys count once). Request-upload compares
   usage + declared size against
   `FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES`; over the line it sets
   `over_soft_limit: true` in the grant response and logs a warning —
   it does NOT block. `GET /files/usage` exposes the counter.
9. **RBAC per governance §1**: view — all roles (`require_read`);
   upload/edit/restore/soft-delete — EDITOR
   (`services/files/utils.py::require_file_write_access`, mirroring
   `require_skill_write_access` over `EDITOR_ROLES`,
   `services/workspaces/utils.py:25`); purge — MANAGER
   (`require_file_purge_access` over `MANAGER_ROLES`, line 24; the §1
   row "Hard-delete / purge files (032)" is admin/owner only).
10. **Every mutation is audited** with a new
    `AuditResourceType.FILE = "file"` member
    (`services/audit_events/enums.py:25-40`) via
    `record_workspace_audit_event`
    (`services/audit_events/workspace_events.py:19-44`): CREATE on
    confirm, UPDATE on edit/restore/rename, DELETE on soft delete and on
    purge (purge carries `details={"purge": true}`). Grant creation is
    not audited (no state changes until confirm). Audit rows survive
    file deletion per governance §3 law 2 (audit FKs are SET NULL,
    enforced today).
11. **Processing status stays honest.** Confirm sets
    `processing_status='ready'` unconditionally — no extraction pipeline
    exists until 033, and a permanently-pending status would imply one
    (AGENTS.md: document capabilities as pending instead of implying
    they work). 033 owns flipping confirm to `pending` + enqueue for
    ingestible types.
12. **Gaps-doc questions resolved here**
    (`docs/legacy/ROADMAP_QUESTIONS_GAPS.md`): §Data Lifecycle "files and
    FileRevisions" retention — implemented per governance §3 (decisions
    6/7); §Notifications "long-running job feedback" for files — sweep
    jobs are initiator-less system jobs, so per governance §6 they log
    only, no notifications (030 decision 8 mechanics).

## Why this matters

This is the plan that makes files exist as a product surface: 031's
schema has no writers, and everything downstream — 033's extraction,
034's agent tools, 035's UI, 036's attachments, 044's ingestion, 050's
artifacts — assumes uploads, edits, restores, and deletion already work
and are safe. It is also the first full expression of the governance
lifecycle on a new resource type: two-phase signed upload with
confirm-time verification (extending the proven assets pattern),
append-only revision history with optimistic concurrency, symmetric
soft-delete → sweep → blob deletion, a storage counter, EDITOR/MANAGER
role gates, and per-operation audit. Getting the shape right here means
037/044/050 copy a working lifecycle instead of inventing three more.

## Current state

All anchors verified at `0cbbb39`, except items marked **[after 030]**
/ **[after 031]**, which this plan consumes from its dependencies and
must re-verify at execution time.

- **[after 031]** `models/files.py`: `File` (soft-delete, mirror columns,
  `current_revision_id` use_alter FK, processing columns), `FileRevision`
  (append-only, provenance CHECK, restore CHECK, immutability listener
  with markdown whitelist), `FileReference`, `FileUpload` (staging:
  pre-generated `file_id`/`revision_id`, unique `object_key`,
  `expires_at`/`consumed_at`); `services/files/contract.py`
  (`FileCategory`, `contract_for_content_type`, `require_matching_pair`,
  `max_size_bytes`, `is_editable`, `is_ingestible`);
  `services/files/utils.py` (`revision_object_key`,
  `revision_markdown_key`, `file_prefix`).
- **[after 030]** `services/jobs/`: `enqueue_job(db, *, kind,
  workspace_id, subject_type, subject_id, payload, content_hash,
  priority, run_after, max_attempts, initiated_by_user_id)`;
  `@job_handler(kind=..., timeout=...)` decorator registering into
  `services/jobs/registry.py` via the `services/jobs/handlers/` assembly
  point; at-least-once semantics (handlers must be idempotent); the
  self-rescheduling sweep pattern (`handlers/sweep_terminal_jobs.py`)
  and the worker loop `workers/job_runner.py` calling ensure-functions
  each pass.
- `apps/api/services/assets/` — the two-phase precedent this plan
  extends: request grant (`create_user_avatar_upload.py:19-53`:
  validate → ref → `create_signed_upload` → token), confirm
  (`services/skills/documents/confirm_document_upload.py:37-127`:
  verify token → key ownership checks → `stat_object` +
  `validate_stored_object` → bytes → flush → audit). Shared helpers:
  `services/assets/utils.py` `validate_upload_metadata` (47),
  `validate_stored_object` (90), `normalize_content_type` (29);
  `services/assets/tokens.py` (decision 1); `AssetKind` StrEnum at
  `services/assets/domain.py:15-20` gains one member.
- `apps/api/services/storage/`: provider protocol
  (`provider.py:14-89` — note: no list, no copy), `StorageBucket.PRIVATE`
  (`domain.py:15-19`), `safe_filename` (`paths.py:93`);
  `best_effort_delete_private_object` pattern to copy (not import — it
  is skills-specific) from `services/skills/documents/utils.py:249-265`.
- Route conventions: `routes/skills/` — one operation per file, thin
  handlers delegating to one service op
  (`routes/skills/create_document_upload.py:17-34` is the exact shape:
  `AsyncDbSessionDep`, `CurrentUserDep`, `CurrentWorkspaceDep` tuple
  unpack), composed only in `__init__.py`; routers registered in
  `routes/__init__.py:22-36`.
- RBAC: `require_role` (`core/dependencies.py:243`),
  `require_owner`/`require_editor`/`require_read` (267-269); role sets
  `MANAGER_ROLES`/`EDITOR_ROLES` (`services/workspaces/utils.py:24-31`);
  service-level gate precedent `require_skill_write_access`
  (`services/skills/utils.py`, used at
  `confirm_document_upload.py:48`).
- Exceptions: `AppValidationError` (`core/exceptions/general.py:16`),
  `NotFoundError` (52), `ConflictError` (91-122 — carries
  `conflicting_resource` and `details`); raise these, never ad-hoc
  `HTTPException`.
- Audit: `AuditResourceType` (`services/audit_events/enums.py:25-40`)
  has no FILE member yet; `record_workspace_audit_event`
  (`workspace_events.py:19-44`) takes action/resource_type/resource_id/
  actor/details/status.
- Settings: `FilesSettingsMixin` (`core/settings/files.py:8`) —
  this plan appends keys to it (no new mixin; it is already composed at
  `core/settings/__init__.py:21,39`).
- Governance anchors: §1 files rows (EDITOR write, MANAGER purge), §3
  two laws + Files row (30 d, tombstone+sweep, audit survives, export
  via signed URL batch — export is NOT in scope, see Scope), §4 storage
  quota row (10 GB soft, counter added by 032), §6 (sweeps: log only).
- Tests: `tests/services/skills/test_skill_documents.py` and
  `tests/services/assets/` show the upload-flow test style;
  `tests/support/storage.py::reset_storage_provider_cache` (8) resets
  the provider singleton between tests; factories per
  `tests/factories/`.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations (this plan adds NO migration) |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/files tests/routes/files -q` | all pass |
| Neighbor regression | `uv run pytest tests/services/skills tests/services/assets tests/services/jobs -q` | all pass, untouched behavior |
| Worker smoke | `uv run python -m workers.job_runner --once` | one pass; `files.sweep_deleted` ensured + executed |
| Registry check | `uv run python -c "from services.jobs.registry import JOB_HANDLERS; print(sorted(JOB_HANDLERS))"` | includes `files.sweep_deleted` |

## Scope

**In scope:**

- `apps/api/core/settings/files.py` (extend `FilesSettingsMixin`)
- `apps/api/services/assets/domain.py` (add `AssetKind.WORKSPACE_FILE`)
- `apps/api/services/audit_events/enums.py` (add
  `AuditResourceType.FILE`)
- `apps/api/services/files/` (extend): `domain.py`, `utils.py`
  (add access gates + best-effort blob delete + hash helper),
  `create_file_upload.py`, `confirm_file_upload.py`, `list_files.py`,
  `get_file.py`, `list_file_revisions.py`, `create_file_download.py`,
  `edit_file.py`, `update_file.py`, `restore_file_revision.py`,
  `delete_file.py`, `purge_file.py`, `get_files_usage.py`,
  `__init__.py` (re-export the operation functions — now permitted, they
  exist)
- `apps/api/services/jobs/handlers/sweep_deleted_files.py` (create —
  the `files.sweep_deleted` kind + `ensure_files_sweep_job`)
- `apps/api/workers/job_runner.py` (one-line ensure call, decision 7)
- `apps/api/routes/files/` (create — one route file per operation +
  `__init__.py` router composition) and `apps/api/routes/__init__.py`
  (register `files_router`)
- `apps/api/tests/services/files/` (extend), `apps/api/tests/routes/files/`
  (create), `tests/factories/files.py` (extend if needed)
- `docs/architecture/governance.md` (Done criteria — flip the §1 files
  rows, §3 Files row, §4 storage-counter cell)

**Out of scope (do NOT touch):**

- Migrations — 031 shipped every column this plan needs (including
  processing columns). If you find yourself writing one, STOP.
- Extraction/`files.extract`/processing-status transitions beyond
  decision 11's constant `'ready'` — plan 033.
- `FileReference` create/delete operations (034/036/050 own their
  targets), agent tools, scratch (034), UI (035), multimodal (036).
- The §3 "Export ✓ (signed URL batch)" cell — single-file signed
  downloads ship here; batch export is a later, unplanned slice. Leave
  the cell `[default — confirm at review]` and record that in Step 10.
- Hard quota enforcement (governance §4 keeps it soft in v1).
- `services/skills/documents/**` and `services/assets/` beyond the one
  enum member (033 owns the converter refactor).

## Git workflow

- Branch: `advisor/032-file-upload-services-routes`
- Commit style: `API - File Upload Services & Routes`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings + enums

Append to `FilesSettingsMixin` (`core/settings/files.py`), all
`Field(..., description=...)` with sane bounds:

```python
FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES: int = 10_737_418_240  # 10 GiB, governance §4 soft quota
FILES_UPLOAD_EXPIRY_HOURS: int = 24            # abandoned FileUpload rows expire after this
FILES_DELETED_RETENTION_DAYS: int = 30         # governance §3 Files row
FILES_SWEEP_INTERVAL_SECONDS: int = 3600       # files.sweep_deleted self-reschedule cadence
FILES_MAX_TEXT_EDIT_BYTES: int = 2_097_152     # 2 MiB cap on JSON-body text edits
```

Add `WORKSPACE_FILE = "workspace_file"` to `AssetKind`
(`services/assets/domain.py:15-20`) and `FILE = "file"` to
`AuditResourceType` (`services/audit_events/enums.py:25-40`).

**Verify**: `uv run python -c "from core.settings import settings; print(settings.FILES_DELETED_RETENTION_DAYS)"`
→ `30`; ruff exit 0.

### Step 2: Domain contracts + service utils

`services/files/domain.py` (Pydantic, patterned on
`services/skills/documents/domain.py`):

- `FileUploadRequest` — `filename` (1–255), `content_type` (1–128),
  `size_bytes` (ge=1), `content_hash: str | None` (64-char hex when
  present), `file_id: UUID | None` (present = replace flow),
  `allow_duplicate_content: bool = False`; whitespace normalization
  validators as in the skills domain.
- `FileUploadGrant` — `upload: SignedUpload`, `upload_token`,
  `max_size_bytes`, `expires_at`, `over_soft_limit: bool = False`
  (decision 8), `file_id: UUID` (pre-generated or existing).
- `FileUploadResult` — union-ish response for request-upload:
  `deduplicated: bool = False`, `file: FileRead | None`,
  `grant: FileUploadGrant | None` (exactly one populated; decision 3).
- `FileConfirmRequest` — `upload_token`.
- `FileEditRequest` — `content: str`, `expected_current_revision_id:
  UUID`.
- `FileUpdateRequest` — `name: str | None`, `description: str | None`
  (rename keeps the extension: validator rejects a changed suffix).
- `FileRestoreRequest` — `revision_id: UUID`,
  `expected_current_revision_id: UUID`.
- `FileRead` — id, workspace_id, name, description, category,
  content_type, extension, size_bytes, content_hash,
  current_revision_id, revision_count, processing_status,
  processing_error, created_at, updated_at.
- `FileRevisionRead` — id, revision_number, revision_kind, content_type,
  size_bytes, content_hash, actor fields, restored_from_revision_id,
  created_at.
- `FileListResponse` (`files`, `total`), `FileRevisionsListResponse`,
  `FileDownloadGrant` (`download: SignedDownload`, `expires_at`),
  `FilesUsageResponse` (`used_bytes`, `soft_limit_bytes`,
  `over_soft_limit`).

Extend `services/files/utils.py`:

- `require_file_write_access(membership)` / `require_file_purge_access(
  membership)` — decision 9, raising the same authorization error type
  the skills gate uses.
- `get_file_for_workspace(db, *, workspace, file_id,
  include_deleted=False) -> File` — workspace-scoped fetch or
  `NotFoundError` (the `get_skill_for_workspace` shape).
- `sha256_hex(data: bytes) -> str`.
- `best_effort_delete_file_object(object_key, *, provider=None)` — the
  `best_effort_delete_private_object` pattern
  (`skills/documents/utils.py:249-265`), local copy (AGENTS.md: do not
  import service-specific helpers across service packages).
- `distinct_object_keys(revisions) -> set[str]` — revision keys plus
  non-NULL `markdown_object_key`s (decisions 5/6).

**Verify**: `uv run ruff check .` → exit 0.

### Step 3: Request-upload (`create_file_upload.py`)

`create_file_upload(db, *, actor, workspace, membership, payload) ->
FileUploadResult`:

1. `require_file_write_access(membership)`.
2. Contract gate: `entry = require_matching_pair(payload.content_type,
   extension_of(safe_filename(payload.filename)))`;
   `payload.size_bytes > max_size_bytes(entry)` →
   `AppValidationError("File is too large", field="size_bytes")`.
3. Replace flow (`payload.file_id` set): fetch the file
   (`get_file_for_workspace`), require its `category` matches the new
   content's category (a replace may change MIME within category — e.g.
   md→txt — but not image→pdf; record in the docstring).
4. Dedup fast path (decision 3): when `content_hash` present and not
   `allow_duplicate_content`, look up live files whose **current
   revision** matches `(workspace_id, content_hash)` (join through
   `files.current_revision_id`; the `ix_file_revisions_workspace_hash`
   index carries it). Hit → return
   `FileUploadResult(deduplicated=True, file=...)`, no grant, nothing
   persisted.
5. Soft-quota check (decision 8): `get_files_usage` + declared size vs
   `FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES` → `over_soft_limit` flag +
   `logger.warning` (never a block).
6. Pre-generate `file_id` (or reuse the replace target's) and
   `revision_id`; build `object_key = revision_object_key(workspace.id,
   file_id, revision_id, entry_extension)`; insert the `FileUpload` row
   (`expires_at = now + FILES_UPLOAD_EXPIRY_HOURS`).
7. `provider.create_signed_upload(ref, content_type=...,
   expires_in=timedelta(minutes=10))` + `create_asset_upload_token(
   kind=AssetKind.WORKSPACE_FILE, actor_user_id=actor.id,
   workspace_id=workspace.id, ref=ref, content_type=...,
   max_size_bytes=max_size_bytes(entry))` (decision 1).
8. Return the grant. No audit row (decision 10).

**Verify** (after Step 6 wires routes; for now):
`uv run pytest tests/services/files/test_create_file_upload.py -q`
(written in Step 9) — or defer to Step 9's suite; ruff exit 0.

### Step 4: Confirm (`confirm_file_upload.py`)

`confirm_file_upload(db, *, request, actor, workspace, membership,
payload) -> FileRead`, the
`confirm_skill_document_upload:37-127` shape:

1. Write access; `verify_asset_upload_token(...,
   expected_kind=AssetKind.WORKSPACE_FILE, actor_user_id=actor.id,
   workspace_id=workspace.id)`; require `ref.bucket ==
   StorageBucket.PRIVATE`.
2. Load the `FileUpload` row by `object_key == ref.key`
   (unique, 031). Missing → `AppValidationError` ("token is not valid");
   `consumed_at` set → return the existing file idempotently (look up by
   `file_upload.file_id`) — a double-confirm must not create a second
   revision.
3. `stat_object` + `validate_stored_object`
   (`services/assets/utils.py:90`) against the token's content type and
   max size; then `data = await provider.get_object(ref)` and
   `content_hash = sha256_hex(data)` (decision 2 — declared hash is
   advisory only).
4. Lock: for the replace flow `SELECT ... FOR UPDATE` the existing
   `File`; if its current revision already has this `content_hash`,
   mark the upload consumed and return the file unchanged (decision 3
   idempotence). For a new file, insert `File` (id =
   `file_upload.file_id`, mirrors from the stored object,
   `processing_status='ready'` — decision 11, `revision_count=0`).
5. Insert `FileRevision` (id = `file_upload.revision_id`,
   `revision_number = file.revision_count + 1`, `revision_kind =
   'create'` for new files / `'replace'` for the replace flow,
   `created_by_user_id=actor.id`, real `size_bytes`/`content_type` from
   the stored object, `content_hash`, `object_key=ref.key`). Flush, then
   set `file.current_revision_id`, bump `revision_count`, refresh the
   mirror columns — same flush discipline 031's maintenance notes
   demand.
6. Stamp `file_upload.consumed_at = now`.
7. Audit: `record_workspace_audit_event(..., action=AuditAction.CREATE,
   resource_type=AuditResourceType.FILE, resource_id=file.id,
   details={"filename": ..., "size_bytes": ..., "revision_kind": ...,
   "content_hash": ...})` (decision 10).

**Verify**: covered by Step 9 tests; ruff exit 0.

### Step 5: Reads, edit, rename, restore, delete, purge, usage

One operation per file (AGENTS.md), all raising typed exceptions:

- `list_files.py` — `list_files(db, *, workspace, category=None,
  search=None, limit=50, offset=0) -> FileListResponse`; excludes
  deleted (`File.query_not_deleted()`), orders by `created_at` desc
  (the `ix_files_workspace_created` partial index), `search` is a
  simple `ILIKE` on name. Any role.
- `get_file.py` — detail incl. current revision metadata. Any role.
- `list_file_revisions.py` — revisions for one file, newest first. Any
  role.
- `create_file_download.py` — `create_signed_download` for the current
  revision or an explicit `revision_id` (must belong to the file),
  `force_download`/`filename` passthrough, short TTL (10 min). Any role.
  Returns `FileDownloadGrant`.
- `edit_file.py` — EDITOR; only `is_editable(file.content_type)`
  categories (else `AppValidationError`); UTF-8 encode `payload.content`,
  cap at `FILES_MAX_TEXT_EDIT_BYTES`; lock the file, check
  `expected_current_revision_id` else `ConflictError` (decision 4);
  `put_object` at a fresh `revision_object_key(...)`; append revision
  (`revision_kind='edit'`, `created_by_user_id`); update mirrors; audit
  UPDATE.
- `update_file.py` — EDITOR; rename (extension-preserving) +
  description; no revision; audit UPDATE with
  `details={"action": "rename"}`.
- `restore_file_revision.py` — EDITOR; lock + optimistic check
  (decision 4); source revision must belong to the file and differ from
  current; append revision (`revision_kind='restore'`,
  `restored_from_revision_id=source.id`, `object_key=source.object_key`
  — decision 5, content fields copied from source); update mirrors;
  audit UPDATE with `details={"action": "restore",
  "restored_from_revision_id": ...}`.
- `delete_file.py` — EDITOR; `file.soft_delete(deleted_by=actor.id)`
  (`models/base.py:45-57`); blobs untouched (decision 6); audit DELETE.
- `purge_file.py` — MANAGER (`require_file_purge_access`); delete
  `distinct_object_keys(revisions)` best-effort via
  `best_effort_delete_file_object`, then hard-delete the row (cascades);
  audit DELETE with `details={"purge": true}` **before** the delete
  flushes (audit FK is SET NULL, survives — governance §3 law 2).
- `get_files_usage.py` — decision 8's distinct-key SUM over
  non-deleted files, returns `FilesUsageResponse`. Any role reads it;
  the docstring records that hard enforcement is deliberately absent
  (governance §4 law).

`services/files/__init__.py` now re-exports exactly these operation
functions.

**Verify**: `uv run ruff check .` → exit 0; imports resolve:
`uv run python -c "import services.files as f; print(len(f.__all__))"`.

### Step 6: Routes (`routes/files/`)

One route file per operation, thin (the
`routes/skills/create_document_upload.py:17-34` shape), composed in
`routes/files/__init__.py` with `APIRouter(prefix="/files",
tags=["files"])`, registered in `routes/__init__.py` (alphabetical —
after `conversations`, before `models`):

| Route file | Method + path | Service op |
|---|---|---|
| `create_file_upload.py` | `POST /files/uploads` | request-upload |
| `confirm_file_upload.py` | `POST /files/uploads/confirm` | confirm |
| `list_files.py` | `GET /files` | list |
| `get_files_usage.py` | `GET /files/usage` | usage (declare BEFORE `/{file_id}` so the literal path wins) |
| `get_file.py` | `GET /files/{file_id}` | detail |
| `update_file.py` | `PATCH /files/{file_id}` | rename/description |
| `delete_file.py` | `DELETE /files/{file_id}` | soft delete |
| `purge_file.py` | `POST /files/{file_id}/purge` | hard delete |
| `edit_file.py` | `PUT /files/{file_id}/content` | text edit |
| `restore_file_revision.py` | `POST /files/{file_id}/restore` | restore |
| `list_file_revisions.py` | `GET /files/{file_id}/revisions` | revisions |
| `create_file_download.py` | `POST /files/{file_id}/download` | signed download |

Role gates live in the service ops (decision 9), matching the skills
convention — routes stay thin and pass `(workspace, membership)` down.

**Verify**: `uv run python -c "from main import app; print(sorted(r.path for r in app.routes if '/files' in r.path))"`
→ the twelve paths above under `/api/v1`.

### Step 7: The sweeper (`services/jobs/handlers/sweep_deleted_files.py`)

Requires 030 landed (STOP otherwise). Register the resource sweep kind
per 030's pattern:

```python
@job_handler(kind="files.sweep_deleted", timeout=300.0)
async def sweep_deleted_files(db, job):
    # pass 1: files soft-deleted longer than FILES_DELETED_RETENTION_DAYS:
    #   delete distinct revision + markdown blobs (best-effort, logged),
    #   then hard-delete the file row (revisions/references cascade)
    # pass 2: file_uploads with consumed_at IS NULL and expires_at < now:
    #   delete the staged blob best-effort, then the row
    # then self-reschedule: enqueue same kind, run_after = now + FILES_SWEEP_INTERVAL_SECONDS
```

Plus `ensure_files_sweep_job(db)` (same file — the
`ensure_sweep_job` shape; 030's dedup index makes it idempotent), and
the one-line call in `workers/job_runner.py::run_once` beside 030's
ensure (decision 7). Batch pass 1 (e.g. 100 files per run) so a huge
backlog cannot blow the handler timeout; the handler is idempotent —
re-running after a crash re-deletes best-effort and moves on
(at-least-once, 030's contract).

**Verify**: `uv run python -m workers.job_runner --once` → exits 0,
log shows `files.sweep_deleted` ensured and executed; registry check
command lists both `jobs.sweep_terminal` and `files.sweep_deleted`.

### Step 8: Wire nothing else — re-read the out-of-scope list

Explicit checkpoint: no migration was added (`uv run alembic check`
still clean), `processing_status` is written only as the constant
`'ready'`, no `FileReference` writes exist, and
`services/skills/documents/` is untouched.

**Verify**: `git status` — changed paths are exactly the in-scope list;
`uv run alembic check` → no pending operations.

### Step 9: Tests

`tests/services/files/` additions (DB-gated, `pytestmark =
pytest.mark.asyncio`, provider reset via
`tests/support/storage.py::reset_storage_provider_cache`) — the
invariants each module pins:

- `test_create_file_upload.py`: unknown MIME and MIME↔extension
  mismatch → `AppValidationError`; size over category cap rejected;
  dedup fast path returns `deduplicated=True` with the existing file and
  persists nothing; `allow_duplicate_content=True` bypasses it;
  soft-limit flag set when usage would exceed 10 GiB (never blocks);
  read_only membership denied; `FileUpload` row shape (final object key,
  expiry).
- `test_confirm_file_upload.py`: happy path creates
  `File`+`FileRevision` with mirrors consistent and
  `processing_status='ready'`; server-computed hash wins over a wrong
  declared hash; stat-vs-token size/content-type mismatch rejects
  (`validate_stored_object`); double-confirm is idempotent (no second
  revision); token from another workspace/actor rejected; replace flow
  appends `revision_kind='replace'` and bumps `revision_number` under
  the lock; audit CREATE row written with `resource_type="file"`.
- `test_edit_file.py`: edit appends an `edit` revision with new blob
  key and updates mirrors; stale `expected_current_revision_id` →
  `ConflictError` carrying `current_revision_id`; non-editable category
  (pdf) rejected; oversized content rejected; audit UPDATE row.
- `test_restore_file.py`: restore appends (`restore`,
  `restored_from_revision_id` set, `object_key` shared with source —
  decision 5), never rewrites history (revision count strictly grows);
  stale expectation → 409; restoring the current revision rejected.
- `test_delete_and_purge_file.py`: soft delete hides the file from
  `list_files` but leaves rows + blobs; purge requires MANAGER (member
  → denied), deletes every distinct blob including shared restore keys
  exactly once and the markdown key when present, hard-deletes with
  cascade; audit rows for both, purge flagged.
- `test_files_usage.py`: usage sums distinct object keys (a restore
  does not double-count); deleted files drop out only after hard
  delete... pin whichever Step 5 implements (soft-deleted files still
  hold blobs — they MUST still count; assert that).
- `test_sweep_deleted_files.py`: file soft-deleted 31 d ago is
  hard-deleted with blobs gone (local provider assertions), 29 d
  survives; abandoned upload past expiry removed with its staged blob,
  consumed/unexpired uploads kept; handler re-enqueues itself;
  `ensure_files_sweep_job` idempotent.

`tests/routes/files/test_files_routes.py`: route-level pass over
list/get/download/edit/delete happy paths + one RBAC denial per gate
tier + 409 shape (problem+json `status == 409`) — the contract the 035
UI codes against.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/files tests/routes/files -q`
→ all pass; without the env var they skip; neighbor regression command
(Commands table) green.

### Step 10: Governance bookkeeping

Flip the shipped cells in `docs/architecture/governance.md`:
§1 "Upload/edit/delete files (031–032)" and "Hard-delete / purge files
(032)" → `*(enforced today: 032, services/files access gates)*`;
§3 Files row soft/hard/cascade/audit cells → `[implemented: plan
031/032]` — EXCEPT the Export cell, which stays
`[default — confirm at review]` with a note "single-file signed
downloads shipped in 032; batch export unplanned"; §4 per-workspace
storage row → `[implemented: plan 032 — counter + soft flag, no hard
enforcement]`.

**Verify**: `git diff docs/architecture/governance.md` touches exactly
those cells.

## Test plan

Covered by Step 9 (~30–35 tests). The pinned invariants: **the stored
hash is server-computed**, **optimistic concurrency actually conflicts**
(two writers cannot both win), **history only grows** (edit/restore
append; nothing rewrites), **deletion is symmetric and two-stage**
(soft keeps blobs; sweep/purge remove blobs AND rows together, shared
restore keys handled once), **RBAC tiers hold** (read_only denied write,
member denied purge), and **every mutation leaves an audit row that
survives the file**.

## Done criteria

- [ ] `uv run ruff check .` exits 0; `uv run alembic check` clean (no
      migration added by this plan)
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/files
      tests/routes/files -q` exits 0
- [ ] `uv run pytest tests/services/skills tests/services/assets
      tests/services/jobs -q` green with zero edits under those trees
      (except the one-word `AssetKind` addition)
- [ ] `/api/v1/files` exposes exactly the twelve Step 6 routes; every
      handler delegates to a single service op
- [ ] `files.sweep_deleted` registered; `uv run python -m
      workers.job_runner --once` ensures and runs it
- [ ] No `HTTPException` raised anywhere under `services/files/` or
      `routes/files/` (grep); only `core/exceptions` types
- [ ] No plan-number references in implementation code
- [ ] `docs/architecture/governance.md` cells updated per Step 10
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row for 032 updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Plan 031 has not been implemented** (no `models/files.py` /
  `services/files/contract.py`) — hard dependency, nothing here can
  start.
- **Plan 030 has not been implemented** when you reach Step 7 (no
  `services/jobs/registry.py` / `@job_handler`): Steps 1–6 and 8–9 can
  land, but the sweeper cannot — report and either hold the plan open or
  split, per operator instruction. Do NOT ship soft delete without a
  recorded path to hard deletion.
- 031's landed schema differs from the "[after 031]" summary (column
  names, staging-table shape, key builders) — reconcile against 031's
  actual code first.
- 030's landed `enqueue_job`/`job_handler` signatures differ from the
  "[after 030]" summary.
- `AssetKind` or the assets token module has changed shape since
  `0cbbb39` (decision 1 assumed it).
- The skills document pipeline (`services/skills/documents/`) has moved
  or been refactored — 033's reuse contract may already be in flight;
  coordinate before touching shared helpers.
- A `routes/files/` package or any `services/files/*_file*.py` operation
  already exists.
- You feel the need to add a migration, write `processing_status`
  transitions, create `FileReference` rows, or touch the converter —
  031/033/034 scope leaking in.

## Maintenance notes

- **Consumers** (do not implement): 033 replaces decision 11's constant
  `'ready'` with pending+enqueue for ingestible types inside
  `confirm_file_upload.py` — keep that assignment a single obvious
  statement; 034's agent tools call `edit_file`/upload ops with
  `created_by_agent_id` provenance (the ops currently hardcode
  `created_by_user_id`; 034 adds an actor-provenance parameter rather
  than a second code path); 035 codes against the Step 6 route
  contract and Step 9's 409 shape; 036 attaches uploads to
  conversations via `FileReference`; 044 reads `file_revision_id` +
  `markdown_object_key`; 050 pins revisions via references.
- **The dedup fast path is advisory.** It trusts a client-declared hash
  only to *skip* an upload, never to record state; the authoritative
  hash is always confirm-computed (decision 2). Reviewers should reject
  any change that persists the declared hash.
- **Blob deletion is deliberately best-effort + idempotent** (matching
  the skills pattern): a failed provider delete logs and proceeds; the
  sweep's next pass or a re-run purge retries. Never let a storage error
  strand the DB in a half-deleted state that blocks the row delete.
- **Quota graduation**: when the 10 GiB soft limit becomes hard
  (governance §4 "enforcement second"), the seam is Step 3's quota
  check — flip flag-to-error there and nowhere else, and update
  governance §4 in the same PR.
- **Replace-vs-category**: Step 3 allows MIME changes within a category
  on replace. If a future plan needs cross-category replace (image →
  pdf), it must also migrate `File.category` consumers (035 icons, 036
  gating) — treat as a schema-semantics change, not a validation tweak.
- Reviewers should scrutinize: the confirm lock ordering (FileUpload
  lookup → File lock → revision insert; deadlock-free because all
  writers lock `File` first), idempotent double-confirm, the
  distinct-keys set on purge/sweep (restore-shared blobs), and that
  `routes/files/get_files_usage.py` registers before the `/{file_id}`
  routes.
