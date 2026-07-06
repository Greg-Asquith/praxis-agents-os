# Plan 002: Harden the files vertical (bugs, streaming hash, download audit)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/improvements/README.md`.
>
> **Drift check (run first)**: the files vertical was UNCOMMITTED working-tree
> code when this plan was written at commit `a0eea1c` (untracked
> `apps/api/routes/files/`, `apps/api/services/files/*.py` operation files,
> plus modified `apps/api/services/files/utils.py`). Before starting, open
> each file cited in "Current state" and confirm the excerpts match. If the
> vertical has since been committed and refactored so an excerpt no longer
> matches, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches upload confirm semantics and the storage provider protocol)
- **Depends on**: none (001 recommended first so `make check` covers this work)
- **Category**: bug / security / perf
- **Planned at**: commit `a0eea1c` + uncommitted files vertical, 2026-07-06

## Why this matters

The freshly written workspace-files vertical has four confirmed defects and
two hardening gaps. Two defects corrupt user intent or 500 under normal
races (dedup overriding an explicit replace; confirming a replace after the
target was soft-deleted). One is a concurrency hole (double-confirm). One
makes search behave wrongly (`%`/`_` treated as wildcards). The hash
computation buffers entire files in memory (video files default to 100 MB,
configurable to 500 MB — concurrent confirms can spike the API by gigabytes).
And file-content egress (download grants) writes no audit event while every
mutation does, which contradicts the product's audit-first positioning.
Fixing all of this now, while the code is fresh, is far cheaper than after
plans 033–036 build on top of it.

## Current state

Relevant files (all under `apps/api/`):

- `services/files/create_file_upload.py` — upload grant + dedup; contains bug 1
- `services/files/confirm_file_upload.py` — confirm + revision append; bugs 2 & 3, perf issue
- `services/files/list_files.py` — listing/search; bug 4
- `services/files/create_file_download.py` — signed download grant; missing audit
- `services/files/domain.py` — request/response models (`FileDownloadRequest` ~line 118)
- `services/files/utils.py` — `sha256_hex`, `get_file_for_workspace(include_deleted=, for_update=)`, `require_file_write_access`
- `services/storage/provider.py` — `StorageProvider` Protocol (`get_object` returns `bytes`, line 31)
- `services/storage/providers/local.py` — local provider (`get_object` at line 117 does `path.read_bytes` via thread)
- `services/storage/providers/` — `gcs.py` / `s3.py` / `azure.py` cloud providers (optional extras; SDKs may not be installed locally)
- `routes/files/create_file_download.py` — download route
- `tests/services/files/test_file_upload_lifecycle.py` — the service-level test pattern to extend
- `tests/routes/files/test_files_routes.py` — the route-level test pattern

**Bug 1 — dedup overrides explicit replace.** `create_file_upload.py:54-74`:

```python
replace_file: File | None = None
if payload.file_id is not None:
    replace_file = await get_file_for_workspace(...)
    ...
if payload.content_hash and not payload.allow_duplicate_content:
    dedup_file = await _find_file_by_current_hash(...)
    if dedup_file is not None:
        return FileUploadResult(deduplicated=True, file=file_to_read(dedup_file))
```

The dedup short-circuit runs even when `payload.file_id` (an explicit replace)
is set, and `_find_file_by_current_hash` (lines 138-151, no ordering) may
return a *different* file — the caller gets pointed at an unrelated file and
the replacement never happens.

**Bug 2 — soft-deleted replace target → 500.** `confirm_file_upload.py:84-108`:

```python
existing_file = await db.scalar(
    select(File)
    .where(
        File.id == file_upload.file_id,
        File.workspace_id == workspace.id,
        File.deleted.is_(False),
    )
    .with_for_update()
)
is_new_file = existing_file is None
if is_new_file:
    file = File(
        id=file_upload.file_id,
        ...
```

If the replace target was soft-deleted between grant and confirm (the grant
window is `FILES_UPLOAD_EXPIRY_HOURS` — hours), the filtered lookup returns
`None`, and the insert reuses the soft-deleted row's primary key →
`IntegrityError` → unhandled 500. (`models/base.py` `soft_delete` only sets
`deleted = True`; the row persists.)

**Bug 3 — confirm not concurrency-safe.** `confirm_file_upload.py:52-68`: the
`FileUpload` row is selected **without** `with_for_update`, then checked
`consumed_at is not None` (idempotent return) — a check-then-act. Two
concurrent confirms of the same token both pass the check; the loser collides
on `FileRevision.id = file_upload.revision_id` (PK) → 500 instead of the
idempotent result.

**Bug 4 — LIKE wildcards unescaped.** `list_files.py:36-39`:

```python
if search:
    pattern = f"%{search.strip()}%"
    stmt = stmt.where(File.name.ilike(pattern))
    count_stmt = count_stmt.where(File.name.ilike(pattern))
```

**Perf — whole-file buffering.** `confirm_file_upload.py:80-81`:

```python
data = await provider.get_object(ref)
content_hash = sha256_hex(data)
```

Size ceilings (`core/settings/files.py`): documents 50 MB, agent files and
video 100 MB default / 500 MB max.

**Audit gap.** `create_file_download.py` mints a signed download with no
`record_workspace_audit_event` call and takes no `request`/`actor` params.
For the call pattern, copy `confirm_file_upload.py:152-166`
(`record_workspace_audit_event(db, request=request, workspace_id=..., action=...,
resource_type=AuditResourceType.FILE, resource_id=..., actor=..., details={...})`).
`AuditAction.READ` already exists (`services/audit_events/enums.py:17`).

**Inline-serving default.** `services/files/domain.py`:

```python
class FileDownloadRequest(BaseModel):
    """Signed download request for a file revision."""

    revision_id: UUID | None = None
    force_download: bool = False
```

Default-inline serving of user bytes is a latent stored-XSS surface (currently
mitigated by `nosniff` + CSP headers and the non-standard `application/html`
MIME in `services/files/contract.py:71`). Flip the default to attachment.

Repo conventions to match: one operation per service file; typed exceptions
from `core/exceptions` (use `ConflictError` from `core/exceptions/general.py:91`
— see its use in `services/files/edit_file.py:51`); terse single-line comments;
DB tests gated on `TEST_DATABASE_URL` using `tests/factories/` +
`tests/support/` helpers exactly as `test_file_upload_lifecycle.py` does.

## Commands you will need

| Purpose | Command (from `apps/api/`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Files tests | `TEST_DATABASE_URL=<url> uv run pytest tests/services/files tests/routes/files -q` | all pass |
| Full suite | `TEST_DATABASE_URL=<url> uv run pytest` | all pass |

## Scope

**In scope**:
- `apps/api/services/files/create_file_upload.py`
- `apps/api/services/files/confirm_file_upload.py`
- `apps/api/services/files/list_files.py`
- `apps/api/services/files/create_file_download.py`
- `apps/api/services/files/domain.py` (the `force_download` default only)
- `apps/api/routes/files/create_file_download.py`
- `apps/api/services/storage/provider.py` (add `stream_object`)
- `apps/api/services/storage/providers/local.py`, `gcs.py`, `s3.py`, `azure.py` (implement `stream_object`)
- `apps/api/tests/services/files/test_file_upload_lifecycle.py`
- `apps/api/tests/routes/files/test_files_routes.py`
- `apps/api/tests/services/storage/**` (streaming test for the local provider)

**Out of scope**:
- `services/files/contract.py` — do not remove `application/html`; plan 035
  (files UI) owns the preview story and may revisit it.
- `services/files/edit_file.py`, `restore_file_revision.py`, `purge_file.py`,
  `delete_file.py` — audited clean; do not "improve while you're in there".
- `services/storage/serve_private_object.py` / `utils.py` response streaming —
  a separate latent issue; do not expand into it.
- The skills document pipeline (`services/skills/documents/`) — same download-
  audit gap exists there; record as follow-up, do not fix here.

## Git workflow

- Branch: `advisor/002-files-vertical-hardening`
- Commit per step; message style e.g. `API - Files Confirm Hardening`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Skip dedup when the request is an explicit replace

In `create_file_upload.py`, change the dedup guard (line 67) to:

```python
if payload.file_id is None and payload.content_hash and not payload.allow_duplicate_content:
```

**Verify**: `uv run ruff check .` → exit 0.

### Step 2: Turn the soft-deleted-replace race into a 409

In `confirm_file_upload.py`, after computing `is_new_file` (line 93): when
`is_new_file` is true, check whether a soft-deleted row still owns that id —

```python
if is_new_file:
    deleted_row = await db.scalar(
        select(File.id).where(File.id == file_upload.file_id, File.deleted.is_(True))
    )
    if deleted_row is not None:
        raise ConflictError("File was deleted while the upload was in progress")
```

Import `ConflictError` from `core.exceptions.general`. Do not mark the upload
consumed or delete the staged object here — the exception rolls the request
back, and the existing `files.sweep_deleted` job already purges abandoned
uploads.

**Verify**: `uv run ruff check .` → exit 0.

### Step 3: Lock the FileUpload row in confirm

Add `.with_for_update()` to the `FileUpload` select in
`confirm_file_upload.py:52-58` so concurrent confirms serialize and the loser
takes the existing `consumed_at is not None` idempotent-return path (lines
61-67).

**Verify**: `uv run ruff check .` → exit 0.

### Step 4: Escape LIKE metacharacters in file search

In `list_files.py`, escape user input before building the pattern and pass
`escape` to both queries:

```python
escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
pattern = f"%{escaped}%"
stmt = stmt.where(File.name.ilike(pattern, escape="\\"))
count_stmt = count_stmt.where(File.name.ilike(pattern, escape="\\"))
```

**Verify**: `uv run ruff check .` → exit 0.

### Step 5: Add `stream_object` to the storage contract and hash incrementally

1. In `services/storage/provider.py`, add to the `StorageProvider` Protocol:

   ```python
   def stream_object(self, ref: StorageObjectRef) -> AsyncIterator[bytes]:
       """Yield object bytes in chunks without buffering the whole object."""
       ...
   ```

   (Import `AsyncIterator` from `collections.abc`. Note: an async generator
   method is declared *without* `async def` in a Protocol when it returns
   `AsyncIterator` — match how the codebase types similar generators, or
   declare it `async def stream_object(...) -> AsyncIterator[bytes]` and
   implement with `yield`; pick one shape and use it consistently across all
   providers.)

2. In `providers/local.py`, implement it with genuinely chunked reads
   (1 MiB chunks) using `asyncio.to_thread` around file-handle reads, raising
   the same `StorageNotFoundError` as `get_object` (line 117) when absent.

3. In `providers/gcs.py`, `s3.py`, `azure.py`, implement `stream_object` using
   each SDK's native streaming/chunked download if it is straightforward
   (GCS blob open/read in chunks, S3 `Body.iter_chunks`, Azure
   `download_blob().chunks()`). If a provider's SDK makes this awkward, a
   compliant fallback is acceptable:

   ```python
   async def stream_object(self, ref):
       yield await self.get_object(ref)
   ```

   — no worse than today, and the contract stays uniform.

4. In `confirm_file_upload.py`, replace lines 80-81 with an incremental hash:

   ```python
   hasher = hashlib.sha256()
   async for chunk in provider.stream_object(ref):
       hasher.update(chunk)
   content_hash = hasher.hexdigest()
   ```

   (Either import `hashlib` here or add a small `sha256_hex_stream` helper
   beside `sha256_hex` in `services/files/utils.py` — prefer the helper so the
   hashing convention stays in one place.)

**Verify**: `uv run ruff check .` → exit 0, and
`TEST_DATABASE_URL=<url> uv run pytest tests/services/files -q` → all pass
(the local provider is what tests exercise). Add a local-provider streaming
test (see Test plan).

### Step 6: Audit file download grants

1. Change `services/files/create_file_download.py` to accept
   `request: Request` and `actor: User` (match `confirm_file_upload`'s
   signature style), and after building the grant, record:

   ```python
   await record_workspace_audit_event(
       db,
       request=request,
       workspace_id=workspace.id,
       action=AuditAction.READ,
       resource_type=AuditResourceType.FILE,
       resource_id=file.id,
       actor=actor,
       details={"filename": file.name, "revision_id": str(revision.id)},
   )
   ```

2. Update `routes/files/create_file_download.py` to pass `request` and the
   current user — add `Request` and `CurrentUserDep` following the pattern of
   whichever `routes/files/` operation already passes them (the confirm route
   does).

**Verify**: `TEST_DATABASE_URL=<url> uv run pytest tests/routes/files -q` →
all pass (update any route test that constructs this call).

### Step 7: Default downloads to attachment

In `services/files/domain.py`, change `FileDownloadRequest.force_download`
default from `False` to `True`. Callers wanting inline preview must opt in
explicitly.

**Verify**: `TEST_DATABASE_URL=<url> uv run pytest tests/services/files tests/routes/files -q` → all pass.

## Test plan

Extend `tests/services/files/test_file_upload_lifecycle.py` (match its
existing fixture/factory usage):

- Replace-with-duplicate-content: grant with `file_id=<file A>` and
  `content_hash` equal to file B's hash → result is a grant for file A, NOT
  `deduplicated=True` for file B (regression for Step 1).
- Confirm after soft-delete: grant a replace, soft-delete the file, confirm →
  `ConflictError`, no new `File`/`FileRevision` rows (regression for Step 2).
- Double confirm sequential already exists (idempotent return); add an
  assertion that the `FileUpload` select path still returns the file (Step 3
  is not directly testable without concurrency; the lock is verified by review).
- Search with `%` / `_` in the term matches literally (create files named
  `a%b.txt` and `axb.txt`; search `a%b` must return only the first) (Step 4).
- Download grant writes an `AuditEvent` with `action="read"`,
  `resource_type="file"` (Step 6) — mirror the audit assertions already in
  the file.

New storage test (place beside the existing storage tests under
`tests/services/storage/`): local provider `stream_object` yields the exact
bytes of a stored object in more than one chunk for content larger than the
chunk size, and raises `StorageNotFoundError` for a missing key.

**Verification**: `TEST_DATABASE_URL=<url> uv run pytest tests/services/files tests/routes/files tests/services/storage -q` → all pass, including the new cases.

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `TEST_DATABASE_URL=<url> uv run pytest tests/services/files tests/routes/files tests/services/storage -q` exits 0 with the new tests present
- [ ] `grep -n "payload.file_id is None and payload.content_hash" apps/api/services/files/create_file_upload.py` matches
- [ ] `grep -n "with_for_update" apps/api/services/files/confirm_file_upload.py` shows the FileUpload select locked
- [ ] `grep -rn "get_object(ref)" apps/api/services/files/confirm_file_upload.py` returns no matches (hashing is streamed)
- [ ] `grep -n "record_workspace_audit_event" apps/api/services/files/create_file_download.py` matches
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/improvements/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The files vertical has been committed and refactored such that any excerpt
  in "Current state" no longer matches.
- Product intent turns out to be "dedup should win over replace" (check
  `docs/plans/032-*.md` if present) — Step 1 assumes replace intent wins.
- A cloud provider file (`gcs.py`/`s3.py`/`azure.py`) fails even to lint
  without its SDK installed — report rather than adding the SDK to core deps.
- Any existing test asserts `force_download=False` behavior as a contract —
  that means a consumer already depends on inline serving.

## Maintenance notes

- Plans 033 (background extraction), 034 (agent file tools), 035 (files UI),
  036 (multimodal input) all build on these services — this plan must land
  before or with them, and 035 will likely want a deliberate inline-preview
  path (explicit `force_download=False` for images/PDF only).
- Follow-up (deferred out of this plan): the same download-audit gap exists in
  `services/skills/documents/create_document_download.py` and
  `get_document_markdown.py`; `storage_object_response` in
  `services/storage/utils.py` still buffers whole objects for non-local
  providers if app-proxied serving is ever enabled.
- Reviewers should scrutinize: transaction semantics in Step 2 (no partial
  state on ConflictError) and that `stream_object` implementations don't leak
  file handles/SDK streams on early exit.
