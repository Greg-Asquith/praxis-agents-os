# Plan 018: Wire assigned skills into the runtime as deferred capabilities

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat ccb721b..HEAD -- apps/api/services/agents/runtime/ apps/api/models/agent.py apps/api/models/skills.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: docs/plans/016-skills-backend-crud.md (skill rows must be
  creatable); document reading additionally needs
  docs/plans/017-skill-documents-pipeline.md
- **Category**: direction (feature foundation)
- **Planned at**: commit `ccb721b`, 2026-07-01

## Why this matters

`agents.skill_ids` is stored and validated but **nothing in the runtime reads
it** — assigned skills have zero effect on a run. This plan makes each assigned
skill a **deferred Pydantic AI `Capability`**: the model always sees a one-line
catalog entry (skill name + description — level 1), calls the framework's
`load_capability` tool to pull in the skill's instructions (level 2), and can
then read the skill's converted documents through a `read_skill_document` tool
(level 3). This is the progressive-disclosure architecture prescribed by the
repo's own digest (`docs/pydantic-ai/04-capabilities-hooks-specs.md`, "How
Praxis should use this": *"Model each user-defined workflow as a deferred
`Capability` with `id` = config PK"*) and by upstream Pydantic AI guidance
("keep the base agent prompt small; put specialist runbooks behind capabilities
on demand").

Two design rules from the digest are load-bearing here:

1. **Stable explicit ids are mandatory** — loaded-capability state is
   reconstructed from `load_capability` call/return pairs in persisted message
   history, so the id must survive across runs and model switches. We use
   `skill:{skill.id}` (the PK).
2. **Read-before-act** — level-3 documents are only readable after the owning
   skill is loaded, enforced with `ModelRetry` (the digest's "Enforcing
   read-before-act" pattern).

## Current state

All paths relative to `apps/api`. Verified against the installed
`pydantic-ai==2.1.0` (pinned in `uv.lock`).

- `services/agents/runtime/loop.py:45-78` — agent construction (requoted
  2026-07-03 at `9208c47`; the delegation commit `f83d210` added the three
  delegation parameters and `_runtime_instructions`, and the token-cap
  commit `05df2d0` added `total_tokens_limit`):

  ```python
  def build_runtime_agent(
      agent: Agent,
      *,
      model: Model | None = None,
      delegate_agents: Sequence[Agent] = (),
      enable_delegation: bool = True,
      force_delegation_tools: bool = False,
  ) -> RuntimeAgent:
      resolved_model = resolve_agent_model(agent)
      runtime_model = model or build_model(resolved_model)
      ...
      return RuntimeAgent(
          agent=PydanticAgent(
              runtime_model,
              name=_agent_name(agent),
              instructions=_runtime_instructions(agent, include_delegation=...),
              deps_type=RuntimeDeps,
              output_type=[str, DeferredToolRequests],
              tools=build_runtime_tools(agent, include_delegation=include_delegation),
              capabilities=build_runtime_capabilities(agent),
          ),
          resolved_model=resolved_model,
          usage_limits=UsageLimits(
              request_limit=resolved_model.max_steps,
              total_tokens_limit=settings.AGENT_RUN_TOTAL_TOKENS_LIMIT,
          ),
      )
  ```

  `_runtime_instructions(agent, *, include_delegation)` (`loop.py:87-91`)
  concatenates `agent.instructions` + `DELEGATION_INSTRUCTIONS` — this is
  the seam Step 6 generalizes into the system-prompt assembler.

- `services/agents/runtime/capabilities.py:15-49` —
  `build_runtime_capabilities(_agent: Agent) -> list[AgentCapability[RuntimeDeps]]`
  currently returns only a `Hooks(id="praxis-runtime-hooks")` with
  before/after tool-execute logging. It ignores its argument.
- `services/agents/runtime/context.py:17-28` — `RuntimeDeps` (frozen
  dataclass): `db, user, workspace, conversation, agent, run, sink,
  delegation_depth=0` (the last added by `f83d210`).
- `services/agents/runtime/execute_run.py` — the driver:
  `load_run_context(...)` at l.92 → `build_runtime_agent(agent, model=model,
  delegate_agents=…, enable_delegation=…, force_delegation_tools=…)` at
  l.143-149 → `runtime_agent.agent.run_stream_events(...)`; the event loop
  `async for event in stream:` is at l.186-203 and already contains an
  `AgentRunResultEvent` guard and an `is_deferred_tool_resume_event` skip
  before `emit_agent_stream_event` (l.198).
- `services/agents/runtime/load_context.py:18-81` — `load_run_context` loads
  run + conversation + agent rows. No skill loading exists anywhere.
- `models/agent.py:59` — `skill_ids = Column(JSONB, nullable=False, default=list, ...)`
  — a JSON list of UUID **strings**.
- `models/skills.py` — `Skill.name`, `human_name`, `description`,
  `instructions`, `documentation_refs` (plan-017 manifest:
  `{name: {"original": key, "markdown": key, "status": "ready"|"failed", ...}}`),
  `is_active`, `last_used_at`.
- `services/agents/runtime/events.py:107-129` — `FunctionToolCallEvent` /
  `FunctionToolResultEvent` are translated to generic `tool.call` /
  `tool.result` sink events keyed by `tool_call_id`/`tool_name`. (Commit
  `6af36b5` shifted these lines and made the translator channel-aware: SSE
  `message.start`/`message.delta` now carry a `channel: "text"|"thinking"`
  field — background context for plan 020; the tool-event translation is
  unchanged.)
- Storage read surface (plan 002): `services/storage/factory.py::get_storage_provider()`,
  `provider.get_object(ref)`, `make_storage_object_ref(StorageBucket.PRIVATE, key)`.

### Verified pydantic-ai 2.1.0 facts (probed against the installed package — trust these)

- `pydantic_ai.capabilities.Capability(instructions=..., toolsets=..., tools=...,
  id=..., description=..., defer_loading=...)` exists with exactly those
  parameters.
- When the model calls `load_capability`, the stream yields a normal
  `FunctionToolCallEvent` whose `.part` is a `LoadCapabilityCallPart`
  (subclass of `ToolCallPart`) with `part.tool_kind == "capability-load"` and
  `part.tool_name == "load_capability"`; the result arrives as a
  `FunctionToolResultEvent` whose `.part` is a `LoadCapabilityReturnPart`,
  also `tool_kind == "capability-load"`. **This means the existing
  `emit_agent_stream_event` already forwards activations as `tool.call` /
  `tool.result` SSE events with `name == "load_capability"` — no protocol
  change is needed** (the frontend discriminates client-side; plan 020).
- These parts serialize through `ModelMessagesTypeAdapter` with
  `part_kind: "tool-call"` / `"tool-return"` **plus** `tool_kind:
  "capability-load"`, so the existing persistence
  (`runtime/persistence.py`) round-trips loaded-capability state with no
  changes.
- Testing gotcha: `FunctionModel` **requires a `stream_function`** when driven
  through `run_stream_events` (`FunctionModel(model_fn, stream_function=stream_fn)`);
  a tool call is streamed as
  `yield {0: DeltaToolCall(name="load_capability", json_args='{"id": "..."}')}`
  (`from pydantic_ai.models.function import DeltaToolCall`).
- `RunContext` exposes `ctx.loaded_capability_ids` (deferred capabilities
  explicitly loaded this run) — the gate for read-before-act.

## Commands you will need

| Purpose   | Command (run from `apps/api`)          | Expected on success |
|-----------|----------------------------------------|---------------------|
| Lint      | `uv run ruff check .`                  | exit 0              |
| Runtime tests | `uv run pytest tests/services/agents/runtime -q` | all pass |
| New tests | `uv run pytest tests/services/agents/runtime/test_runtime_skills.py -q` | all pass |
| Streaming regression | `uv run pytest tests/routes/conversations -q` | all pass |

## Suggested executor toolkit

- Read `docs/pydantic-ai/04-capabilities-hooks-specs.md` (sections "On-demand /
  deferred loading", "Resumable across runs", "Enforcing read-before-act")
  before Step 2 — it is the repo's own verified reference for this API.
- If the `building-pydantic-ai-agents` skill is available in your environment,
  its `references/ON-DEMAND-CAPABILITIES.md` covers the same ground.

## Scope

**In scope**:

- `apps/api/services/agents/runtime/skills.py` (create — capability + tool assembly)
- `apps/api/services/agents/runtime/load_context.py` (add `load_agent_skills`)
- `apps/api/services/agents/runtime/loop.py` (accept `skills` parameter;
  generalize `_runtime_instructions` per Step 6)
- `apps/api/services/agents/runtime/prompt.py` (create — the system-prompt
  assembler, Step 6)
- `apps/api/services/agents/runtime/execute_run.py` (fetch skills, pass them,
  record activations)
- `apps/api/tests/services/agents/runtime/test_runtime_skills.py` (create)
- `apps/api/tests/services/agents/runtime/test_prompt_assembly.py` (create,
  Step 6)
- Existing call sites of `build_runtime_agent` in tests, if the signature
  change breaks them (find with `grep -rn "build_runtime_agent" --include="*.py" . | grep -v .venv`)

**Out of scope** (do NOT touch):

- `services/agents/runtime/events.py` and the SSE protocol — activation
  already flows through `tool.call`/`tool.result`; the frontend work is plan 020.
- `services/agents/runtime/capabilities.py` hooks — leave the logging hooks
  alone; skills get their own module.
- `runtime/tools/registry.py` — `read_skill_document` is **not** a
  user-toggleable catalog tool; it ships automatically with skills.
- `services/skills/*` routes/services (plans 016/017).
- History trimming (plan 013) — but see maintenance notes.

## Git workflow

- Branch: `advisor/018-runtime-skill-disclosure`
- Commit style: `API - Runtime Skill Disclosure`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Load skill rows for a run

In `load_context.py`, add:

```python
async def load_agent_skills(db: AsyncSession, agent: Agent) -> list[Skill]:
    """Load the active, non-deleted skills assigned to an agent, preserving order."""
```

- Return `[]` fast when `agent.skill_ids` is falsy.
- Parse each entry with `UUID(value)`, skipping (with a `logger.warning`
  including agent id and the bad value) anything unparseable.
- Single `select(Skill).where(Skill.id.in_(ids), Skill.workspace_id == agent.workspace_id,
  Skill.deleted == False, Skill.is_active.is_(True))`.
- Re-order results to match `agent.skill_ids` order; log a warning listing any
  ids that resolved to nothing (deleted/deactivated skills are silently
  skipped at runtime by design — agent config may lag).

**Verify**: `uv run ruff check .` → exit 0.

### Step 2: Build skill capabilities — new module `runtime/skills.py`

```python
SKILL_CAPABILITY_PREFIX = "skill:"

def skill_capability_id(skill: Skill) -> str:
    return f"{SKILL_CAPABILITY_PREFIX}{skill.id}"
```

`build_skill_capabilities(skills: Sequence[Skill]) -> list[AgentCapability[RuntimeDeps]]`:

1. For each skill, one deferred `Capability`:

   ```python
   Capability(
       id=skill_capability_id(skill),
       description=_catalog_description(skill),
       instructions=_loaded_instructions(skill),
       defer_loading=True,
   )
   ```

   - `_catalog_description(skill)` → `f"{skill.human_name or skill.name}: {skill.description}"`.
     This is the always-visible level-1 line; keep it to exactly that — no doc
     lists, no instructions.
   - `_loaded_instructions(skill)` → the skill's `instructions`, and **iff**
     the skill has manifest entries with `status == "ready"`, append:

     ```
     ## Skill documents

     Read these with read_skill_document(skill="<skill.name>", document="<name>"):
     - <name>: <filename>
     ```

     Build the list from `skill.documentation_refs`, skipping non-ready
     entries. This keeps level-3 pointers inside level 2, per the SKILL.md
     standard ("reference files clearly with guidance on when to read them").
2. If **any** skill has at least one ready document, append one extra
   non-deferred capability carrying the shared reader tool:

   ```python
   Capability(
       id="skills-documents",
       instructions=(
           "Some skills provide reference documents. Load a skill with "
           "load_capability before reading its documents."
       ),
       tools=[_build_read_skill_document_tool(skills)],
   )
   ```

   The tool is shared (tool names must be unique in a run — one tool per skill
   would collide).
3. `_build_read_skill_document_tool(skills)` returns a `pydantic_ai.Tool`
   (`takes_ctx=True`) wrapping an async closure:

   ```python
   async def read_skill_document(ctx: RunContext[RuntimeDeps], skill: str, document: str) -> str:
       """Read one of a loaded skill's reference documents as markdown."""
   ```

   Behavior, in order:
   - Resolve `skill` against the closed-over skills by `Skill.name` (exact
     match). Unknown → `ModelRetry` listing the valid skill names.
   - **Read-before-act gate**: if `skill_capability_id(matched) not in
     ctx.loaded_capability_ids`, raise
     `ModelRetry(f'Call load_capability with id="{skill_capability_id(matched)}" before reading its documents.')`.
   - Look up `document` in the manifest; missing or not `status == "ready"` →
     `ModelRetry` listing the ready document names.
   - `provider = get_storage_provider()`;
     `data = await provider.get_object(make_storage_object_ref(StorageBucket.PRIVATE, entry["markdown"]))`;
     decode UTF-8 (`errors="replace"`).
   - Return the content prefixed with a one-line provenance header:
     `f"<skill-document skill={skill!r} document={document!r}>\n"` + content +
     `"\n</skill-document>"` — the converted markdown is user-uploaded data,
     and the wrapper makes that boundary explicit to the model.
   - Map `StorageNotFoundError` to `ModelRetry("Document content is unavailable.")`
     (manifest/storage drift must not kill the run).

**Verify**: `uv run ruff check .` → exit 0.

### Step 3: Thread skills through construction

- `loop.py`: **add** a keyword-only `skills: Sequence[Skill] = ()` to the
  existing signature — which already carries `model`, `delegate_agents`,
  `enable_delegation`, and `force_delegation_tools` (see the requoted
  constructor in "Current state"); do NOT rewrite the signature or you will
  drop the delegation parameters and the token cap — and set
  `capabilities=[*build_runtime_capabilities(agent), *build_skill_capabilities(skills)]`.
  Leave `instructions`, `tools`, and `usage_limits` untouched.
- `execute_run.py`: after `load_run_context(...)` (l.92), add
  `skills = await load_agent_skills(db, agent)` and merge `skills=skills`
  into the existing `build_runtime_agent(...)` call at l.143-149,
  **preserving the delegation kwargs**.
- Fix any other `build_runtime_agent` call sites found by
  `grep -rn "build_runtime_agent" --include="*.py" . | grep -v .venv`
  (keyword-only `skills` defaults to empty, so most call sites need no change —
  verify rather than assume; the delegation runtime under
  `runtime/delegation/` is a known caller).

**Verify**: `uv run pytest tests/services/agents/runtime -q` → all pass
(existing tests, no skills assigned → behavior unchanged).

### Step 4: Record activations (`last_used_at`)

In `execute_run.py`'s event loop (the `async for event in stream:` block at
l.186-203), before `emit_agent_stream_event` (l.198) — note the loop already
has an `AgentRunResultEvent` guard and an `is_deferred_tool_resume_event`
skip; insert after those so resumes are not double-counted — detect
activations:

```python
part = getattr(event, "part", None)
if (
    isinstance(event, FunctionToolCallEvent)
    and getattr(part, "tool_kind", None) == "capability-load"
):
    record_skill_activation(skills, part, run=run)
```

Implement `record_skill_activation` in `runtime/skills.py`: parse the
capability id out of `part.args` (args may be a dict **or** a JSON string —
handle both; the id is under key `"id"`), match it against the loaded skills
via `skill_capability_id`, and set `matched.last_used_at =
datetime.now(UTC)` on the ORM row plus a `logger.info` with run/agent/skill
ids. The row is committed by `execute_run`'s existing end-of-run commits — do
not add a commit. Non-skill capability loads (no `skill:` prefix) are ignored.

**Verify**: covered by Step 5 tests.

### Step 5: Tests — `tests/services/agents/runtime/test_runtime_skills.py`

Model the file layout and fixtures on the existing
`tests/services/agents/runtime/test_runtime_core.py` /
`test_runtime_streaming.py` (read them first), plus `tests/factories/skills.py`
from plan 016. Use `FunctionModel` with the streaming gotcha from "Current
state" (both `model_fn` and `stream_function` are required). Cases:

1. **Catalog assembly**: `build_skill_capabilities` with two skills → two
   deferred capabilities with ids `skill:{id}`, correct descriptions; no
   `skills-documents` capability when no skill has ready docs; present when
   one does.
2. **Activation round-trip**: agent with one skill; `FunctionModel` first
   responds with `DeltaToolCall(name="load_capability", json_args='{"id": "skill:<id>"}')`,
   then a text answer. Assert the run completes, the sink (use
   `CollectingSink` from `runtime/sinks.py`) captured a `tool.call` with
   `name == "load_capability"`, and `skill.last_used_at` is set.
3. **Read-before-act**: call the `read_skill_document` tool function directly
   with a `RunContext` whose `loaded_capability_ids` is empty (construct the
   context the way existing runtime tool tests do; if none exist, invoke the
   closure with a minimal stub carrying `deps` and `loaded_capability_ids`)
   → raises `ModelRetry`.
4. **Document read happy path**: with `STORAGE_PROVIDER=local_fs` (see
   `tests/support/storage.py` for wiring), put a small markdown object at the
   manifest key, mark the capability id as loaded, assert the returned string
   contains the content and the `<skill-document` provenance wrapper.
5. **Dangling ids**: `load_agent_skills` with a `skill_ids` list containing a
   deleted skill id, an inactive skill id, a malformed string, and one good id
   → returns only the good skill, no exception.

**Verify**: `uv run pytest tests/services/agents/runtime/test_runtime_skills.py -q`
→ all pass. Then the full gates in Done criteria.

### Step 6: System-prompt assembler (Gate G2 deliverable — roadmap requirement)

The roadmap (`000_MASTER_ROADMAP.md` §Phase 2, Gate G2, decision D6) requires
this plan to deliver **the system-prompt assembly design** — ordered,
budgeted blocks with an extension point — that plans 034 (`<available_files>`
block), 040 (active integration context block), and 049 (core-memory block)
later plug into. Skills themselves ride capabilities, not the prompt, so this
step is small but load-bearing: it prevents three future plans from each
accreting their own string concatenation onto `_runtime_instructions`.

Create `runtime/prompt.py`:

```python
@dataclass(frozen=True)
class PromptBlock:
    key: str          # stable identity, e.g. "identity", "delegation"
    content: str      # rendered text; empty string → block omitted
    budget: int | None = None  # optional soft char budget; truncate + log when exceeded

def build_system_prompt(blocks: Sequence[PromptBlock]) -> str:
    """Join non-empty blocks with blank-line separators, in the given order."""
```

- Ordering is the caller's list order; define the canonical order in ONE
  place: a `runtime_prompt_blocks(agent, *, include_delegation) ->
  list[PromptBlock]` function that today returns
  `[PromptBlock("identity", agent.instructions),
  PromptBlock("delegation", DELEGATION_INSTRUCTIONS if include_delegation else "")]`.
- Budgets are soft in v1: truncate the block content at `budget` chars with a
  trailing `"\n[truncated]"` marker and a `logger.warning` — future plans
  (034/040/049) set real budgets; today's two blocks pass `None`.
- Refactor `_runtime_instructions` in `loop.py` to delegate to
  `build_system_prompt(runtime_prompt_blocks(...))` — behavior must be
  byte-identical for the current two blocks (assert this in a test against
  the old concatenation).
- Extension point: future plans append `PromptBlock`s to
  `runtime_prompt_blocks` — never concatenate strings elsewhere. Say this in
  the module docstring.

Tests (`test_prompt_assembly.py`): ordering respected; empty blocks omitted;
budget truncation + marker; the `_runtime_instructions` equivalence check.

**Verify**: `uv run pytest tests/services/agents/runtime -q` → all pass.

## Test plan

Covered by Step 5 — the risk surfaces are: capability id stability (test 2
implicitly pins the `skill:` prefix), the approval-path interplay (existing
`tests/routes/conversations` streaming tests must stay green), and defensive
handling of stale agent config (test 5).

## Done criteria

ALL must hold (run from `apps/api`):

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run pytest tests/services/agents/runtime -q` exits 0 (old + new)
- [ ] `uv run pytest tests/routes/conversations -q` exits 0
- [ ] `grep -n "skill_capability_id" services/agents/runtime/skills.py` matches
- [ ] `grep -n "load_agent_skills" services/agents/runtime/execute_run.py` matches
- [ ] `grep -n "build_system_prompt" services/agents/runtime/loop.py` matches
      (Step 6 assembler is wired, not just created)
- [ ] `grep -rn "documentation_refs\[" services/agents/runtime/` returns no
      matches for **mutation** (reads are fine; the runtime never writes the manifest)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The installed pydantic-ai is no longer 2.1.0 **and** any probed fact in
  "Current state" fails (re-probe: `Capability` signature,
  `tool_kind == "capability-load"`, `ctx.loaded_capability_ids`).
- `Capability(tools=[...])` rejects a `pydantic_ai.Tool` instance (it may want
  bare callables in this version) — check the signature and adapt only if the
  fix is local to `_build_read_skill_document_tool`; otherwise report.
- Existing streaming tests fail in a way unrelated to your diff (baseline broken).
- `load_capability` calls do **not** show up as `FunctionToolCallEvent` in the
  driver's event loop (framework behavior differs from the probe) — report
  what they arrive as.
- You find yourself wanting to modify `events.py` or the SSE protocol — that
  is plan 020's decision space; stop and report why.

## Maintenance notes

- **Interaction with plan 013 (history trimming)**: loaded-capability state is
  reconstructed from `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pairs
  in message history. Any `ProcessHistory` trimming MUST preserve those pairs
  or agents silently lose loaded skills mid-conversation. Plan 013's executor
  must read this note; a cross-reference lives in the plans README.
- **Interaction with plan 009 (delegation — landed)**: delegated sub-agents
  build their own runtime agents via the same `build_runtime_agent`; decide
  whether sub-agents get their own `skill_ids` treatment (they should — this
  module is reusable as-is; the keyword-only default keeps them skill-less
  until wired).
- **The Step 6 assembler is the G2 contract**: plans 034
  (`<available_files>`), 040 (active context), and 049 (core memories) add
  `PromptBlock`s to `runtime_prompt_blocks` with real budgets. If any of
  them concatenates strings around it instead, that is a regression of this
  plan.
- **Prompt-cache cost**: per the digest, instructions-only deferral is
  cache-stable, but tool-visibility changes on load can break provider prompt
  caches. The shared reader tool is deliberately **non-deferred** so the tool
  list stays stable across a load.
- **Deferred follow-ups**: per-activation audit rows (only `last_used_at` +
  logs today); skill usage analytics; `script_refs` execution (needs the
  sandbox story — see the CodeMode rejection note in the plans README);
  semantic skill matching (unnecessary while catalogs are small — the model
  routes off descriptions).
- Reviewers should scrutinize: that `read_skill_document` cannot read another
  workspace's objects (keys come only from the closed-over, workspace-scoped
  skill rows), and that no code path writes `documentation_refs` from the
  runtime.
