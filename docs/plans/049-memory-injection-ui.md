# Plan 049: Core-memory prompt injection, memory routes, and memory UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Amendment (2026-07-07, plan 075 — prompt-injection threat model)**:
> core-memory rendering is threat-model.md §2(b) — content interpolated
> into the system prompt is the highest-authority laundering target.
> Three deltas to the Step 1 formatter and Step 4 tests: (1) rendered
> title/content are escaped per threat-model §3 — text mimicking the
> block's own header or line format (e.g. a title of `## Instructions`)
> must not be renderable as additional lines or headers; (2) stored
> provenance is surfaced in the rendered line (e.g. an `agent-written` /
> `user-written` tag) **or** the rejection of that default is recorded in
> threat-model §2(b) with rationale — decision 4 currently strips at
> render what 048 deliberately stores; (3) Step 4 gains a red-team
> rendering test: hostile memory fixtures (shared set, §4) render inert,
> with byte-level assertions that fixture text cannot escape its line,
> forge the `## Memory` header, or impersonate the `memory_policy` block.
>
> **Gate pre-flights (run before Step 1)**:
> - **048 is landed**: `agent_memories` exists, the four memory tools are in
>   the registry, and `services/memories/` exposes the Step-4 seams 048's
>   maintenance notes promise (`effective_confidence`, `scope_filter`,
>   `get_memory`, `MEMORY_CORE_CHAR_BUDGET`). This plan cannot start
>   without them.
> - **G2** — plan 018 is DONE (verified 2026-07-06): injection composes
>   through the prompt assembler (`services/agents/runtime/prompt.py`), the
>   one designed system-prompt assembly point. Do not render memories into
>   the prompt anywhere else.
> - **G3** — `docs/architecture/governance.md` exists (029 DONE
>   2026-07-06). This plan implements the §1 memory rows and the §3
>   "hard-delete only by user action" clause — flip those cells to
>   `[implemented: plan 049]` in the same PR.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/services/agents/runtime/ apps/api/routes/ apps/api/services/memories/ apps/api/core/dependencies.py apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/features/`
> In-scope files WILL have changed since `0cbbb39` (048 and earlier phases
> land in between). Re-verify every "Current state" excerpt against the
> live code; treat an *unexplained* mismatch (one not accounted for by a
> landed plan) as a STOP condition.

## Status

- **Priority**: P1 (completes Phase 5; memory without a human surface
  violates the "human-legible memory" design principle)
- **Effort**: L
- **Risk**: MEDIUM — the injection block touches every runtime turn's
  system prompt (a formatting bug degrades all agents at once), and the
  routes expose cross-scope data (a wrong visibility predicate leaks
  user-scope memories).
- **Depends on**: **hard** — 048 (model, write service, tools, settings,
  eval harness). Gate G2 (018 DONE — assembler), Gate G3
  (`docs/architecture/governance.md` §1/§3). Soft: 023's audit-viewer UI
  patterns (detail dialog), 019's skills feature layout (frontend
  precedent).
- **Category**: Phase 5 memory (roadmap `000_MASTER_ROADMAP.md` §4 Phase 5
  row 049; donor `DONOR_PORT_ROADMAP.md` §4.5 / §6 row E2)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Injection follows the skills loading pattern.** `build_runtime_agent`
   is synchronous and builds instructions from the agent row alone
   (`runtime/loop.py:40-90`), so the DB fetch happens where skills already
   do: `execute_run` loads data (`load_agent_skills`, `execute_run.py:113`)
   and passes it into `build_runtime_agent(..., skills=skills)`
   (`execute_run.py:159-166`, parameter at `loop.py:47`). This plan adds
   `core_memory_block: str = ""` the same way: a new
   `services/memories/core_block.py` loads + renders it in `execute_run`,
   and `runtime_prompt_blocks` gains the parameter and inserts
   `PromptBlock("memory", core_memory_block, budget=...)` directly after
   `identity`. One assembler, per Gate G2.
2. **The formatter enforces the hard budget; the block budget is a
   backstop.** `PromptBlock.budget` is soft — `_render_block`
   (`prompt.py:73-85`) truncates with `[truncated]` and logs. The
   `render_core_memory_block` formatter therefore does its own hard
   character budgeting (`MEMORY_CORE_CHAR_BUDGET`, default 2000, from 048
   settings) via greedy importance-ranked selection, and passes the same
   number as the `PromptBlock` budget so the backstop can only fire on a
   formatter bug (the warning log is then the alarm).
3. **Ranking is global across scopes, deterministic, summary-plus-pointers**
   (donor §4.5 context-formatter pattern). Candidates: `active` `core`
   memories for the three visible scopes (agent-scope pinned to the run's
   agent, user-scope to the run's user, workspace-scope), fetched through
   048's `scope_filter` and the partial core-lookup index. Sort key:
   `importance` desc, `effective_confidence` desc, `last_reinforced_at`
   (fallback `created_at`) desc, `id` asc as the final tiebreak — fully
   deterministic so the rendered block (and the provider prompt-cache
   prefix) only changes when memories actually change. No per-scope quotas
   in v1; revisit only with eval evidence (Gate G4 harness exists).
   Omitted memories become one pointer line, and every clamped line points
   at `search_memory` — the block is a summary whose details are one tool
   call away.
4. **No timestamps, counters, or other volatile values are rendered** into
   the block — decay-derived ordering may use them, but the rendered text
   carries only scope/type/title/content. This is the prompt-cache
   discipline plan 013 depends on (memory is prompt-side, not
   history-side; a byte-stable prefix between memory writes keeps provider
   prefix caches hitting).
5. **Route delete archives; purge is the explicit hard delete.**
   `DELETE /memories/{id}` archives with `archive_reason='user_deleted'`
   (memories are never hard-deleted by default, `governance.md` §3);
   `DELETE /memories/{id}?purge=true` is the §3 "hard-delete only by user
   action" clause — it removes the row (audit rows survive via SET NULL
   FKs, `models/audit_event.py:17-22`). Both are audited with
   `AuditResourceType.MEMORY`.
6. **RBAC per `governance.md` §1, with one recorded interpretation.**
   Enforced rows: workspace-scope memory *delete/purge* is admin+
   (`MANAGER_ROLES`); own-scope (user/agent) edit/delete is member+
   (`EDITOR_ROLES`); all listing/read is read_only+ (`READ_ROLES`).
   Interpretations this plan records into the note: (a) *user-scope
   memories are visible and mutable only to their owning user* — they are
   personal context, and §1's "own-scope" language supports it; (b)
   *workspace-scope edit* (not listed in §1) is member+, matching the KB
   documents row. Enforcement lives in `services/memories/authorisation.py`
   (the `agent_schedules/authorisation.py` precedent), not scattered
   through routes.
7. **Route edits reuse 048's service semantics**: a content change
   supersedes (new row, `source='user'`, `created_by='user'`); metadata
   changes edit in place. The UI therefore gets supersession-chain edit
   history for free, and there is exactly one write path for agents and
   humans.
8. **Detail/edit is a Dialog on the table, not a detail route.** The
   audit viewer precedent (`features/audit/components/audit-event-detail.tsx`
   uses `Dialog` from `components/ui/dialog.tsx`; there is no sheet/drawer
   primitive in `components/ui/`). Memories are small records — a dense
   single-page table with filters plus a detail dialog beats a
   route-per-memory. One route: `/memories`.
9. **Navigation entry "Memory"** with lucide `BrainIcon`, placed between
   Skills and Schedules in `config/navigation.ts`, visible to all roles
   (read access is read_only+ per §1; user-scope filtering happens
   server-side).
10. **No helper-LLM usage.** The block is mechanical formatting. If a
    memory summarizer is ever wanted, follow the conversation-naming
    precedent (`services/conversations/naming.py:16`,
    `resolve_naming_model`) — recorded so nobody reaches for the primary
    agent model.
11. **List responses return effective confidence, not raw confidence
    alone.** Read-time decay (048 decision 7) is part of the product
    surface: the UI shows what the runtime actually believes, plus the
    stored base value in the detail view.

## Why this matters

Roadmap Targets §1.3: "Nothing an agent can do is invisible: memories are
editable." 048 gives agents a memory they can write; without this plan
that memory is a black box — invisible in the product, uncorrectable by
the humans it describes, and never actually injected, so agents don't
benefit from their own core memories. This plan closes the loop in both
directions: core memories flow into every run's system prompt through the
one designed assembler (Gate G2's entire point), and a first-class Memory
surface lets users read, correct, and delete anything an agent remembered
— the direct mitigation for memory poisoning that approval flows alone
can't provide, and a genuine differentiator over black-box extraction
pipelines (donor §4.5).

## Current state

Anchors verified at `0cbbb39` unless marked as an 048 deliverable.

- **Prompt assembler (018)**: `runtime/prompt.py:39-45` `PromptBlock(key,
  content, budget=None)`; `runtime_prompt_blocks(agent, *,
  include_delegation)` (48-60) returns `identity`/`planning`/`delegation`
  blocks (048 adds `memory_policy`); `build_system_prompt` (63-70) joins
  non-empty blocks; soft-budget truncation in `_render_block` (73-85).
- **Runtime construction**: `runtime/loop.py:40-78` `build_runtime_agent`
  is sync; `skills: Sequence[Skill] = ()` at line 47 is the
  caller-loads-and-passes precedent; `_runtime_instructions` (87-90) calls
  the assembler. `runtime/execute_run.py:113` `load_agent_skills`, call
  site 159-166, `RuntimeDeps` built at 176-186. Delegated runs re-enter
  through the same `execute_run`, so injection lands for interactive,
  scheduled, and delegated principals with zero extra wiring.
- **048 deliverables this plan consumes** (verify at execution):
  `models/agent_memories.py` (status/kind/scope columns, partial
  core-lookup index `(workspace_id, scope, agent_id, user_id) WHERE
  status='active' AND kind='core'`), `services/memories/` ops +
  `utils.effective_confidence` + `utils.scope_filter` +
  `authorisation.py` skeleton, `MemorySettingsMixin`
  (`MEMORY_CORE_CHAR_BUDGET=2000`), `AuditResourceType.MEMORY`, and the
  Gate G4 eval-test harness under `tests/services/memories/`.
- **Route conventions**: route-per-file packages composed in
  `routes/<domain>/__init__.py` (e.g. `routes/skills/__init__.py`);
  top-level registration in `routes/__init__.py:23-35`
  (`api_router.include_router(...)`, alphabetical). Operation shape:
  `routes/skills/list_skills.py` — `AsyncDbSessionDep` +
  `CurrentWorkspaceDep` (returns `(workspace, membership)`), paginated
  `Query` params, typed response models from the service `schemas.py`.
- **RBAC machinery**: `core/dependencies.py:243` `require_role`, shortcuts
  `require_owner`/`require_editor`/`require_read` (267-269); role sets in
  `services/workspaces/utils.py:24-31`. Service-level authorisation
  precedent: `services/agent_schedules/authorisation.py` (owner-or-admin
  mutation checks cited by `governance.md` §1).
- **Audit writer**: `services/audit_events/workspace_events.py:19`
  `record_workspace_audit_event(db, *, request, workspace_id, action,
  resource_type, resource_id, actor, details, status=...)` — used by
  skills routes (`services/skills/create_skill.py:52`).
- **Exceptions**: `core/exceptions/general.py:16/52/91`
  (`AppValidationError`/`NotFoundError`/`ConflictError`),
  `core/exceptions/auth.py:41` (`AuthorizationError`) — RFC 7807 mapped;
  no ad-hoc `HTTPException`.
- **Frontend feature layout precedent** (`features/skills/`, plan 019):
  `api/` one file per operation (`list-skills.ts` shows the pattern:
  `queryOptions` factory + `useSuspenseQuery` hook + structured
  `skillsQueryKeys` scoped by `getActiveWorkspaceSlug()`), `components/`,
  `routes/`, `types.ts` with snake_case fields mirroring the API and
  `type` aliases only. Mutations invalidate via the key factory.
- **Router**: code-based tree in `apps/web/src/app/router.tsx`; skills
  routes at lines 159-183 show the `createRoute` + `lazyRouteComponent`
  shape; routes registered in the `appRoute` children list (~line 249).
- **Navigation**: `apps/web/src/config/navigation.ts:29-65`
  `mainNavigation` array; Skills entry at lines 41-46;
  `navigationItemsForRole` filters `managerOnly` items.
- **UI primitives**: `components/ui/` has `dialog.tsx`, `table.tsx`,
  `select.tsx`, `badge.tsx`, `pagination-controls.tsx`, `empty-state.tsx`
  — no sheet/drawer (decision 8). Audit detail dialog precedent:
  `features/audit/components/audit-event-detail.tsx:4-6`.
- **Frontend gate**: no test framework; `pnpm check` (typecheck, eslint
  zero-warnings, prettier, knip, dependency-cruiser, build) is the gate.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Backend lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Backend tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/memories tests/routes/memories tests/services/agents -q` | all pass |
| Injection smoke | `cd apps/api && uv run pytest tests/services/memories/test_core_memory_block.py -q` | all pass |
| Frontend gate | `cd apps/web && pnpm check` | exit 0, zero warnings |
| Frontend dev | `cd apps/web && pnpm dev` | `/memories` renders |

## Scope

**In scope:**

- `apps/api/services/memories/core_block.py` (create — loader + budgeted
  formatter) and `services/memories/schemas.py`, `list_memories.py`,
  `get_memory_detail.py`, `edit_memory.py`, `remove_memory.py` (create —
  route-facing ops wrapping 048 services) + fill `authorisation.py`
- `apps/api/services/agents/runtime/prompt.py` (edit —
  `core_memory_block` parameter + `memory` block),
  `runtime/loop.py` (edit — pass-through parameter),
  `runtime/execute_run.py` (edit — load + pass, the skills pattern)
- `apps/api/routes/memories/` (create): `__init__.py`,
  `list_memories.py`, `get_memory.py`, `update_memory.py`,
  `delete_memory.py`; register in `routes/__init__.py`
- `apps/api/tests/services/memories/test_core_memory_block.py`,
  `apps/api/tests/routes/memories/` (create)
- `apps/web/src/features/memories/` (create): `types.ts`, `api/`
  (`list-memories.ts`, `get-memory.ts`, `update-memory.ts`,
  `delete-memory.ts`), `components/` (`memories-table.tsx`,
  `memory-filter-bar.tsx`, `memory-detail-dialog.tsx`,
  `memory-edit-form.tsx`, `memory-form-model.ts`,
  `supersession-chain.tsx`), `routes/memories-route.tsx`
- `apps/web/src/app/router.tsx` (edit — `/memories` route),
  `apps/web/src/config/navigation.ts` (edit — Memory entry)
- `docs/architecture/governance.md` (edit — flip §1 memory rows and the
  §3 user-action hard-delete cell to `[implemented: plan 049]`; record
  decision 6's interpretations)

**Out of scope (do NOT touch):**

- The memory model, write service internals, tools, dedup/decay math, job
  kinds — 048 owns them; this plan only calls them.
- Note injection of any kind — notes reach the model exclusively through
  `search_memory` (donor §4.5: "notes come only through search").
- Memory creation from the UI. Memories are written by agents (tools) or
  edited by humans; a "new memory" form is not in Phase 5 — document as
  pending if asked.
- Per-scope injection quotas, rerankers, consolidation — eval-gated
  follow-ups (Gate G4).
- History trimming (013), skills/files/KB prompt blocks — siblings that
  compose through the same assembler; do not reorder their blocks.
- Approval-queue UI changes — core-write approvals ride the existing
  conversation approval treatment from 026/008.

## Git workflow

- Branch: `advisor/049-memory-injection-ui`
- Commit style: `API - Core Memory Injection & Routes` for backend work,
  `Web - Memory UI` for frontend work (split commits along that line)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Budgeted core-memory formatter

Create `services/memories/core_block.py` with two functions:

```python
async def load_core_memories(db, *, workspace, agent, user) -> list[AgentMemory]:
    # active core rows for the three visible scopes, via 048's scope_filter,
    # riding the partial core-lookup index; no LIMIT — the cap (048
    # MEMORY_CORE_MAX_PER_SCOPE) bounds it at 3 * 20 rows worst case.

def render_core_memory_block(memories, *, now, budget) -> str:
    # deterministic, hard-budgeted, summary-plus-pointers (decisions 2-4)
```

Rendering algorithm (pin in the docstring):

1. Rank by `(-importance, -effective_confidence(memory, now=now),
   -(last_reinforced_at or created_at), id)` — `id` as the final tiebreak
   makes the ordering total and the output byte-stable (decision 3).
2. Format each memory as one line:
   `- [{scope} {memory_type}] {title}: {content_md}` with newlines in
   content flattened to spaces. Lines longer than
   `MEMORY_CORE_LINE_MAX_CHARS` (new 048-mixin setting, default 300) are
   clamped at a word boundary with the pointer suffix
   `… (full text: search_memory("{title}"))` — each line carries the call
   that fetches its detail (donor summary-plus-pointers pattern).
3. Greedily append ranked lines while the running total (header + lines +
   reserved footer) stays ≤ `budget`. Never truncate mid-line: a line that
   doesn't fit is skipped and counted as omitted (do not continue scanning
   more than the ranked list — order is significance order).
4. Header: `## Memory` plus two fixed sentences: these are standing
   memories saved from previous work; verify anything surprising and use
   `search_memory` for details and notes.
5. Footer (only when memories were omitted):
   `{n} more core memories not shown — retrieve them with search_memory.`
6. Zero core memories → return `""` (the assembler drops empty blocks,
   `prompt.py:65`).

No timestamps, confidences, ids, or counts other than the omitted count
appear in the output (decision 4).

**Verify**: `uv run pytest tests/services/memories/test_core_memory_block.py -q`
(written in Step 4) passes; ruff exit 0.

### Step 2: Runtime wiring through the assembler

Three small edits, mirroring the skills pattern exactly (decision 1):

- `runtime/prompt.py` — `runtime_prompt_blocks(agent, *,
  include_delegation, core_memory_block: str = "")`; insert
  `PromptBlock("memory", core_memory_block,
  budget=settings.MEMORY_CORE_CHAR_BUDGET)` immediately after the
  `identity` block (order: identity, memory, then 048's `memory_policy`
  and the existing planning/delegation blocks — memories are context,
  policy/planning are behavior).
- `runtime/loop.py` — `build_runtime_agent(..., core_memory_block: str =
  "")` passed through `_runtime_instructions` to the assembler.
- `runtime/execute_run.py` — next to `load_agent_skills` (line 113):

  ```python
  core_memories = await load_core_memories(db, workspace=workspace, agent=agent, user=user)
  core_memory_block = render_core_memory_block(
      core_memories, now=datetime.now(UTC), budget=settings.MEMORY_CORE_CHAR_BUDGET
  )
  ```

  passed into the `build_runtime_agent` call at 159-166. Note the ordering
  constraint: `load_actor_context` (line 150) resolves `user`/`workspace`
  — the memory load goes after it. Delegated and scheduled runs flow
  through this same function, so all three principals get injection; the
  delegate agent's *own* agent-scope memories load for the delegated run
  (its `agent` is the delegate), which is the intended isolation.

**Verify**: `uv run pytest tests/services/agents -q` green (existing
prompt tests updated for the new parameter, not weakened); a runtime test
asserts a core memory's title appears in the built instructions and a
note-kind memory's does not.

### Step 3: Memory routes + authorisation

Fill `services/memories/authorisation.py` (decision 6) with the whole
matrix in one place:

```python
def visible_memory_filter(*, workspace_id, user_id):   # list/read predicate:
    # workspace + (scope != 'user' OR user_id == current) — user scope is owner-only
def ensure_can_edit_memory(memory, *, membership, user) -> None:    # member+; user-scope owner-only
def ensure_can_delete_memory(memory, *, membership, user) -> None:  # edit rules + workspace scope admin+
```

Raise `AuthorizationError` (`core/exceptions/auth.py:41`) on denial.

Route-facing service ops (one per file; `schemas.py` holds the Pydantic
response models):

- `list_memories.py` — filters `scope`, `kind`, `memory_type`, `agent_id`,
  `status` (default `active`; `superseded`/`archived` opt-in), `limit`
  (≤ 200, default 50), `offset`; ordered `updated_at` desc; each item
  carries `effective_confidence` (decision 11). Returns
  `MemoriesListResponse {memories: list[MemoryResponse], total: int}`.
- `get_memory_detail.py` — one row plus its supersession chain: walk
  predecessors (rows whose `superseded_by_id` points at the current
  lineage) and successors (follow `superseded_by_id`) into
  `MemoryDetailResponse {memory, chain: list[MemoryChainEntry]}` ordered
  oldest→newest; chain entries are visibility-filtered like everything
  else.
- `edit_memory.py` — wraps 048's `update_memory` with user-minted
  provenance (`source='user'`, `created_by='user'`) after
  `ensure_can_edit_memory`; content change supersedes (decision 7) and the
  response returns the *current* (possibly new) row.
- `remove_memory.py` — after `ensure_can_delete_memory`: default archives
  with `archive_reason='user_deleted'`; `purge=True` hard-deletes the row
  (decision 5). Both paths audit via `record_workspace_audit_event`
  (`AuditAction.DELETE`, `AuditResourceType.MEMORY`, details include
  scope/kind/purge flag).

`routes/memories/` (route-per-file; `router = APIRouter(prefix="/memories",
tags=["memories"])` in `__init__.py`; register alphabetically in
`routes/__init__.py`):

| File | Operation | RBAC |
|------|-----------|------|
| `list_memories.py` | `GET /memories/` with the filter/pagination query params | `require_read` + visibility filter |
| `get_memory.py` | `GET /memories/{memory_id}` → detail + chain | `require_read` + visibility filter |
| `update_memory.py` | `PATCH /memories/{memory_id}` body `{title?, content_md?, importance?, expires_in_days?}` | `require_editor` + `ensure_can_edit_memory` |
| `delete_memory.py` | `DELETE /memories/{memory_id}?purge=false` → 204 | `require_editor` + `ensure_can_delete_memory` (workspace scope: admin+ inside the check) |

Routes stay thin (AGENTS.md): dependency wiring + one service call each.

**Verify**: `uv run ruff check .` exit 0; manual smoke with two users in
one workspace confirms user-scope rows are absent from the other user's
list.

### Step 4: Backend tests

- `tests/services/memories/test_core_memory_block.py` (mostly no-DB, plus
  one DB loader test): budget never exceeded across sizes (property-style
  loop over budgets 200/500/2000); ranking order pinned (importance beats
  confidence beats recency; id tiebreak); line clamp adds the
  `search_memory` pointer at a word boundary; omitted-count footer exact;
  empty input → `""`; determinism — same rows in shuffled input order
  render byte-identical output; rendered text contains no timestamps or
  ids; DB loader returns core-kind active rows for exactly the three
  visible scope tuples and never another agent's or user's.
- `tests/routes/memories/` (`pytestmark = pytest.mark.asyncio`, conftest
  fixtures, skip without `TEST_DATABASE_URL`): RBAC matrix — read_only can
  list but not PATCH/DELETE (403); member edits agent-scope, cannot delete
  workspace-scope (403); admin deletes workspace-scope; user B never sees
  or mutates user A's user-scope rows (list omits; GET/PATCH/DELETE 404);
  DELETE default archives (row present, `status='archived'`,
  `archive_reason='user_deleted'`) and `?purge=true` removes the row, both
  leaving `AuditResourceType.MEMORY` audit rows; PATCH content change
  returns a new id and GET on the old id shows the chain; filters and
  pagination behave; archived rows excluded from default lists.
- Extend the runtime suite (Step 2's verify): injection includes core,
  excludes notes, and delegated-run injection uses the delegate's
  agent-scope memories.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/memories tests/routes/memories tests/services/agents -q`
→ all pass; skip cleanly without the env var.

### Step 5: Frontend types + API operations

`src/features/memories/types.ts` — snake_case mirroring the API
(`features/skills/types.ts` precedent), `type` aliases only:

```ts
export type MemoryScope = "agent" | "user" | "workspace"
export type MemoryKind = "core" | "note"
export type MemoryType = "fact" | "preference" | "episode" | "outcome"
export type MemoryStatus = "active" | "superseded" | "archived"
export type Memory = {
  id: string; scope: MemoryScope; kind: MemoryKind; memory_type: MemoryType
  status: MemoryStatus; title: string; content_md: string
  importance: number; confidence: number; effective_confidence: number
  agent_id: string | null; user_id: string | null
  source: "interactive" | "scheduled" | "delegated" | "user"
  created_by: "agent" | "user"
  expires_at: string | null; superseded_by_id: string | null
  archived_at: string | null; archive_reason: string | null
  created_at: string; updated_at: string
}
export type MemoriesListResponse = { memories: Memory[]; total: number }
export type MemoryDetailResponse = { memory: Memory; chain: Memory[] }
```

`api/` one file per operation, all through `apiRequest` from
`src/lib/api/client.ts` (never raw `fetch`):

- `list-memories.ts` — `memoriesQueryKeys` factory scoped by
  `getActiveWorkspaceSlug()` (clone the `skillsQueryKeys` shape from
  `features/skills/api/list-skills.ts`), `memoriesQueryOptions(params)`,
  `useMemoriesQuery(params)`; params: scope/kind/memory_type/agent_id/
  status/limit/offset.
- `get-memory.ts` — `memoryDetailQueryOptions(memoryId)` +
  `useMemoryDetailQuery`.
- `update-memory.ts` — `useUpdateMemoryMutation` (PATCH), invalidates
  `memoriesQueryKeys.workspace()` on success (a content edit changes ids,
  so invalidate broadly rather than seeding the detail).
- `delete-memory.ts` — `useDeleteMemoryMutation({memoryId, purge})`,
  same invalidation.

**Verify**: `pnpm typecheck` (or `pnpm check` subset) exit 0.

### Step 6: Memory UI + router + navigation

Components (dense, operational — AGENTS.md UI rules; shadcn primitives
from `components/ui/`, no new hand-built widgets):

- `memories-table.tsx` — the surface: columns Title, Scope (badge),
  Kind (badge — `core` visually distinct), Type, Agent (name when
  agent-scope), Confidence (effective, as a percentage), Updated; row
  click opens the detail dialog; `pagination-controls.tsx` at the foot;
  `empty-state.tsx` copy explains that agents save memories as they work.
- `memory-filter-bar.tsx` — selects for scope/kind/type/agent + a status
  toggle (Active / Archived / Superseded), driving the list query params
  (the `audit-filter-bar.tsx` pattern).
- `memory-detail-dialog.tsx` — full content_md, provenance line (created
  by agent/user, source, dates), stored vs effective confidence,
  expires_at, edit + delete/purge actions gated by role (hide
  workspace-scope delete from non-managers using the existing membership
  role from workspace context), and the supersession chain.
- `supersession-chain.tsx` — vertical oldest→newest list from
  `MemoryDetailResponse.chain`, current row highlighted, superseded
  entries linking their content for comparison.
- `memory-edit-form.tsx` + `memory-form-model.ts` — native form +
  `FormData` via `src/lib/forms.ts` helpers with a hand-rolled validation
  model (no form library): title ≤ 200, content within the API caps,
  importance 1–5. On save, call the update mutation; surface the
  "content edits create a new version" behavior in helper text.
- `routes/memories-route.tsx` — shell composing filter bar + table +
  dialog, exported as `MemoriesRoute`.

Wiring: add `memoriesRoute` (`path: "/memories"`,
`lazyRouteComponent(() => import("@/features/memories/routes/memories-route"), "MemoriesRoute")`)
in `src/app/router.tsx` and register it in the `appRoute` children;
add the Memory nav item (decision 9) to `config/navigation.ts`.

Delete flows use the existing confirm-dialog treatment; purge is a
separate, explicitly-labeled destructive action inside the detail dialog
("Delete permanently"), never the default button.

**Verify**: `pnpm dev` — `/memories` lists seeded memories; filters,
edit (metadata and content paths), archive, and purge behave; a
read_only member sees no mutation affordances.

### Step 7: Gates + governance flip

Run the full gates. Flip `governance.md` §1 memory rows (workspace-scope
delete admin+, own-scope member+) and the §3 user-action hard-delete cell
to `[implemented: plan 049]`, recording decision 6's two interpretations
in the note.

**Verify**: `cd apps/web && pnpm check` exit 0 (zero warnings; knip and
dependency-cruiser clean — the new feature must not import route shells or
`app/`); `cd apps/api && uv run ruff check .` exit 0; full backend suite
from Step 4 green.

## Test plan

Backend covered by Step 4 (~22–28 tests). Pinned invariants: **the budget
is hard** (no rendered block ever exceeds it, and the assembler's
`[truncated]` backstop never fires in tests), **rendering is
deterministic** (byte-identical output for identical rows — the
prompt-cache contract), **notes never render into the prompt**,
**user-scope memories are invisible cross-user at every route**, **route
deletes archive by default and only explicit purge hard-deletes, both
audited**, and **the RBAC matrix matches governance §1 exactly**. Frontend
has no test framework; `pnpm check` plus the Step 6 manual matrix is the
gate (call out anything not manually verified).

## Done criteria

- [ ] Core memories render into the system prompt via a `PromptBlock`
      through the 018 assembler — one assembly point, no side channel
- [ ] Injection covers interactive, scheduled, and delegated runs (all via
      `execute_run`); zero core memories → no `memory` block at all
- [ ] Formatter enforces the hard budget with importance-ranked,
      deterministic, summary-plus-pointers output; omitted memories and
      clamped lines point at `search_memory`
- [ ] `GET/PATCH/DELETE /api/v1/memories` live, route-per-file, thin, RFC
      7807 errors; RBAC per governance §1 with decision 6's
      interpretations recorded in the note
- [ ] Delete archives; purge is the only hard delete and both are audited
      with `AuditResourceType.MEMORY`
- [ ] `/memories` UI: filterable list (scope/kind/type/agent/status),
      detail dialog with provenance + supersession chain, edit form,
      role-gated delete/purge; Memory nav entry present
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/memories tests/routes/memories tests/services/agents -q` exits 0
- [ ] `pnpm check` exits 0 with zero warnings
- [ ] No plan numbers in implementation code; `governance.md` cells flipped
- [ ] `git status` clean outside the in-scope list;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 048 is not landed, or its seams differ from what this plan consumes
  (`scope_filter`, `effective_confidence`, `update_memory` supersession
  semantics, `MEMORY_CORE_CHAR_BUDGET`, the partial core-lookup index) —
  reconcile with the landed 048 first.
- The prompt assembler API changed: `PromptBlock` /
  `runtime_prompt_blocks` / `build_system_prompt`
  (`runtime/prompt.py:39-70`) or the `_runtime_instructions` call path
  (`loop.py:87-90`) no longer match Current state.
- `execute_run.py` no longer follows the load-then-pass skills shape
  (`execute_run.py:113`, `159-166`) — the Step 2 seam assumed it.
- A `routes/memories/` package or `features/memories/` directory already
  exists.
- `governance.md` §1/§3 memory rows changed since `0cbbb39` — the note
  wins; reconcile the RBAC matrix before coding.
- The visibility interpretation (decision 6a) conflicts with a landed
  admin/compliance surface (e.g. an admin memory-oversight requirement
  appeared) — resolve the policy question in the note first.
- Frontend conventions moved (query-key factory shape, router structure,
  navigation config) in a way that makes the Step 5/6 clones wrong —
  follow the live precedent and note the deviation.
- You feel the need to inject notes, add per-scope quotas, or build a
  reranker — eval-gated follow-ups (Gate G4), not this plan.

## Maintenance notes

- **Prompt-cache discipline**: the rendered block must stay byte-stable
  between memory writes (decisions 3/4). Anyone adding volatile values
  (timestamps, counts, confidences) to the rendered text is breaking the
  cache contract plan 013's chunked trimming relies on — the determinism
  test is the tripwire.
- **Block ordering**: identity → memory → memory_policy → planning →
  delegation. Later assembler consumers (034 `<available_files>`, 040
  active context) slot in without reordering these; a reorder busts every
  provider prompt cache once and needs a deliberate decision.
- **Tuning is eval-gated (G4)**: budget size, per-scope quotas, ranking
  weights, and line clamp length only change alongside updates to
  `test_core_memory_block.py` and 048's eval suite.
- **User-scope visibility (decision 6a)** is a product policy admins may
  eventually want oversight over; if that lands, it is a governance-note
  change first, then an authorisation-module change — the matrix lives in
  one file by design.
- Reviewers should scrutinize: `visible_memory_filter` reuse across
  list/get/update/delete (no route may query `AgentMemory` directly), the
  purge path (hard delete + audit survival via SET-NULL FKs), and that the
  runtime memory load did not add a second DB round-trip per turn beyond
  the one core-lookup query.
