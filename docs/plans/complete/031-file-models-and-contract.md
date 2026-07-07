# Plan 031: File, FileRevision, and FileReference models + the file contract

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G3**: `docs/architecture/governance.md` EXISTS and is DONE
> (written 2026-07-06 at `0cbbb39`, plan 029). This plan cites its sections
> directly — no pre-flight confirmation is needed. If a cited default has
> been flipped since (the note is a living document), the note wins;
> reconcile before coding.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/models/ apps/api/alembic/versions/core/ apps/api/services/files/ apps/api/core/settings/files.py apps/api/tests/factories/ apps/api/tests/services/files/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM (schema + pure policy data only; no routes, no
  storage writes, no runtime changes — but three new core tables and one
  ORM-listener invariant that every later file plan builds on)
- **Depends on**: none hard for code (models + contract stand alone).
  Sequencing: plan 030 is expected to land its `jobs` core migration
  first — this plan's migration number assumes that (see Step 2 and STOP
  conditions). Soft: `docs/architecture/governance.md` (Gate G3, cited
  throughout).
- **Category**: Phase 3 files substrate (roadmap `000_MASTER_ROADMAP.md`
  §4 Phase 3 row 031; donor `DONOR_PORT_ROADMAP.md` §4.3 / §6 row B2)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Three tables plus one staging table.** The dictated shape is `File`
   (logical, workspace-scoped, soft-delete) + immutable `FileRevision`
   (append-only) + non-copying `FileReference` (generic `target_type`).
   This plan adds a fourth, `FileUpload` — a small upload-staging table —
   because the `StorageProvider` protocol has **no list operation**
   (verified `services/storage/provider.py:14-89`: put/get/stat/delete/
   signed only), so plan 032's abandoned-upload expiry job cannot discover
   orphaned blobs by scanning the store; pending uploads must be DB rows.
   The assets pattern gets away with stateless tokens because avatars
   overwrite one fixed key per user (`create_user_avatar_upload.py:33`);
   file revisions use unique per-revision keys, so abandoned grants would
   otherwise leak blobs forever.
2. **Processing-status columns land here, not in 033.** `File` carries
   `processing_status` (`pending/processing/ready/error`),
   `processing_error`, and `processing_attempts` from this migration so
   plan 033 needs no second migration. `server_default 'ready'`: until 033
   ships there is no processor, and a `pending` row that nothing will ever
   process is a lie (AGENTS.md: keep public behavior explicit). Plan 033
   flips confirm-time logic to set `pending` for ingestible types and is
   the only writer of `processing/error`.
3. **Revision immutability is an ORM listener with a derived-column
   whitelist.** A `before_update` listener on `FileRevision` raises unless
   every changed attribute is in
   `{markdown_object_key, markdown_size_bytes}` **and** its previous value
   was `NULL` (set-once). Immutability protects content and provenance;
   extraction output (033) is derived enrichment, not history rewriting.
   This guards the ORM path only — raw `update()` statements bypass it;
   that constraint is recorded in Maintenance notes as a review rule
   rather than a DB trigger (no trigger precedent in this codebase, and
   the only writers are our own services).
4. **Exactly-one-actor provenance is a CHECK constraint**, per the donor
   design (`DONOR_PORT_ROADMAP.md` §4.3): `created_by_user_id` XOR
   `created_by_agent_id` XOR `created_by_system`, enforced as a
   three-way-sum CHECK (Step 2). Style follows the existing constraint
   blocks in `models/agent.py:222-230`.
5. **The file contract is code-level data, not settings.** Categories with
   strict MIME↔extension pairs live in `services/files/contract.py` as
   frozen dataclasses; unknown MIME types and mismatched pairs are
   rejected outright. This resolves gaps-doc §Files Q1 ("which file types
   are v1"): editable-text (txt/md/mdx/csv/json/html), ingestible-document
   (pdf/docx/pptx/xlsx — exactly the installed `markitdown` extras,
   `apps/api/pyproject.toml:15`), image (png/jpeg/webp), video (mp4/mov).
   The `audio` category exists as a reserved enum value but has no accepted
   MIME entry yet. **Size limits stay in settings** — the contract maps each
   category to a `core/settings/files.py` key, per governance §4 ("Upload
   size: existing `core/settings/files.py` keys … *(enforced today)*").
   Plan 031 also normalized the image/video size setting names from
   AI-specific `MAX_FILE_SIZE_AI_IMAGE`/`MAX_FILE_SIZE_AI_VIDEO` to shared
   `MAX_FILE_SIZE_IMAGE`/`MAX_FILE_SIZE_VIDEO`, because these limits now
   apply to first-class files, not only generated AI media.
   Unlike `ALLOWED_DOCUMENT_TYPES`, the pairs are not env-configurable:
   the frontend (035) must mirror them exactly, and a strict contract is
   the point.
6. **Files are workspace-shared in v1** — no user-private flag. Resolves
   gaps-doc §Files Q2; matches governance §1 where "View …files…" is ✓
   for every role including read_only. A privacy flag can be added later
   without unwinding anything; the reverse is not true.
7. **`FileReference` ships as schema only.** No service creates references
   in 031/032 — consumers own creation: 034 (agent tools), 036 (chat
   attachments, resolving gaps-doc §Files Q5), 050 (artifacts).
   `target_type` is generic from day one
   (`conversation/artifact/agent/schedule_run`) with a plain-UUID
   `target_id` (no polymorphic FK; the owning service validates the
   target). `file_revision_id` is nullable: NULL follows the file's
   current revision; a value pins one revision (050 artifacts).
8. **Restore is roll-forward and non-copying at the model level.** A
   `restore` revision must carry `restored_from_revision_id`
   (CHECK-enforced both ways) and may share the source revision's
   `object_key` — safe because revisions are never hard-deleted
   individually, only with their whole file (032 sweeps at file
   granularity), so blob refcounting stays unnecessary (donor §4.3 "one
   storage path scheme … makes blob refcounting unnecessary").
9. **Storage key scheme** is the dictated
   `workspaces/{workspace_id}/files/{file_id}/{revision_id}{ext}` in the
   PRIVATE bucket, built through `validate_object_key`
   (`services/storage/paths.py:14`). Extraction markdown (033) derives
   `.../{revision_id}.extracted.md` — the `.extracted.md` suffix cannot
   collide with a revision key because revision keys end in the revision's
   own single extension.
10. **Gaps-doc questions resolved or deferred**
    (`docs/legacy/ROADMAP_QUESTIONS_GAPS.md` §Files): Q1 v1 types —
    resolved here (decision 5); Q2 private files — resolved here
    (decision 6); Q3 agent durable writes — deferred to 034 per
    governance §2 (external-effect writes default `approval`); Q4 scratch
    TTL/size — 034's to answer (governance §3 scratch row); Q5 chat
    attach-by-default — deferred to 036 (decision 7).

## Why this matters

Every remaining Phase 3–6 vertical stands on these three tables: 032's
upload/edit/restore/delete services, 033's extraction pipeline, 034's
agent file tools and scratch promotion, 035's files UI, 036's multimodal
attachments, 044's KB ingestion (which references `file_revision_id` for
provenance instead of the donor's `KnowledgeSource` triple-bookkeeping),
and 050's artifacts (which ARE FileRevisions). The donor's
logical-file/immutable-revision split is called out in
`DONOR_PORT_ROADMAP.md` §4.3 as "its strongest single idea" — but the
donor enforced immutability by convention and leaked provenance into
nullable columns nobody checked. This plan lands the invariants as
schema: CHECK-enforced actor provenance, CHECK-enforced revision kinds,
listener-enforced immutability, and a strict MIME↔extension contract as
data, so 032+ ship operations, not invariants.

## Current state

All anchors verified at `0cbbb39`. Nothing file-shaped exists in the
database layer; storage and the upload pattern are proven but stateless:

- `apps/api/models/base.py`: `BaseModel` (130-138) = Base + `UUIDMixin`
  (18-21) + `TimestampMixin` (24-30) + `SoftDeleteMixin` (33-115;
  `deleted_at` is indexed at line 37; `_cascade_soft_delete` hook at
  74-78). `CreatedAtMixin` (124-127) is the append-only composition.
- `apps/api/models/__init__.py:13-25` — the model registry; new models
  must be imported here.
- `apps/api/models/agent.py` — the constraint/index house style:
  `CheckConstraint` with a named `IN (...)` list (153-157, 222-230),
  `UniqueConstraint` (231-235), partial `Index` with
  `postgresql_where=text(...)` (236-273).
- Migrations: core head is **`core_0008`**
  (`alembic/versions/core/0008_add_conversation_todos.py:15`). Plan 030
  (written earlier, at `9208c47` when the head was `core_0006`) plans a
  jobs migration it numbers `core_0007`; its own STOP condition forces a
  renumber at execution time — **expected landing: `core_0009`**. This
  plan therefore targets `core_0010` (Step 2), to be re-verified.
  Roadmap decision D5: all roadmap tables go on the **core** branch.
- `apps/api/services/storage/provider.py:14-89` — the `StorageProvider`
  protocol: `put_object` (19), `get_object` (31), `stat_object` (35),
  `delete_object` (39), `create_signed_upload` (43),
  `create_signed_download` (53). **No list/copy operations** (decision 1
  and decision 8 both hang off this).
- `apps/api/services/storage/domain.py`: `StorageBucket` PUBLIC/PRIVATE
  (15-19), frozen `StorageObjectRef` (22-28), `make_storage_object_ref`
  (76). `services/storage/paths.py`: `validate_object_key` (14),
  `safe_filename` (93).
- `apps/api/core/settings/files.py`: `FilesSettingsMixin` with
  `MAX_FILE_SIZE_DOCUMENT` (49-54), `MAX_FILE_SIZE_AGENT_FILE` (67-72),
  `MAX_FILE_SIZE_IMAGE` (73-78), `MAX_FILE_SIZE_VIDEO` (79-84),
  `ALLOWED_IMAGE_TYPES` (87-90), `ALLOWED_DOCUMENT_TYPES` (95-98) —
  governance §4 names these exact keys as the enforced upload limits.
  The mixin composes into `Settings` at `core/settings/__init__.py:21,39`.
- `apps/api/services/skills/documents/utils.py:32-37`
  `_CONTENT_TYPE_EXTENSIONS` — the only MIME↔extension map today,
  private to skills; the file contract generalizes the idea (033 later
  unifies the conversion side).
- `apps/api/services/assets/create_user_avatar_upload.py:19-53` — the
  proven two-phase request pattern 032 will extend; relevant here only as
  the reason `FileUpload` exists (decision 1).
- `apps/api/pyproject.toml:15` — `markitdown[docx,pdf,pptx,xlsx]>=0.1.6`
  pins the ingestible set (decision 5).
- Tests: DB-backed tests gate on `TEST_DATABASE_URL` via `conftest.py`
  fixtures (`db_session` at `tests/conftest.py:167-176`); factories live
  in `tests/factories/` (`build_workspace` at
  `tests/factories/workspaces.py:9`, `build_workspace_membership` at 25).
  No `tests/services/files/` exists yet.
- Governance anchors this plan implements a slice of:
  `docs/architecture/governance.md` §1 (files rows), §3 (Files row: soft
  delete ✓, hard delete 30 d, storage cascade, audit survives), §4
  (upload-size keys row).
- Will exist after other plans (do not assume now): `jobs` table +
  `services/jobs/` (030), file services/routes (032), `files.extract`
  handler and markdown backfill writes (033).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Generate migration | `uv run alembic revision --autogenerate --head core@head --version-path alembic/versions/core -m "add file tables"` | new file under `alembic/versions/core/` |
| Migration sanity | `uv run alembic check` | no pending operations after Step 3 |
| Apply migration | `uv run alembic upgrade heads` | `files`, `file_revisions`, `file_references`, `file_uploads` created |
| Round-trip | `uv run alembic downgrade core@-1 && uv run alembic upgrade heads` | clean both ways |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/files -q` | all pass |
| Contract tests (no DB) | `uv run pytest tests/services/files/test_file_contract.py -q` | all pass without `TEST_DATABASE_URL` |

## Scope

**In scope:**

- `apps/api/models/files.py` (create — `File`, `FileRevision`,
  `FileReference`, `FileUpload`, the immutability listener, and the
  status/kind constant tuples the CHECKs are built from)
- `apps/api/models/__init__.py` (register imports)
- `apps/api/alembic/versions/core/0010_*.py` (create — core branch, D5;
  renumber against the real head, Step 2)
- `apps/api/services/files/` (create — `__init__.py` docstring only,
  `contract.py`, `utils.py` with storage-key builders). **No operations,
  no domain.py** — 032 owns those.
- `apps/api/tests/services/files/` (create — model + contract tests),
  `apps/api/tests/factories/files.py` (create)
- `docs/architecture/governance.md` (Done criteria — mark the schema
  slice of the §3 Files row)

**Out of scope (do NOT touch):**

- HTTP routes, upload/confirm/edit/delete services, audit events, RBAC
  helpers — all plan 032. Files have **no public surface** after this
  plan; per AGENTS.md, that stays documented as pending.
- Job kinds, sweepers, `services/jobs/`, `workers/` — 030/032/033.
- `services/skills/documents/**` — 033 refactors the converter; this
  plan must not pre-empt it.
- New lifecycle settings — the contract reads only
  `core/settings/files.py` limits; 031 normalized the image/video setting
  names for shared file use, and 032 adds the files-lifecycle keys.
- `FileReference` write services (decision 7 — consumers own creation).
- Frontend anything (035 mirrors the contract).

## Git workflow

- Branch: `advisor/031-file-models-and-contract`
- Commit style: `API - File Models & Contract`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: The file contract (`services/files/contract.py`)

Create `services/files/` with an `__init__.py` module docstring noting
that operations arrive with the upload/lifecycle services plan and that
`contract.py`/`utils.py` are importable directly (the service-package
rule reserves `__init__.py` re-exports for operation functions).

`contract.py` defines the policy as data:

```python
class FileCategory(StrEnum):
    EDITABLE_TEXT = "editable_text"
    INGESTIBLE_DOCUMENT = "ingestible_document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"  # reserved; no accepted MIME entries in 031

@dataclass(frozen=True)
class FileContractEntry:
    category: FileCategory
    content_type: str          # normalized, lowercase, no parameters
    extensions: tuple[str, ...]  # dot-prefixed, lowercase; first is canonical
    max_size_setting: str      # name of the settings attribute holding the byte cap
    editable: bool             # text edits via API allowed (032)
    ingestible: bool           # extraction -> markdown applies (033)
```

The catalog (one entry per MIME type — strict pairs, decision 5):

| Category | MIME | Extensions | Size setting | editable | ingestible |
|---|---|---|---|---|---|
| editable_text | `text/plain` | `.txt` | `MAX_FILE_SIZE_DOCUMENT` | ✓ | — |
| editable_text | `text/markdown` | `.md`, `.markdown`, `.mdx` | `MAX_FILE_SIZE_DOCUMENT` | ✓ | — |
| editable_text | `text/csv` | `.csv` | `MAX_FILE_SIZE_DOCUMENT` | ✓ | — |
| editable_text | `application/json` | `.json` | `MAX_FILE_SIZE_DOCUMENT` | ✓ | — |
| editable_text | `text/html` | `.html` | `MAX_FILE_SIZE_DOCUMENT` | ✓ | — |
| ingestible_document | `application/pdf` | `.pdf` | `MAX_FILE_SIZE_DOCUMENT` | — | ✓ |
| ingestible_document | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `.docx` | `MAX_FILE_SIZE_DOCUMENT` | — | ✓ |
| ingestible_document | `application/vnd.openxmlformats-officedocument.presentationml.presentation` | `.pptx` | `MAX_FILE_SIZE_DOCUMENT` | — | ✓ |
| ingestible_document | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | `.xlsx` | `MAX_FILE_SIZE_DOCUMENT` | — | ✓ |
| image | `image/png` | `.png` | `MAX_FILE_SIZE_IMAGE` | — | — |
| image | `image/jpeg` | `.jpg`, `.jpeg` | `MAX_FILE_SIZE_IMAGE` | — | — |
| image | `image/webp` | `.webp` | `MAX_FILE_SIZE_IMAGE` | — | — |
| video | `video/mp4` | `.mp4` | `MAX_FILE_SIZE_VIDEO` | — | — |
| video | `video/mov` | `.mov` | `MAX_FILE_SIZE_VIDEO` | — | — |

Helper functions (all pure; reuse `normalize_content_type` from
`services/assets/utils.py:29` rather than re-implementing):

- `contract_for_content_type(content_type) -> FileContractEntry` — raises
  `AppValidationError` (`core/exceptions/general.py:16`) on unknown types.
- `require_matching_pair(content_type, extension) -> FileContractEntry` —
  the strict pairing gate; raises `AppValidationError` on mismatch
  (e.g. `application/pdf` + `.docx`).
- `max_size_bytes(entry) -> int` — resolves `entry.max_size_setting` off
  the live `settings` object (governance §4 keys stay authoritative).
- `is_ingestible(content_type) -> bool`, `is_editable(...) -> bool` —
  033's and 032's gates respectively.
- An import-time self-check: no extension maps to two MIME types within
  the catalog; violation raises `RuntimeError` (the plan 025/030
  fail-the-process convention).

`utils.py` gets the key builders (decision 9), built on
`validate_object_key`/`make_storage_object_ref`:

```python
def revision_object_key(workspace_id, file_id, revision_id, extension) -> str:
    # workspaces/{workspace_id}/files/{file_id}/{revision_id}{extension}

def revision_markdown_key(workspace_id, file_id, revision_id) -> str:
    # workspaces/{workspace_id}/files/{file_id}/{revision_id}.extracted.md

def file_prefix(workspace_id, file_id) -> str:
    # workspaces/{workspace_id}/files/{file_id}
```

**Verify**: `uv run python -c "from services.files.contract import contract_for_content_type; print(contract_for_content_type('application/pdf').category)"`
→ `FileCategory.INGESTIBLE_DOCUMENT`, and `uv run ruff check .` → exit 0.

### Step 2: Models (`models/files.py`)

Module-level constants the CHECKs and later plans share:
`FILE_PROCESSING_STATUSES = ("pending", "processing", "ready", "error")`,
`FILE_REVISION_KINDS = ("create", "edit", "replace", "restore", "import")`,
`FILE_REFERENCE_TARGET_TYPES = ("conversation", "artifact", "agent",
"schedule_run")`.

**`File(BaseModel)`** — logical file, soft-delete (governance §3 Files
row), `__tablename__ = "files"`:

- `workspace_id` UUID FK `workspaces.id`, not null, indexed
- `name` String(255) not null — display filename (032 applies
  `safe_filename`); `description` Text nullable
- `category` String(32) not null — a `FileCategory` value
- `content_type` String(128) not null; `extension` String(16) not null —
  mirrors of the current revision
- `size_bytes` BigInteger not null server_default `0`; `content_hash`
  String(64) not null server_default `''` — current-revision mirrors
  (dedup fast path reads these without a join)
- `current_revision_id` UUID FK `file_revisions.id`, **nullable**, with
  `use_alter=True` and an explicit constraint name
  (`fk_files_current_revision`) to break the FK cycle. Nullable is a
  schema concession to insert ordering only — 032 must flush the revision
  first and never commit a NULL; record that in the column comment.
- `revision_count` Integer not null server_default `0`, CHECK `>= 0`
- `processing_status` String(16) not null server_default `'ready'`
  (decision 2), CHECK in `FILE_PROCESSING_STATUSES`
- `processing_error` Text nullable; `processing_attempts` Integer not
  null server_default `0`, CHECK `>= 0`
- Indexes: `ix_files_workspace_created` on `(workspace_id, created_at)`
  partial `WHERE deleted = false`; `ix_files_workspace_processing` on
  `(workspace_id, processing_status)` partial `WHERE deleted = false`
  (033's status surface); the sweep predicate rides the existing
  `deleted_at` index from `SoftDeleteMixin` (`models/base.py:37`).

**`FileRevision(Base, UUIDMixin, CreatedAtMixin)`** — append-only
(no `updated_at`, no soft delete; the `RateLimitAttempt`-style lean
composition, here with `CreatedAtMixin`), `__tablename__ =
"file_revisions"`:

- `file_id` UUID FK `files.id` `ondelete="CASCADE"`, not null, indexed
- `workspace_id` UUID FK `workspaces.id`, not null — denormalized for
  scoping and the dedup index
- `revision_number` Integer not null, CHECK `> 0`;
  `UniqueConstraint("file_id", "revision_number",
  name="uq_file_revisions_file_number")`
- `revision_kind` String(16) not null, CHECK in `FILE_REVISION_KINDS`
- `content_type` String(128) not null; `extension` String(16) not null
- `size_bytes` BigInteger not null, CHECK `>= 0`
- `content_hash` String(64) not null — sha256 hex; index
  `ix_file_revisions_workspace_hash` on `(workspace_id, content_hash)`
  (032's dedup lookup)
- `object_key` String(1024) not null — decision 9 scheme
- Provenance (decision 4): `created_by_user_id` UUID FK `users.id`
  nullable; `created_by_agent_id` UUID FK `agents.id` nullable;
  `created_by_system` Boolean not null server_default `false`; CHECK
  named `file_revisions_exactly_one_actor_check`:

  ```sql
  (CASE WHEN created_by_user_id  IS NOT NULL THEN 1 ELSE 0 END
 + CASE WHEN created_by_agent_id IS NOT NULL THEN 1 ELSE 0 END
 + CASE WHEN created_by_system THEN 1 ELSE 0 END) = 1
  ```

- `restored_from_revision_id` UUID FK `file_revisions.id` nullable;
  CHECK named `file_revisions_restore_source_check`:
  `(revision_kind = 'restore') = (restored_from_revision_id IS NOT NULL)`
- Derived extraction output (decision 3, written only by 033):
  `markdown_object_key` String(1024) nullable; `markdown_size_bytes`
  BigInteger nullable

**`FileReference(Base, UUIDMixin, CreatedAtMixin)`** — non-copying
attachment rows, hard-deleted with their file (decision 7),
`__tablename__ = "file_references"`:

- `file_id` UUID FK `files.id` `ondelete="CASCADE"`, not null
- `workspace_id` UUID FK `workspaces.id`, not null, indexed
- `target_type` String(32) not null, CHECK in
  `FILE_REFERENCE_TARGET_TYPES`
- `target_id` UUID not null — no FK (polymorphic; owning service
  validates)
- `file_revision_id` UUID FK `file_revisions.id` `ondelete="CASCADE"`,
  nullable — NULL follows current, value pins (decision 7)
- `created_by_user_id` UUID FK `users.id`, nullable
- `UniqueConstraint("file_id", "target_type", "target_id",
  name="uq_file_references_file_target")`; index
  `ix_file_references_target` on `(target_type, target_id)`

**`FileUpload(Base, UUIDMixin, CreatedAtMixin)`** — upload staging
(decision 1), `__tablename__ = "file_uploads"`:

- `workspace_id` UUID FK `workspaces.id`, not null, indexed
- `file_id` UUID not null — **plain UUID, deliberately no FK**: for a
  new-file upload the `files` row does not exist until confirm; the
  column comment must say exactly that
- `revision_id` UUID not null — pre-generated so the object key is final
  from the start (no copy/move op exists on `StorageProvider`)
- `object_key` String(1024) not null;
  `UniqueConstraint("object_key", name="uq_file_uploads_object_key")`
  (032's confirm looks the row up by the token's bound key)
- `filename` String(255) not null; `content_type` String(128) not null;
  `declared_size_bytes` BigInteger not null; `declared_content_hash`
  String(64) nullable
- `created_by_user_id` UUID FK `users.id`, not null
- `expires_at` DateTime(tz) not null; `consumed_at` DateTime(tz) nullable
- Index `ix_file_uploads_pending_expiry` on `(expires_at)` partial
  `WHERE consumed_at IS NULL` (032's expiry sweep)

**Immutability listener** (decision 3), in the same module:

```python
_REVISION_MUTABLE_ONCE = frozenset({"markdown_object_key", "markdown_size_bytes"})

@event.listens_for(FileRevision, "before_update")
def _reject_file_revision_mutation(mapper, connection, target):
    # file revisions are append-only history; only NULL->value backfill of
    # derived extraction columns is permitted
    ...
```

Use `sqlalchemy.inspect(target).attrs[...].history` to find changed
attributes; raise `RuntimeError` (invariant violation, not user error)
naming the offending column when a change falls outside the whitelist or
overwrites a non-NULL derived value. No plan-number references in any
comment — describe runtime behavior only.

Register all four models in `models/__init__.py` (alphabetical, matching
lines 13-25).

**Verify**: `uv run python -c "import models; from models.files import File, FileRevision, FileReference, FileUpload; print(File.__tablename__, FileRevision.__tablename__)"`
→ `files file_revisions`, and `uv run ruff check .` → exit 0.

### Step 3: Core migration

Confirm the live core head first:
`uv run alembic heads` — **expected `core_0009` (030's jobs migration)
on the core branch**. If 030 has not landed, the head is `core_0008`; if
anything else has landed, it is later. Whatever it is, generate against
it (D5):

```bash
uv run alembic revision --autogenerate \
  --head core@head \
  --version-path alembic/versions/core \
  -m "add file tables"
```

Name/number the file to follow the real head (expected
`0010_add_file_tables.py`, revision `core_0010`). Then hand-check the
autogenerate output — it routinely misses or mangles:

- the `use_alter` FK `fk_files_current_revision` (must be created via
  `op.create_foreign_key` after both tables exist, and dropped first in
  `downgrade`)
- the three-way provenance CHECK and the restore CHECK (add via
  `op.create_check_constraint` with the exact names from Step 2 if
  absent)
- the partial indexes (`postgresql_where`) on `files`, `file_uploads`

`downgrade` drops in reverse dependency order: the `use_alter` FK, then
`file_references`, `file_uploads`, `file_revisions`, `files`.

**Verify**: `uv run alembic upgrade heads` applies cleanly;
`uv run alembic check` → no pending operations;
`uv run alembic downgrade core@-1 && uv run alembic upgrade heads`
round-trips; and in psql
`\d file_revisions` shows both named CHECK constraints.

### Step 4: Factories + tests

`tests/factories/files.py` — pattern of
`tests/factories/workspaces.py:9-25`: `build_file(workspace, **over)`,
`build_file_revision(file, *, revision_number=1,
revision_kind="create", created_by_user_id=..., **over)` (defaults to a
valid single-actor row and a decision-9 object key),
`build_file_reference(...)`, `build_file_upload(...)`.

`tests/services/files/` (new; DB-backed modules set
`pytestmark = pytest.mark.asyncio` and use the `conftest.py` fixtures so
they skip cleanly without `TEST_DATABASE_URL`):

- `test_file_contract.py` (no DB): every catalog entry round-trips
  through `contract_for_content_type`; `require_matching_pair` rejects
  `application/pdf` + `.docx` and unknown MIME types with
  `AppValidationError`; extensions are unique across the catalog;
  `max_size_bytes` resolves the governance §4 settings keys
  (`MAX_FILE_SIZE_DOCUMENT` for pdf, `MAX_FILE_SIZE_VIDEO` for mp4);
  `is_ingestible` true exactly for the four document types;
  `revision_object_key`/`revision_markdown_key` produce the decision-9
  shapes and pass `validate_object_key`.
- `test_file_models.py` (DB): provenance CHECK — zero actors and two
  actors both raise `IntegrityError`, each single-actor variant inserts;
  `revision_kind` outside the tuple raises; `restore` without
  `restored_from_revision_id` raises and vice versa; duplicate
  `(file_id, revision_number)` raises; `processing_status` outside the
  enum raises; `FileReference` duplicate `(file_id, target_type,
  target_id)` raises; `FileUpload` duplicate `object_key` raises;
  deleting a `files` row cascades `file_revisions` and
  `file_references`.
- `test_file_revision_immutability.py` (DB): mutating `content_hash`,
  `object_key`, `size_bytes`, or provenance on a flushed revision raises
  on flush; backfilling `markdown_object_key`+`markdown_size_bytes` from
  NULL succeeds exactly once; overwriting a non-NULL
  `markdown_object_key` raises; `File` rows stay freely mutable
  (mirrors update fine).

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/files -q` → all
pass; `uv run pytest tests/services/files/test_file_contract.py -q`
(no env var) → passes, DB modules skip.

### Step 5: Governance bookkeeping

Per the governance rule block (`docs/architecture/governance.md` lines
5-10), mark the shipped slice: in §3, annotate the
"Files/FileRevisions (031/032)" row's *Soft delete* semantics as
`[implemented: plan 031 (schema + provenance/immutability invariants);
lifecycle behavior: plan 032]` — the hard-delete/cascade cells stay
default until 032's sweeper ships. Do not touch any other cell.

**Verify**: `git diff docs/architecture/governance.md` shows exactly the
one-row annotation.

## Test plan

Covered by Step 4 (~16–20 tests). The pinned invariants: **provenance is
exactly one actor** (CHECK, not convention), **revisions cannot be
rewritten** (listener, with the sole NULL→value derived-column
exception), **restore rows always name their source**, **the contract
rejects unknown and mismatched types**, and **cascade topology** (file
hard-delete takes revisions and references with it — what 032's sweeper
relies on).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no pending operations; the migration
      is on the **core** branch (D5), numbered after the live head, and
      downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/files -q`
      exits 0; contract tests pass without the env var
- [ ] Existing suites untouched:
      `uv run pytest tests/services/skills tests/services/assets -q`
      still green with zero edits to those trees
- [ ] `services/files/` contains only `__init__.py` (docstring),
      `contract.py`, `utils.py` — no operations, no routes package exists
- [ ] No comment or docstring in implementation code references plan
      numbers or roadmap files
- [ ] `docs/architecture/governance.md` §3 Files row annotated per Step 5
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row for 031 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows changes to `apps/api/models/` or
  `alembic/versions/core/` that the "Current state" excerpts do not
  describe.
- `models/files.py`, any of the four tables, or `services/files/`
  already exists (someone started the substrate first).
- **The core head at execution time is not the expected `core_0009`
  (030's jobs migration)**: if 030 has not landed, the head is
  `core_0008` — renumber this migration to sit directly on the real head
  and note in your report that 030 must renumber above it (whichever
  lands second rebases; coordinate rather than guess). If the head is
  something else entirely, re-verify no landed migration created a
  conflicting table or index name before renumbering.
- `docs/architecture/governance.md` §1/§3/§4 defaults cited in
  "Decisions taken" have been flipped since `0cbbb39` (the living note
  wins — reconcile the affected decision first).
- The `before_update` listener cannot express the whitelist-with-history
  check against the installed SQLAlchemy 2 version — report rather than
  silently weakening immutability.
- You feel the need to add routes, upload services, settings keys, job
  kinds, or a `domain.py` — that is 032/033 scope leaking in.

## Maintenance notes

- **Consumers of this schema** (do not implement here): 032
  (upload/confirm/edit/restore/delete services + routes, sweeper, usage
  counter), 033 (`files.extract` job kind; sole writer of
  `processing/error` statuses and the markdown backfill columns), 034
  (agent file tools + scratch promote → `revision_kind='create'/'edit'`
  with `created_by_agent_id`), 035 (files UI; mirrors
  `services/files/contract.py` in its feature `types.ts` by hand — no
  codegen exists), 036 (chat attachments → `FileReference
  target_type='conversation'`), 044 (KB ingestion referencing
  `file_revision_id` for provenance), 050 (artifacts as FileRevisions
  with a `source_type`-style `agent_artifact` provenance — if 050 needs
  a new `revision_kind` or reference `target_type`, it extends the
  constant tuples AND the CHECKs in one migration).
- **The immutability listener guards the ORM path only.** Reviewers must
  block any `update(FileRevision)` core statement outside the
  NULL→value markdown backfill; if a future plan needs bulk revision
  writes, it must argue for a DB trigger instead of weakening the
  listener.
- **`files` mirror columns** (`content_type`/`size_bytes`/
  `content_hash`/`extension`) are denormalized copies of the current
  revision. 032 is the only writer and must update them and
  `current_revision_id`/`revision_count` in the same flush; a reviewer
  who sees them drift from the revision row should block.
- **`FileUpload` rows are ephemeral by design** — consumed at confirm,
  expired by 032's sweep. Nothing else may read them; they are not an
  upload-history feature.
- **Category vs. per-file overrides**: `MAX_FILE_SIZE_AGENT_FILE`
  (100 MB) is deliberately unused by the contract — 034 applies it to
  agent durable writes at its own seam. If 036 needs multimodal
  gating, it adds a `multimodal` flag to `FileContractEntry` rather than
  a parallel table.
- The `.extracted.md` derived-key suffix (decision 9) is load-bearing:
  032's blob deletion must delete both the revision key and, when
  `markdown_object_key` is set, the markdown key.
