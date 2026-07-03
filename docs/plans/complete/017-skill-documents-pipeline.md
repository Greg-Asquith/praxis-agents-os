# Plan 017: Build the skill document upload and markdown-conversion pipeline

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat ccb721b..HEAD -- apps/api/services/assets/ apps/api/services/storage/ apps/api/core/settings/files.py apps/api/models/skills.py apps/api/routes/storage/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: docs/plans/complete/016-skills-backend-crud.md
- **Category**: direction (feature foundation)
- **Planned at**: commit `ccb721b`, 2026-07-01

## Why this matters

Skills carry reference documents (PDFs, Word docs, plain text) that agents read
on demand — level 3 of progressive disclosure. **Product decision: Praxis owns
these files in its own provider-neutral storage and converts them to markdown
itself.** We do not use model providers' native file APIs, so documents work
identically across Anthropic/OpenAI/Google/Azure and stay under our
workspace/audit controls. This plan builds the upload → convert → manifest
pipeline; plan 018 gives agents a tool to read the converted markdown.

Storing both the original and a converted markdown copy follows the design
already written into the model: the agent reads markdown for text context, the
original remains available for download and future sandbox processing.

## Current state

- `apps/api/models/skills.py:46-55` — the manifest column exists and documents
  the intended shape:

  ```python
  # Progressive Discovery Documentation (Level 3 - loaded as needed from Cloud Bucket provider)
  # Keys are semantic names, values contain both original + markdown paths
  # Example: {
  #   "quick_start": {"original": "QUICKSTART.pdf", "markdown": "QUICKSTART.md"},
  #   "api_reference": {"original": "REFERENCE.docx", "markdown": "REFERENCE.md"}
  # }
  documentation_refs = Column(JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb"))
  ```

  The model docstring also fixes the path convention:
  `{PRIVATE_BUCKET}/workspaces/{workspace_id}/skills/{skill_id}/`.
- **Storage foundation** (plans 002/003, already landed):
  - `services/storage/domain.py` — `StorageBucket.PRIVATE`, frozen
    `StorageObjectRef{bucket, key}`, `StoredObject`, `SignedUpload` (PUT),
    `SignedDownload` (GET), `make_storage_object_ref(bucket, key)`.
  - `services/storage/provider.py` — `StorageProvider` protocol:
    `put_object`, `get_object`, `stat_object`, `delete_object`,
    `create_signed_upload(ref, *, content_type, expires_in)`,
    `create_signed_download(ref, *, expires_in, force_download=False, filename=None)`.
  - `services/storage/factory.py::get_storage_provider()` — singleton selected
    by `settings.STORAGE_PROVIDER` (`local_fs`/`gcs`/`s3`/`azure_blob`).
  - `services/storage/paths.py` — `validate_object_key`, `safe_filename`,
    `unique_object_key`.
  - `services/storage/errors.py` — `StorageNotFoundError`,
    `StorageValidationError`, etc.
- **Two-phase signed upload exemplar** (plan 004, already landed) — copy this
  flow: `services/assets/create_user_avatar_upload.py` validates declared
  metadata, builds a ref, calls `provider.create_signed_upload(ref,
  content_type=..., expires_in=timedelta(minutes=10))`, mints a JWT grant via
  `services/assets/tokens.py::create_asset_upload_token`, returns an
  `AssetUploadGrant{upload, upload_token, max_size_bytes, expires_at}`. The
  confirm step (`confirm_user_avatar_upload.py`) verifies the token, calls
  `provider.stat_object(ref)`, and validates content type + size before
  mutating the DB.
- `services/assets/domain.py:15-19` — the token payload's `kind` enum:

  ```python
  class AssetKind(StrEnum):
      """Application-managed public asset categories."""

      USER_AVATAR = "user_avatar"
      WORKSPACE_ICON = "workspace_icon"
  ```

  `AssetUploadTokenPayload` already carries `workspace_id`, `bucket:
  StorageBucket`, `object_key`, `content_type`, `max_size_bytes` — it supports
  private-bucket grants without change.
- `core/settings/files.py:49-54, 83-86` — existing limits to reuse:

  ```python
  MAX_FILE_SIZE_DOCUMENT: int = Field(default=52428800, ...)  # 50MB
  ALLOWED_DOCUMENT_TYPES: str = Field(
      default="application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown", ...)
  ```

- For local dev, a generic proxy PUT exists: `routes/storage/upload_object.py`
  (`PUT /storage/upload/{bucket}/{object_key:path}`), which is what
  `SignedUpload.url` points at under `local_fs`.
- **No markdown-conversion dependency exists** in `apps/api/pyproject.toml`,
  and there is no content-byte sniffing anywhere — validation today is
  declared-metadata + post-upload `stat_object` re-check. Keep that model.
- Plan 016 (dependency) created `services/skills/` with `schemas.py`,
  `utils.py::get_skill_for_workspace`, `require_skill_write_access`, and
  `routes/skills/`.

### Repo conventions that apply

- One route operation per file; one service operation per file; helpers in the
  service package's `utils.py` (see plan-016 exemplars).
- Audit mutations with `record_workspace_audit_event` (`AuditAction.UPDATE`,
  `AuditResourceType.SKILL` — added by plan 016).
- Errors through `core/exceptions` types; storage errors already subclass
  `IntegrationError` and render as problem+json.

## Commands you will need

| Purpose   | Command (run from `apps/api`)          | Expected on success |
|-----------|----------------------------------------|---------------------|
| Add dependency | `uv add "markitdown[pdf,docx,pptx,xlsx]"` | exit 0, lockfile updated |
| Install   | `uv sync`                              | exit 0              |
| Lint      | `uv run ruff check .`                  | exit 0              |
| Tests     | `uv run pytest tests/routes/skills tests/services/skills -q` | all pass |
| Migration sanity | `uv run alembic check`          | no new operations   |

## Suggested executor toolkit

- `docs/pydantic-ai/13-advanced-and-ecosystem.md` — background only; not needed
  to execute.
- MarkItDown API (from its README): `MarkItDown().convert_stream(io.BytesIO(data), file_extension=".pdf")`
  returns an object with a `.text_content` (or `.markdown`) attribute. Verify
  the exact attribute against the installed version in Step 3 before relying
  on it.

## Scope

**In scope**:

- `apps/api/pyproject.toml` + `uv.lock` (add `markitdown` extra deps)
- `apps/api/core/settings/files.py` (two new settings, additive)
- `apps/api/services/assets/domain.py` (add `SKILL_DOCUMENT` to `AssetKind` —
  one line)
- `apps/api/services/skills/documents/__init__.py`, `domain.py`, `utils.py`,
  `create_document_upload.py`, `confirm_document_upload.py`,
  `list_documents.py`, `get_document_markdown.py`,
  `create_document_download.py`, `delete_document.py` (create)
- `apps/api/routes/skills/` — six new route operation files + registration in
  `routes/skills/__init__.py`
- `apps/api/tests/services/skills/test_skill_documents.py` (create)
- `apps/api/tests/routes/skills/test_skill_document_routes.py` (create)

**Out of scope** (do NOT touch):

- `services/storage/*` — the provider contract is frozen; build on top of it.
- `services/assets/*` other than the one-line `AssetKind` addition — avatar and
  icon flows must not change behavior.
- `models/skills.py` — the JSONB column is already right.
- Any runtime/tool consumption of the manifest — plan 018.
- Background/async job infrastructure — conversion runs in-request via a
  thread for now (see maintenance notes).

## Git workflow

- Branch: `advisor/017-skill-documents-pipeline`
- Commit style: `API - Add Skill Document Pipeline`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the dependency and settings

1. `uv add "markitdown[pdf,docx,pptx,xlsx]"` from `apps/api`.
2. In `core/settings/files.py`, add (following the existing Field style):
   - `MAX_SKILL_DOCUMENTS_PER_SKILL: int = Field(default=20, ge=1, le=100, description="Max documents per skill")`
   - `MAX_SKILL_DOC_MARKDOWN_BYTES: int = Field(default=2097152, ge=65536, le=10485760, description="Max size of converted skill-document markdown (2MB)")`

**Verify**: `uv run python -c "from markitdown import MarkItDown; print('ok')"`
→ prints `ok`. `uv run ruff check .` → exit 0.

### Step 2: Domain contracts — `services/skills/documents/domain.py`

- `SKILL_DOC_NAME_PATTERN = r"^[a-z0-9]+(_[a-z0-9]+)*$"` — snake_case semantic
  names, max 64, matching the model docstring examples (`quick_start`,
  `api_reference`).
- `SkillDocumentEntry` (Pydantic): the manifest value. Fields:
  `original: str` (object key), `markdown: str | None` (object key),
  `filename: str`, `content_type: str`, `size_bytes: int`,
  `markdown_size_bytes: int | None`, `status: Literal["ready", "failed"]`,
  `error: str | None = None`, `updated_at: datetime`. Keep the `original` /
  `markdown` key names from the model docstring.
- `SkillDocumentUploadRequest`: `document_name` (pattern above) +
  `filename`, `content_type`, `size_bytes` (copy the field rules of
  `services/assets/domain.py::AssetUploadRequest`).
- `SkillDocumentConfirmRequest`: `upload_token` (copy `AssetConfirmRequest`).
- `SkillDocumentRead` / `SkillDocumentsListResponse`: `name` + the entry
  fields, minus raw object keys if you prefer — but keep keys included; they
  are workspace-internal, not secrets.
- `SkillDocumentMarkdownResponse`: `name: str`, `content: str`,
  `truncated: bool = False`.

**Verify**: `uv run ruff check .` → exit 0.

### Step 3: Conversion helper — `services/skills/documents/utils.py`

- `skill_doc_prefix(workspace_id, skill_id, document_name) -> str` returning
  `workspaces/{workspace_id}/skills/{skill_id}/docs/{document_name}` (the
  model-docstring path convention).
- `original_ref(...)` / `markdown_ref_for_original(...)` building
  **PRIVATE**-bucket refs under an upload-scoped directory:
  `.../uploads/{upload_id}/original/{safe_filename}` and
  `.../uploads/{upload_id}/converted.md`. The upload id keeps unconfirmed
  replacements from overwriting the currently referenced objects, and the
  filename segment preserves the original download name after sanitization.
- `convert_document_to_markdown(data: bytes, *, content_type: str, filename: str) -> str`:
  - `text/plain` and `text/markdown`: decode UTF-8 (`errors="replace"`) and
    return as-is — no conversion.
  - Otherwise run MarkItDown **in a worker thread** (it is synchronous):
    `await asyncio.to_thread(_convert_sync, data, extension)`. Inside
    `_convert_sync`, call `MarkItDown().convert_stream(io.BytesIO(data), file_extension=ext)`
    and return its markdown text attribute. First confirm the attribute name
    against the installed version (`python -c "import inspect, markitdown; ..."`
    or read the package) — use whatever the installed version exposes
    (`.text_content` on current releases).
  - Enforce `settings.MAX_SKILL_DOC_MARKDOWN_BYTES` on the UTF-8-encoded
    result: if exceeded, truncate at a character boundary and append
    `\n\n[Truncated: document exceeds the converted size limit.]`.
  - Wrap conversion exceptions and return/raise a typed error the confirm step
    records as `status="failed"` (do not 500 the request for a bad PDF).
- `validate_document_upload(payload, *, existing_manifest)` — enforce
  `ALLOWED_DOCUMENT_TYPES`, `MAX_FILE_SIZE_DOCUMENT`,
  `MAX_SKILL_DOCUMENTS_PER_SKILL` (adding a new name when at the cap → 400;
  replacing an existing name is allowed), and the document-name pattern.

**Verify**: `uv run ruff check .` → exit 0, plus the Step-7 unit tests for this
helper.

### Step 4: Upload grant + confirm services

- `create_document_upload.py` —
  `create_skill_document_upload(db, *, actor, workspace, membership, skill_id, payload) -> AssetUploadGrant`:
  require write access (plan-016 helper), load the skill via
  `get_skill_for_workspace`, validate (Step 3), build the original ref, call
  `provider.create_signed_upload(ref, content_type=..., expires_in=timedelta(minutes=10))`,
  mint the grant token with `create_asset_upload_token(kind=AssetKind.SKILL_DOCUMENT,
  actor_user_id=actor.id, workspace_id=workspace.id, ref=ref, content_type=...,
  max_size_bytes=settings.MAX_FILE_SIZE_DOCUMENT)`. Read
  `services/assets/tokens.py` first and pass exactly the kwargs it accepts —
  if it cannot carry `skill_id`/`document_name`, encode them in the object key
  (they already are, via the path convention) and re-derive them at confirm
  time by parsing the key; add a small `parse_skill_doc_key` helper for that.
- `confirm_document_upload.py` —
  `confirm_skill_document_upload(db, *, request, actor, workspace, membership, skill_id, payload) -> SkillDocumentRead`:
  1. Verify the token (`verify_asset_upload_token`), check
     `kind == SKILL_DOCUMENT`, `workspace_id` matches, actor matches, and the
     object key belongs to this skill's prefix.
  2. `stored = await provider.stat_object(ref)` → 400 if missing; validate
     size/content-type against the token exactly the way
     `confirm_user_avatar_upload.py` does (reuse
     `services/assets/utils.py::validate_stored_object` if it is
     bucket-agnostic — read it first; otherwise write a private-bucket
     equivalent in the skills documents `utils.py`).
  3. `data = await provider.get_object(ref)`; run
     `convert_document_to_markdown`; on success `put_object` the markdown beside
     the uploaded original with `content_type="text/markdown"`; on conversion
     failure record `status="failed"` with the error message and no markdown key.
  4. Update the manifest. **JSONB mutation gotcha**: SQLAlchemy does not track
     in-place dict mutation. Always reassign:
     `skill.documentation_refs = {**(skill.documentation_refs or {}), name: entry.model_dump(mode="json")}`.
  5. Best-effort delete any previously-stored objects for a replaced document
     whose manifest keys changed — model on
     `best_effort_delete_public_object` in `services/assets/utils.py`.
  6. Audit `AuditAction.UPDATE` / `AuditResourceType.SKILL` with
     `details={"document": name, "action": "upload", "status": entry.status}`.

**Verify**: `uv run ruff check .` → exit 0.

### Step 5: Read + delete services

- `list_documents.py` — parse the manifest into `SkillDocumentsListResponse`
  (tolerate legacy/malformed entries by skipping them with a log warning).
- `get_document_markdown.py` — 404 if the name is missing or `status !=
  "ready"`; `provider.get_object(entry.markdown)` → decode → return
  `SkillDocumentMarkdownResponse`. Map `StorageNotFoundError` to a 404
  `NotFoundError` (manifest/storage drift).
- `create_document_download.py` — return
  `provider.create_signed_download(original_ref, expires_in=timedelta(minutes=10), force_download=True, filename=entry.filename)`.
- `delete_document.py` — write access required; remove the manifest entry
  (reassign the dict), best-effort delete both objects, audit `UPDATE` with
  `details={"document": name, "action": "delete"}`.

**Verify**: `uv run ruff check .` → exit 0.

### Step 6: Routes

Six new operation files in `routes/skills/`, registered in
`routes/skills/__init__.py` after the CRUD routes:

| Route | Handler file | Access |
|---|---|---|
| `POST /skills/{skill_id}/documents/upload` | `create_document_upload.py` | write |
| `POST /skills/{skill_id}/documents/confirm` | `confirm_document_upload.py` | write |
| `GET /skills/{skill_id}/documents` | `list_documents.py` | read |
| `GET /skills/{skill_id}/documents/{document_name}/markdown` | `get_document_markdown.py` | read |
| `GET /skills/{skill_id}/documents/{document_name}/download` | `create_document_download.py` | read |
| `DELETE /skills/{skill_id}/documents/{document_name}` | `delete_document.py` | write |

Same dependency-injection shape as every other route (see plan 016 excerpt).

**Verify**:
`uv run python -c "from main import app; print(sorted({r.path for r in app.routes if 'documents' in r.path}))"`
→ prints the six paths.

### Step 7: Tests

- `tests/services/skills/test_skill_documents.py`:
  - `convert_document_to_markdown` passthrough for `text/markdown` and
    `text/plain`; truncation at `MAX_SKILL_DOC_MARKDOWN_BYTES` (use a
    settings override fixture — see `tests/support/settings.py`).
  - One real conversion through MarkItDown using a tiny generated `.docx`
    or `.html`-free path — if generating a docx in-test is awkward, convert a
    small PDF fixture; if neither is practical without new dev deps, unit-test
    `_convert_sync` with `text/plain` fallback plus a mocked MarkItDown and
    note it. Do not add heavyweight test fixtures.
  - Manifest validation: doc cap, bad names, disallowed content type.
- `tests/routes/skills/test_skill_document_routes.py` — with
  `STORAGE_PROVIDER=local_fs` (model the provider/test wiring on
  `tests/routes/auth/test_avatar_assets.py`, which exercises the same
  grant → PUT (local proxy route) → confirm loop):
  - full happy path for a `text/markdown` upload: grant → direct PUT →
    confirm → manifest entry `status == "ready"` → GET markdown returns the
    content → download returns a signed URL → delete removes the entry.
  - confirm with a token for a different skill/workspace → 4xx.
  - upload beyond `MAX_SKILL_DOCUMENTS_PER_SKILL` → 400.
  - markdown fetch for `status == "failed"` entry → 404.

**Verify**: `uv run pytest tests/routes/skills tests/services/skills -q` → all
pass.

## Test plan

Covered by Step 7 — the highest-risk surfaces are the token/workspace boundary
on confirm, the JSONB reassignment (a silent-no-op bug if done in place), and
conversion failure handling. Each has a named test above.

## Done criteria

ALL must hold (run from `apps/api`):

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no new operations
- [ ] `uv run pytest tests/routes/skills tests/services/skills -q` exits 0
- [ ] `grep -n "SKILL_DOCUMENT" services/assets/domain.py` returns one match
- [ ] `grep -rn "markitdown" pyproject.toml` returns a match
- [ ] `grep -rn "documentation_refs\[" services/skills/` returns **no** matches
      (no in-place JSONB mutation; assignments only)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `uv add "markitdown[pdf,docx,pptx,xlsx]"` fails to resolve against the
  existing lock (dependency conflict) — report the conflict, do not force.
- The installed MarkItDown version exposes neither `convert_stream` nor a
  documented equivalent — report its actual API surface.
- `services/assets/tokens.py` hard-codes public-bucket or avatar/icon
  assumptions that cannot carry a private-bucket skill-document grant without
  modifying avatar/icon behavior — report; do not refactor the assets package.
- The landed plan-016 `services/skills/` package is missing or no longer exposes
  `get_skill_for_workspace` / `require_skill_write_access`.
- Converting a legitimate small PDF takes >30s in tests (thread-pool conversion
  is the wrong architecture sooner than expected).

## Maintenance notes

- **Reuse contract (roadmap requirement — Phase 3 / plan 033).**
  `convert_document_to_markdown` / `_convert_sync` and the
  `original_ref`/`markdown_ref_for_original` helpers must be structured as a standalone,
  storage-ref-agnostic conversion module so plan 033 (background
  extraction→markdown jobs over Files) can call the same code path. Do not
  couple conversion to the skills manifest: keep the manifest-write in the
  confirm service and the conversion in a reusable helper. The roadmap is
  explicit that 033 must NOT build a second converter
  (`000_MASTER_ROADMAP.md` §Phase 2 note and plan 033's scope).
- **Conversion runs in-request** (`asyncio.to_thread`). If real-world uploads
  are large/slow, move conversion to a background job keyed off the manifest
  `status` (add `"converting"` to the status literal then). This was
  deliberately deferred — and dovetails with the 033 reuse contract above.
- **Converted markdown is untrusted user content.** Plan 018 must present it to
  agents as data, not instructions (it wraps tool returns accordingly). Any
  future indexing/embedding of these docs must treat them the same way.
- `ALLOWED_DOCUMENT_TYPES` currently gates to pdf/docx/txt/md. Extending to
  pptx/xlsx/html is a settings change; MarkItDown already handles them via the
  extras installed here.
- Reviewers should scrutinize: the confirm-token boundary checks (skill prefix,
  workspace, kind), and that no route leaks a private-bucket object without a
  signed URL.
- Deferred: content-byte sniffing (magic numbers). Today's declared-type +
  post-upload `stat_object` model matches avatars; revisit if abuse shows up.
