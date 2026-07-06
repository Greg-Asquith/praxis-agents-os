# Plan 033: Background file processing — extraction to markdown via jobs

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
> `git diff --stat 0cbbb39..HEAD -- apps/api/services/skills/documents/ apps/api/services/files/ apps/api/services/jobs/ apps/api/workers/ apps/api/routes/files/ apps/api/utils/ apps/api/core/settings/files.py apps/api/models/files.py`
> Changes from plans 030/031/032 under `services/jobs/`, `workers/`,
> `models/files.py`, `services/files/`, and `routes/files/` are EXPECTED —
> verify them against the "[after 03x]" summaries below. Any drift under
> `services/skills/documents/` or `apps/api/utils/` that the "Current
> state" excerpts do not describe is a STOP condition (the conversion
> machinery this plan refactors must be where the plan says it is).

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (refactors the live skills conversion path — must be
  behavior-preserving with the skills suite green untouched — and adds
  the first high-volume job producer plus the first hard per-workspace
  job cap at the claim seam)
- **Depends on**: 030 (hard — `enqueue_job`, `@job_handler`, worker loop,
  retry/notification mechanics), 031 (hard — processing columns,
  markdown backfill whitelist, `revision_markdown_key`), 032 (hard — the
  confirm/restore seams this plan wires into), 017's conversion
  machinery (exists today at `0cbbb39`, verified below). Soft:
  `docs/architecture/governance.md` (Gate G3).
- **Category**: Phase 3 files substrate (roadmap `000_MASTER_ROADMAP.md`
  §4 Phase 3 row 033; donor `DONOR_PORT_ROADMAP.md` §4.3 / §6 row B4)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **One converter, hoisted — not copied.** The roadmap is explicit
   (`000_MASTER_ROADMAP.md` Phase 2 note: "017's document pipeline
   anticipates Phase 3's file processing … 033 must reuse that machinery
   rather than build a second converter"; recorded again in
   `docs/plans/000_README.md` 017 note). The extraction core —
   `convert_document_to_markdown`, `_convert_sync`, `truncate_markdown`,
   the truncation marker (`services/skills/documents/utils.py:30,
   134-180`) — moves to a new top-level `apps/api/utils/`
   module (`utils/document_markdown.py`); per AGENTS.md, non-service-
   specific reusable helpers belong there, and this helper now has two
   service consumers. The move is **behavior-preserving**: skills code
   imports the shared module, `SkillDocumentConversionError` becomes a
   subclass of the shared `DocumentConversionError` so existing `except`
   clauses keep matching, and `tests/services/skills` must pass with
   zero test edits.
2. **`files.extract` payload is ids only** (030's payload discipline —
   "ids and small parameters only, never blobs"): `{"file_id": ...,
   "revision_id": ...}`, `subject_type="file_revision"`,
   `subject_id=revision_id`, `content_hash=` the revision's
   `content_hash` — so 030's in-flight dedup index collapses duplicate
   enqueues for the same revision content for free.
3. **Bounded retries with an honest terminal state.**
   `@job_handler(kind="files.extract", timeout=300.0, max_attempts=3)`:
   conversion failures are usually deterministic (a corrupt PDF fails
   identically every attempt), so three attempts, not five, bounds the
   waste while still absorbing transient storage errors. The handler
   stamps `File.processing_status='error'` + a sanitized message
   *before* re-raising, so the UI shows the truth between retries; a
   later retry resets it to `'processing'`. When 030's harness exhausts
   attempts it marks the job failed and — because
   `initiated_by_user_id` is set at enqueue — notifies the initiator,
   **only then** (governance §6: "Job pipeline failure — only after
   final retry exhausted → initiator"; mechanics live in 030's
   `finalize_job_failure`, this plan adds no notification code).
4. **The handler is idempotent and current-revision-aware**
   (at-least-once execution, 030's contract). Re-runs short-circuit when
   the revision's `markdown_object_key` is already set. The markdown
   blob is written to `revision_markdown_key(...)` (031 decision 9),
   then backfilled onto the revision through 031's NULL→value listener
   whitelist. `File.processing_status` flips to `'ready'` **only if the
   processed revision is still `file.current_revision_id`** — a replace
   that lands mid-extraction must not have its status clobbered by a
   stale job. The revision backfill happens regardless (044 wants
   per-revision markdown).
5. **Restore revisions copy the pointer instead of re-extracting.** A
   `restore` revision shares its source's `object_key` (032 decision 5)
   — identical bytes, identical markdown. The handler detects
   `restored_from_revision_id` with a non-NULL source
   `markdown_object_key` and backfills the same key (a NULL→value write,
   whitelist-legal) without touching MarkItDown. Cheap, and it keeps
   markdown keys shared exactly where object keys are shared, which
   032's distinct-key blob deletion already handles.
6. **Enqueue happens at the two revision-creating seams for ingestible
   content**: `confirm_file_upload` (create/replace) and
   `restore_file_revision`, gated by `is_ingestible(content_type)`
   (031's contract). These seams set `processing_status='pending'` in
   the same flush as the revision, replacing 032's deliberate constant
   `'ready'` (032 decision 11 named this plan as the owner of that
   change). Text edits never enqueue — editable-text categories are
   directly readable and `is_ingestible` is false for them.
7. **The status surface is files-shaped, not jobs-shaped.** 030 shipped
   jobs with "no public surface" and deferred the first user-visible
   status to this plan (030 decisions 7/9). This plan delivers it as:
   live `processing_status`/`processing_error` in the existing file
   list/detail responses (fields exist since 032; now they move), plus
   one new `GET /files/processing` summary route — per-status counts
   for the workspace and the in-flight `files.extract` job count via
   030's `count_in_flight_jobs`. No generic `/jobs` routes package —
   jobs remain infrastructure (030's boundary holds).
8. **Hard per-workspace job concurrency lands here, at the claim seam.**
   030 decision 7 deferred enforcement to "plan 033 (the first
   high-volume producer)" and its maintenance note fixes the seam: "add
   a per-workspace cap to the claim query, do not bolt a check onto
   enqueue (enqueue-time checks race)". The claim query in
   `services/jobs/claim_jobs.py` gains an exclusion for pending jobs
   whose workspace already has `>= JOBS_WORKSPACE_CONCURRENCY_LIMIT`
   jobs `running` (governance §4: "4/workspace, observed at claim time;
   … 033 (first enforcement seam)"). `workspace_id IS NULL` system jobs
   (sweeps) are exempt. Excluded jobs are not failed — they stay
   `pending` and are picked up on a later pass; the decision-7 warning
   log stays.
9. **Markdown size cap is files-owned.** New setting
   `FILES_MAX_MARKDOWN_BYTES` (default 2 MiB, the
   `MAX_SKILL_DOC_MARKDOWN_BYTES` shape at `core/settings/files.py:61-66`)
   caps converted output through the shared `truncate_markdown`; skills
   keep their own key. One converter, two policy knobs — deliberate,
   since KB ingestion (044) will want a third.
10. **Gaps-doc questions resolved or confirmed**
    (`docs/legacy/ROADMAP_QUESTIONS_GAPS.md`): §Notifications "are job
    failures shown only on detail pages, or also as notifications" —
    030 resolved the policy; this plan is the first pipeline exercising
    it end to end (decision 3). "Job-status UI feedback" (030 decision 9
    deferred it here) — resolved as decision 7's surface; the UI itself
    renders in 035.

## Why this matters

This plan closes the Phase 3 loop: 030 built the queue, 031 the schema,
032 the lifecycle — but an uploaded PDF is still an opaque blob. After
033, ingestible documents become markdown that agents (034
`read_file`), the KB pipeline (044 chunking/embedding via
`file_revision_id` + `markdown_object_key`), and the UI (035) all
consume. It is also deliberately the pattern-setter for every later
pipeline: the donor ran extraction synchronously inside request handlers
and built a second parallel queue when that fell over
(`DONOR_PORT_ROADMAP.md` §4.3 "never synchronous in the confirm
request"); this plan demonstrates the sanctioned shape — enqueue at the
write seam, idempotent handler, honest status lifecycle on the domain
row, notify only on final failure — that 039 (discovery) and 044
(ingestion) copy. And it hardens the harness itself with the first real
producer: the per-workspace claim cap keeps one workspace's bulk upload
from starving everyone else's jobs.

## Current state

Verified at `0cbbb39`, except items marked **[after 03x]**, which this
plan consumes from its dependencies and must re-verify at execution
time.

- `apps/api/services/skills/documents/utils.py` — the conversion
  machinery to hoist (decision 1): `TRUNCATION_MARKER` (30),
  `convert_document_to_markdown` (134-151: text types decoded directly,
  others through `asyncio.to_thread(_convert_sync, ...)`),
  `_convert_sync` (154-163: `MarkItDown().convert_stream(...,
  file_extension=...)`), `truncate_markdown` (166-180: UTF-8-boundary
  truncation + marker), `document_extension` (61-68) and
  `_CONTENT_TYPE_EXTENSIONS` (32-37) — the extension fallback the
  converter needs; `SkillDocumentConversionError` at
  `services/skills/documents/domain.py:17-22`. Consumed in-request at
  `confirm_document_upload.py:80-96`.
- `apps/api/utils/` — the existing top-level shared-helpers package
  (`dates.py`, `json_safe.py`, `security.py`, …); the AGENTS.md-blessed
  home for the hoisted converter. No conversion module exists there yet.
- `apps/api/pyproject.toml:15` — `markitdown[docx,pdf,pptx,xlsx]>=0.1.6`
  already covers every ingestible type in 031's contract.
- **[after 030]** `services/jobs/`: `enqueue_job(db, *, kind, …,
  content_hash, max_attempts, initiated_by_user_id)`;
  `@job_handler(kind=..., timeout=..., max_attempts=...)` registering
  through the `services/jobs/handlers/` assembly point (030 Step 3
  names 033 as an extender); `claim_jobs.py` — the SKIP-LOCKED claim
  query this plan amends (decision 8), which already logs the over-limit
  warning via `count_in_flight_jobs`; `finalize_job.py` — final-failure
  notification to `initiated_by_user_id` (030 decision 8; this plan's
  decision 3 rides it); `JOBS_WORKSPACE_CONCURRENCY_LIMIT` setting
  (default 4); the sanitize-error 1000-char cap convention.
- **[after 031]** `models/files.py`: `File.processing_status`
  (`pending/processing/ready/error`, server_default `'ready'`),
  `processing_error`, `processing_attempts`;
  `FileRevision.markdown_object_key`/`markdown_size_bytes` writable
  exactly once from NULL (listener whitelist);
  `restored_from_revision_id`; `ix_files_workspace_processing` partial
  index. `services/files/contract.py::is_ingestible`;
  `services/files/utils.py::revision_markdown_key` →
  `workspaces/{ws}/files/{file_id}/{revision_id}.extracted.md`.
- **[after 032]** `services/files/confirm_file_upload.py` — sets
  `processing_status='ready'` as a single deliberate statement this plan
  replaces (032 decision 11); `restore_file_revision.py` — the other
  revision-creating seam; `list_files.py`/`get_file.py` — responses
  already carry `processing_status`/`processing_error`;
  `routes/files/__init__.py` — router this plan adds one route to
  (literal paths before `/{file_id}`); `distinct_object_keys` already
  includes markdown keys in blob deletion.
- `apps/api/core/settings/files.py`: `MAX_SKILL_DOC_MARKDOWN_BYTES`
  (61-66) — the shape decision 9 copies; `FilesSettingsMixin` composed
  at `core/settings/__init__.py:21,39`.
- `apps/api/services/notifications/service.py:105` —
  `create_notification`, invoked by 030's finalize path; this plan calls
  it nowhere directly.
- Exceptions: `AppValidationError` (`core/exceptions/general.py:16`),
  `NotFoundError` (52) — the handler raises ordinary exceptions to
  signal retryable failure to the harness; no HTTP exceptions in worker
  code.
- Tests: `tests/services/skills/test_skill_documents.py` — the suite
  that pins decision 1's behavior preservation;
  `tests/services/jobs/` **[after 030]** — where the claim-cap tests
  land; `tests/services/files/` **[after 031/032]**.
- Governance anchors: §6 notification row (job pipeline failure →
  initiator, final retry only), §4 job-concurrency row (this plan is
  the named enforcement seam), §3 jobs row (terminal rows 30 d —
  unchanged here).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations (this plan adds NO migration) |
| Skills regression (decision 1) | `uv run pytest tests/services/skills -q` | all pass with zero test-file edits |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/files tests/services/jobs -q` | all pass |
| Registry check | `uv run python -c "from services.jobs.registry import JOB_HANDLERS; print(sorted(JOB_HANDLERS))"` | includes `files.extract` |
| Worker smoke | `uv run python -m workers.job_runner --once` | one pass, exit 0 |
| Converter probe | `uv run python -c "from utils.document_markdown import convert_document_to_markdown; print('ok')"` | `ok` |

## Scope

**In scope:**

- `apps/api/utils/document_markdown.py` (create — hoisted converter,
  decision 1) and the matching import updates inside
  `apps/api/services/skills/documents/` (`utils.py`, `domain.py` —
  imports and the exception subclassing ONLY; no behavior edits)
- `apps/api/core/settings/files.py` (add `FILES_MAX_MARKDOWN_BYTES`)
- `apps/api/services/jobs/handlers/extract_file_markdown.py` (create —
  the `files.extract` handler)
- `apps/api/services/jobs/claim_jobs.py` (amend — decision 8 claim cap)
- `apps/api/services/files/`: `confirm_file_upload.py` +
  `restore_file_revision.py` (enqueue + pending status, decision 6),
  `utils.py` (status-transition helper), new
  `get_files_processing_summary.py` (+ `__init__.py` re-export)
- `apps/api/routes/files/get_files_processing.py` (create) +
  `routes/files/__init__.py` (register)
- `apps/api/tests/`: `tests/services/files/` (extraction + enqueue
  tests), `tests/services/jobs/` (claim-cap test), factories as needed
- `docs/architecture/governance.md` (Done criteria — §4 job-concurrency
  cell)

**Out of scope (do NOT touch):**

- Migrations — 031 shipped every column (that was the point). Finding
  yourself in `alembic/versions/` is a STOP.
- Any enrichment beyond extraction→markdown: chunking, embedding,
  contextual annotation, summaries — all 044 (`DONOR_PORT_ROADMAP.md`
  §4.4 pipeline).
- Multimodal model input (036), agent file tools (034), files UI (035 —
  it renders this plan's status fields, it is not this plan).
- A `routes/jobs/` package or any generic jobs API (decision 7).
- Skills **behavior**: no changes to skill document limits, manifest
  shapes, routes, or the in-request conversion timing of the skills
  confirm path. Only the import seam moves.
- Notification code — 030's finalize owns it (decision 3).

## Git workflow

- Branch: `advisor/033-background-file-processing`
- Commit style: `API - Background File Processing`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Hoist the converter (behavior-preserving)

Create `apps/api/utils/document_markdown.py` containing, moved verbatim
from `services/skills/documents/utils.py` (adjusting only imports and
names):

- `DocumentConversionError(Exception)` — message-carrying, the
  `SkillDocumentConversionError` shape
  (`skills/documents/domain.py:17-22`)
- `TRUNCATION_MARKER` (the exact current string — persisted markdown
  ends with it today; changing it would silently alter stored content
  semantics)
- `convert_document_to_markdown(data, *, content_type, filename,
  max_bytes) -> str` — one signature change: the cap becomes an explicit
  `max_bytes` parameter instead of reading
  `settings.MAX_SKILL_DOC_MARKDOWN_BYTES` internally (each caller passes
  its own knob — decision 9)
- `_convert_sync`, `truncate_markdown`, and the
  content-type→extension fallback (`_CONTENT_TYPE_EXTENSIONS` +
  `document_extension`) — extend the extension map with the pptx/xlsx
  pairs from 031's contract so the fallback covers every ingestible
  type

Then re-point skills: `services/skills/documents/utils.py` imports the
shared functions and re-exposes `convert_document_to_markdown(...)` as
a thin wrapper passing
`max_bytes=settings.MAX_SKILL_DOC_MARKDOWN_BYTES` (call sites
unchanged); `SkillDocumentConversionError` in `domain.py` becomes
`class SkillDocumentConversionError(DocumentConversionError)` with the
same `__init__`. The skills confirm path
(`confirm_document_upload.py:80-96`) must not change at all.

Add `FILES_MAX_MARKDOWN_BYTES` to `FilesSettingsMixin` (default
`2097152`, bounds `ge=65536, le=10485760` — the
`MAX_SKILL_DOC_MARKDOWN_BYTES` shape).

**Verify**: `uv run pytest tests/services/skills -q` → all pass with
**zero edits** under `tests/services/skills/`; converter probe command →
`ok`; ruff exit 0.

### Step 2: The `files.extract` handler

`services/jobs/handlers/extract_file_markdown.py`:

```python
@job_handler(kind="files.extract", timeout=300.0, max_attempts=3)
async def extract_file_markdown(db, job):
    # payload: {"file_id": ..., "revision_id": ...} — ids only
```

Handler flow (each numbered branch is a test in Step 5):

1. Load file + revision (workspace-scoped by the revision's own
   `workspace_id`; job `workspace_id` matches). Revision missing or
   file hard-deleted → log and return success (the subject died; a
   retry cannot help). File soft-deleted → same.
2. Idempotence (decision 4): `revision.markdown_object_key` already set
   → ensure `File.processing_status` is consistent (flip to `'ready'`
   if this is still the current revision and status is
   `pending/processing`) and return.
3. Restore fast path (decision 5): `revision.revision_kind ==
   'restore'` and the source revision's `markdown_object_key` is set →
   backfill the same key + `markdown_size_bytes` (NULL→value,
   whitelist-legal), flip status as in 4, return. MarkItDown never
   runs.
4. Mark started: `processing_status='processing'`,
   `processing_attempts += 1`, clear `processing_error`; flush + commit
   semantics per 030's handler-session contract so the UI sees
   `processing` while conversion runs.
5. Convert: `data = await provider.get_object(ref)`;
   `markdown = await convert_document_to_markdown(data,
   content_type=revision.content_type, filename=file.name,
   max_bytes=settings.FILES_MAX_MARKDOWN_BYTES)`.
6. Persist: `put_object` at
   `revision_markdown_key(workspace_id, file_id, revision_id)` with
   `content_type="text/markdown"`; backfill
   `markdown_object_key`/`markdown_size_bytes`; if the revision is
   still `file.current_revision_id` (decision 4), set
   `processing_status='ready'`, clear `processing_error`.
7. On `DocumentConversionError` or any storage error: stamp
   `processing_status='error'` + sanitized message (1000-char cap, the
   030 convention) on the file **if this is still the current
   revision**, flush, then **re-raise** — the harness owns
   retry/backoff/final-failure, and final failure notifies the
   initiator (decision 3; no notification code here).

Comments describe runtime behavior only — no plan numbers.

**Verify**: registry check command lists `files.extract`;
`uv run python -m workers.job_runner --once` → exit 0.

### Step 3: Enqueue at the revision-creating seams

In `services/files/confirm_file_upload.py`, replace 032's constant with
the gated form (decision 6):

```python
if is_ingestible(revision.content_type):
    file.processing_status = "pending"
    await enqueue_job(
        db,
        kind="files.extract",
        workspace_id=workspace.id,
        subject_type="file_revision",
        subject_id=revision.id,
        payload={"file_id": str(file.id), "revision_id": str(revision.id)},
        content_hash=revision.content_hash,
        initiated_by_user_id=actor.id,
    )
else:
    file.processing_status = "ready"
```

Same gate in `restore_file_revision.py` (the restore fast path in the
handler makes this cheap — decision 5). Add a small
`services/files/utils.py` helper if the two seams would otherwise
duplicate the block. `edit_file.py` is untouched (editable text is
never ingestible — assert that with a test, not a comment).

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/files/test_confirm_file_upload.py -q`
— existing 032 assertions updated ONLY where they pinned the constant
`'ready'` for ingestible fixtures (that was 032's documented
placeholder); non-ingestible fixtures still assert `'ready'`.

### Step 4: Claim-seam concurrency cap + the status surface

**Claim cap** (decision 8), in `services/jobs/claim_jobs.py`: exclude
pending jobs whose `workspace_id` currently has at least
`JOBS_WORKSPACE_CONCURRENCY_LIMIT` rows in `status='running'`. Sketch —
keep it one correlated condition on the existing SKIP-LOCKED select,
system jobs exempt:

```python
running_counts = (
    select(Job.workspace_id, func.count().label("n"))
    .where(Job.status == JOB_STATUS_RUNNING, Job.workspace_id.is_not(None))
    .group_by(Job.workspace_id)
    .subquery()
)
# ... .where(or_(Job.workspace_id.is_(None),
#                running_counts.c.n < limit,  via outerjoin
#                running_counts.c.n.is_(None)))
```

The count is computed at claim time in the same transaction — slightly
stale across concurrent workers is acceptable (the limit is a fairness
valve, not a hard invariant; governance §4 keeps quotas soft-first, and
this is the "enforcement second" step for the one quota 030 explicitly
assigned here). Keep 030's over-limit warning log. Update the
`count_in_flight_jobs` docstring: the surface owner clause ("deferred
to 033") is now satisfied — point it at the files processing summary.

**Status surface** (decision 7):
`services/files/get_files_processing_summary.py` —
`get_files_processing_summary(db, *, workspace) ->
FilesProcessingSummary` (add the Pydantic model to
`services/files/domain.py`): per-status counts over non-deleted files
(the `ix_files_workspace_processing` index), plus
`in_flight_jobs = count_in_flight_jobs(db, workspace_id=workspace.id)`.
Route `routes/files/get_files_processing.py` → `GET /files/processing`
(any role; registered before the `/{file_id}` routes like `/usage`).

**Verify**: route appears in the app route dump; claim-cap behavior
pinned by Step 5's jobs test.

### Step 5: Tests

`tests/services/files/` (DB-gated, `pytestmark = pytest.mark.asyncio`):

- `test_extract_file_markdown.py` — the handler, branch by branch:
  pdf fixture bytes → markdown stored at the `.extracted.md` key,
  revision backfilled, file `ready` (use a tiny real PDF fixture — the
  markitdown path is the point); truncation applied at
  `FILES_MAX_MARKDOWN_BYTES` with the marker; idempotent re-run (no
  second put, no listener violation); stale revision — replace lands
  first, old job completes, file status NOT clobbered, revision still
  backfilled; deleted file/revision → job succeeds as a no-op; restore
  fast path copies the source's markdown key without converting;
  conversion failure → file `error` + sanitized message, exception
  propagates (retryable), attempts increment.
- `test_processing_enqueue.py`: confirm of an ingestible upload sets
  `pending` and enqueues `files.extract` with ids-only payload,
  revision subject, revision `content_hash`, and
  `initiated_by_user_id`; non-ingestible upload stays `ready` with no
  job; restore of an ingestible file enqueues; text edit does not;
  double-confirm does not enqueue twice (030's in-flight dedup — same
  subject + hash).
- `test_final_failure_notification.py`: drive a permanently-failing
  extraction through the harness's finalize path to attempt exhaustion
  → job `failed`, exactly one notification row for the uploading user,
  none on intermediate attempts (governance §6; the assertion style of
  030's finalize tests).
- `test_files_processing_summary.py`: counts by status for the
  workspace only; in-flight job count included; deleted files excluded.

`tests/services/jobs/test_claim_workspace_cap.py`: a workspace with
`limit` running jobs has its pending jobs skipped while another
workspace's are claimed; NULL-workspace jobs always claimable; capped
jobs remain `pending` (not failed) and are claimed once a running job
finalizes.

Skills: **no new tests, no edited tests** — the existing suite is the
regression harness for Step 1.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/files tests/services/jobs tests/services/skills -q`
→ all pass; without the env var, DB modules skip.

### Step 6: Governance bookkeeping

In `docs/architecture/governance.md` §4, flip the "Job concurrency" row
to `[implemented: plan 030 (counter/warning), plan 033 (claim-seam
enforcement, files surface)]`. §6's job-failure row belongs to 030 —
confirm its cell reflects 030's landed state and leave it to 030's
bookkeeping if not. No other cells.

**Verify**: `git diff docs/architecture/governance.md` shows exactly
the one-cell change.

## Test plan

Covered by Step 5 (~18–22 new tests) plus the untouched skills suite as
a regression gate. The pinned invariants: **the converter moved without
behavior change** (skills green, zero test edits), **extraction is
idempotent and never clobbers a newer revision's status**
(at-least-once safety), **status tells the truth at every stage**
(`pending` only when a job exists; `error` visible between retries;
`ready` only with markdown persisted or non-ingestible content),
**notification fires exactly once, only on final failure, only to the
initiator**, and **one workspace cannot monopolize the worker** (claim
cap splits fairly, capped jobs survive as pending).

## Done criteria

- [ ] `uv run ruff check .` exits 0; `uv run alembic check` clean (no
      migration added by this plan)
- [ ] `uv run pytest tests/services/skills -q` green with zero edits
      under `tests/services/skills/`
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/files
      tests/services/jobs -q` exits 0
- [ ] `files.extract` registered; worker `--once` smoke passes; grep
      shows exactly one MarkItDown call site
      (`utils/document_markdown.py`) across `apps/api`
- [ ] Confirm/restore set `pending`+enqueue for ingestible types only;
      `GET /files/processing` live; list/detail expose meaningful
      `processing_status`
- [ ] Claim query enforces the per-workspace cap; system (NULL
      workspace) jobs exempt
- [ ] No notification code outside 030's finalize path; no plan-number
      references in implementation code
- [ ] `docs/architecture/governance.md` §4 job-concurrency cell updated
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row for 033 updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Plan 030 is not implemented at execution time** (no
  `services/jobs/registry.py`, `enqueue_job`, or worker loop) — this
  plan hard-depends on it; there is no synchronous fallback (the donor's
  synchronous-confirm mistake is explicitly what this plan exists to
  avoid).
- **Plan 031 or 032 is not implemented** (no processing columns /
  markdown whitelist / confirm seam) — nothing here can start.
- **The skills document pipeline has moved**: the conversion helpers
  are no longer at `services/skills/documents/utils.py:134-180`, their
  signatures changed, or `MAX_SKILL_DOC_MARKDOWN_BYTES` is consumed
  elsewhere too — re-ground Step 1 against the real code before moving
  anything.
- 030's landed handler/enqueue signatures differ from the
  "[after 030]" summary (especially `max_attempts` on `@job_handler`
  and dedup semantics decision 2 relies on).
- 031's markdown-backfill whitelist rejects the handler's write pattern
  (listener semantics drifted) — reconcile with 031's landed listener,
  do not weaken it.
- The `tests/services/skills` suite fails BEFORE your changes.
- Amending the claim query breaks any existing
  `tests/services/jobs` test in a way that looks semantic (ordering or
  SKIP-LOCKED splits) rather than additive — the harness contract wins;
  report.
- You feel the need to add a migration, a `routes/jobs/` package,
  chunking/embedding, or notification code — 031/044/030 scope leaking
  in.

## Maintenance notes

- **Downstream consumers** (do not implement): 034 agent file tools
  read extracted markdown for `read_file` content mode and add
  scratch-promote (a `create` revision with agent provenance — its
  uploads flow through these same seams, so extraction is free); 035
  renders `processing_status`/`processing_error` and the
  `/files/processing` summary; 036 multimodal attachments bypass
  extraction (raw bytes to the model) but respect the same contract
  gates; 044 KB ingestion consumes `file_revision_id` +
  `markdown_object_key` as its upload-source input and registers its
  own job kinds — it must reuse `utils/document_markdown.py` (third
  consumer, third `max_bytes` knob) rather than fork it; 050 artifacts
  create text revisions (never ingestible).
- **The converter module is now load-bearing for two verticals.** Any
  change to `TRUNCATION_MARKER`, truncation semantics, or MarkItDown
  invocation alters both skills documents and file extraction — and
  044's chunker later. Treat it like a wire format: additive changes
  only, both test suites in the same PR.
- **`processing_status` semantics**: `pending`/`processing`/`error` are
  meaningful only for the **current** revision's extraction; per-
  revision truth lives in `markdown_object_key`. If a future plan needs
  per-revision status (unlikely before 044), that is a new column on
  the revision, not more states on the file.
- **Deterministic-failure fast-fail**: decision 3 accepts up to three
  attempts on a doomed conversion. If 030's harness ever grows a
  non-retryable failure signal, the `DocumentConversionError` branch in
  the handler is the first adopter — update governance §6 if the
  notification timing changes with it.
- **Claim-cap tuning**: the limit is `JOBS_WORKSPACE_CONCURRENCY_LIMIT`
  (settings, default 4). If 044's embedding fan-out needs per-kind caps,
  extend the claim seam — do not add enqueue-time checks (they race;
  030's maintenance note stands).
- Reviewers should scrutinize: the stale-revision guard (status flips
  gated on `current_revision_id`), commit boundaries in the handler
  (the `processing` stamp must be visible mid-conversion without
  holding a transaction open across MarkItDown), the restore fast
  path's shared markdown keys against 032's distinct-key deletion, and
  that the claim-cap outerjoin preserves SKIP-LOCKED behavior under
  concurrent workers.
