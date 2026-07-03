# Plan 025: Tool registry contract, decorator, and catalog API

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/api/services/agents/runtime/tools/ apps/api/services/agents/utils.py apps/api/services/agents/schemas.py apps/api/routes/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (touches how every agent's tools are built; behavior of
  the two live tools must not change)
- **Depends on**: none (first plan of roadmap Phase 1; donor design A1)
- **Category**: harness spine (roadmap `000_MASTER_ROADMAP.md` Phase 1)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

1. **`off` stays "absent from `tool_names`".** The donor's three-mode
   `off/auto/approval` model maps onto the existing representation
   (`tool_names` allowlist + `tool_policies` values `auto|approval`); the
   frontend already models "off" as absence. No agent schema change.
2. **Extend `RuntimeToolDefinition` in place** — no parallel "ToolDefinition
   v2" class. The existing frozen dataclass grows `provider`, `label`,
   `effect`, `supports_auto`, `supports_approval`, and optional
   `output_model`; `to_pydantic_tool()` remains the single generation path.
   Honest incremental over a rename that churns every import.
3. **Input schemas stay function-signature-derived.** pydantic-ai already
   builds validated input schemas from type hints; a mandatory parallel
   input model would be schema duplication (the donor's own disease).
   `output_model` is declared now, **enforced in plan 026** (output-contract
   validation belongs to the dispatch choke point).
4. **`provider` and `name` are separate structured fields** (donor rule:
   never a parsed string). Core tools use `provider="core"`. `name` stays
   globally unique across providers — asserted at import time.
5. **The catalog endpoint is readable by any authenticated workspace
   member.** Tool metadata is not a secret; configuration is gated at write
   time. Availability filtering (e.g. "provider not connected") arrives with
   integrations (Phase 4a) through the `is_tool_allowed` seam this plan
   introduces.
6. **Delegation tools stay out of the configurable catalog.**
   `list_delegate_agents`/`delegate_to_agent` are injected by runtime policy
   (`allowed_agent_ids`), not by `tool_names`; they will pass through 026's
   choke point but are not user-configurable entries.

## Why this matters

Everything on the roadmap that gives agents capability — files (034),
integrations (041), knowledge (046), memory (048), artifacts (050) — ships
as registry entries. Today the "registry" is a two-entry hardcoded dict with
no provider concept, no effect metadata, no read API, and a frontend list
that must be kept in sync by hand (the code comment in
`runtime-tools.ts:4-5` says exactly that). This plan turns the kernel into
the actual contract: typed definitions, decorator registration with
import-time invariants, policy-capability metadata that write-time
validation enforces, and a catalog endpoint. Plans 026 (dispatch/audit) and
027 (frontend catalog) complete donor Phase A on top of it.

## Current state

- `apps/api/services/agents/runtime/tools/contract.py` (59 lines):

  ```python
  ToolPolicy = Literal["auto", "approval"]
  VALID_TOOL_POLICIES = frozenset({TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL})

  @dataclass(frozen=True)
  class RuntimeToolDefinition:
      name: str
      function: Callable[..., Any]
      description: str
      takes_ctx: bool = False
      default_policy: ToolPolicy = TOOL_POLICY_AUTO
      timeout: float | None = None
      max_retries: int | None = None
      args_validator: Callable[..., Any] | None = None
      defer_loading: bool = False
  ```

  `to_pydantic_tool(policy=...)` (lines 35–58) validates the policy and
  builds `pydantic_ai.Tool(..., requires_approval=resolved == "approval",
  defer_loading=...)`.
- `.../tools/registry.py`: `RUNTIME_TOOL_CATALOG: dict[str,
  RuntimeToolDefinition]` with exactly `get_runtime_context`
  (`takes_ctx=True`, timeout 5) and `add_numbers` (timeout 5,
  max_retries 1) (lines 20–53); `build_runtime_tools(agent, *,
  include_delegation=False)` resolves names/policies and appends delegation
  tools (56–84); normalizers raise `ModelConfigurationError` (87–128).
- Write-time validation already exists:
  `services/agents/utils.py:96-138` `validate_tool_configuration(*,
  tool_names, tool_policies)` — unknown names, orphan policy keys, invalid
  policy values; called from `create_agent.py:37` and
  `update_agent.py:93-96`. Schema-level shape checks in
  `services/agents/schemas.py` (`ToolPolicyValue = Literal["auto",
  "approval"]`).
- Route precedent for a catalog endpoint: `routes/models/list_catalog.py`
  (`GET /models/catalog`), consumed by the frontend's
  `useModelCatalogQuery` — the exact pattern plan 027 replicates for tools.
- Tests today: `tests/routes/agents/test_agent_routes.py:288`
  (`test_create_agent_rejects_unknown_runtime_tool`),
  `tests/services/agents/test_agent_utils.py` (tool config validation),
  runtime tests build agents with `tool_names=["get_runtime_context"]`.
- pydantic-ai 2.1.0 facts (verified in `docs/pydantic-ai/03/04`): `Tool`
  accepts `requires_approval`, `defer_loading`, `timeout`, `max_retries`,
  `args_validator`; deferred approval flows through
  `DeferredToolRequests`/`DeferredToolResults` and is already wired in
  `execute_run.py`.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no new operations (no migration) |
| New/changed tests | `uv run pytest tests/services/agents tests/routes/agents tests/routes/tools -q` | all pass |
| Runtime regression | `uv run pytest tests/services/agents/runtime -q` | all pass |

## Scope

**In scope:**

- `apps/api/services/agents/runtime/tools/contract.py` (extend the
  dataclass + policy capability logic)
- `apps/api/services/agents/runtime/tools/registry.py` (decorator,
  import-time checks, catalog assembly; keep `build_runtime_tools` API)
- `apps/api/services/agents/runtime/tools/core.py` (create — the two demo
  tools move here as the first "provider package")
- `apps/api/services/agents/runtime/tools/permissions.py` (create —
  `is_tool_allowed` seam)
- `apps/api/services/agents/runtime/tools/__init__.py` (re-exports)
- `apps/api/services/agents/utils.py` (extend `validate_tool_configuration`)
- `apps/api/services/agents/runtime/tools/schemas.py` or
  `services/tools/schemas.py` (catalog read models — see Step 4)
- `apps/api/routes/tools/__init__.py`, `routes/tools/list_catalog.py`
- `apps/api/routes/__init__.py` (register `tools_router`)
- `apps/api/tests/services/agents/runtime/test_tool_registry.py` (create)
- `apps/api/tests/routes/tools/test_tool_catalog_routes.py` (create)
- `apps/api/tests/contract/test_openapi_routes.py` (modify)

**Out of scope (do NOT touch):**

- Dispatch, audit rows, mutation tracking, output-model **enforcement**,
  capability envelopes — plan 026.
- The frontend — plan 027.
- New real tools (planning/TODO, native tools) — plan 028.
- `Agent` model / migrations — `tool_names`/`tool_policies` JSONB columns are
  unchanged.
- Delegation tool construction (`runtime/delegation/`) — decision 6.
- MCP anything (roadmap D7).

## Git workflow

- Branch: `advisor/025-tool-registry-contract`
- Commit style: `API - Add Tool Registry Contract & Catalog`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Extend the contract

In `contract.py`, add to `RuntimeToolDefinition` (keeping it frozen, all new
fields defaulted so existing constructions still compile):

- `provider: str = "core"` — structured origin, lowercase kebab/snake token;
  validated by the registry, not free text.
- `label: str = ""` — human display name (backend becomes the source of the
  labels currently hardcoded in the frontend; empty → derive from `name` at
  registration).
- `effect: Literal["read", "write"] = "read"` — coarse side-effect class.
  Write tools are the ones 026 audits as mutations and 029's governance
  matrix keys on.
- `supports_auto: bool = True`, `supports_approval: bool = True` — policy
  capability. Add `allowed_policies()` returning the permitted subset and
  have `to_pydantic_tool` raise `ModelConfigurationError` when the resolved
  policy is outside it (defense in depth behind write-time validation).
- `output_model: type[BaseModel] | None = None` — declared now, enforced by
  026. Docstring must say exactly that.

Add a module-level invariant helper `validate_definition(defn)` checking:
non-blank name matching `^[a-z][a-z0-9_]*$`, non-blank description,
`default_policy in allowed_policies()`, at least one supported policy, and
`effect == "write"` requires `supports_approval` (a write tool that cannot
be put behind approval is a policy dead end).

**Verify**: `uv run ruff check .` → exit 0.

### Step 2: Decorator registry + import-time checks

Rework `registry.py`:

- `RUNTIME_TOOL_CATALOG: dict[str, RuntimeToolDefinition]` stays the public
  name (runtime code and tests reference it).
- Add `def runtime_tool(*, name, description, provider="core", label=None,
  effect="read", default_policy="auto", supports_auto=True,
  supports_approval=True, takes_ctx=False, timeout=None, max_retries=None,
  args_validator=None, defer_loading=False, output_model=None)` — a
  decorator that builds the definition from the wrapped function, runs
  `validate_definition`, asserts `name not in RUNTIME_TOOL_CATALOG`
  (duplicate → raise `RuntimeError` at import time — fail the app, not the
  request), and registers it.
- Move the two demo tools to a new `core.py` "provider package" using the
  decorator (`provider="core"`, labels "Runtime context" / "Add numbers" to
  match the current frontend strings, `effect="read"`). Note: only the
  *labels* match the frontend; the registry `description` strings are terser
  than the frontend's hardcoded copy, so 027's catalog-driven form will show
  the backend descriptions — expected, not a regression; `registry.py`
  imports `core` for its registration side effect with a comment naming that
  as the assembly point future providers (028, 034, 041, 046, 048, 050)
  extend.
- `build_runtime_tools` behavior is unchanged (same normalization, same
  errors, same delegation append) — only the catalog's construction moved.

**Verify**: `uv run ruff check .` → exit 0, and
`uv run python -c "from services.agents.runtime.tools import RUNTIME_TOOL_CATALOG as c; print(sorted(c))"`
→ `['add_numbers', 'get_runtime_context']`.

### Step 3: Policy-capability enforcement at write time

Extend `validate_tool_configuration` (`services/agents/utils.py:96-138`):
after the existing unknown-name/orphan-key/invalid-value checks, reject a
`tool_policies[name]` outside `RUNTIME_TOOL_CATALOG[name].allowed_policies()`
with `AppValidationError(field="tool_policies")` whose message names the
tool and its permitted policies. (With both demo tools supporting both
policies this is a no-op today — the test seam matters: 028's native tools
and 041's spend tools rely on it.)

Create `permissions.py` with the single permission seam the donor design
calls for:

```python
def is_tool_allowed(definition: RuntimeToolDefinition, *, workspace, agent=None) -> bool:
    return True  # v1: all registered tools; integrations (040/041) narrow this
```

Call it from the catalog service (Step 4) and from `build_runtime_tools`
(skip disallowed tools with a log line rather than erroring — an agent
configured yesterday must not 500 today; write-time validation still blocks
new configuration). Keep the signature keyword-only so later context
(connections, envelopes) is additive.

**Verify**: `uv run pytest tests/services/agents -q` → all pass (existing
validation tests still green).

### Step 4: Catalog read API

Schemas (`services/agents/runtime/tools/schemas.py`): `ToolCatalogEntry`
(`name`, `provider`, `label`, `description`, `effect`, `default_policy`,
`supported_policies: list[str]`, `defer_loading`) and
`ToolCatalogResponse{tools: list[ToolCatalogEntry]}`. Do NOT expose
`function`, `timeout`, `max_retries`, or `output_model` — the catalog is a
product contract, not a debug dump.

Route `routes/tools/list_catalog.py` — `GET /tools/catalog`, deps
`CurrentUserDep` + `CurrentWorkspaceDep` (any member, decision 5), returns
entries for which `is_tool_allowed(...)` is true, sorted by
`(provider, name)`. Compose `routes/tools/__init__.py`
(`prefix="/tools"`, `tags=["tools"]`) and register alphabetically in
`routes/__init__.py`. Model the whole thing on `routes/models/list_catalog.py`.

**Verify**:
`uv run python -c "from main import app; print([r.path for r in app.routes if 'tools' in r.path])"`
→ `['/api/v1/tools/catalog']`.

### Step 5: Tests

`tests/services/agents/runtime/test_tool_registry.py`:

- decorator registers with derived label; duplicate name raises at
  registration; invalid name pattern / blank description / write-without-
  approval-support all rejected by `validate_definition`
- `allowed_policies` + `to_pydantic_tool` reject an unsupported policy
- `validate_tool_configuration` rejects a policy outside a tool's supported
  set (register a throwaway definition in the test via the decorator and
  clean it out of the catalog in a fixture teardown — do not leak test tools)
- `build_runtime_tools` output for the two core tools is unchanged: same
  names, `requires_approval` False under default policies, True when policy
  `approval` (this pins the no-behavior-change guarantee)
- `is_tool_allowed` False → tool skipped by `build_runtime_tools`, catalog
  omits it

`tests/routes/tools/test_tool_catalog_routes.py`: authenticated member →
200 with both core entries and the documented fields; unauthenticated → 401.
Extend the contract test with `/api/v1/tools/catalog`.

**Verify**: `uv run pytest tests/services/agents tests/routes/tools tests/routes/agents tests/contract -q` → all pass, then the full runtime suite
`uv run pytest tests/services/agents/runtime -q` → all pass.

## Test plan

Covered by Step 5 (~12–15 tests). The pinned invariant is Step 5's
"no-behavior-change" test: existing agents' tool construction must be
byte-for-byte equivalent in effect (same tool names, same approval flags,
same timeouts).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no new operations
- [ ] `uv run pytest tests/services/agents tests/routes/tools tests/routes/agents tests/contract -q` exits 0
- [ ] `uv run pytest tests/services/agents/runtime -q` exits 0 (delegation,
      approval, streaming — all untouched behavior)
- [ ] `GET /api/v1/tools/catalog` appears in the OpenAPI schema
- [ ] The two demo tools are registered via the decorator; grep shows no
      literal dict-construction of `RUNTIME_TOOL_CATALOG` entries outside it
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `contract.py`/`registry.py` differ structurally from the "Current state"
  excerpts (someone extended the kernel first).
- A `routes/tools/` package already exists.
- Making `RuntimeToolDefinition` fields defaulted breaks frozen-dataclass
  ordering in a way that forces field reordering — that changes positional
  construction sites; report the sites instead of reordering.
- Existing runtime tests fail before your changes.
- You feel the need to touch `execute_run.py`, `capabilities.py`, or
  anything under `runtime/delegation/` — that is 026 scope leaking in.

## Maintenance notes

- Plan 026 consumes `effect` (mutation tracking), `output_model`
  (output-contract validation), and wraps execution — it must not need to
  touch this contract's shape. If 026 finds a missing field, amend THIS plan
  doc's contract section as part of 026's review.
- Plan 027 consumes the catalog endpoint and deletes
  `apps/web/src/features/agents/runtime-tools.ts`; `label` strings here were
  chosen to match it so the UI diff is pure plumbing.
- Plan 028 registers the first non-demo tools; 034/041/046/048/050 each add
  provider modules to the Step 2 assembly point. Import-time uniqueness is
  the only namespace law — keep names short, snake_case, verb-first.
- `defer_loading` remains plumbed-but-unused until the catalog is big enough
  (roadmap D7 note); do not enable it per-tool without checking provider
  tool-search support (`docs/pydantic-ai/04`, line 197 caveat re prompt
  caching).
- Reviewers should scrutinize: import-time failure on duplicates (not
  request-time), the write-tool-requires-approval-support invariant, and
  that `build_runtime_tools` still errors on unknown configured names but
  merely *skips* disallowed ones.
