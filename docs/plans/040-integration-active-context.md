# Plan 040: Integration active context — selection, resolution, runtime injection

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Sibling-plan pre-flight (run before Step 1)**: this plan was written in
> parallel with plans 037/038/039 against a dictated contract (see "Current
> state — dictated 037–039 contract"). Before coding, verify the *implemented*
> 037/038/039 code matches every dictated name used below
> (`integration_connections`, `integration_resources`, connection status
> machine, `services/integrations/manifest.py` with `provider_keys`/
> `resource_types` compatibility metadata, `routes/integrations/`). Any
> mismatch is a STOP condition — reconcile against the landed code, do not
> guess.
>
> **Drift check (run first)**: `git diff --stat 0cbbb39..HEAD -- apps/api/services/agents/runtime/ apps/api/models/agent.py apps/api/models/agent_run.py apps/api/services/agent_schedules/ apps/api/routes/schedules/ apps/api/services/integrations/ apps/web/src/features/schedules/`
> Integration files changing is EXPECTED (037–039 land first). If any
> *runtime or schedule* file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM-HIGH (touches the runtime turn construction path used by
  every conversation, schedule, and delegation; adds a field to a frozen
  runtime dataclass; changes schedule route contracts)
- **Depends on**: 037/038/039 (hard — models, manifest, credential service,
  discovery, resource selection), 018 (hard, DONE — the prompt-block
  assembler), 025/026 (hard, DONE — tool contract and dispatch), 021/022
  (hard, DONE — schedule routes/UI this plan extends)
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md` §4
  row 040; donor `DONOR_PORT_ROADMAP.md` §4.2 "Active Context" / §6 row C4;
  decision D3 full multi-connection)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Final table names** (roadmap left them open): `active_context_selections`
   (one row per user per workspace), `integration_context_groups`
   (workspace-scoped, soft-deleted — `BaseModel`), and
   `integration_context_group_members` (plain join rows, hard-deleted with
   the group: `Base + UUIDMixin + CreatedAtMixin`, the
   `models/rate_limiting.py:16` non-soft-delete composition). All on the
   **core** migration branch (roadmap D5).
2. **One selection value shape everywhere.** The persisted selection is
   exactly the shape the donor comment on `AgentSchedule.active_context`
   already documents (`models/agent.py:138-140`):
   `{"type": "resource", "integration_resource_id": <uuid>}` or
   `{"type": "context_group", "context_group_id": <uuid>}`. One Pydantic
   model (`ActiveContextSelectionValue`, discriminated on `type`) validates
   it for the selection routes, the schedule routes, and the schedule
   worker path. `active_context_selections` stores it relationally (XOR FK
   columns + CHECK), `agent_schedules.active_context` keeps the existing
   JSONB column — no schema change needed there, the column already exists.
3. **Context source is chosen by run principal.** Resolution happens once
   per run in `execute_run` before `RuntimeDeps` is built: `interactive`
   runs read the caller's `active_context_selections` row; `scheduled` runs
   read `AgentSchedule.active_context` (found via
   `AgentScheduleRun.agent_run_id`); `delegated` runs walk
   `AgentRun.parent_run_id` (`models/agent_run.py:45`) to the root run and
   use *its* source, so a scheduled parent's delegates operate on the
   schedule's saved context, not the delegating user's live selection.
4. **Resolution failure degrades, never crashes a run.** A dangling
   resource/group id, a deleted group, or an all-unavailable context
   resolves to an empty `ResolvedActiveContext` with `unavailable` entries
   recorded; the run proceeds with integration tools filtered out and the
   prompt block saying why. A broken selection must not brick chat.
5. **Multi-connection (D3) falls out of resource-driven resolution.**
   Resources belong to connections; a group may span N resources across N
   connections of the same provider, and all resolve. Entries whose
   connection status is `active` or `degraded` are usable (`degraded`
   flagged in the prompt block); `needs_reauth`/`error`/`revoked`/
   pre-active statuses make the entry **unavailable** (listed, not usable).
   Duplicate external principals across connections (same
   `provider_key` + resource `external_id`, detectable via 037's principal
   fingerprints) dedup to the most recently created active connection.
6. **Tool compatibility metadata lives on the tool definition.** 040 adds
   one optional frozen field to `RuntimeToolDefinition`
   (`contract.py:33-57`): `integration_binding: IntegrationToolBinding |
   None = None`, a frozen dataclass of `provider_keys: frozenset[str]`,
   `resource_types: frozenset[str]`, `requires_write: bool`.
   `validate_definition` checks bindings at import time against the 037
   manifest (unknown provider key or resource type fails the process, the
   plan 025/030 fail-at-import shape).
7. **The donor law is enforced at import time**: context is
   server-resolved; integration tool schemas NEVER take account/connection
   parameters. `validate_definition` rejects any integration-bound
   function tool whose signature declares a parameter named in a
   deny-list (`connection_id`, `connection_label`, `resource_id`,
   `integration_resource_id`, `account_id`, `customer_id`, `base_id`,
   `mailbox`, `principal`). A reviewer seeing such a parameter blocks the
   PR; the import-time check means it never even boots.
8. **Filtering is build-time, not run-time.** Integration-bound tools are
   skipped in `build_runtime_tools` when the resolved context has no
   compatible usable entry — the same skip pattern the registry already
   uses for disallowed tools (`registry.py:127-133`). Probed alternative
   (recorded below): pydantic-ai 2.1.0 `FilteredToolset` filters per
   request via `filter_func(ctx, tool_def)`. Rejected because the Praxis
   agent is constructed fresh per turn with plain `tools=[...]`
   (`loop.py:57-66`), the prompt block needs the same resolved context
   anyway, and a second filtering mechanism would split one policy across
   two layers. Tool bodies still re-check (decision 10) against races.
9. **The catalog stays unfiltered.** `list_allowed_tool_definitions`
   (`registry.py:189-203`) and the agent form keep showing integration
   tools regardless of the caller's current context — configuring a tool
   on an agent is config-time; hiding it from the *model* is run-time.
   The `is_tool_allowed` seam (`permissions.py:8-15`) is left for
   workspace-level availability (041 gates by provider configuration
   there); context filtering gets its own explicit predicate.
10. **Fan-out is sequential in v1** with a per-resource result envelope:
    one entry failing never fails the others, write-gated entries produce
    a per-resource `write_not_permitted` error without touching the
    provider, and an empty compatible set raises `ModelRetry` (the tool
    was mounted, then the context changed between turns). Bounded
    concurrency is a recorded follow-up, not built now.
11. **No per-conversation context override in v1.** Selection is
    per-user-per-workspace plus per-schedule, exactly the roadmap scope.
    042's chat-header picker writes the workspace-level selection (042
    must match this shape — recorded there as a dependency note).
12. **040 ships the minimal schedule-form selector**, extending 022's UI
    with a flat resource/group `Select` fed by this plan's list routes.
    042 replaces it with the shared rich picker. Roadmap assigns the 022
    extension to 040 explicitly; shipping schedule routes that accept
    `active_context` with no way to set it would violate the AGENTS.md
    "wired end to end" rule.
13. **Roles per `governance.md` §1**: selection and context-group editing
    are member+ (`require_editor`); reads are `require_read`. Group
    mutations and selection changes write audit events (workspace flows
    stay debuggable per AGENTS.md).
14. **Prompt block budget 2000 chars**, using the 018 assembler's soft
    budget (`prompt.py:73-85` truncates and warns). Big contexts truncate
    the *listing*, never the law text, so the block renders the rules
    first.

## Why this matters

Integrations without active context reproduce the donor's worst UX: every
tool call asks "which account?", the model guesses, and multi-tenant agency
work (D3's whole point) becomes prompt roulette. This plan is the seam that
makes 041's providers safe and usable: the server decides what the agent
operates on (selection → resolution → injection), the model is told in the
system prompt, tools that can't act on the current context never reach the
model, and every fan-out result is attributable to one resource on one
connection. It is also the last structural change to the runtime turn path
in Phase 4a — 041 only *adds registry entries* on top of the binding,
filtering, and fan-out machinery built here.

## Current state

All anchors verified at `0cbbb39`.

### Runtime seam

- `apps/api/services/agents/runtime/context.py:18-30` — `RuntimeDeps` is a
  frozen dataclass (`db/user/workspace/conversation/agent/run/sink/
  envelope/delegation_depth`); the injection target.
- `apps/api/services/agents/runtime/execute_run.py:159-186` —
  `build_runtime_agent(...)` is called at 159, `RuntimeDeps(...)`
  constructed at 176, both inside one function with `db`, `user`,
  `workspace`, `run` in scope — resolution slots in between.
- `apps/api/services/agents/runtime/loop.py:40-78` — `build_runtime_agent`
  mounts `tools=build_runtime_tools(agent, include_delegation=...)` (line
  66) and instructions via `_runtime_instructions` (87-90) which calls
  `build_system_prompt(runtime_prompt_blocks(agent, ...))`.
- `apps/api/services/agents/runtime/prompt.py:39-46` — `PromptBlock(key,
  content, budget)`; `runtime_prompt_blocks` (48-60) returns the ordered
  `identity`/`planning`/`delegation` blocks; `build_system_prompt` (63-70)
  joins non-empty blocks; `_render_block` (73-85) enforces the soft budget
  with a `[truncated]` marker and warning log. This is 018's designed
  extension point ("future context slices append here", line 3).
- `apps/api/services/agents/runtime/tools/contract.py` —
  `RuntimeToolDefinition` fields (33-57): `name/function/description/
  provider/label/kind/effect/takes_ctx/default_policy/supports_auto/
  supports_approval/timeout/max_retries/args_validator/defer_loading/
  output_model/capability_factory/supported_model_providers/configurable/
  auto_mount`. **No compatibility metadata exists** — this plan adds it.
  Tool name pattern is `^[a-z][a-z0-9_]*$` (line 29) — **dots are
  invalid**, so 041's names are snake_case. `validate_definition`
  (109-176) is the import-time invariant checker to extend.
- `apps/api/services/agents/runtime/tools/registry.py` — catalog dict
  (line 30), `runtime_tool` decorator (33-91), `build_runtime_tools`
  (94-147) with the skip-pattern precedent at 125-133 (capabilities
  skipped, `is_tool_allowed` skip logged at info), catalog read
  `list_allowed_tool_definitions` (189-203), registration side-effect
  imports at 254-258.
- `apps/api/services/agents/runtime/tools/permissions.py:8-15` —
  `is_tool_allowed(definition, *, workspace, agent=None)` is a stub
  returning `True`; signature takes no user/context.
- `apps/api/services/agents/runtime/dispatch.py:127-227` —
  `dispatch_tool_execution` audits the *outer* tool call (args digest,
  outcome, approval refs). Per-resource audit inside fan-out is
  additional, not a replacement (041 emits it).
- `apps/api/services/agents/runtime/envelope.py:13-30` — `RunPrincipal =
  interactive|scheduled|delegated` mirrors `AgentRun.trigger`
  (`models/agent_run.py:58`, CHECK at 103).

### Schedules

- `apps/api/models/agent.py:104-165` — `AgentSchedule`;
  **`active_context` already exists** (JSONB, nullable, lines 138-140)
  with the exact selection-shape comment this plan adopts. No migration
  needed on this table.
- `apps/api/services/agent_schedules/schemas.py` — `AgentScheduleRead`
  (55-109) omits `active_context`; create/update requests (126-178) don't
  accept it. `tests/routes/schedules/test_schedule_routes.py:140` pins
  `assert "active_context" not in body` — flip it in Step 8.
- `apps/api/services/agent_schedules/prepare_schedule_run_execution.py:46-113`
  creates the conversation + `AgentRun` for a claimed schedule run;
  `AgentScheduleRun.agent_run_id` links run → schedule (the join Step 4's
  scheduled-principal lookup uses).
- `apps/web/src/features/schedules/` — 022's UI: form model
  (`components/schedule-form-model.ts:26-35` `ScheduleFormState`), form
  sections, per-operation API files with workspace-scoped query keys
  (`api/list-schedules.ts:16-27`).
- `apps/api/models/agent_run.py:45` `parent_run_id`, 50
  `delegation_depth` — the delegated-root walk is bounded by depth.
  `services/agents/runtime/delegation/delegate_to_agent.py:94` shows
  delegated runs keep the parent's `user_id`.

### Dictated 037–039 contract (verify against landed code)

- 037: `models/integrations.py` — `external_credentials`,
  `integration_connections` (owner user XOR workspace, required `label`,
  no per-provider uniqueness, status machine `auth_pending →
  discovery_pending → needs_resource_selection →
  active/degraded/error/revoked/needs_reauth`), `integration_resources`
  (generic, `enabled`, write-permission metadata),
  `integration_discovery_runs`; `services/integrations/manifest.py`
  (auth modes, owner scope, resource types, capability flags,
  `provider_keys`/`resource_types` compatibility metadata);
  `services/secrets/` references-only abstraction.
- 038: OAuth + api-key connect + test/revoke/refresh routes under
  `/api/v1/integrations` (`routes/integrations/` package).
- 039: discovery job kind `integrations.discover_resources`; resource
  selection routes; `needs_resource_selection` computed from enabled
  resources.
- None of this exists at `0cbbb39` (`services/integrations/` and
  `services/secrets/` absent — verified).

### pydantic-ai 2.1.0 probe results (recorded 2026-07-06)

- `pydantic_ai.toolsets` exposes `FilteredToolset`, `PreparedToolset`,
  `CombinedToolset`, `FunctionToolset`, etc. `AbstractToolset.filtered`
  signature: `filtered(filter_func: Callable[[RunContext[AgentDepsT],
  ToolDefinition], bool | Awaitable[bool]])`; `FilteredToolset.get_tools`
  awaits the predicate per tool per request — run-time filtering with
  `ctx.deps` is available if ever needed (decision 8 rejected it for now).
- `pydantic_ai.tools.ToolDefinition` carries a `metadata` field (and
  `SetMetadataToolset`/`with_metadata` exist) — bindings *could* ride
  toolset metadata, but Praxis mounts plain `Tool` objects, so the binding
  stays on `RuntimeToolDefinition` (decision 6).
- `Agent.__init__` accepts both `tools` and `toolsets`; Praxis uses
  `tools` only (`loop.py:57-66`).

### Migrations

- Core head at `0cbbb39` is `core_0008`
  (`alembic/versions/core/0008_add_conversation_todos.py`). 037/039 land
  core migrations first — number this plan's migration against the real
  head at execution time.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations after Step 1 |
| Apply migration | `uv run alembic upgrade heads` | three tables created |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/routes/integrations -q` | all pass |
| Runtime regression | `TEST_DATABASE_URL=... uv run pytest tests/services/agents -q` | all pass |
| Schedule regression | `TEST_DATABASE_URL=... uv run pytest tests/services/agent_schedules tests/routes/schedules -q` | all pass |
| Frontend gate (Step 9) | `cd apps/web && pnpm check` | exit 0, zero warnings |

## Scope

**In scope:**

- `apps/api/models/integration_context.py` (create — three models) +
  `models/__init__.py` registration
- `apps/api/alembic/versions/core/00NN_*.py` (create — core branch, D5)
- `apps/api/services/integrations/context/` (create): `__init__.py`,
  `domain.py`, `schemas.py`, `utils.py`, `get_active_context_selection.py`,
  `set_active_context_selection.py`, `clear_active_context_selection.py`,
  `list_context_groups.py`, `create_context_group.py`,
  `update_context_group.py`, `delete_context_group.py`,
  `resolve_active_context.py`, `fan_out.py`, `prompt_block.py`
- `apps/api/services/agents/runtime/`: `context.py` (one field),
  `prompt.py` (one block slot), `loop.py` + `execute_run.py` (threading),
  `tools/contract.py` (binding + validation), `tools/registry.py`
  (build-time filter)
- `apps/api/routes/integrations/` (extend 038's package): `get_context.py`,
  `set_context.py`, `clear_context.py`, `list_context_groups.py`,
  `create_context_group.py`, `update_context_group.py`,
  `delete_context_group.py`
- Schedule surface: `services/agent_schedules/schemas.py`,
  `create_schedule.py`, `update_schedule.py`, `routes/schedules/` (no new
  files — request/response contracts only)
- `apps/web/src/features/schedules/` minimal selector +
  `apps/web/src/features/integrations/api/` first read-only files
  (context groups list, resources list re-use of 039's endpoint, active
  context get/set for the schedule form)
- `apps/api/tests/services/integrations/context/`,
  `tests/routes/integrations/`, updates to
  `tests/routes/schedules/test_schedule_routes.py`, `tests/factories/`
  helpers for connections/resources/groups

**Out of scope (do NOT touch):**

- ANY provider implementation, manifest entry, or agent-callable
  integration tool — 041 owns those (this plan ships machinery with zero
  integration tools registered).
- Connections/credentials/discovery models, OAuth flows, resource
  selection routes — 037/038/039 own them; this plan only *reads*
  connections and resources.
- The rich connection/context pickers, provider cards, chat-header picker
  — 042. This plan's only UI is the minimal schedule-form selector
  (decision 12).
- Per-conversation context overrides (decision 11).
- `is_tool_allowed` behavior changes (041 uses that seam for
  provider-configured gating).
- MCP, concurrency in fan-out, notification changes.

## Git workflow

- Branch: `advisor/040-integration-active-context`
- Commit style: `API - Integration Active Context` for backend commits,
  `Web - Schedule Active Context Selector` for the Step 9 frontend slice
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Models + core migration

Create `models/integration_context.py`:

`IntegrationContextGroup(BaseModel)` — `__tablename__ =
"integration_context_groups"`:

- `workspace_id` UUID FK `workspaces.id` `ondelete="CASCADE"`, not null,
  indexed
- `name` String(120) not null; `created_by_user_id` UUID FK `users.id`
  `ondelete="SET NULL"`, nullable
- Partial unique index `(workspace_id, lower(name)) WHERE deleted = false`
  (expression index — add by hand in the migration, mirror in
  `__table_args__` with `sa.text`, the plan 030 Step 2 shape)
- Relationship `members` → cascade `all, delete-orphan`

`IntegrationContextGroupMember(Base, UUIDMixin, CreatedAtMixin)` —
`__tablename__ = "integration_context_group_members"`:

- `group_id` UUID FK `integration_context_groups.id` `ondelete="CASCADE"`,
  not null, indexed
- `integration_resource_id` UUID FK `integration_resources.id`
  `ondelete="CASCADE"`, not null, indexed
- UniqueConstraint `(group_id, integration_resource_id)`

`ActiveContextSelection(Base, UUIDMixin, TimestampMixin)` —
`__tablename__ = "active_context_selections"` (no soft delete — clearing
deletes the row, decision 1):

- `user_id` UUID FK `users.id` `ondelete="CASCADE"`, not null
- `workspace_id` UUID FK `workspaces.id` `ondelete="CASCADE"`, not null
- `integration_resource_id` UUID FK `integration_resources.id`
  `ondelete="CASCADE"`, nullable
- `context_group_id` UUID FK `integration_context_groups.id`
  `ondelete="CASCADE"`, nullable
- UniqueConstraint `(user_id, workspace_id)`
- CHECK `num_nonnulls(integration_resource_id, context_group_id) = 1`
  (name it `active_context_selections_target_check`)

Register all three in `models/__init__.py`. Generate on the core branch:
`uv run alembic revision --autogenerate --head core@head --version-path
alembic/versions/core -m "add active context tables"` — hand-check the
expression index and CHECK made it in with matching `downgrade`.

**Verify**: `uv run alembic upgrade heads` applies; `uv run alembic check`
clean; downgrade/upgrade round-trips.

### Step 2: Domain, selection schema, resolved-context types

`services/integrations/context/domain.py`:

- `SELECTION_TYPE_RESOURCE = "resource"`,
  `SELECTION_TYPE_CONTEXT_GROUP = "context_group"`
- Frozen dataclasses: `ResolvedContextEntry(integration_resource_id,
  provider_key, resource_type, external_id, display_name, connection_id,
  connection_label, connection_status, write_allowed: bool)`;
  `UnavailableContextEntry(display_name, provider_key, reason)` (reason ∈
  `connection_needs_reauth | connection_revoked | connection_error |
  connection_inactive | resource_disabled | resource_removed | dangling`);
  `ResolvedActiveContext(source: Literal["user_selection",
  "schedule"] | None, selection_kind, group_id, group_name,
  entries: tuple[ResolvedContextEntry, ...],
  unavailable: tuple[UnavailableContextEntry, ...])` with helpers
  `is_empty` and `compatible_entries(binding)` (provider_key ∈
  `binding.provider_keys` AND resource_type ∈ `binding.resource_types`).
- `EMPTY_ACTIVE_CONTEXT` singleton for "no selection".

`services/integrations/context/schemas.py`: `ActiveContextSelectionValue`
— discriminated union on `type` matching decision 2, plus route response
models (`ActiveContextRead` echoing selection + resolved entry summaries,
`ContextGroupRead` with members, list responses). Reuse this model in
`agent_schedules/schemas.py` (Step 8) — one shape everywhere.

**Verify**: `uv run ruff check .` exit 0;
`uv run python -c "from services.integrations.context.schemas import ActiveContextSelectionValue; print(ActiveContextSelectionValue.model_validate({'type':'resource','integration_resource_id':'00000000-0000-0000-0000-000000000001'}).type)"`
→ `resource`.

### Step 3: Selection + context-group service operations (one per file)

- `get_active_context_selection.py` — load the caller's row (or None).
- `set_active_context_selection.py` — validate the target exists in this
  workspace and is not deleted (resource: also its connection belongs to
  this workspace or to this user in this workspace; group: workspace
  match), upsert the `(user, workspace)` row, write an audit event
  (`services/audit_events` operations precedent), return the row. Raise
  `AppValidationError` for a dangling target, `NotFoundError` for
  cross-workspace ids (do not leak existence).
- `clear_active_context_selection.py` — delete the row if present; audit.
- `list_context_groups.py` — workspace groups with member resources
  (selectinload), ordered by name.
- `create_context_group.py` / `update_context_group.py` — validate name
  non-blank ≤120, member resource ids exist in-workspace and are not
  deleted; enforce the name uniqueness index (catch `IntegrityError` →
  `ConflictError`); update replaces the member set; audit both.
- `delete_context_group.py` — soft-delete the group; **also delete any
  `active_context_selections` rows pointing at it and null any
  `agent_schedules.active_context` referencing it** is NOT done — instead
  resolution treats dangling references as `unavailable` (decision 4);
  document that in the docstring. Audit.

`services/integrations/context/__init__.py` re-exports operations only
(AGENTS.md service-package rule). Helpers (`_load_workspace_resource`,
`_load_workspace_group`) go in `utils.py`.

**Verify**: ruff exit 0; unit smoke via Step 10 tests.

### Step 4: Resolution

`resolve_active_context.py` — `resolve_active_context(db, *, run,
user, workspace) -> ResolvedActiveContext`. Algorithm (each numbered step
is load-bearing):

1. **Pick the source by principal.** `trigger = run.trigger`; while
   `trigger == "delegated"` and `run.parent_run_id` is set, load the
   parent (bounded by `delegation_depth`, max `settings`-configured depth)
   and take its trigger — decision 3. `interactive` → the root run's
   user's `active_context_selections` row for this workspace; `scheduled`
   → the `AgentScheduleRun` with `agent_run_id == root_run.id` →
   `schedule.active_context` parsed through
   `ActiveContextSelectionValue` (malformed JSON → treat as no selection,
   log warning). No selection → `EMPTY_ACTIVE_CONTEXT`.
2. **Expand the selection.** `resource` → `[resource_id]`; `context_group`
   → the group's member resource ids (deleted group → return empty with
   one `dangling` unavailable entry, decision 4).
3. **Load resources + connections in one query** (join
   `integration_resources` → `integration_connections`, workspace-scoped).
   Classify each: resource soft-deleted/`removed` lifecycle →
   `resource_removed`; resource not `enabled` → `resource_disabled`;
   connection status `active`/`degraded` → usable; `needs_reauth`,
   `revoked`, `error` → corresponding unavailable reason; any pre-active
   status → `connection_inactive`.
4. **Dedup external principals** (decision 5): group usable entries by
   `(provider_key, external_id)`; keep the one on the most recently
   created `active` connection (prefer `active` over `degraded`, then
   newest `created_at`); drop the rest silently (log debug).
5. **Compute `write_allowed`** from the resource's discovered
   write-permission metadata (037 contract: `integration_resources`
   carries it). Absent metadata → `False` (fail closed; 041's discovery
   populates it).
6. Return the frozen `ResolvedActiveContext` (usable entries sorted by
   provider_key then display_name; unavailable listed).

**Verify**: ruff exit 0; behavior pinned in Step 10
`test_resolve_active_context.py`.

### Step 5: Tool binding + import-time law + build-time filtering

`services/agents/runtime/tools/contract.py`:

- Add frozen dataclass `IntegrationToolBinding(provider_keys:
  frozenset[str], resource_types: frozenset[str], requires_write: bool =
  False)` and field `integration_binding: IntegrationToolBinding | None =
  None` on `RuntimeToolDefinition` (defaulted — zero impact on existing
  definitions).
- Extend `validate_definition` (after the existing checks at 109-176):
  binding ⇒ `kind == function`; `provider_keys`/`resource_types` non-empty
  lowercase tokens; every `provider_key` exists in the 037 manifest and
  every `resource_type` is declared by one of those providers (import the
  manifest inside the function to keep contract.py import-light);
  `requires_write` ⇒ `effect == "write"`; **and the decision-7 deny-list**:
  inspect `definition.function`'s signature (skip `ctx`) and raise
  `RuntimeError("Integration tools must not take connection/account
  parameters; context is server-resolved")` on any denied name.
- Mirror the binding in `runtime_tool(...)` decorator kwargs
  (`registry.py:33-91`) and in `ToolCatalogEntry`
  (`tools/schemas.py`) as optional `provider_keys`/`resource_types`
  fields so 042 can group by real provider.

`services/agents/runtime/tools/registry.py`:

- `build_runtime_tools(agent, *, include_delegation=False,
  active_context: ResolvedActiveContext | None = None)` — before
  mounting, skip any definition where `integration_binding is not None`
  and `(active_context is None or not
  active_context.compatible_entries(definition.integration_binding))`;
  log at info like the 127-133 precedent. Type the parameter with a
  `TYPE_CHECKING` import if needed to avoid a runtime import cycle
  (contract → context domain is fine; keep the domain module free of
  runtime imports).

**Verify**: `uv run pytest tests/services/agents -q` still green
(no integration tools exist yet, so behavior is unchanged); a throwaway
in-test definition with `connection_id` in its signature raises at
`validate_definition` (Step 10 contract test).

### Step 6: Fan-out executor + write gating

`services/integrations/context/fan_out.py`:

```python
@dataclass(frozen=True)
class FanOutEntryResult:
    integration_resource_id: UUID
    connection_id: UUID
    provider_key: str
    external_id: str
    display_name: str
    status: Literal["success", "error"]
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None

async def run_context_fan_out(deps, *, binding, operation, write: bool = False) -> list[FanOutEntryResult]:
    ...
```

Behavior (decision 10):

- `entries = deps.active_context.compatible_entries(binding)`; empty →
  `raise ModelRetry("No compatible resources in the active context. Ask
  the user to select a context that includes <provider labels>.")`.
- `write=True` (or `binding.requires_write`): entries with
  `write_allowed=False` get a `FanOutEntryResult(status="error",
  error_code="write_not_permitted")` **without** invoking `operation`.
- Execute `operation(entry)` sequentially per remaining entry; catch
  `IntegrationError` subclasses (`core/exceptions/integration.py:14-137`)
  and generic exceptions into per-entry error results
  (`error_code = exc.__class__.__name__`, message via the schedule
  runner's 1000-char sanitize rule — copy the tiny helper into
  `utils.py`, do not import across service packages).
- Sanitized error messages only; one entry's failure never aborts the
  loop. The executor itself does not audit — 041's operations emit the
  per-resource audit event inside `operation` so provider context
  (external change ids) is available.

**Verify**: `test_fan_out.py` (Step 10) pins partial failure, write
gating, and the empty-set retry.

### Step 7: RuntimeDeps injection + prompt block

- `context.py`: add `active_context: "ResolvedActiveContext | None" =
  None` to `RuntimeDeps` (defaulted — existing constructors and tests
  keep working; delegation sub-runs build their own deps and re-resolve).
- `services/integrations/context/prompt_block.py`:
  `render_active_context_block(resolved) -> str`. Empty context → `""`
  (block drops out per `build_system_prompt`, `prompt.py:65`). Otherwise
  render, in order: (a) the law — "You are operating on the following
  active context. You cannot choose different accounts or connections;
  integration tools run against every compatible resource below and
  return per-resource results."; (b) group name when present; (c) one
  line per entry: `- {display_name} ({provider label} {resource_type},
  connection "{connection_label}"{, degraded}{, read-only})`; (d)
  unavailable entries with reasons ("needs re-authentication" etc.).
- `prompt.py`: `runtime_prompt_blocks(agent, *, include_delegation,
  active_context_block: str = "")` appends
  `PromptBlock("active_context", active_context_block, budget=2000)`
  after `delegation` (decision 14).
- `loop.py`: `build_runtime_agent(..., active_context:
  ResolvedActiveContext | None = None)` threads the resolved context into
  both `build_runtime_tools` (Step 5) and `_runtime_instructions` (which
  calls `render_active_context_block`).
- `execute_run.py`: between `load_actor_context` (line 150) and
  `build_runtime_agent` (159), call `resolve_active_context(db, run=run,
  user=user, workspace=workspace)` inside a `try/except Exception` that
  logs and falls back to `EMPTY_ACTIVE_CONTEXT` (decision 4); pass the
  result to `build_runtime_agent` and `RuntimeDeps`.

**Verify**: `TEST_DATABASE_URL=... uv run pytest tests/services/agents -q`
green; a manual prompt-assembly unit test shows the block appears only
when entries or unavailable items exist.

### Step 8: Routes + schedule contract

Routes (one operation per file in `routes/integrations/`, composed in the
package `__init__.py` created by 038; RBAC per decision 13):

- `GET /integrations/context` (`require_read`) → the caller's selection +
  a resolved summary (entries/unavailable) so pickers can render state
- `PUT /integrations/context` (`require_editor`) — body
  `ActiveContextSelectionValue`
- `DELETE /integrations/context` (`require_editor`) → 204
- `GET /integrations/context-groups` (`require_read`)
- `POST /integrations/context-groups` (`require_editor`) — `{name,
  resource_ids}`
- `PATCH /integrations/context-groups/{group_id}` (`require_editor`)
- `DELETE /integrations/context-groups/{group_id}` (`require_editor`)

Schedule contract: add `active_context: ActiveContextSelectionValue |
None` to `AgentScheduleCreateRequest`/`AgentScheduleUpdateRequest`
(update: explicit-null clears — use a sentinel-aware
`model_fields_set` check, matching how other optional clears behave in
`update_schedule.py`) and to `AgentScheduleRead.from_schedule`. Validate
the target through the same Step 3 helpers before persisting. Flip the
pinned assertion at `tests/routes/schedules/test_schedule_routes.py:140`
to assert the field IS present (null by default). The worker path needs
no change — Step 4's scheduled-principal branch reads the column.

**Verify**: `TEST_DATABASE_URL=... uv run pytest tests/routes/schedules
tests/routes/integrations -q` green; manual curl of PUT context with a
cross-workspace resource id → 404 problem+json.

### Step 9: Minimal 022 UI extension (schedule form)

Frontend slice (decision 12), following the feature conventions:

- `apps/web/src/features/integrations/types.ts` — selection value,
  context group, resolved summary types (hand-written, `type` aliases).
- `apps/web/src/features/integrations/api/list-context-groups.ts` and
  `get-active-context.ts` — `queryOptions` factories +
  `useSuspenseQuery` hooks with workspace-scoped query keys
  (`integrationsQueryKeys`, the `list-schedules.ts:16-27` shape).
- `apps/web/src/features/schedules/components/schedule-context-field.tsx`
  — a flat `Select` ("No active context" / groups / enabled resources,
  groups first) storing the selection value in `ScheduleFormState` as
  `activeContext: ActiveContextSelectionValue | null`
  (`schedule-form-model.ts` + payload builders + `types.ts` gain the
  field), rendered in the form near the prompt field.
- Send/read `active_context` in `create-schedule.ts`/`update-schedule.ts`
  request bodies and the `AgentSchedule` type.

**Verify**: `cd apps/web && pnpm check` → exit 0; creating a schedule
with a group in the dev UI persists and round-trips the value.

### Step 10: Tests

`tests/services/integrations/context/` (all `pytestmark =
pytest.mark.asyncio`; DB-backed via `conftest.py`/`tests/factories/` —
add connection/resource/group factories to `tests/factories/`):

- `test_resolve_active_context.py`: single-resource selection resolves;
  group expands to enabled members only; disabled/removed resources →
  unavailable with reasons; `needs_reauth`/`revoked`/`error` connections
  → unavailable; `degraded` usable and flagged; **two connections of the
  same provider both resolve (D3 pinned)**; duplicate
  `(provider_key, external_id)` across connections dedups to the newest
  active connection; scheduled principal reads
  `schedule.active_context`; delegated run walks `parent_run_id` to a
  scheduled root and gets the schedule's context; dangling group id →
  empty + `dangling` entry, no exception; malformed schedule JSON →
  empty + warning.
- `test_fan_out.py`: three compatible entries, middle one raising
  `IntegrationRateLimitError` → results `[success, error, success]`
  (partial-failure invariant pinned); `requires_write` with a read-only
  entry → `write_not_permitted` without the operation being called
  (assert via a spy); zero compatible entries → `ModelRetry`.
- `test_context_binding.py` (no DB): binding with unknown provider key →
  `RuntimeError` at validate; `requires_write` on a read tool →
  `RuntimeError`; **a function tool declaring `connection_id` (and each
  deny-listed name) → `RuntimeError` — the context-never-in-tool-schemas
  law pinned**; `build_runtime_tools` mounts a bound test tool when a
  compatible entry exists and skips it when the context is empty or
  incompatible (register throwaway tools in a fixture, remove from
  `RUNTIME_TOOL_CATALOG` in teardown — the plan 030 Step 7 hygiene rule);
  non-integration tools unaffected by context.
- `test_context_groups.py` + `test_selection_ops.py`: CRUD; duplicate
  name in workspace → conflict; cross-workspace resource in group →
  validation error; selection upsert (set twice keeps one row); clear
  deletes; audit rows written.
- `test_prompt_block.py`: empty context renders `""`; entries render the
  law + per-entry lines + read-only/degraded markers; unavailable section
  renders; oversized listing truncates at the 2000 budget with the law
  intact (law first, decision 14).
- `tests/routes/integrations/test_context_routes.py`: RBAC
  (read_only can GET, cannot PUT — per governance §1), PUT validation,
  cross-workspace 404.
- Updated `tests/routes/schedules/test_schedule_routes.py`: create/update
  with `active_context`, explicit-null clear, invalid target rejected.

**Verify**: full new suites + `tests/services/agents` +
`tests/services/agent_schedules` green; without `TEST_DATABASE_URL` the
DB suites skip, not fail.

## Test plan

Covered by Step 10 (~30-35 tests). Pinned invariants: **fan-out partial
failure isolation**, **compatibility filtering hides incompatible tools
from the model but never from the catalog**, **context never appears in
tool schemas (import-time law)**, **multi-connection resolution (D3)**,
**scheduled and delegated principals resolve from the schedule, not the
user's live selection**, **resolution failure degrades instead of failing
the run**, and **the schedule route contract change is additive** (all
pre-existing schedule tests green with one deliberate flip at line 140).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` clean; migration on the **core** branch (D5)
      and downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/integrations
      tests/routes/integrations tests/services/agents
      tests/services/agent_schedules tests/routes/schedules -q` exits 0
- [ ] `cd apps/web && pnpm check` exits 0
- [ ] Grep shows **zero** registered tools with `integration_binding`
      (041 registers the first ones)
- [ ] `RUNTIME_TOOL_CATALOG` import-time guard rejects deny-listed
      parameter names (covered by test)
- [ ] Schedule create/update accepts, returns, and clears
      `active_context`; the schedule form can set it end to end
- [ ] `docs/architecture/governance.md` §1 rows "Select integration
      resources / edit context groups" flipped to `[implemented: plan 040]`
- [ ] No per-conversation override surface exists anywhere (decision 11)
- [ ] `git status` clean outside the in-scope list;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 037/038/039 are not implemented, or the landed code deviates from the
  dictated contract used here: table/column names, the connection status
  machine values, the manifest module path or its
  `provider_keys`/`resource_types` metadata shape, or
  `integration_resources` lacking write-permission metadata.
- `AgentSchedule.active_context` does not exist at execution time, or its
  documented shape (`models/agent.py:138-140`) changed — the whole
  selection-value decision (2) assumed it.
- `RuntimeDeps`, `build_runtime_agent`, `runtime_prompt_blocks`, or
  `execute_run`'s build-order (agent built at 159, deps at 176) no longer
  match the "Current state" excerpts.
- The core migration head at execution time is not what 037/039 left —
  renumber and re-verify index/constraint names don't collide.
- pydantic-ai has been upgraded past 2.1.0 and `Tool`/toolset mounting
  semantics changed (re-probe before Step 5).
- You feel the need to add provider code, a manifest entry, an
  agent-callable integration tool, or a rich picker component — scope
  leaking into 041/042.
- Adding the `active_context` field to `RuntimeDeps` breaks frozen-
  dataclass construction anywhere you cannot fix by passing the new
  keyword (an unknown construction site means the runtime map above is
  stale).

## Maintenance notes

- **041 consumes**: `IntegrationToolBinding` (every provider tool must set
  it), `run_context_fan_out` (every multi-resource operation rides it),
  and the per-entry audit slot inside `operation`. 041's review checklist:
  no tool without a binding, no binding without manifest backing, no
  denied parameter names.
- **042 consumes**: the context routes (Step 8) and must honor decision 11
  (no per-conversation override) — the chat-header picker writes the
  per-user-per-workspace selection and invalidates the GET.
- **Dedup rule** (decision 5, newest-active-connection wins) is a policy
  default — if agencies need explicit per-resource connection pinning,
  the seam is Step 4 point 4; record any change in
  `docs/architecture/governance.md`.
- **Fan-out concurrency**: when a provider's rate limits allow it, add
  bounded concurrency inside `run_context_fan_out` only — tool bodies must
  stay ignorant of execution strategy.
- Reviewers should scrutinize: the delegated-root walk (must terminate,
  bounded by depth), the fail-closed `write_allowed` default, the
  SAVEPOINT-free upsert in `set_active_context_selection` (unique
  constraint race → retry or `ConflictError`, never a 500), and that the
  prompt block renders the law before the listing so budget truncation
  never eats the rules.
