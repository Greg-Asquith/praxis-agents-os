# Plan 034: Agent file tools and scratch space

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and move the governance cells listed in
> "Done criteria" to `[implemented: plan 034]`.
>
> **Sibling-plan pre-flight (run before Step 1)**: this plan was written in
> parallel with plans 030–033 and depends on their dictated contracts. Before
> coding, verify all of these exist in the codebase (not just as plan docs):
> `services/jobs/` with `enqueue_job` + `@job_handler` (030),
> `models/files.py` with `File`/`FileRevision`/`FileReference` and the
> file-contract policy (031), and `services/files/` with the upload/edit
> service operations (032). Plan 033 (`files.extract` markdown conversion) is
> a soft dependency — `read_file` degrades gracefully without it. If a hard
> dependency is missing, STOP. Where this plan quotes a sibling contract
> (model names, service signatures), the landed code wins — reconcile before
> coding, and report any semantic mismatch.
>
> **Drift check (run first)**: `git diff --stat 0cbbb39..HEAD -- apps/api/services/agents/runtime/ apps/api/models/ apps/api/core/settings/ apps/api/services/jobs/ apps/api/services/files/ apps/api/workers/`
> Changes under `services/jobs/`, `services/files/`, and `models/files.py`
> are *expected* (plans 030–032 landing). For any OTHER in-scope file that
> changed since `0cbbb39`, compare the "Current state" excerpts below against
> the live code before proceeding; on a mismatch, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (adds four agent-callable tools, one new table, a prompt
  block for every agent turn, and a dynamic approval path; nothing existing
  changes behavior except the system prompt gaining one block)
- **Depends on**: 031 + 032 (hard — File/FileRevision/FileReference models
  and the files service), 030 (hard — the scratch sweep rides the jobs
  harness), 033 (soft — converted markdown for ingestible reads), 018
  (DONE — `runtime/prompt.py` assembler; **Gate G2 satisfied**: the roadmap
  requires the `<available_files>` block to plug into the one designed
  system-prompt assembler, and that assembler exists), 025/026/028 (DONE —
  registry contract, dispatch choke point, registry-tool precedents)
- **Category**: Phase 3 files & jobs (roadmap `000_MASTER_ROADMAP.md` §4
  row 034; donor `DONOR_PORT_ROADMAP.md` §4.3 / §6 row B5)
- **Governance**: implements `docs/architecture/governance.md` §2 (approval
  defaults for `write_file`/`promote_scratch`) and §3 (scratch retention:
  7 d rolling TTL, purge on expiry, delete after promotion)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Four registry tools, one dispatch path.** `list_files`, `read_file`,
   `write_file`, `promote_scratch` register through the plan 025
   `@runtime_tool` decorator (`runtime/tools/registry.py:33-91`) and execute
   through the plan 026 dispatch choke point (`runtime/dispatch.py:127`), so
   audit rows, envelope checks, and output-contract validation come for
   free. Tool bodies stay thin; reusable logic lives in `services/files/`
   (032's package) and the new `services/scratch/`.
2. **One `write_file` tool with a dynamic approval branch.** Governance §2
   splits by target: scratch (Praxis-internal state) defaults `auto`;
   durable writes to real Files default `approval`. Per-tool mount policy
   cannot express that split, so `write_file` mounts with
   `default_policy=auto` and its body raises `ApprovalRequired` when
   `destination="file"` and `ctx.tool_call_approved` is false. This is the
   documented pydantic-ai pattern (conditional `ApprovalRequired`,
   `docs/pydantic-ai/03-tools-and-toolsets.md:284-290`; constructor probed:
   `ApprovalRequired(metadata: dict[str, Any] | None = None)`), and the 026
   dispatch already audits handler-raised `ApprovalRequired` as
   `approval_requested` (`dispatch.py:163-177`) — no dispatch changes.
   Denials replay as `ToolDenied` and are audited from the resume path
   (`dispatch.py:230-259`), also unchanged.
3. **`promote_scratch` mounts `default_policy=approval`** (`effect="write"`,
   `supports_auto=True` so per-agent policy may relax it — governance §2
   reserves `supports_auto=False` for money-spending tools only). Promotion
   creates a **new** File via 032's create path with agent provenance
   (`revision_kind="create"`); promoting onto an existing file name is a
   model-visible error in v1 — durable edits go through `write_file` with
   `destination="file"`.
4. **Scratch is a hard-deleted operational table.** `models/scratch.py`
   `ScratchEntry(Base, UUIDMixin, TimestampMixin)` — the `Job`/
   `RateLimitAttempt` composition (plan 030 decision 2), not soft-delete
   `BaseModel`. Governance §3 says purge content on expiry and delete after
   promotion; soft-delete columns would only poison the sweep predicate.
   Audit survival comes from dispatch audit rows ("rows summarized"), not
   from keeping scratch corpses.
5. **Scope is conversation XOR run, CHECK-enforced; v1 always writes
   conversation scope.** Every run in this codebase has a conversation
   (interactive, scheduled, and delegated runs all create one —
   `execute_run.py:107-112` loads run+conversation together), so
   conversation scope covers all principals today, including delegated
   sub-runs (each delegated run gets its own conversation, so parallel
   delegates cannot collide). The `run_id` column and XOR CHECK exist per
   the dictated 031-era contract for future conversation-less runs; writing
   run scope is out of scope here.
6. **Rolling 7 d TTL, refreshed on read AND write** (governance §3 "7 d
   rolling TTL"): every successful `write_file(destination="scratch")` and
   every scratch read stamps `expires_at = now + SCRATCH_TTL_DAYS`. The
   sweep job kind `scratch.sweep_expired` (registered on the 030 harness at
   its Step 3 assembly point, per 030 decision 6: "each later plan registers
   its own sweep kind") hard-deletes expired rows. Overwrite-in-place:
   one row per (scope, name), upserted.
7. **Size caps as settings**: `SCRATCH_MAX_ENTRY_BYTES` (256 KiB) and
   `SCRATCH_MAX_ENTRIES_PER_SCOPE` (20). Over-cap writes raise `ModelRetry`
   with the limit in the message (the `planning.py:49-50` precedent).
   Durable writes are capped by 032's existing enforcement of
   `MAX_FILE_SIZE_AGENT_FILE` (100 MB, `core/settings/files.py:67-72`,
   governance §4 *(enforced today)*).
8. **`read_file` has two modes.** `mode="content"` returns text with
   truncation hints (`offset`/`max_bytes` args, default cap
   `READ_FILE_MAX_CONTENT_BYTES` = 49152); for ingestible documents it
   returns 033's converted markdown when `processing_status == "ready"`,
   and a structured "processing pending/error — retry later or use url
   mode" message otherwise (soft 033 dependency, degrades honestly).
   `mode="url"` returns a short-lived signed download URL via the storage
   provider seam (`services/storage/provider.py:53`
   `create_signed_download`) for the agent to hand to the user. For images
   on vision-capable models, content mode returns
   `ToolReturn(return_value={...metadata...}, content=[BinaryContent(...)])`
   so the model actually sees the image — probed against installed
   pydantic-ai 2.1.0: `ToolReturn` fields are `return_value:
   ToolReturnContent`, `content: str | Sequence[UserContent] | None`,
   `metadata: Any` (`pydantic_ai.messages.ToolReturn`), and `BinaryContent`
   fields are `data: bytes`, `media_type: str`, `vendor_metadata`,
   `identifier` (alias). Vision capability comes from the existing catalog
   flag `ModelInfo.supports_vision` (`services/agents/models/domain.py:54`,
   set on every current entry in `services/agents/models/registry.py`).
   `read_file` declares **no `output_model`** — the dispatch validator
   (`dispatch.py:106-124`) would reject the polymorphic
   `ToolReturn`-vs-dict result; `list_files`, `write_file`, and
   `promote_scratch` declare output models normally.
9. **`<available_files>` prompt block, budgeted.** Loaded in `execute_run`
   beside `load_agent_skills` (`execute_run.py:113`), passed through
   `build_runtime_agent` into `runtime_prompt_blocks` (a new keyword
   parameter, matching how `skills` already threads through
   `loop.py:47,70`). The block lists conversation-attached files
   (FileReference rows with `target_type="conversation"`): id, name,
   contract category, media type, size, processing status — ids the model
   passes straight to `read_file`. Budget 4000 chars via the existing
   `PromptBlock.budget` soft-truncation (`prompt.py:73-85`). Empty list →
   empty block → omitted by `build_system_prompt` (`prompt.py:63-70`).
10. **Non-interactive principals need no special casing.** The 026 envelope
    already denies write tools when `side_effect_policy == "deny"`
    (`dispatch.py:91-103`); scheduled runs suspend on `ApprovalRequired`
    and resume through the existing approval path (026 decision,
    governance §2 *(enforced today)*); delegated runs inherit the parent
    envelope. Scratch being conversation-scoped (decision 5) keeps
    delegated sub-runs isolated for free. This plan adds tests proving the
    envelope denial and scheduled-suspend behavior for `write_file`.
11. **`search_files` is explicitly deferred** (donor §4.3 names it "rides
    the hybrid search engine once KB chunking exists") — it belongs to
    Phase 4b, not here.

## Why this matters

Files (031–033) exist so agents can use them. Without this plan the file
substrate is invisible to the model: uploads land, revisions accrue, and no
agent can list, read, or produce a file. Scratch is the donor's
cheapest-loved feature — a place for drafts and intermediate state that
costs nothing to write and requires human sign-off only when it graduates
to a durable File. The `<available_files>` block is the third consumer of
the Gate G2 assembler (after identity/planning/delegation and skills),
proving the "server-injected context, agent-driven retrieval" model the
roadmap targets (§1 Context pillar). And because all four tools ride the
026 dispatch, this plan is also the first real exercise of governance §2's
internal-vs-external write split.

## Current state

All anchors verified at `0cbbb39`.

- `apps/api/services/agents/runtime/tools/contract.py` —
  `RuntimeToolDefinition` (33-57): `name`, `function`, `effect`
  (read/write, line 43), `default_policy`, `supports_auto`/
  `supports_approval`, `timeout`, `output_model` (52), `configurable`,
  `auto_mount`. Invariant: write tools must support approval unless
  auto-mounted (171-176). `to_pydantic_tool` maps policy →
  `requires_approval` (96-106).
- `apps/api/services/agents/runtime/tools/registry.py` — `@runtime_tool`
  decorator with import-time validation + duplicate-name RuntimeError
  (33-91); provider modules imported for registration side effects at the
  bottom (254-258: `native`, `planning`) — **this is the assembly point
  Step 4 extends**. `build_runtime_tools` resolves per-agent policy
  (94-147).
- `apps/api/services/agents/runtime/tools/planning.py` — the
  internal-write precedent: `write_todos` registers `effect=TOOL_EFFECT_WRITE,
  supports_approval=False, auto_mount=True` (29-43), caps input via
  `ModelRetry` (49-50), upserts via `insert(...).on_conflict_do_update`
  (54-74). File tools follow the same always-on hidden-tool model:
  `configurable=False`, `auto_mount=True`, with their own default approval
  policy preserved at mount time.
- `apps/api/services/agents/runtime/tools/native/web_search.py` — the
  configurable-tool precedent with probe-findings docstring (5-19),
  `output_model=WebSearchOutput` (90), and catalog interplay (39,
  `get_model`).
- `apps/api/services/agents/runtime/dispatch.py` — the choke point:
  `dispatch_tool_execution` audits success/failure/denial (127-227);
  handler-raised `ApprovalRequired` audited as `approval_requested`
  (163-177); envelope denial for write tools (91-103); output validation
  only when `output_model` is set (106-124); denied approvals audited on
  resume (230-259).
- `apps/api/services/agents/runtime/context.py` — `RuntimeDeps` (18-30):
  `db`, `user`, `workspace`, `conversation`, `agent`, `run`, `sink`,
  `envelope`, `delegation_depth`. Everything the tools need is already
  there; **no RuntimeDeps change required**.
- `apps/api/services/agents/runtime/prompt.py` — the Gate G2 assembler:
  `PromptBlock(key, content, budget)` (39-45), `runtime_prompt_blocks(agent,
  *, include_delegation)` returns identity/planning/delegation (48-60),
  `build_system_prompt` joins non-empty blocks (63-70), `_render_block`
  soft-truncates over budget with a warning log (73-85).
- `apps/api/services/agents/runtime/loop.py` — `build_runtime_agent(agent, *,
  model, delegate_agents, enable_delegation, force_delegation_tools,
  skills)` (40-78); `_runtime_instructions` calls the assembler (87-90).
  `skills` threading (47, 70) is the pattern the new `available_files`
  parameter copies.
- `apps/api/services/agents/runtime/execute_run.py` — `load_agent_skills`
  called at 113, `build_runtime_agent(...)` at 159-166, `RuntimeDeps`
  construction at 176-186. The available-files load slots beside skills.
- `apps/api/services/agents/runtime/load_context.py` — `load_run_context`
  (22), `load_agent_skills` (88), `load_actor_context` (131): the loader
  module the new `load_available_files` joins.
- `apps/api/services/agents/runtime/envelope.py` — `SideEffectPolicy`
  allow/require_approval/deny (14), `build_run_envelope` (26-30).
- `apps/api/core/settings/files.py` — `MAX_FILE_SIZE_AGENT_FILE` 100 MB
  (67-72), `MAX_FILE_SIZE_DOCUMENT` 50 MB (49-54); governance §4 marks
  these *(enforced today)*.
- `apps/api/models/base.py` — `UUIDMixin` (18-21), `TimestampMixin`
  (24-30); non-soft-delete composition precedent
  `models/rate_limiting.py:16`. New models must be imported in
  `models/__init__.py`.
- Tests precedent: `tests/services/agents/runtime/` holds
  `test_planning_tools.py`, `test_dispatch.py`, `test_prompt_assembly.py`,
  `test_native_tools.py` — the shapes Step 6 follows. Async modules set
  `pytestmark = pytest.mark.asyncio`; DB tests skip without
  `TEST_DATABASE_URL`.
- Probed against installed **pydantic-ai 2.1.0** (record kept here, per the
  018/028/030 convention):
  - `ApprovalRequired(metadata: dict[str, Any] | None = None)` is raisable
    from a tool body ("conditional approval", docs digest 03:284-290);
    `RunContext` has a `tool_call_approved` field (verified via
    `dataclasses.fields`).
  - `pydantic_ai.messages.ToolReturn`: `return_value`, `content: str |
    Sequence[UserContent] | None`, `metadata`.
  - `pydantic_ai.messages.BinaryContent`: `data: bytes`, `media_type`,
    `vendor_metadata`, `identifier` (pydantic alias for `_identifier`);
    `is_image` property works.
  - `ImageMediaType` = jpeg/png/gif/webp; `DocumentMediaType` = pdf, plain,
    csv, docx, xlsx, html, markdown, msword, ms-excel.
- **Will exist after sibling plans (verify at pre-flight, do not assume
  shapes beyond the dictated contract)**: `models/files.py` — `File`
  (workspace-scoped, soft-delete, `processing_status`
  pending/processing/ready/error), immutable `FileRevision` (sha256
  `content_hash`, `revision_kind` create/edit/replace/restore/import,
  exactly-one-actor provenance), `FileReference` (`target_type`
  conversation/artifact/agent/schedule_run), file-contract policy
  (editable-text / ingestible-document / image with strict MIME↔extension
  pairs) (031); `services/files/` with two-phase upload, edit with
  `expected_current_revision_id`, restore, delete, signed downloads (032);
  `services/jobs/` `enqueue_job` + `@job_handler` + the self-rescheduling
  sweep pattern (030); `files.extract` markdown output (033).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations after Step 2 |
| Apply migration | `uv run alembic upgrade heads` | `scratch_entries` table created |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/scratch tests/services/agents/runtime -q` | all pass |
| Registry sanity | `uv run python -c "from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG; print(sorted(RUNTIME_TOOL_CATALOG))"` | includes `list_files`, `read_file`, `write_file`, `promote_scratch` |
| Sweep kind sanity | `uv run python -c "from services.jobs.registry import JOB_HANDLERS; print(sorted(JOB_HANDLERS))"` | includes `scratch.sweep_expired` |
| Runtime regression | `uv run pytest tests/services/agents -q` | all pass |

## Scope

**In scope:**

- `apps/api/core/settings/scratch.py` (create — `ScratchSettingsMixin`) +
  `apps/api/core/settings/__init__.py` (compose it)
- `apps/api/models/scratch.py` (create — `ScratchEntry`) +
  `apps/api/models/__init__.py` (register import)
- `apps/api/alembic/versions/core/` next revision (core branch, roadmap D5)
- `apps/api/services/scratch/` (create): `__init__.py`, `domain.py`,
  `upsert_scratch_entry.py`, `read_scratch_entry.py`,
  `list_scratch_entries.py`, `delete_scratch_entry.py`,
  `purge_expired_scratch.py`, `utils.py`
- `apps/api/services/jobs/handlers/sweep_expired_scratch.py` (create) +
  the jobs handlers assembly point import (per 030's Step 3 comment)
- `apps/api/services/agents/runtime/tools/files/` (create package —
  `__init__.py`, one file per tool, and shared `utils.py`) + the registration import in
  `runtime/tools/registry.py:254-258`
- `apps/api/services/agents/runtime/prompt.py` (extend —
  `available_files` block), `runtime/loop.py` (thread the parameter),
  `runtime/load_context.py` (add `load_available_files`),
  `runtime/execute_run.py` (call it)
- `apps/api/tests/services/scratch/` (create),
  `apps/api/tests/services/agents/runtime/test_file_tools.py` (create),
  `test_prompt_assembly.py` (extend)
- `docs/architecture/governance.md` (move the §2/§3 cells this plan
  implements to `[implemented: plan 034]`)

**Out of scope (do NOT touch):**

- HTTP routes and UI for files or scratch (035 owns the UI; 032 owns file
  routes). Scratch has **no public HTTP surface** — per AGENTS.md, that is
  documented as pending, not implied.
- `search_files` (decision 11 — Phase 4b).
- Multimodal chat attachments (036) — this plan only *lists* attached
  files in the prompt; it does not create FileReferences.
- The 032 files service internals — call them; never reimplement upload,
  dedup, or optimistic concurrency here.
- Writing run-scoped scratch (decision 5 — column + CHECK only).
- `RuntimeDeps`, `dispatch.py`, and the SSE event protocol — zero changes.
  Tool calls/results already stream through the existing
  `tool.call`/`tool.result` events; a new event name would break stale
  clients (the parser throws on unknown names,
  `apps/web/src/features/conversations/stream/sse.ts:74` — the 000_README
  skills precedent applies).

## Git workflow

- Branch: `advisor/034-agent-file-tools-scratch`
- Commit style: `API - Agent File Tools & Scratch Space`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Create `core/settings/scratch.py` with `ScratchSettingsMixin` (shape of
the plan 030 `JobsSettingsMixin`; all `Field(..., gt=0, description=...)`):

```python
SCRATCH_TTL_DAYS: int = 7                      # governance §3 rolling TTL
SCRATCH_MAX_ENTRY_BYTES: int = 262144          # 256 KiB per entry
SCRATCH_MAX_ENTRIES_PER_SCOPE: int = 20        # per conversation
SCRATCH_SWEEP_INTERVAL_SECONDS: int = 3600     # sweep self-reschedule cadence
READ_FILE_MAX_CONTENT_BYTES: int = 49152       # default content-mode slice
AVAILABLE_FILES_PROMPT_BUDGET: int = 4000      # prompt block soft budget
AVAILABLE_FILES_MAX_LISTED: int = 50           # newest-first cap in the block
```

Compose the mixin into `Settings` in `core/settings/__init__.py`. No
production-safety validator change (no local-only values).

**Verify**: `uv run python -c "from core.settings import settings; print(settings.SCRATCH_TTL_DAYS)"`
→ `7`; ruff exit 0.

### Step 2: Scratch model + core migration

Create `models/scratch.py` with
`ScratchEntry(Base, UUIDMixin, TimestampMixin)` (decision 4),
`__tablename__ = "scratch_entries"`:

- `workspace_id` UUID FK `workspaces.id`, not null, indexed
- `conversation_id` UUID FK `conversations.id` `ondelete="CASCADE"`,
  nullable; `run_id` UUID FK `agent_runs.id` `ondelete="CASCADE"`,
  nullable; CHECK `num_nonnulls(conversation_id, run_id) = 1` (the
  conversation-XOR-run contract, decision 5)
- `name` String(255) not null (snake-case-ish free name chosen by the
  model; validate non-blank + length in the service, not the DB)
- `content` Text not null; `content_bytes` Integer not null, CHECK
  `content_bytes >= 0`
- `expires_at` DateTime(tz) not null, indexed (sweep predicate)
- `created_by_run_id` UUID FK `agent_runs.id` `ondelete="SET NULL"`,
  nullable (provenance for the audit trail; the writing run)

Uniqueness for overwrite-in-place (decision 6) — two partial unique
indexes, since UNIQUE treats NULLs as distinct:

```sql
CREATE UNIQUE INDEX uq_scratch_conversation_name ON scratch_entries (conversation_id, name)
  WHERE conversation_id IS NOT NULL;
CREATE UNIQUE INDEX uq_scratch_run_name ON scratch_entries (run_id, name)
  WHERE run_id IS NOT NULL;
```

Import in `models/__init__.py`. Generate on the **core** branch (D5):
`uv run alembic revision --autogenerate --head core@head --version-path
alembic/versions/core -m "add scratch entries table"` — number against the
real core head at execution time (031/032 will have moved it past the
`core_0007` that exists at `0cbbb39`). Hand-check the partial unique
indexes and the CHECK made it into the migration (autogenerate often
misses both; add manually with matching `downgrade`).

**Verify**: `uv run alembic upgrade heads` applies; `uv run alembic check`
clean; downgrade/upgrade round-trips
(`uv run alembic downgrade core@-1 && uv run alembic upgrade heads`).

### Step 3: Scratch service (one operation per file)

`services/scratch/domain.py`: `SCRATCH_NAME_MAX_LENGTH = 255`, name
validation helper (non-blank, stripped), and a small frozen
`ScratchScope` dataclass (`conversation_id: UUID | None`,
`run_id: UUID | None`) with a constructor guard enforcing XOR.

- `upsert_scratch_entry.py` — `upsert_scratch_entry(db, *, workspace_id,
  scope: ScratchScope, name, content, created_by_run_id) -> ScratchEntry`.
  Validates name and size (`len(content.encode()) <=
  SCRATCH_MAX_ENTRY_BYTES` → raise `AppValidationError` from
  `core/exceptions/general.py:16` otherwise — typed, not HTTPException);
  enforces `SCRATCH_MAX_ENTRIES_PER_SCOPE` on insert (count query first;
  overwrite of an existing name is always allowed); upserts via
  `insert(...).on_conflict_do_update` against the matching partial unique
  index (the `planning.py:54-74` shape, but with `index_elements` +
  `index_where` since these are partial indexes, not named constraints);
  stamps `expires_at = now + SCRATCH_TTL_DAYS` and `content_bytes`.
- `read_scratch_entry.py` — returns the entry or None; on hit, refreshes
  `expires_at` (decision 6 rolling TTL) and flushes.
- `list_scratch_entries.py` — entries for a scope ordered by
  `updated_at desc`: name, `content_bytes`, `updated_at`, `expires_at`
  (no content — the model reads one entry at a time).
- `delete_scratch_entry.py` — hard delete by scope+name, returns bool
  (used by promotion, decision 3 / governance §3 "delete after
  promotion").
- `purge_expired_scratch.py` — `DELETE FROM scratch_entries WHERE
  expires_at < now()` returning the count (the sweep body).
- `services/scratch/__init__.py` re-exports operation functions only
  (AGENTS.md service-package rule).

**Verify**: ruff exit 0;
`TEST_DATABASE_URL=... uv run pytest tests/services/scratch -q` after
Step 6 writes the tests.

### Step 4: Sweep job kind

`services/jobs/handlers/sweep_expired_scratch.py`, copying the 030
`jobs.sweep_terminal` pattern exactly (self-rescheduling handler + an
idempotent `ensure_*` helper backed by the in-flight dedup index):

```python
@job_handler(kind="scratch.sweep_expired", timeout=120.0)
async def sweep_expired_scratch(db, job):
    # purge_expired_scratch(db); log count
    # self-reschedule: enqueue same kind, run_after = now + SCRATCH_SWEEP_INTERVAL_SECONDS
```

Register the module at the jobs handlers assembly point (the import 030's
Step 3 comment designates for 032/033/039/044/051), and add
`ensure_scratch_sweep_job(db)` to the worker's per-pass ensure call
alongside the jobs sweep — mirror however 032's file sweeper wired its
ensure at execution time; if 032 established a different bootstrap
convention, follow it and note the deviation.

**Verify**: the sweep-kind sanity command (Commands table) lists
`scratch.sweep_expired`; `uv run python -m workers.job_runner --once`
exits 0 with the sweep enqueued.

### Step 5: The four runtime tools

Create `services/agents/runtime/tools/files/`, registered from
`registry.py`'s assembly point (append to the import block at 254-258).
Use one file per tool plus a shared `utils.py`; the package `__init__.py`
imports/re-exports the tools and records the probe findings above. All four:
`provider="core"`, `takes_ctx=True`, sensible `timeout` (10–30 s; url mode
and image reads touch storage), `configurable=False`, `auto_mount=True`.
Scoping
law for every query: `workspace_id == ctx.deps.workspace.id` — a file id
from another workspace is a model-visible "not found" `ModelRetry`, never
an exception leak.

1. **`list_files`** — `effect=read`, `default_policy=auto`,
   `output_model=ListFilesOutput` (files: list of {id, name, category,
   media_type, size_bytes, processing_status, updated_at}, total, plus the
   scope's scratch entries as a separate `scratch` list so one call shows
   the model everything it can read). Args: optional `name_contains`,
   `limit` (default 25, max 100).
2. **`read_file`** — `effect=read`, `default_policy=auto`, **no
   `output_model`** (decision 8). Args: `file_id: UUID | None`,
   `scratch_name: str | None` (exactly one — else `ModelRetry`),
   `mode: Literal["content", "url"] = "content"`, `offset: int = 0`,
   `max_bytes: int | None`. Content mode: editable-text → current revision
   text sliced with a trailing
   `[truncated: showing bytes {a}-{b} of {n}; call again with offset={b}]`
   hint; ingestible-document → 033 markdown when ready, else the pending/
   error guidance (decision 8); image → `ToolReturn(return_value={...},
   content=[BinaryContent(data=..., media_type=...,
   identifier=str(file_id))])` when the resolved agent model's catalog
   entry has `supports_vision`, else a `ModelRetry` steering to url mode.
   Url mode: `create_signed_download` result (url + expiry) with an
   explicit "share this link with the user; it expires" note in the
   return. Scratch reads are always content mode.
3. **`write_file`** — `effect=write`, `default_policy=auto`,
   `supports_auto=True`, `supports_approval=True`,
   `output_model=WriteFileOutput` ({destination, name, file_id | None,
   revision_id | None, bytes_written, expires_at | None}). Args:
   `destination: Literal["scratch", "file"] = "scratch"`, `name`,
   `content: str`, `file_id: UUID | None` (durable edits target an
   existing file), `expected_current_revision_id: UUID | None`. Scratch
   branch: `upsert_scratch_entry` (free, auto — governance §2
   Praxis-internal). Durable branch: if not `ctx.tool_call_approved`,
   `raise ApprovalRequired(metadata={"destination": "file", "name": name,
   "bytes": len(content.encode())})` (decision 2 — governance §2 external
   side effects); once approved, route to 032's create-or-edit service op
   with agent provenance (`FileRevision` actor = agent, `revision_kind`
   `create` for new / `edit` with `expected_current_revision_id` for
   existing; a 032 concurrency conflict surfaces as `ModelRetry` telling
   the model to re-read). Durable content type is the editable-text
   contract category only — writing binary/base64 through a text tool is
   rejected with guidance.
4. **`promote_scratch`** — `effect=write`, `default_policy=approval`
   (decision 3), `output_model=PromoteScratchOutput` ({file_id,
   revision_id, name, deleted_scratch: true}). Args: `scratch_name`,
   `file_name: str | None` (defaults to scratch name + `.md`). Body:
   read scratch (miss → `ModelRetry`), create the durable File via 032
   (agent provenance, `revision_kind="create"`, `revision_kind="import"`
   is reserved for external sources — confirm against 031's landed
   vocabulary), then `delete_scratch_entry` (governance §3), return ids.

**Verify**: registry sanity command lists all four; `uv run pytest
tests/services/agents/runtime/test_tool_registry.py -q` still green
(catalog invariants hold); ruff exit 0.

### Step 6: `<available_files>` prompt block

1. `runtime/load_context.py`: add `load_available_files(db, conversation)
   -> list[AvailableFile]` — join `FileReference(target_type=
   "conversation", target id = conversation.id)` → `File` (not deleted),
   newest-first, capped at `AVAILABLE_FILES_MAX_LISTED`. `AvailableFile`
   is a small frozen dataclass (id, name, category, media_type,
   size_bytes, processing_status).
2. `runtime/prompt.py`: add a renderer producing the block —

   ```
   <available_files>
   These workspace files are attached to this conversation. Use read_file
   with the id to read one; use list_files to see everything available.
   - {id} — {name} ({category}, {media_type}, {size}, {status})
   </available_files>
   ```

   Extend the signature: `runtime_prompt_blocks(agent, *,
   include_delegation, available_files: Sequence[AvailableFile] = ())`,
   appending `PromptBlock("available_files", rendered,
   budget=settings.AVAILABLE_FILES_PROMPT_BUDGET)`. Empty sequence renders
   `""` and the assembler drops it (`prompt.py:65`).
3. `runtime/loop.py`: thread `available_files` through
   `build_runtime_agent` into `_runtime_instructions` (the `skills`
   pattern, 47/70/87-90).
4. `runtime/execute_run.py`: `available_files = await
   load_available_files(db, conversation)` beside `load_agent_skills`
   (113); pass it to `build_runtime_agent` (159-166). Resume runs load it
   the same way — instructions are rebuilt per turn, so the block stays
   current as attachments accrue (036 will rely on this).

**Verify**: `uv run pytest tests/services/agents/runtime/test_prompt_assembly.py -q`
green after extending it (Step 7); a quick REPL render with two fake files
shows the block; with zero files the system prompt is byte-identical to
before this plan (assert this in the tests — it pins that agents without
files see no change).

### Step 7: Tests

All async modules set `pytestmark = pytest.mark.asyncio`; DB-backed tests
use `conftest.py` fixtures and skip without `TEST_DATABASE_URL`; live LLM
calls are blocked in tests (runtime tool tests call tool functions with a
stubbed `RunContext`/`RuntimeDeps`, the `test_planning_tools.py` shape).

`tests/services/scratch/`:

- `test_upsert_and_read.py`: create; overwrite-in-place keeps one row;
  over-size rejected with `AppValidationError`; entry-count cap enforced
  on new names but not overwrites; read refreshes `expires_at`; XOR guard
  rejects both-or-neither scopes.
- `test_purge_expired.py`: expired rows deleted, live rows kept; the
  sweep handler purges and re-enqueues itself (031/030 fixtures).

`tests/services/agents/runtime/test_file_tools.py`:

- `list_files` returns workspace files + scratch, respects `limit`, and
  never leaks another workspace's files (build two workspaces).
- `read_file` content mode slices with a truncation hint; offset
  continuation works; ingestible without markdown → pending guidance;
  ingestible with markdown → markdown; image + vision model →
  `ToolReturn` with one `BinaryContent` whose `identifier` is the file id;
  url mode returns a signed url; wrong-workspace id → `ModelRetry`.
- `write_file` scratch branch writes without approval and returns
  `expires_at`; durable branch raises `ApprovalRequired` when
  `tool_call_approved` is false and writes via 032 when true; 032
  concurrency conflict → `ModelRetry`.
- `promote_scratch` creates a File with agent provenance and deletes the
  scratch entry; missing scratch → `ModelRetry`.
- Envelope: `side_effect_policy="deny"` blocks `write_file` and
  `promote_scratch` through `dispatch_tool_execution` with a
  `denied_envelope` audit row, and leaves the read tools alone
  (decision 10; extend or mirror `test_dispatch.py`).

`tests/services/agents/runtime/test_prompt_assembly.py` (extend): block
renders ids/names/status; obeys the budget (truncation warning path);
zero files → unchanged prompt.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/scratch tests/services/agents/runtime -q`
→ all pass; without the env var the DB tests skip, not fail.

## Test plan

Covered by Step 7 (~20–26 tests). Pinned invariants: **workspace isolation
on every tool path** (a foreign file id is indistinguishable from a missing
one), **the governance §2 split is real** (scratch writes never require
approval; durable writes always do until approved; `promote_scratch`
defaults to approval), **governance §3 lifecycle** (rolling TTL refresh,
purge on expiry, delete after promotion), and **agents without files see a
byte-identical system prompt**.

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` clean; migration on the **core** branch and
      downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/scratch tests/services/agents/runtime -q` exits 0
- [ ] Registry sanity lists exactly the four new tools; jobs registry
      lists `scratch.sweep_expired`
- [ ] `uv run pytest tests/services/agents tests/services/conversations -q`
      green (no runtime regression)
- [ ] No HTTP routes added for scratch; no SSE protocol change
      (`grep -r "scratch" apps/api/routes/` is empty)
- [ ] `docs/architecture/governance.md`: §2 cells for internal-write auto +
      external-write approval, and the §3 Scratch row, moved to
      `[implemented: plan 034]` (the §Consumed By table already names 034)
- [ ] Probe-findings docstring present in `runtime/tools/files/__init__.py`
- [ ] `docs/plans/000_README.md` status row updated (add the 034 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- The sibling-plan pre-flight fails: 030/031/032 are not implemented in
  code at execution time, or their landed contracts differ semantically
  from the dictated vocabulary quoted here (e.g. `FileReference` lacks
  `target_type="conversation"`, `FileRevision.revision_kind` values
  differ, or 032 has no agent-provenance create/edit seam).
- The prompt-assembler API changed: `runtime_prompt_blocks` /
  `build_system_prompt` / `PromptBlock` no longer match the "Current
  state" excerpts (something else extended the assembler first —
  reconcile ordering before adding a block).
- The pydantic-ai probe records above do not match the installed package
  at execution time (`ApprovalRequired` from a tool body, `ToolReturn`
  fields, `BinaryContent` fields) — re-probe and reconcile before coding.
- You feel the need to add a new SSE event name — that requires shipping
  the client whitelist first (000_README skills precedent); this plan
  must not need it.
- `dispatch.py` no longer audits handler-raised `ApprovalRequired`
  (decision 2's foundation) — the dynamic-approval design needs
  rethinking, not patching.
- A `scratch_entries` table, `services/scratch/`, or
  `runtime/tools/files/` already exists.
- Existing `tests/services/agents/runtime` tests fail before your changes.

## Maintenance notes

- **036 consumes this plan's block**: chat attachments (FileReference
  target conversation) appear in `<available_files>` automatically once
  036 creates the references — no prompt work should be needed there. If
  036 lands first in some order shuffle, the block simply renders empty.
- **Dynamic approval is a pattern now**: `write_file`'s conditional
  `ApprovalRequired` is the template for any future tool whose approval
  depends on arguments (041's spend-guard tools may want it). Keep the
  metadata dict small and human-legible — the approval UI renders it.
- **`read_file` image returns and plan 013**: history trimming treats
  `ToolReturn` content parts like any other tool return; add a multimodal
  tool-return fixture here if image-return support expands the file tools.
- **Scratch stays conversation-scoped until someone needs run scope** —
  the first conversation-less run type (if ever) flips decision 5; the
  CHECK and column are already there.
- Reviewers should scrutinize: workspace scoping on every query, the
  partial-unique upsert (`index_elements` + `index_where` must target the
  right partial index), TTL refresh on read (easy to forget), the
  approval metadata leaking file content (it must carry sizes/names, never
  content), and that `list_files` output stays digest-sized (no content in
  tool results that land in audit args).
