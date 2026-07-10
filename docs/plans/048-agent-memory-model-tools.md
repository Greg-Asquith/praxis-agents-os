# Plan 048: Agent memory model, write service, and registry memory tools

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Amendment (2026-07-07, plan 075 — prompt-injection threat model)**:
> memory is threat-model.md §2(a) — a persistence channel where injected
> instructions saved during one run return verbatim through search in
> later runs. Three deltas: (1) `search_memory` results frame stored
> content with the shared untrusted-content markers (threat-model §3) —
> memory content is agent-authored under possibly-hostile inputs, not
> trusted text; (2) provenance is surfaced at read time — search results
> carry `source`/`created_by` so the model can weigh a
> scheduled-run-written note against a user-stated fact; (3) Step 8
> gains `test_memory_adversarial_content.py` over the shared fixtures
> (threat-model §4): hostile titles/content round-trip save→search with
> markers intact and forged markers neutralized.
>
> **Gate pre-flights (run before Step 1)**:
> - **G2** — plan 018 is DONE (verified 2026-07-06): the prompt assembler
>   exists at `services/agents/runtime/prompt.py` (`PromptBlock`,
>   `runtime_prompt_blocks`, `build_system_prompt`). The write-policy snippet
>   in Step 6 composes through it; do not invent a second assembly path.
> - **G3** — `docs/architecture/governance.md` exists (029 DONE 2026-07-06).
>   Re-verify every governance citation below against the live note (the note
>   wins; reconcile any flipped default before coding). This plan implements
>   its §1/§2/§3 memory slices — flip the relevant cells to
>   `[implemented: plan 048]` in the same PR.
> - **G4** — the memory eval tests in Step 8 are part of this plan's Done
>   criteria. No write-policy tuning (dedup threshold, decay rates, approval
>   defaults) may happen after this plan without those tests passing first.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/models/ apps/api/alembic/versions/core/ apps/api/core/settings/ apps/api/services/agents/runtime/ apps/api/services/audit_events/enums.py apps/api/services/embeddings/ apps/api/services/search/ apps/api/services/jobs/ apps/api/services/memories/`
> In-scope files WILL have changed since `0cbbb39` — plans 030/043/044/045
> land between planning and execution and are hard dependencies. Re-verify
> every "Current state" excerpt against the live code and reconcile the
> dependency seams in Step 0 before proceeding; treat an *unexplained*
> mismatch (one not accounted for by a landed plan) as a STOP condition.

## Status

- **Priority**: P1 (Phase 5 backbone; 049 hard-depends on it)
- **Effort**: L
- **Risk**: HIGH — memory is long-lived, prompt-adjacent, agent-writable
  state; a bad write policy is a memory-poisoning vector, and a bad scope
  predicate leaks one agent's or user's memories into another's context.
- **Depends on**: **hard** — 043 (`services/embeddings/` provider ABC and
  the deterministic `FakeEmbeddingProvider` in
  `tests/support/embeddings.py`), 045 (hybrid search recipe + shared
  `services/retrieval/` parts serving `agent_memories`; see decision 1),
  030 (jobs harness for the
  `memory.embed` and `memory.sweep_expired` kinds), 025/026 (DONE — registry
  + dispatch choke point give memory tools audit/approval for free), Gate G2
  (018 DONE), Gate G3 (`docs/architecture/governance.md`). **Soft** — 044
  (brings the `pgvector` Python package and the halfvec/tsvector column
  precedent this model mirrors; see STOP conditions).
- **Category**: Phase 5 memory (roadmap `000_MASTER_ROADMAP.md` §4 Phase 5
  row 048; donor `DONOR_PORT_ROADMAP.md` §4.5 / §6 row E1)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Thin layer on KB infrastructure, no memory framework** (donor §4.5,
   binding): no Letta/Mem0/Zep dependency. `agent_memories` is one table
   riding the 043 embeddings ABC and the 045 hybrid engine. `search_memory`
   is NOT a second engine: per 045 decision 2, "the engine" is the shared
   pure parts in `services/retrieval/` (`rrf_merge`, domain types, the
   reranker seam) plus 045's written RRF-in-SQL shape — the memories query
   composes those parts over `agent_memories` exactly as 045's maintenance
   notes prescribe (swap the table, keep the CTE predicates, collection
   guard, and RRF-in-SQL). Any drift from that recipe is a fork; reconcile
   with 045 rather than diverge.
2. **Backend-minted provenance, always.** Tool signatures carry no
   conversation/run/user parameters. The service resolves
   `source_conversation_id`/`source_run_id`/`source`/`created_by_user_id`
   from `RuntimeDeps` (`runtime/context.py:18-30`); `source` stores the run
   trigger verbatim (`interactive`/`scheduled`/`delegated`, the
   `agent_runs_trigger_check` vocabulary at `models/agent_run.py:103`) plus
   `user` for human writes via 049 routes. A provenance argument appearing
   in a tool schema is a review-blocking defect.
3. **Core writes require approval; note writes are `auto`.**
   `governance.md` §2 defaults memory *notes* (Praxis-internal writes) to
   `auto` — kept. But `kind="core"` memories are injected into every future
   system prompt (049), the highest-leverage poisoning target, so
   `save_memory`/`update_memory` raise `ApprovalRequired` from the tool body
   when the write targets a core memory and `ctx.tool_call_approved` is
   false. Probe-verified against installed `pydantic-ai==2.1.0`:
   `ApprovalRequired(metadata: dict | None = None)` is a raisable exception
   ("raise when a tool call requires human-in-the-loop approval"),
   `RunContext.tool_call_approved` exists, and `dispatch.py:163-177` already
   catches the raise and audits `approval_requested`. Record this tightening
   into `governance.md` §2 in the same PR (a core-memory bullet next to the
   notes bullet).
4. **`memory_type` includes `outcome`.** Vocabulary: `fact` / `preference` /
   `episode` / `outcome`. `outcome` is intended for schedule-run results
   ("the weekly report ran; client X numbers were down") — documented intent,
   not a principal restriction; any run may write one. Default TTLs per type
   (decision 8) make episodes and outcomes self-expiring.
5. **Lifecycle in a `status` column, no `SoftDeleteMixin`.** `AgentMemory`
   uses `Base + UUIDMixin + TimestampMixin` (the `RateLimitAttempt` / plan
   030 decision-2 composition, `models/base.py:18-30`), with
   `status IN ('active','superseded','archived')`. Per `governance.md` §3:
   supersession never hard-deletes, TTL expiry archives, and hard delete
   happens only by explicit user action (the 049 purge route). Soft-delete
   columns would duplicate this state machine.
6. **Dedup-reinforce at write time, cosine ≥ 0.92.** `save_memory` embeds
   the candidate synchronously through the 043 provider (short timeout);
   nearest same-collection neighbour = same workspace + same scope tuple
   (`scope`,`agent_id`,`user_id`) + same `kind`, `status='active'`,
   `embedding IS NOT NULL`. Similarity ≥ `MEMORY_DEDUP_SIMILARITY` (0.92)
   → reinforce instead of insert: `confidence = min(1.0, confidence + 0.1)`,
   `last_reinforced_at = now()`, `reinforcement_count += 1`; return the
   existing row flagged `reinforced: true`. If the embed call fails or times
   out, insert with `embedding NULL` and enqueue `memory.embed`; the embed
   job re-runs the dedup check before stamping the vector and, on a hit,
   reinforces the existing row and marks the new row
   `superseded`→existing (no silent row loss, chain stays visible).
7. **Read-time confidence decay, per-type rates, rows never mutated by
   reads.** `effective_confidence = confidence * exp(-rate_per_day[type] *
   age_days)`, `age_days` measured from `last_reinforced_at` (falling back
   to `created_at`), floored at 0.05. Rates: fact `0.005`/day (half-life
   ≈ 139 d), preference `0.002` (≈ 347 d), episode `0.02` (≈ 35 d), outcome
   `0.01` (≈ 69 d). Decay is a pure function computed at read (Python and
   mirrored in the search SQL ordering); it never writes. *Reinforcement*
   does write: dedup hits and `update_memory` reset the decay clock; search
   access bumps `access_count`/`last_accessed_at` only (a ranking signal,
   not a confidence change).
8. **TTL + archival.** `expires_at` set explicitly via `expires_in_days`,
   else defaulted per type: episode 90 d, outcome 180 d, fact/preference
   none. `memory.sweep_expired` (030 harness, self-rescheduling like
   `jobs.sweep_terminal`) archives `active` rows past `expires_at` with
   `archive_reason='expired'` — archive, never delete (`governance.md` §3).
9. **`update_memory` supersedes on content change; edits metadata in
   place.** A content change inserts a new row (same scope/kind/type,
   provenance freshly minted) and marks the old row
   `status='superseded'`, `superseded_by_id=<new>`; title/importance/expiry
   changes mutate in place. This keeps the supersession chain an honest edit
   history for 049's UI without churning rows on metadata tweaks.
   `forget_memory` archives (`archive_reason='forgotten'`) — forget is never
   a hard delete.
10. **Core memories are capped, small.** `MEMORY_CORE_MAX_PER_SCOPE` (20)
    active core memories per scope tuple and `MEMORY_CORE_MAX_CHARS` (500)
    per core memory; notes cap at `MEMORY_NOTE_MAX_CHARS` (4000). Breach →
    `ModelRetry` telling the model to update/forget instead (the
    `planning.py:49-50` precedent). Keeps 049's injection budget honest.
11. **Embedding collection discipline mirrors 044**: `embedding
    halfvec(<dims>)` with dims pinned at migration time from the 043 default
    model, and `embedding_provider`/`embedding_model`/`embedding_dims`
    recorded per row (all-null or all-set, CHECK-enforced) so a future model
    migration can re-embed. HNSW (`halfvec_cosine_ops`) + tsvector GIN from
    day one, matching `kb_chunks`.
12. **Audit**: new `AuditResourceType.MEMORY = "memory"` member
    (`services/audit_events/enums.py`). Tool-call audit rows come free from
    the 026 dispatch choke point (`dispatch.py:127-227`); the write service
    additionally records memory-resource audit events for supersession and
    archival so the trail names the memory id, not just the tool call.
13. **Standing write-policy snippet through the 018 assembler**: a
    `PromptBlock("memory_policy", ...)` appended in `runtime_prompt_blocks`
    only when the agent has a memory tool configured — telling the model
    what is worth remembering, that core memories are precious/capped, and
    to search before saving. Injection of the memories themselves is 049,
    not this plan.
14. **Roadmap open decision "memory approval defaults"**
    (`docs/legacy/ROADMAP_QUESTIONS_GAPS.md` §Open Product Decisions) —
    resolved here by decision 3. The background consolidation job stays
    deferred until note sprawl is real (donor §4.5).

## Why this matters

Memory is the difference between agents that restart from zero every
conversation and agents that accumulate working context. The donor's verdict
(donor roadmap §4.5) is that the winning shape is small and boring: a capped
always-injected core plus searchable notes, agent-initiated writes with
backend-minted provenance, human-visible and human-editable. Everything
expensive here is already built: 025/026 give memory writes audit and
approval for free because they are ordinary registry tool calls through the
dispatch choke point; 043/045 give embeddings and hybrid retrieval; 030
gives the embed/sweep queue. This plan is deliberately a thin layer that
wires those together — and the eval tests (Gate G4) pin the behaviors that
make memory safe (approval on core writes, scope isolation, dedup instead
of sprawl) before anyone is tempted to tune them.

## Current state

Anchors verified at `0cbbb39`; probe outputs recorded from the installed
packages in `apps/api` (`uv run python`).

- **No memory anything exists**: no `agent_memories` table, no
  `models/agent_memories.py`, no `services/memories/`, no memory tools in
  `services/agents/runtime/tools/` (contents: `contract.py`, `registry.py`,
  `permissions.py`, `planning.py`, `schemas.py`, `native/`).
- **Registry + contract (025)**:
  `services/agents/runtime/tools/contract.py:33-57` `RuntimeToolDefinition`
  (frozen dataclass: `name`, `function`, `description`, `provider`,
  `effect`, `takes_ctx`, `default_policy`, `supports_auto`,
  `supports_approval`, `timeout`, `output_model`, `configurable`,
  `auto_mount`, …); policy/effect vocabularies at `contract.py:16-28`
  (`auto`/`approval`, `read`/`write`); write tools must support approval
  (`contract.py:171-176`). `tools/registry.py:33-91` `runtime_tool(...)`
  decorator registers into `RUNTIME_TOOL_CATALOG` (line 30) with duplicate
  names raising at import; provider modules are imported for side effects at
  `registry.py:254-258` — the assembly point this plan extends.
- **Dispatch choke point (026)**: `runtime/dispatch.py:127-227`
  `dispatch_tool_execution` audits every invocation (args digest, latency,
  outcome), catches `ApprovalRequired` at lines 163-177 (audits
  `approval_requested`, re-raises), enforces the run envelope
  (write-effect tools denied when `envelope.side_effect_policy == "deny"`,
  `dispatch.py:91-103`; `RunEnvelope` at `runtime/envelope.py:17-30`), and
  validates declared `output_model`s. Memory tools inherit all of it.
- **Prompt assembler (018, Gate G2)**: `runtime/prompt.py:39-45`
  `PromptBlock(key, content, budget=None)`; `runtime_prompt_blocks(agent, *,
  include_delegation)` (48-60) returns ordered blocks
  (`identity`/`planning`/`delegation`); `build_system_prompt` (63-70) joins
  non-empty blocks; block budgets are soft — `_render_block` (73-85)
  truncates with `[truncated]` and a warning. Consumed by
  `runtime/loop.py:87-90`.
- **RuntimeDeps (provenance source)**: `runtime/context.py:18-30` — frozen
  dataclass with `db`, `user`, `workspace`, `conversation`, `agent`, `run`,
  `sink`, `envelope`, `delegation_depth`. Constructed in
  `runtime/execute_run.py:176-186`. `AgentRun.trigger` CHECK
  `('interactive','scheduled','delegated')` at `models/agent_run.py:103`.
- **Tool precedents (028)**: `tools/planning.py:29-43` — `write_todos` is
  the Praxis-internal auto-write precedent (`effect=TOOL_EFFECT_WRITE`,
  `supports_approval=False`, `auto_mount=True`); this plan's tools are
  instead `configurable=True`, default `auto`, `supports_approval=True`.
  `tools/native/web_search.py:1-20` is the probe-findings-docstring
  precedent this plan's tool module copies.
- **Model/migration conventions**: `models/base.py:18-30` mixins,
  `BaseModel` (130-138, not used here — decision 5); registry import list
  `models/__init__.py:13-25`. Core Alembic head at `0cbbb39` is
  `core_0008` (`alembic/versions/core/0008_add_conversation_todos.py`);
  plans 030/031/037/044 each add core migrations before this plan runs, so
  the real head at execution will be higher — renumber then (STOP
  condition). pgvector the *extension* is enabled
  (`alembic/versions/core/0001_create_core_schema.py:28`), but the
  `pgvector` *Python package* is NOT installed at `0cbbb39` (probe:
  `ModuleNotFoundError: No module named 'pgvector'`) — it arrives with 044.
- **pydantic-ai probes** (installed `pydantic-ai==2.1.0`):
  `Tool.__init__` accepts `requires_approval`, `timeout`, `args_validator`,
  `defer_loading` (full parameter list probed 2026-07-06);
  `RunContext` dataclass fields include `tool_call_approved` and
  `loaded_capability_ids`; `ApprovalRequired.__init__(metadata: dict[str,
  Any] | None = None)`, docstring: "Exception to raise when a tool call
  requires human-in-the-loop approval." — decision 3 rests on these three
  facts.
- **Audit**: `services/audit_events/enums.py` `AuditResourceType` members
  end at `SKILL` — no memory member yet.
  `services/audit_events/workspace_events.py:19` provides
  `record_workspace_audit_event(db, *, request, workspace_id, action,
  resource_type, resource_id, actor, details, status=...)`; skills services
  already use it (`services/skills/create_skill.py:52`).
- **Exceptions**: typed layer at `core/exceptions/general.py:16`
  `AppValidationError`, `:52` `NotFoundError`, `:91` `ConflictError`;
  `core/exceptions/auth.py:41` `AuthorizationError`. No ad-hoc
  `HTTPException`.
- **Will exist at execution (hard dependencies, verify then)**: 043's
  `services/embeddings/` ABC + default provider; 045's hybrid engine
  (tsvector + halfvec cosine, RRF merge, pending-embedding lexical fallback)
  with an `agent_memories` target and its deterministic fake embedding
  provider in the test harness; 030's `services/jobs/` (`@job_handler`
  decorator, `enqueue_job`, handler assembly point) and `jobs` table.
  Resolve exact import paths against the landed code in Step 0.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations after Step 2 |
| Apply migration | `uv run alembic upgrade heads` | `agent_memories` table created |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/memories -q` | all pass |
| Registry sanity | `uv run python -c "from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG; print(sorted(n for n in RUNTIME_TOOL_CATALOG if 'memory' in n))"` | the four memory tools |
| Runtime regression | `uv run pytest tests/services/agents -q` | all pass |
| Worker smoke | `uv run python -m workers.job_runner --once` | exit 0, memory kinds registered |

## Scope

**In scope:**

- `apps/api/models/agent_memories.py` (create — `AgentMemory`) +
  `apps/api/models/__init__.py` (register import)
- `apps/api/alembic/versions/core/NNNN_add_agent_memories.py` (create —
  core branch per roadmap D5; number against the real head at execution)
- `apps/api/core/settings/memory.py` (create — `MemorySettingsMixin`) +
  `apps/api/core/settings/__init__.py` (compose it)
- `apps/api/services/memories/` (create): `__init__.py`, `domain.py`,
  `utils.py`, `authorisation.py` (skeleton — 049 fills the route-facing
  matrix), `save_memory.py`, `search_memories.py`, `update_memory.py`,
  `forget_memory.py`, `get_memory.py`, `jobs.py`
- Jobs wiring: register `services/memories/jobs.py` at 030's handler
  assembly point (the import-for-side-effects list in `services/jobs`)
- `apps/api/services/agents/runtime/tools/memory.py` (create — the four
  registry tools) + `tools/registry.py:254-258` import list
- `apps/api/services/agents/runtime/prompt.py` (edit — memory write-policy
  block, decision 13)
- `apps/api/services/audit_events/enums.py` (edit — `MEMORY` member)
- `apps/api/tests/services/memories/` (create) + a memory factory in
  `tests/factories/`
- `docs/architecture/governance.md` (edit — flip §2/§3 memory cells to
  `[implemented: plan 048]`; add the core-write approval bullet, decision 3)

**Out of scope (do NOT touch):**

- Core-memory prompt *injection* and the budgeted formatter — plan 049.
- HTTP routes and any UI — plan 049. Memories have **no public surface** in
  this plan; per AGENTS.md, that is documented as pending, not implied.
- The 045 engine's internals — `services/retrieval/` and
  `services/kb/search_chunks.py` are consumed/copied per decision 1,
  never modified here; anything they lack is a reconciliation with 045's
  plan, not a fork.
- Background consolidation/summarisation jobs (deferred, decision 14).
- `kb_documents`/`kb_chunks`, files, integrations — sibling verticals.
- History trimming (013) — memory is prompt-side, not history-side.

## Git workflow

- Branch: `advisor/048-agent-memory-model-tools`
- Commit style: `API - Agent Memory Model & Tools`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Dependency reconnaissance

Verify and record (in the PR description) the landed shapes of: the 043
embeddings ABC (provider resolution + default model/dims), 045's shared
retrieval parts (`services/retrieval/` — `rrf_merge`, domain types,
reranker seam) and its written RRF-in-SQL shape in
`services/kb/search_chunks.py` (the recipe the memories query copies,
decision 1), 043's deterministic fake embedding provider
(`tests/support/embeddings.py`, consumed by 045's harness), and 030's
`@job_handler` + `enqueue_job` signatures and
handler assembly point. Also confirm the `pgvector` Python package is
installed (044) and note the current core Alembic head.

**Verify**: `uv run python -c "import pgvector"` → no error; each seam's
import path recorded. Any missing seam → STOP conditions.

### Step 1: Settings

Create `core/settings/memory.py` with `MemorySettingsMixin` (shape of the
existing per-concern mixins; compose into `Settings` in
`core/settings/__init__.py` — no production-safety validator change, no
local-only values):

```python
MEMORY_DEDUP_SIMILARITY: float = 0.92        # cosine similarity floor for reinforce-instead-of-insert
MEMORY_EMBED_WRITE_TIMEOUT_SECONDS: float = 5.0  # sync embed budget inside save_memory
MEMORY_DECAY_RATE_FACT: float = 0.005        # per-day; decision 7
MEMORY_DECAY_RATE_PREFERENCE: float = 0.002
MEMORY_DECAY_RATE_EPISODE: float = 0.02
MEMORY_DECAY_RATE_OUTCOME: float = 0.01
MEMORY_CONFIDENCE_FLOOR: float = 0.05
MEMORY_DEFAULT_CONFIDENCE: float = 0.8
MEMORY_REINFORCE_CONFIDENCE_STEP: float = 0.1
MEMORY_EPISODE_TTL_DAYS: int = 90            # decision 8 defaults
MEMORY_OUTCOME_TTL_DAYS: int = 180
MEMORY_CORE_MAX_PER_SCOPE: int = 20          # decision 10
MEMORY_CORE_MAX_CHARS: int = 500
MEMORY_NOTE_MAX_CHARS: int = 4000
MEMORY_SEARCH_DEFAULT_LIMIT: int = 10
MEMORY_CORE_CHAR_BUDGET: int = 2000          # consumed by 049's injection formatter
MEMORY_SWEEP_INTERVAL_SECONDS: int = 3600
```

All `Field(..., description=...)` with sensible bounds (`gt=0`, and
`0 < MEMORY_DEDUP_SIMILARITY < 1`).

**Verify**: `uv run python -c "from core.settings import settings; print(settings.MEMORY_DEDUP_SIMILARITY)"`
→ `0.92`; ruff exit 0.

### Step 2: Model + core migration

Create `models/agent_memories.py` with
`AgentMemory(Base, UUIDMixin, TimestampMixin)` (decision 5),
`__tablename__ = "agent_memories"`:

- `workspace_id` UUID FK `workspaces.id` ondelete CASCADE, not null, indexed
- `scope` String(16) not null; `agent_id` UUID FK `agents.id` ondelete
  CASCADE, nullable; `user_id` UUID FK `users.id` ondelete CASCADE, nullable
- `kind` String(8) not null, server_default `'note'`
- `memory_type` String(16) not null, server_default `'fact'`
- `title` String(200) not null; `content_md` Text not null
- `embedding` `HALFVEC(<dims>)` nullable (pending-embed rows are legal —
  045's lexical fallback finds them); dims pinned from the 043 default
  model at migration time (decision 11)
- `embedding_provider` String(50), `embedding_model` String(100),
  `embedding_dims` Integer — all nullable
- `content_tsv` TSVECTOR, generated always as
  `to_tsvector('english', title || ' ' || content_md)` stored (mirror 044's
  Computed-column construction)
- `importance` Integer not null, server_default `3`
- `confidence` Float not null, server_default `0.8`
- `last_reinforced_at` DateTime(tz) nullable; `reinforcement_count` Integer
  not null server_default `0`
- `last_accessed_at` DateTime(tz) nullable; `access_count` Integer not null
  server_default `0`
- `expires_at` DateTime(tz) nullable
- `status` String(16) not null, server_default `'active'`
- `superseded_by_id` UUID FK `agent_memories.id` ondelete SET NULL, nullable
- `archived_at` DateTime(tz) nullable; `archive_reason` String(32) nullable
- provenance (decision 2): `source_conversation_id` UUID FK
  `conversations.id` ondelete SET NULL; `source_run_id` UUID FK
  `agent_runs.id` ondelete SET NULL; `source` String(16) not null;
  `created_by` String(8) not null; `created_by_user_id` UUID FK `users.id`
  ondelete SET NULL

CHECK constraints (named, in `__table_args__`):

```sql
agent_memories_scope_check:      scope IN ('agent','user','workspace')
agent_memories_scope_refs_check: (scope = 'agent'     AND agent_id IS NOT NULL AND user_id IS NULL)
                              OR (scope = 'user'      AND user_id IS NOT NULL AND agent_id IS NULL)
                              OR (scope = 'workspace' AND agent_id IS NULL     AND user_id IS NULL)
agent_memories_kind_check:       kind IN ('core','note')
agent_memories_type_check:       memory_type IN ('fact','preference','episode','outcome')
agent_memories_status_check:     status IN ('active','superseded','archived')
agent_memories_superseded_check: (status = 'superseded') = (superseded_by_id IS NOT NULL)
agent_memories_archived_check:   (status = 'archived') = (archived_at IS NOT NULL)
agent_memories_archive_reason_check: archive_reason IS NULL OR archive_reason IN ('expired','forgotten','user_deleted')
agent_memories_importance_check: importance BETWEEN 1 AND 5
agent_memories_confidence_check: confidence >= 0 AND confidence <= 1
agent_memories_embedding_meta_check: (embedding IS NULL) = (embedding_model IS NULL)
                                 AND (embedding_model IS NULL) = (embedding_provider IS NULL)
                                 AND (embedding_model IS NULL) = (embedding_dims IS NULL)
agent_memories_source_check:     source IN ('interactive','scheduled','delegated','user')
agent_memories_created_by_check: created_by IN ('agent','user')
```

Indexes: `(workspace_id, scope, status)`; partial
`(workspace_id, scope, agent_id, user_id) WHERE status = 'active' AND kind
= 'core'` (049's injection lookup); partial `(expires_at) WHERE status =
'active' AND expires_at IS NOT NULL` (sweep); GIN on `content_tsv`; HNSW on
`embedding` with `halfvec_cosine_ops` (mirror 044's DDL); plain index on
`superseded_by_id`.

Import `AgentMemory` in `models/__init__.py`. Generate on the **core**
branch (D5): `uv run alembic revision --autogenerate --head core@head
--version-path alembic/versions/core -m "add agent memories table"` —
number against the real head at execution, and hand-check the generated
migration: autogenerate typically misses the HNSW index, the generated
tsvector column, and halfvec types — add them manually with a matching
`downgrade`.

**Verify**: `uv run alembic upgrade heads` clean; `uv run alembic check`
no pending; downgrade round-trip
(`uv run alembic downgrade core@-1 && uv run alembic upgrade heads`).

### Step 3: Domain + pure functions

`services/memories/domain.py`: the vocabulary constants —
`MEMORY_SCOPE_AGENT/_USER/_WORKSPACE`, `MEMORY_KIND_CORE/_NOTE`,
`MEMORY_TYPE_FACT/_PREFERENCE/_EPISODE/_OUTCOME`,
`MEMORY_STATUS_ACTIVE/_SUPERSEDED/_ARCHIVED`,
`ARCHIVE_REASON_EXPIRED/_FORGOTTEN/_USER_DELETED`,
`MEMORY_SOURCE_USER = "user"`, and the `Literal` aliases the tool schemas
reuse.

`services/memories/utils.py` (service-specific helpers, AGENTS.md rule):

```python
def effective_confidence(memory: AgentMemory, *, now: datetime) -> float:
    # confidence * exp(-rate[memory_type] * age_days); age from
    # last_reinforced_at or created_at; floored at MEMORY_CONFIDENCE_FLOOR.

def default_expires_at(memory_type: str, *, now: datetime) -> datetime | None:
    # episode -> +MEMORY_EPISODE_TTL_DAYS, outcome -> +MEMORY_OUTCOME_TTL_DAYS, else None

def scope_filter(scope: str, *, workspace_id, agent_id, user_id):  # -> SQLA predicate
    # THE isolation predicate — every read path goes through this one function.
```

`scope_filter` is the single source of scope truth: agent scope pins
`agent_id == <current agent>`, user scope pins `user_id == <current user>`,
workspace scope pins only `workspace_id`. Duplicating this predicate
anywhere is a review-blocking defect.

**Verify**: ruff exit 0; the Step 8 decay tests exercise
`effective_confidence` directly (no DB).

### Step 4: Write service operations (one per file)

All operations take explicit identity kwargs — they serve both the runtime
tools (identity from `RuntimeDeps`) and 049's routes (identity from the
request context). None of them accept caller-supplied provenance.

- `save_memory.py` — `save_memory(db, *, workspace, agent, user, scope,
  kind, memory_type, title, content_md, importance, expires_in_days,
  provenance: MemoryProvenance) -> MemorySaveResult`.
  `MemoryProvenance` is a small frozen dataclass
  (`source`, `source_conversation_id`, `source_run_id`,
  `created_by`, `created_by_user_id`) built ONLY by the tool layer (from
  `RuntimeDeps`) or the 049 route layer (from the session user). Flow:
  validate lengths/caps (decision 10 → `AppValidationError`; the tool layer
  converts to `ModelRetry`), attempt sync embed via the 043 provider under
  `asyncio.wait_for(..., MEMORY_EMBED_WRITE_TIMEOUT_SECONDS)`, run the
  dedup query (decision 6: cosine distance via pgvector `<=>` against the
  same scope tuple + kind, `status='active'`, `embedding IS NOT NULL`,
  `LIMIT 1`), reinforce-or-insert, default `expires_at` (decision 8),
  enqueue `memory.embed` when the row was inserted without a vector,
  `db.flush()` (the `planning.py:75-76` precedent — the run transaction
  owns the commit).
- `search_memories.py` — `search_memories(db, *, workspace, agent, user,
  query, scope=None, kind=None, memory_type=None, limit) ->
  MemorySearchResult`. Composes the memories hybrid query from 045's
  recipe (decision 1: RRF over tsvector + cosine per the written SQL
  shape, pending-embedding lexical fallback, `services/retrieval/` parts)
  with `scope_filter` visibility: when `scope` is None,
  search the union of the caller's three visible scopes; always
  `status='active'`. Post-process: attach `effective_confidence`, then bump
  `access_count`/`last_accessed_at` on returned ids with one UPDATE
  (decision 7 — access reinforcement, not confidence mutation).
- `update_memory.py` — `update_memory(db, *, workspace, agent, user,
  memory_id, title=None, content_md=None, importance=None,
  expires_in_days=None, provenance) -> MemoryUpdateResult`. Loads the row
  through `scope_filter` (miss → `NotFoundError` — out-of-scope ids are
  indistinguishable from missing ones), rejects non-`active` targets
  (`ConflictError`), then decision 9: content change → insert successor +
  mark predecessor superseded (+ enqueue `memory.embed` for the successor);
  metadata-only → in-place update + `last_reinforced_at = now()`.
- `forget_memory.py` — `forget_memory(db, *, workspace, agent, user,
  memory_id, reason=None) -> MemoryForgetResult`: archive with
  `archive_reason='forgotten'`; already-archived is idempotent success.
- `get_memory.py` — scope-filtered single fetch (tool error messages and
  049 reuse it).
- Supersession and archival record memory-resource audit events via
  `record_workspace_audit_event` (`workspace_events.py:19`) with
  `AuditResourceType.MEMORY` (decision 12).

`services/memories/__init__.py` re-exports operation functions only.

**Verify**: ruff exit 0; `uv run pytest tests/services/agents -q` still
green (nothing runtime-side touched yet).

### Step 5: Job kinds

`services/memories/jobs.py`, registered at 030's handler assembly point:

- `@job_handler(kind="memory.embed", timeout=120.0)` — payload
  `{"memory_id": ...}` (ids only, 030 payload discipline). Load the row; if
  no longer `active` or already embedded, no-op (idempotent — 030 handlers
  are at-least-once). Embed via the 043 provider, re-run the decision-6
  dedup check first: on a hit, reinforce the existing row and mark this row
  superseded by it; otherwise stamp
  `embedding`/`embedding_provider`/`embedding_model`/`embedding_dims`.
- `@job_handler(kind="memory.sweep_expired", timeout=120.0)` — archive
  `active` rows with `expires_at < now()` (`archive_reason='expired'`),
  then self-reschedule (`run_after = now + MEMORY_SWEEP_INTERVAL_SECONDS`),
  plus an `ensure_memory_sweep_job(db)` idempotent-enqueue helper called
  the same way 030's `ensure_sweep_job` is — copy that file's pattern
  exactly.

**Verify**: `uv run python -m workers.job_runner --once` → exit 0;
registry print includes `memory.embed` and `memory.sweep_expired`.

### Step 6: Registry tools + write-policy prompt block

`services/agents/runtime/tools/memory.py` — module docstring records the
Step 0 / planning-time probe findings (the `native/web_search.py:1-20`
precedent). Four tools calling the Step 4 services with provenance minted
from `ctx.deps` (decision 2); scope/kind/type parameters are `Literal`
types from `domain.py` so schemas stay closed vocabularies:

```python
@runtime_tool(name="save_memory", provider="core", label="Save memory",
              effect=TOOL_EFFECT_WRITE, takes_ctx=True, timeout=15,
              default_policy=TOOL_POLICY_AUTO)   # governance §2: notes are auto
async def save_memory(ctx: RunContext[RuntimeDeps], title: str, content: str,
                      scope: MemoryScope = "agent", kind: MemoryKind = "note",
                      memory_type: MemoryType = "fact", importance: int = 3,
                      expires_in_days: int | None = None) -> dict[str, object]:
    if kind == "core" and not ctx.tool_call_approved:
        raise ApprovalRequired(metadata={"reason": "core_memory_write"})  # decision 3
    ...

@runtime_tool(name="search_memory", provider="core", label="Search memory",
              effect=TOOL_EFFECT_READ, takes_ctx=True, timeout=15)
async def search_memory(ctx, query: str, scope: MemoryScope | None = None,
                        kind: MemoryKind | None = None,
                        memory_type: MemoryType | None = None,
                        limit: int = 10) -> dict[str, object]: ...

@runtime_tool(name="update_memory", provider="core", label="Update memory",
              effect=TOOL_EFFECT_WRITE, takes_ctx=True, timeout=15)
async def update_memory(ctx, memory_id: str, title: str | None = None,
                        content: str | None = None, importance: int | None = None,
                        expires_in_days: int | None = None) -> dict[str, object]:
    # loads the row first; targets with kind == "core" require approval (decision 3)

@runtime_tool(name="forget_memory", provider="core", label="Forget memory",
              effect=TOOL_EFFECT_WRITE, takes_ctx=True, timeout=15)
async def forget_memory(ctx, memory_id: str, reason: str | None = None) -> dict[str, object]:
    # archives, never deletes (governance §3)
```

All four are `configurable=True` (agents opt in via `tool_names`; per-agent
`tool_policies` may tighten any of them to `approval` — never loosen the
conditional core approval, which lives in the tool body). Typed service
exceptions surface to the model as `ModelRetry` with actionable messages
(cap breach → "update or forget an existing core memory first";
unknown/out-of-scope id → "memory not found"). Add the module to the
registration import list at `tools/registry.py:254-258`.

In `runtime/prompt.py`, add `MEMORY_INSTRUCTIONS` (the standing
write-policy snippet, decision 13) and append
`PromptBlock("memory_policy", MEMORY_INSTRUCTIONS if has_memory_tools else "")`
in `runtime_prompt_blocks`, where `has_memory_tools` checks
`agent.tool_names` against the four names. Snippet content (≤ ~600 chars):
save durable facts/preferences/episodes worth reusing; search before
saving; core memories are capped and always-visible — reserve them for
identity-level facts and expect approval; forget stale memories instead of
contradicting them.

**Verify**: registry sanity command lists
`['forget_memory', 'save_memory', 'search_memory', 'update_memory']`;
`uv run pytest tests/services/agents -q` green; a quick
`runtime_prompt_blocks` unit check shows the block present only when a
memory tool is configured.

### Step 7: Audit enum + governance flip

Add `MEMORY = "memory"` to `AuditResourceType`
(`services/audit_events/enums.py`). Update `docs/architecture/governance.md`:
flip §2's memory-notes cell and §3's memories row to
`[implemented: plan 048]`, and add the decision-3 core-write approval
bullet to §2.

**Verify**: grep shows one new enum member; governance diff reviewed.

### Step 8: Memory eval tests (Gate G4)

`tests/services/memories/` (modules set
`pytestmark = pytest.mark.asyncio`; DB-backed tests use the `conftest.py`
fixtures and skip without `TEST_DATABASE_URL`; embeddings use 045's
deterministic fake provider — never a live model; live LLM calls are
blocked in tests already):

- `test_memory_decay.py` (no DB): decay math pinned — per-type rates
  ordered episode > outcome > fact > preference at equal age; floor holds;
  `last_reinforced_at` resets the clock; `now == created_at` →
  `effective_confidence == confidence`.
- `test_save_memory_dedup.py` (DB): near-duplicate (fake-provider cosine
  ≥ 0.92, same scope tuple + kind) reinforces — no new row,
  `reinforcement_count` +1, confidence stepped and capped at 1.0; below
  threshold inserts; same content in a *different* scope tuple inserts (no
  cross-scope dedup); embed failure inserts with NULL embedding + enqueues
  `memory.embed`; core cap breach rejects with the actionable error.
- `test_memory_scope_isolation.py` (DB): agent A never reads agent B's
  agent-scope memories (search and get); user-scope isolation across two
  users; workspace isolation across two workspaces; workspace-scope rows
  visible to both agents; `update_memory`/`forget_memory` on an
  out-of-scope id behave as not-found.
- `test_memory_tools_policy.py` (DB): through
  `dispatch_tool_execution` — note-kind `save_memory` runs under `auto`
  and writes a tool audit row (`completed`); core-kind raises
  `ApprovalRequired` and audits `approval_requested`; with
  `tool_call_approved` the core write completes; write tools denied under a
  `side_effect_policy="deny"` envelope (`dispatch.py:91-103`);
  `forget_memory` archives (row still present, `status='archived'`);
  supersession/archival write `AuditResourceType.MEMORY` audit events.
- `test_memory_jobs.py` (DB): `memory.embed` stamps vector + collection
  metadata, is idempotent on re-run, and reinforces-and-supersedes on a
  job-time dedup hit; `memory.sweep_expired` archives expired rows only and
  self-reschedules; pending-embedding rows are still found lexically
  through `search_memories` (the 045 fallback, "I just told you that").

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/memories tests/services/agents -q`
→ all pass; without the env var, DB tests skip.

## Test plan

Covered by Step 8 (~25–30 tests). The pinned invariants, per Gate G4:
**core writes cannot land without approval** (and the approval round-trip
is audited on both sides), **scope isolation is absolute** (agent/user/
workspace, enforced by one predicate), **duplicates reinforce instead of
sprawl** (and job-time dedup cannot lose a write silently), **decay is
read-only math** (no read path mutates confidence), and **nothing
memory-shaped is ever hard-deleted by agent action** (forget/expiry
archive; supersession chains stay intact). These tests are the
prerequisite Gate G4 names for any later tuning of thresholds, rates, or
approval defaults.

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` clean; migration on the **core** branch (D5),
      numbered against the real head, downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/memories tests/services/agents -q` exits 0
- [ ] Registry lists exactly four memory tools; all four route through the
      026 dispatch choke point with audit rows (verified by Step 8)
- [ ] No memory tool schema exposes provenance parameters (decision 2)
- [ ] `memory.embed` + `memory.sweep_expired` registered on the 030
      harness; `uv run python -m workers.job_runner --once` exits 0
- [ ] Write-policy `PromptBlock` renders only for agents with memory tools
- [ ] `AuditResourceType.MEMORY` exists; supersession/archival audited
- [ ] No HTTP routes or UI added (049's surface); no plan numbers cited in
      implementation code (AGENTS.md)
- [ ] `docs/architecture/governance.md` memory cells flipped to
      `[implemented: plan 048]` and the core-approval bullet added
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 043 (`services/embeddings/`) or 045 (hybrid engine + eval fake provider)
  is not implemented at execution time — this plan cannot start before
  them.
- 045's shared parts are missing or diverged: no `services/retrieval/`
  package (`rrf_merge`/domain types/reranker seam), or its written
  RRF-in-SQL shape is absent from `services/kb/search_chunks.py` — the
  memories query has no recipe to copy (decision 1); reconcile with 045
  rather than building a parallel memory search path here.
- Plan 030's jobs harness is not landed (no `@job_handler`, no `jobs`
  table) — the embed/sweep kinds have nowhere to ride.
- An `agent_memories` table, `models/agent_memories.py`, or
  `services/memories/` already exists.
- The `pgvector` Python package is still not installed (044 did not land or
  landed without it) — the halfvec column type cannot be declared.
- The prompt assembler API changed — `PromptBlock` /
  `runtime_prompt_blocks` / `build_system_prompt`
  (`runtime/prompt.py:39-70`) no longer match Current state.
- The `ApprovalRequired`-from-tool-body flow does not defer as probed
  (approval never requested, or the approved replay does not re-execute
  with `ctx.tool_call_approved` true) — decision 3's mechanism is broken;
  do not ship core writes as plain `auto`.
- The core Alembic head at execution is `core_0008` **or** the number you
  picked collides — renumber against the real head and re-verify index
  names don't collide with landed migrations.
- 044's collection discipline (halfvec dims / provider-model-dims
  recording) contradicts decision 11 — mirror what actually landed.
- `governance.md` §2/§3 memory defaults changed since `0cbbb39` — the note
  wins; reconcile before coding.

## Maintenance notes

- **049 consumes**: `MEMORY_CORE_CHAR_BUDGET`, the partial core-lookup
  index, `effective_confidence`, `scope_filter`, `get_memory`, and the
  Step 4 service seams (routes must not re-implement scope logic).
  `authorisation.py` here is a skeleton; 049 fills the route-facing role
  matrix per governance §1.
- **Tuning is gated**: any change to `MEMORY_DEDUP_SIMILARITY`, decay
  rates, TTL defaults, or the core-approval rule must update the Step 8
  eval tests in the same PR (Gate G4) and, for the approval rule,
  `governance.md` §2.
- **Prompt-cache interaction (013)**: memory blocks live in instructions
  (prompt-side), never in message history, so ProcessHistory trimming
  (plan 013) is unaffected. 049 must keep its rendered core-memory block
  deterministic so the system-prompt prefix only changes when memories
  actually change.
- **Consolidation stays deferred** until note sprawl is real (donor §4.5);
  if it arrives, it is a 030 job kind riding the same dedup/supersession
  primitives — not a new lifecycle.
- Reviewers should scrutinize: the `scope_filter` predicate (the one place
  isolation lives), the dedup SAVEPOINT/flush behavior inside the run
  transaction (a dedup hit must not poison the caller's transaction), the
  job-time dedup path (at-least-once embed jobs must stay idempotent), and
  that no tool schema grew a provenance or account parameter.
