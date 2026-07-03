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
3. **Native web search ships as a normal `function` entry with
   `provider="native"`.** pydantic-ai's `WebSearch` capability cannot choose
   a model independently from the active agent request. The shipped
   `web_search` tool therefore runs a short helper agent with native search
   enabled and returns the helper's answer to the active agent. This is the
   pattern future native tools such as image creation should follow when the
   executor model may differ from the active agent model.
4. **Native-only in v1, no DuckDuckGo local fallback** — no new scraping
   dependency, deterministic provider behavior. `web_search` exposes
   `model_provider` and optional `model` as tool arguments, validates them
   against the available native-search providers, and uses the active agent
   model only when no provider is requested and it supports native search.
   This lets an OpenAI agent use, for example, Anthropic native web search
   on a single call.
5. **Approval is not offered for native search** (`supports_approval=False`,
   `effect="read"`): the outer `web_search` call is read-only and provider
   execution happens inside the helper model request, so approval would not
   intercept the provider-native call itself. The tool can still be switched
   off per agent.
6. **Native helper tool calls are audited by the dispatch choke point.**
   Because `web_search` is mounted as a normal runtime function tool, 026's
   dispatch hook emits the digest-only audit row with
   `tool_provider="native"`. The event translator still understands
   provider-native parts for any future direct capability use, but the shipped
   search path does not rely on active-model builtin parts.

## Why this matters

Two demo tools prove nothing about the registry's ergonomics; these entries
do. The TODO tool gives every agent visible multi-step planning (the chat UI
already renders tool calls generically, so plans are user-legible for free)
— the NOTES ask, built our way. Native web search is the first
native provider-backed entry and forces the registry to answer "how do
provider-native tools get policy/audit treatment" *now*, with a read-only
tool and a per-call selectable helper model, rather than during
integrations. After this plan, the pattern for 034/041/046/048/050 tools is
fully rehearsed.

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
  execute in the request prefix. **Import path (verified 2026-07-03 against
  the installed package): `from pydantic_ai.capabilities import WebSearch` —
  it is NOT importable from top-level `pydantic_ai` (that raises and suggests
  `WebSearchTool`, which is the native-tool *config object*, a different
  thing). Constructor: `WebSearch(*, native=…, local=…, search_context_size=…,
  user_location=…, blocked_domains=…, allowed_domains=…, max_uses=…, id=…,
  defer_loading=…, description=…)`.** The builtin-tool event/part shapes and
  which of our configured providers support native search must still be
  probed against the installed package, not assumed (plan 018 set the
  precedent for recording probe results in the plan/code).
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
- `apps/api/services/agents/runtime/tools/native/web_search.py` (create —
  provider module: helper-model backed `web_search` function entry)
- `apps/api/services/agents/runtime/tools/registry.py` (assembly imports;
  capability entries remain supported for future use)
- `apps/api/core/settings/models.py` and `apps/api/.env.example` (native
  web-search helper max-step setting only; provider/model are tool arguments)
- `apps/api/services/agents/runtime/execute_run.py` or the event translator
  it uses (builtin-call audit emission, decision 6)
- `apps/api/services/agents/runtime/tools/schemas.py` (catalog entry gains
  `kind` — additive)
- Tests: `tests/services/agents/runtime/test_planning_tools.py`,
  `test_native_tools.py` (create), catalog route test extension

**Out of scope (do NOT touch):**

- `WebFetch`, code execution, image generation, memory native tools —
  deferred (decision 4; memory is Phase 5 our-way).
- Frontend — only configurable tools should appear in the agent form. TODO
  tools are always-on runtime affordances, not form options.
- Prompt-injection of the todo list into the system prompt beyond the
  always-on planning guidance block.
- A dedicated todos UI — the transcript's generic tool rendering is v1.
- `defer_loading`, MCP (D7).

## Git workflow

- Branch: `advisor/028-first-registry-tools`
- Commit style: `API - Add Planning & Native Search Tools`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Probe (scratch, not committed)

Against the installed pydantic-ai 2.1.0, record: `WebSearch` import path
(`from pydantic_ai.capabilities import WebSearch` — pre-verified, see
"Current state") and constructor signature; whether capabilities can be
instantiated per-run
(vs per-agent) and mixed with `Hooks` in `capabilities=[...]`; which model
providers configured in `core/settings` support native search (from the
capability's own provider table); the exact builtin tool call/result
part/event class names and fields as they appear in `run_stream_events`; and
whether 026's tool-execution hooks fire for builtin tools (expected: no —
hence decision 6). Record findings in `native/web_search.py`'s header comment.

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

### Step 4: `web_search` helper-model entry

`runtime/tools/native/web_search.py`: register `web_search` as
`@runtime_tool(name="web_search", provider="native", label="Web search",
effect="read", default_policy="auto", supports_approval=False,
takes_ctx=True, output_model=WebSearchOutput)`.

The tool resolves a helper model independently from the active agent:
`model_provider` and optional `model` are tool arguments selected per call
from the available native-search providers. When neither is supplied, the
active agent model is used if its provider supports native search. The helper
agent mounts `WebSearch(native=True, local=False)`, and the outer
`web_search` function remains the audited runtime tool.

`registry.py`: capability-kind entries still exist for future use, but
`web_search` is mounted by `build_runtime_tools`, not
`build_runtime_native_capabilities`.

**Verify**: `uv run ruff check .` → exit 0.

### Step 5: Builtin-call audit

The shipped `web_search` path audits through 026's function-tool dispatch
hook. The event translation path still records digest-only audit rows for
provider-native `NativeToolCallPart`/`NativeToolReturnPart` pairs so future
direct capability entries do not become unaudited.

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
  "function"`, `provider: "native"`, and `supports_approval` false;
  mounting includes it as a function tool alongside the always-on todos;
  helper-model resolution can select a provider different from the active
  agent; write-time validation rejects
  `tool_policies: {"web_search": "approval"}`.
- Builtin audit: unit-test the translator function with synthetic parts per
  Step 1's recorded shapes (do not attempt a live provider call in tests).
- Catalog route test: now returns 4+ entries including the new ones.

**Verify**: `uv run pytest tests/services/agents/runtime tests/routes/tools -q`
→ all pass; `uv run pytest -q` → full suite green.

## Test plan

Covered by Step 6 (~14 tests). Manual (dev, requires a provider key with
native search — likely Anthropic): enable `web_search` on an agent via the
UI; ask for a researched multi-step task; confirm the always-on TODO tools
render as tool calls in chat and audit rows exist for both the todo writes
and the native search.

## Completion notes

Completed 2026-07-03. The manual provider-search pass was skipped because
no search-capable provider key was available in this environment; native
helper-model resolution, stream event translation for future direct native
parts, and digest-only audit persistence are covered by tests. Because 018's prompt
assembler already exists, the planning usage guidance is injected as a
prompt block for every agent. Follow-up feedback removed the old demo
`get_runtime_context`/`add_numbers` tools and made `read_todos`/`write_todos`
hidden auto-mounted tools instead of agent-form options.

Follow-up feedback also changed the native-tool pattern: `web_search` is no
longer mounted as an active-model capability. It is an audited
`provider="native"` function tool that runs a helper model with native web
search enabled. Its `model_provider` and optional `model` tool arguments let
that helper use a different provider/model than the active agent, matching
the expected pattern for later native tools such as image creation.

## Done criteria

- [x] `uv run ruff check .` exits 0
- [x] Migration applied; `uv run alembic check` clean; downgrade/upgrade
      cycle tested once
- [x] `uv run pytest -q` exits 0
- [x] Runtime catalog registers `write_todos`, `read_todos`, and
      `web_search` with correct `kind`/`effect`/policy capabilities; the
      public catalog exposes only configurable entries (`web_search`)
- [x] Probe findings recorded in `native/web_search.py` header
- [x] Manual pass done or explicitly called out as skipped (no search-capable
      key available)
- [x] `git status` shows no modified files outside the in-scope list
- [x] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 025/026 are not DONE, or their delivered shapes differ from "Current
  state".
- Step 1 finds `WebSearch` cannot be mounted inside the helper agent or
  helper-model construction cannot use the explicit provider credential seam.
- The helper-model pattern cannot preserve normal dispatch audit semantics
  for the outer `web_search` call.
- Autogenerate emits anything beyond the one table.
- You are tempted to add a local search fallback dependency to make tests
  easier — decision 4 says no; test the mounting logic, not DuckDuckGo.

## Maintenance notes

- **018 interaction**: the planning instructions block is injected for every
  agent because TODO tools are always mounted; keep future planning guidance
  in the assembler instead of bloating the tool description.
- Direct `kind="capability"` machinery remains in the registry for future
  provider-adaptive entries, but native tools that need an executor model
  independent of the active agent should follow the `native/` package's
  helper-model function-tool pattern.
- `conversation_todos` retention rides conversation deletion (CASCADE);
  029's retention matrix should still list it explicitly.
- If workspaces later want search domain allow/deny lists, thread those into
  the helper model's native `WebSearch` configuration from server-owned
  context — a 040-era follow-up, do not pre-build.
- Reviewers should scrutinize: helper-model resolution through the
  `model_provider`/`model` tool arguments, replace-not-merge todo semantics,
  and that tool audit rows carry digests, not todo/search content.
