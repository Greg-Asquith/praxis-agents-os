# Plan 028: First real registry tools — agent TODO planning + native web search

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat <plan-026-merge>..HEAD -- apps/api/services/agents/runtime/ apps/api/models/ apps/api/routes/tools/`
> Plans 025 AND 026 must be DONE. If the registry/dispatch files differ from
> what those plans specify, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM (first contract amendment — capability-backed entries —
  and first migration of this phase; native-tool mounting varies by model
  provider)
- **Depends on**: 025, 026 (hard). 027 lands these in the UI automatically.
  018 (soft — see Maintenance notes on instructions injection).
- **Category**: harness spine (roadmap `000_MASTER_ROADMAP.md` Phase 1,
  final item — proves the registry with entries beyond demos)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

1. **The TODO tool is conversation-scoped and durable** — one row per
   conversation (`conversation_todos`, `core` branch), whole-list-replace
   semantics (`write_todos`) plus `read_todos`. This is our own build,
   informed by the donor and by the pydantic-ai-todo pattern from NOTES:
   whole-list replace is what models handle reliably; per-item CRUD invites
   drift. Items are `{content, status}` with status
   `pending|in_progress|completed`, capped (50 items, 500 chars each) — a
   planning scratchpad, not a datastore.
2. **`write_todos` is honestly `effect="write"`** (it mutates DB state) with
   `default_policy="auto"` — approval on a self-notes tool would train users
   to rubber-stamp. The 026 envelope can still deny it wholesale for
   hypothetical locked-down principals.
3. **Native web search ships as a `capability`-kind registry entry.**
   pydantic-ai's `WebSearch` is a capability, not a function tool, so the
   contract gains a second kind (`kind: "function" | "capability"` +
   `capability_factory`) — the amendment 025's maintenance note anticipated.
   Policy/catalog/write-time validation treat it like any entry; mounting
   differs (it joins `capabilities=[...]`, not `tools=[...]`).
4. **Native-only in v1, no DuckDuckGo local fallback** — no new scraping
   dependency, deterministic provider behavior. Entries declare
   `supported_model_providers`; at mounting time an agent whose resolved
   model provider lacks native search gets the capability **skipped with a
   log line** (mirror of `is_tool_allowed` skip semantics from 025), never a
   broken run. `WebFetch` is explicitly deferred (SSRF/story needs 029's
   governance pass).
5. **Approval is not offered for native search** (`supports_approval=False`,
   `effect="read"`): provider-native execution happens server-side at the
   model provider — our choke point cannot intercept it, so offering an
   approval mode would be a lie. It CAN still be audited after the fact
   (decision 6) and switched off per agent.
6. **Builtin tool calls are audited from stream events.** Provider-native
   invocations surface as builtin tool parts in the event stream;
   `execute_run`'s translator emits the same
   `record_tool_invocation_audit_event` with `tool_provider="native"` and a
   digest of the search input. Latency is provider-side and recorded as
   null.

## Why this matters

Two demo tools prove nothing about the registry's ergonomics; these entries
do. The TODO tool gives every agent visible multi-step planning (the chat UI
already renders tool calls generically, so plans are user-legible for free)
— the NOTES ask, built our way. Native web search is the first
capability-backed entry and forces the registry to answer "how do
provider-native tools get policy/audit treatment" *now*, with a read-only
tool, rather than during integrations. After this plan, the pattern for
034/041/046/048/050 tools is fully rehearsed.

## Current state

- Registry (after 025): `@runtime_tool` decorator, `RUNTIME_TOOL_CATALOG`,
  provider modules assembled in `registry.py`, catalog read API,
  `is_tool_allowed` seam, write-time policy-capability validation.
- Dispatch (after 026): hooks/wrapper choke point, `record_tool_invocation_
  audit_event` (own-session, fire-and-forget), `RunEnvelope` on
  `RuntimeDeps`, output-contract validation, mutation warnings.
- Agent construction: `loop.py` `build_runtime_agent` passes
  `tools=build_runtime_tools(...)` and
  `capabilities=build_runtime_capabilities(agent)`; the runtime knows the
  resolved model (`RuntimeAgent.resolved_model`).
- `RuntimeDeps` carries `db`, `conversation`, `workspace`, `agent`, `run` —
  everything the TODO tool needs; tools receive it via
  `RunContext[RuntimeDeps]` (`takes_ctx=True` pattern in
  `runtime/tools/core.py` after 025).
- `Conversation` model: `models/conversation.py` (id/workspace/source
  columns per plan 021's report). **No todo/plan storage exists anywhere.**
- pydantic-ai 2.1.0 (repo digest `docs/pydantic-ai/04:163-197`): `WebSearch`
  is provider-adaptive (`native=`/`local=` knobs); provider-native tools
  execute in the request prefix; **exact capability constructor args, the
  builtin-tool event/part shapes, and which of our configured providers
  support native search must be probed against the installed package, not
  assumed** (plan 018 set the precedent for recording probe results in the
  plan/code).
- Migrations: `core` branch; `uq_`/`ix_` naming and JSONB defaults per
  existing models (`models/agent.py` JSONB columns with
  `server_default=text("'[]'::jsonb")`).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration | `uv run alembic revision --autogenerate --head core@head --version-path alembic/versions/core -m "add conversation todos"` | one table only |
| Apply + sanity | `uv run alembic upgrade heads && uv run alembic check` | clean |
| Tests | `uv run pytest tests/services/agents/runtime tests/services/conversations tests/routes/tools -q` | all pass |
| Full | `uv run pytest -q` | all pass |

## Scope

**In scope:**

- `apps/api/models/conversation_todos.py` (create) + one `core` migration
- `apps/api/services/agents/runtime/tools/contract.py` (amend: `kind`,
  `capability_factory`, `supported_model_providers`; validation)
- `apps/api/services/agents/runtime/tools/planning.py` (create — provider
  module: `write_todos`, `read_todos`)
- `apps/api/services/agents/runtime/tools/native.py` (create — provider
  module: `web_search` capability entry)
- `apps/api/services/agents/runtime/tools/registry.py` (assembly imports;
  `build_runtime_native_capabilities(agent, resolved_model)`)
- `apps/api/services/agents/runtime/loop.py` (mount native capabilities)
- `apps/api/services/agents/runtime/execute_run.py` or the event translator
  it uses (builtin-call audit emission, decision 6)
- `apps/api/services/agents/runtime/tools/schemas.py` (catalog entry gains
  `kind` — additive)
- Tests: `tests/services/agents/runtime/test_planning_tools.py`,
  `test_native_tools.py` (create), catalog route test extension

**Out of scope (do NOT touch):**

- `WebFetch`, code execution, image generation, memory native tools —
  deferred (decision 4; memory is Phase 5 our-way).
- Frontend — 027's contract makes these appear automatically; the only
  follow-up is optional icon/copy polish.
- Prompt-injection of the todo list into the system prompt (018's assembler
  owns prompt blocks; see Maintenance notes).
- A dedicated todos UI — the transcript's generic tool rendering is v1.
- `defer_loading`, MCP (D7).

## Git workflow

- Branch: `advisor/028-first-registry-tools`
- Commit style: `API - Add Planning & Native Search Tools`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Probe (scratch, not committed)

Against the installed pydantic-ai 2.1.0, record: `WebSearch` import path and
constructor signature; whether capabilities can be instantiated per-run
(vs per-agent) and mixed with `Hooks` in `capabilities=[...]`; which model
providers configured in `core/settings` support native search (from the
capability's own provider table); the exact builtin tool call/result
part/event class names and fields as they appear in `run_stream_events`; and
whether 026's tool-execution hooks fire for builtin tools (expected: no —
hence decision 6). Record findings in `native.py`'s header comment.

**Verify**: findings written down; the supported-provider set is explicit.

### Step 2: Contract amendment

In `contract.py` (documenting this as the 025-anticipated amendment):

- `kind: Literal["function", "capability"] = "function"`
- `capability_factory: Callable[[], Any] | None = None`
- `supported_model_providers: frozenset[str] | None = None` (None = all)
- `validate_definition`: `function` XOR `capability_factory` must match
  `kind`; capability entries may not set `takes_ctx`/`timeout`/
  `max_retries`/`args_validator`/`output_model` (they are not function
  tools); capability entries must be `effect="read"` in this plan (a write
  native tool with no approval interception is exactly what decision 5
  forbids — revisit only with a real envelope story).
- `to_pydantic_tool()` raises for capability entries (mounting is separate).
- Catalog schema: add `kind` to `ToolCatalogEntry` (additive; 027's types
  mirror it in its next touch).

**Verify**: `uv run ruff check .` → exit 0; 025's registry tests still pass.

### Step 3: `conversation_todos` + planning tools

Model (`models/conversation_todos.py`): `ConversationTodoList` —
`conversation_id` (FK CASCADE, **unique**), `workspace_id` (FK, indexed),
`items` JSONB not null default `[]`, `updated_by_run_id` (FK agent_runs SET
NULL, nullable), timestamps via the usual mixins. Autogenerate + hand-check
the migration.

`runtime/tools/planning.py`:

- `@runtime_tool(name="write_todos", provider="core", label="Write todo
  list", effect="write", takes_ctx=True, timeout=5)` —
  `write_todos(ctx, items: list[TodoItemInput]) -> dict`: validate ≤50
  items, content 1–500 chars, status in the enum, ≥1 item unless clearing;
  upsert the row for `ctx.deps.conversation.id` (workspace from deps);
  return `{"items": [...], "counts": {...}}` so the model sees the accepted
  state. Description must carry the usage contract ("replace the whole
  list; keep exactly one item in_progress while working").
- `@runtime_tool(name="read_todos", ...effect="read")` — returns the list
  (empty list, not an error, when no row).
- Input validation via a Pydantic `TodoItemInput` — pydantic-ai validates
  from the signature; bad items → `ModelRetry`-style messages for free.

Import `planning` in `registry.py`'s assembly point.

**Verify**: `uv run alembic upgrade heads && uv run alembic check` → clean;
`uv run python -c "...print(sorted(RUNTIME_TOOL_CATALOG))"` → includes
`read_todos`, `write_todos`.

### Step 4: `web_search` capability entry + mounting

`runtime/tools/native.py`: register
`@runtime_tool(name="web_search", provider="native", label="Web search",
kind="capability", capability_factory=<WebSearch per Step 1>,
effect="read", default_policy="auto", supports_approval=False,
supported_model_providers=<Step 1 set>)`.

`registry.py`: `build_runtime_native_capabilities(agent, resolved_model) ->
list` — catalog entries with `kind == "capability"` selected by the agent's
`tool_names`, filtered by `is_tool_allowed` AND
`supported_model_providers` vs the resolved model's provider (skip + log,
decision 4). `build_runtime_tools` must now skip capability entries (they
are not `Tool`s).

`loop.py`: extend the `capabilities=` list with the result (existing
`build_runtime_capabilities(agent)` + natives). Write-time validation
needs no change — `web_search` is a normal catalog name; its
`supports_approval=False` already restricts policies via 025's Step 3.

**Verify**: `uv run ruff check .` → exit 0.

### Step 5: Builtin-call audit

Per Step 1's part shapes: in the event translation path of `execute_run`,
on a builtin tool call/result pair emit
`record_tool_invocation_audit_event(tool_name="web_search",
tool_provider="native", args digest from the call part's input, latency
null, outcome/status from the result part)`. Guard so unknown future builtin
names still audit under their raw name. If Step 1 showed 026's hooks DO
fire for builtins, delete this step and say so in the completion note.

**Verify**: `uv run ruff check .` → exit 0.

### Step 6: Tests

- `test_planning_tools.py` (FunctionModel/TestModel per runtime test
  conventions): write→read round trip persists across two `execute_run`
  turns of one conversation; replace semantics (second write wins); caps
  and bad status rejected with model-visible errors; row is
  workspace/conversation-scoped (conversation B sees empty); 026 audit row
  written for `write_todos` with `effect`-consistent outcome; envelope
  `side_effect_policy="deny"` blocks it (reuses 026's test seam).
- `test_native_tools.py`: catalog lists `web_search` with `kind:
  "capability"`, `supports_approval` false; mounting includes the capability
  for a supported provider and skips+logs for an unsupported one (unit-test
  `build_runtime_native_capabilities` directly with fake resolved models);
  `build_runtime_tools` ignores capability entries; write-time validation
  rejects `tool_policies: {"web_search": "approval"}`.
- Builtin audit: unit-test the translator function with synthetic parts per
  Step 1's recorded shapes (do not attempt a live provider call in tests).
- Catalog route test: now returns 4+ entries including the new ones.

**Verify**: `uv run pytest tests/services/agents/runtime tests/routes/tools -q`
→ all pass; `uv run pytest -q` → full suite green.

## Test plan

Covered by Step 6 (~14 tests). Manual (dev, requires a provider key with
native search — likely Anthropic): enable `web_search` + `write_todos` on
an agent via the UI (they appear automatically if 027 landed — that is
027's acceptance test too); ask for a researched multi-step task; confirm
the todo list renders as tool calls in chat and audit rows exist for both
the todos writes and the native search.

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] Migration applied; `uv run alembic check` clean; downgrade/upgrade
      cycle tested once
- [ ] `uv run pytest -q` exits 0
- [ ] Catalog endpoint lists `write_todos`, `read_todos`, `web_search` with
      correct `kind`/`effect`/policy capabilities
- [ ] Probe findings recorded in `native.py` header
- [ ] Manual pass done or explicitly called out as skipped (no search-capable
      key available)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 025/026 are not DONE, or their delivered shapes differ from "Current
  state".
- Step 1 finds `WebSearch` cannot be mounted per-agent alongside the
  existing `Hooks` capability, or 2.1.0's builtin parts are not observable
  in `run_stream_events` (decision 6 has no data path — the native entry
  then ships unaudited or not at all; that is a product call).
- The capability needs per-run construction but only per-agent mounting is
  available (or vice versa) in a way that breaks `capability_factory`.
- Autogenerate emits anything beyond the one table.
- You are tempted to add a local search fallback dependency to make tests
  easier — decision 4 says no; test the mounting logic, not DuckDuckGo.

## Maintenance notes

- **018 interaction**: when the skills/prompt assembler lands, add a small
  "planning" instructions block injected only when `write_todos` is enabled
  (usage norms live better in the assembler than in a bloated tool
  description). Until then the description carries the contract.
- The `kind="capability"` machinery is exactly what a future MCP entry (D7)
  and 036's multimodal helpers will reuse — treat `native.py` as the
  reference implementation.
- `conversation_todos` retention rides conversation deletion (CASCADE);
  029's retention matrix should still list it explicitly.
- If workspaces later want search domain allow/deny lists, that is
  `capability_factory` gaining workspace config from deps — a 040-era
  follow-up, do not pre-build.
- Reviewers should scrutinize: XOR validation on the contract kinds, the
  unsupported-provider skip (must log, never raise mid-run), replace-not-
  merge todo semantics, and that `write_todos` audit rows carry the digest,
  not todo content.
