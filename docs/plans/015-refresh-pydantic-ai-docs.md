# Plan 015: Close the verified-against-2.1.0 gaps in the pydantic-ai docs digest

> **Executor instructions**: Follow this plan step by step. This is a
> docs-only plan — no source code changes. All facts you need are inlined
> below; they were verified against the installed package and the live
> upstream docs on 2026-07-01. Do not re-research unless a claim conflicts
> with the installed package (then STOP and report). When done, update the
> status row for this plan in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat 1a51665..HEAD -- docs/pydantic-ai`
> If the digest changed since this plan was written, reconcile before editing.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (docs only)
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `1a51665`, 2026-07-01

## Why this matters

`docs/pydantic-ai/` is load-bearing: plans and runtime decisions cite it, and
it honestly flags itself as "written against v1 (GA)" with an explicit
"Open items still to verify" list in `99-applying-to-praxis.md:140-153`. Those
items have now been verified against the installed `pydantic-ai==2.1.0` and the
current upstream docs. Leaving stale ⚠️ flags means every future task re-does
this verification; recording wrong-name risks (e.g. `BuiltinToolCallEvent`)
prevents an executor from building on removed APIs.

## Current state

- `docs/pydantic-ai/99-applying-to-praxis.md:140-153` — the "Open items still
  to verify (not yet exercised)" list (capabilities spellings, native-tool
  event classes, `UsageLimits` fields, MCP surface, settings precedence,
  `tool_timeout` kwarg names).
- Version notes referencing "written against v1" appear in `README.md:4-5` and
  per-file version-note blocks (e.g. `07-streaming.md:5-11`,
  `06-messages-and-history.md:209-210` VERSION-SENSITIVE flags,
  `13-advanced-and-ecosystem.md:5`).

## Verified facts to record (source of truth for this plan)

All confirmed on 2026-07-01 against the installed `pydantic-ai==2.1.0` in
`apps/api/.venv` and https://pydantic.dev/docs/ai/ (v2.0.0 released
2026-06-23; 2.1.0 2026-06-29; 2.2.0 2026-06-30 — 2.1/2.2 are non-breaking):

1. **Capabilities (2.1.0 spellings, all in `pydantic_ai.capabilities`)**:
   `NativeTool`, `NativeOrLocalTool`, `ImageGeneration`,
   `IncludeToolReturnSchemas`, `Instrumentation`, `MCP`, `PrefixTools`,
   `PrepareTools`, `PrepareOutputTools`, `ProcessHistory`,
   `ProcessEventStream`, `ReinjectSystemPrompt`, `SetToolMetadata`, `Thinking`,
   `ToolSearch`, `Toolset`, `WebFetch`, `WebSearch`, `XSearch`, `Hooks`,
   `HandleDeferredToolCalls`, `Capability`, `CombinedCapability`,
   `WrapperCapability`, `DynamicCapability`, `ThreadExecutor`. A
   `CAPABILITY_TYPES` registry backs YAML/JSON specs (`Agent.from_spec` /
   `Agent.from_file`). `ProcessHistory` exists exactly as doc 06 hoped;
   `HandleDeferredToolCalls` exists as doc 03/04 hoped.
2. **`Agent.__init__` (2.1.0)**: `model, *, output_type, instructions,
   system_prompt, deps_type, name, description, model_settings, retries,
   validation_context, tools, toolsets, defer_model_check, end_strategy
   ('graceful' default — changed from 'early' in 2.0), metadata, tool_timeout,
   max_concurrency, capabilities`. **Removed** (hard, no deprecation shim):
   `history_processors=`, `instrument=`, `event_stream_handler=`,
   `prepare_tools=` — all replaced by capabilities (`ProcessHistory`,
   `Instrumentation`, `ProcessEventStream`, `PrepareTools`).
   `retries` accepts an int or an `AgentRetries` TypedDict (`{'tools': 3, 'output': 1}`).
   `model_settings` may be a static dict or a callable taking `RunContext`
   (dynamic settings, evaluated per request).
3. **Native/builtin tool events**: `BuiltinToolCallEvent`/`BuiltinToolResultEvent`
   were **removed in 2.0** — native (provider-executed) tool activity surfaces
   only via `PartStartEvent`/`PartDeltaEvent` parts. Output tools emit dedicated
   `OutputToolCallEvent`/`OutputToolResultEvent` (subclasses of `ToolCallEvent`/
   `ToolResultEvent`; no longer function-tool events). Wire-level native tool
   configs live in `pydantic_ai.native_tools` (`WebSearchTool`,
   `CodeExecutionTool`, `WebFetchTool`, `XSearchTool`, `ImageGenerationTool`,
   `MemoryTool`, `MCPServerTool`, `FileSearchTool`); the old
   `pydantic_ai.builtin_tools` module name is gone.
4. **`UsageLimits` (2.1.0 fields)**: `request_limit` (default 50),
   `tool_calls_limit`, `input_tokens_limit`, `output_tokens_limit`,
   `total_tokens_limit`, `count_tokens_before_request` (all optional/off).
   `RunUsage` fields: `requests`, `tool_calls`, `input_tokens`, `output_tokens`,
   `cache_write_tokens`, `cache_read_tokens`, audio variants, `details`.
   2.0 renames: `Usage`→`RunUsage`; `request_tokens`/`response_tokens` →
   `input_tokens`/`output_tokens` (and the same for the `*_limit` kwargs).
5. **MCP (2.1.0)**: the ergonomic surface is the `MCP` capability —
   `MCP(url=None, *, native=False, local=None, id=None, authorization_token=None,
   headers=None, allowed_tools=None, description=None, defer_loading=False)`.
   `native=True` requires `url=` and runs server-side (bypasses local wrapping).
6. **Approval surface (2.1.0)**: `Tool(..., requires_approval=True)` produces
   `ToolDefinition.kind == 'unapproved'` (`ToolKind = Literal['function',
   'output', 'external', 'unapproved']`) — `ToolDefinition` has no
   `requires_approval` field. Toolset-level wrappers exist:
   `ApprovalRequiredToolset`, `DeferredLoadingToolset`.
   `DeferredToolRequests.build_results(...)` / `.remaining(...)` helpers exist.
7. **Tool kwargs (2.1.0)**: `Tool(function, *, takes_ctx, name, description,
   max_retries, requires_approval, args_validator, timeout, defer_loading,
   prepare, metadata, sequential, strict, docstring_format,
   require_parameter_descriptions, schema_generator, function_schema,
   include_return_schema)` — the digest's "`tool_timeout`/agent-wide retries
   kwarg names" open item resolves to: per-tool `timeout=`, agent-wide
   `tool_timeout=`, agent-wide `retries=`/`AgentRetries`.
8. **Other 2.0 changes worth flagging in the digest**: bare `openai:` model
   strings now resolve to `OpenAIResponsesModel` (`openai-chat:` for Chat
   Completions); `OpenAIModel` → `OpenAIChatModel`; `result.usage()`/
   `.timestamp()` are properties; `StreamedRunResult.stream` → `stream_output`;
   `FunctionToolResultEvent.result` → `.part`; instrumentation defaults to
   semconv `version=5` (2–4 deprecated); `pydantic_graph.persistence` and
   `pydantic_graph.mermaid` removed (graph API rewritten around
   `graph_builder`); `DeferredToolCalls` (1.x name) removed in favor of
   `DeferredToolRequests`; `providers.grok.*` → `providers.xai.*`;
   `GoogleGLAProvider`/`GoogleVertexProvider` → `GoogleProvider`/`GoogleCloudProvider`.
9. **Capabilities on demand (2.1.0)**: `AbstractCapability.defer_loading: bool`
   field; deferred capabilities REQUIRE a stable explicit `id`; loading happens
   via an auto-injected `load_capability` tool; loaded state is reconstructed
   from `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pairs in message
   history — **a history processor that strips those parts forces re-loading**
   (directly relevant to Plan 013's trimmer; turn-boundary trimming keeps the
   pairs intact within kept turns).
10. **Harness**: `pydantic-ai-harness` v0.5.0 (2026-07-01) is the official
    optional capability library; requires `pydantic-ai-slim>=1.95.1` (satisfied
    by 2.1.0). `CodeMode(tools=..., max_retries=3)` needs the
    `pydantic-ai-harness[codemode]` extra (Monty sandbox). Constraints: Python
    subset (no classes, no third-party imports, small stdlib allowlist, no
    timing primitives); **approval-required and deferred tools are excluded
    from the sandbox**; `native=True` tools bypass it. Not installed in Praxis;
    adoption deferred (see plans README).
11. **Docs URLs**: `ai.pydantic.dev/*` 301-redirects to
    `pydantic.dev/docs/ai/*` (e.g. `/agents/` → `/docs/ai/core-concepts/agent/`,
    `/deferred-tools/` → `/docs/ai/tools-toolsets/deferred-tools/`,
    `/changelog/` → `/docs/ai/project/changelog/`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Spot-check an import claim | `cd apps/api && uv run python -c "from pydantic_ai.capabilities import ProcessHistory, Instrumentation, MCP; print('ok')"` | `ok` |
| Nothing else builds/tests | docs-only change | — |

## Scope

**In scope** (docs only):
- `docs/pydantic-ai/99-applying-to-praxis.md` (rewrite the "Open items" section
  into a "Verified against 2.1.0 (second pass)" section using the facts above)
- `docs/pydantic-ai/README.md` (version note)
- `docs/pydantic-ai/03-tools-and-toolsets.md`, `04-capabilities-hooks-specs.md`,
  `06-messages-and-history.md`, `07-streaming.md`, `10-mcp.md`,
  `13-advanced-and-ecosystem.md` (update only the VERSION-SENSITIVE / ⚠️
  flagged passages and version notes that the facts above resolve)
- `docs/plans/000_README.md` (status row)

**Out of scope**:
- Any `apps/` source or test file.
- Rewriting digest content that is still accurate — touch flagged passages only.
- `docs/architecture/*.md`.

## Git workflow

- Branch: `advisor/015-refresh-pydantic-ai-docs`
- Commit style: `Docs - Verify Pydantic AI Digest Against 2.1.0`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Update `99-applying-to-praxis.md`

Replace the "Open items still to verify (not yet exercised)" section with a
"Verified against 2.1.0 (2026-07-01)" section answering each former open item
using facts 1–9 above. Keep the existing "Spike findings" section untouched.
Keep the item about the meta-package install decision (it is a decision, not
an open item — move it to the decisions section or leave in place).

**Verify**: `grep -n "Open items still to verify" docs/pydantic-ai/99-applying-to-praxis.md` → no matches

### Step 2: Update per-file flagged passages

For each file, resolve only the flagged uncertainty, citing "verified against
installed 2.1.0, 2026-07-01":

- `07-streaming.md`: native-tool events note (fact 3); the version-note block.
- `06-messages-and-history.md`: the two VERSION-SENSITIVE gotchas (facts 1, 9 —
  `ProcessHistory` confirmed; `ReinjectSystemPrompt` confirmed; add the
  LoadCapability-parts caveat for history processors).
- `04-capabilities-hooks-specs.md`: confirm the capability roster (fact 1) and
  deferred-loading semantics (fact 9).
- `03-tools-and-toolsets.md`: tool kwargs and approval surface (facts 6, 7).
- `10-mcp.md`: the 2.1.0 `MCP` capability signature (fact 5).
- `13-advanced-and-ecosystem.md`: thinking-delta names confirmed
  (`ThinkingPartDelta` with nullable `content_delta`), harness version/compat
  (fact 10), instrumentation semconv v5 (fact 8).
- `README.md`: version banner → "verified against 2.1.0 on 2026-07-01".

**Verify**: `grep -rn "VERSION-SENSITIVE" docs/pydantic-ai/ | wc -l` → fewer flags than before the edit (record before/after counts in your report); every remaining flag is genuinely unresolved.

### Step 3: Spot-check three claims

Run the import spot-check command from the table, plus:
`cd apps/api && uv run python -c "from pydantic_ai import ApprovalRequiredToolset; from pydantic_ai.native_tools import WebSearchTool; print('ok')"`
(adjust import path if `native_tools` exports differ — then fix the digest text
to the true path, and note it).

**Verify**: both print `ok` (or the digest text matches what actually imports)

## Test plan

Docs-only; the spot-check imports in Step 3 are the verification.

## Done criteria

- [ ] "Open items still to verify" section is gone, replaced with verified answers
- [ ] All edited claims cite the verification date and installed version
- [ ] Spot-check imports succeed as documented
- [ ] `git status` shows only `docs/pydantic-ai/*` and `docs/plans/000_README.md` modified
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back if:

- Any inlined fact above conflicts with the installed package when spot-checked
  (a version bump may have landed) — report the conflict, do not guess.
- Resolving a flag requires rewriting more than the flagged passage (digest
  structure drifted).

## Maintenance notes

- When `pydantic-ai` is next upgraded, re-run the spike
  (`apps/api/tests/services/agents/runtime/test_pydantic_ai_spike.py`) first;
  it pins the load-bearing names and will catch breaks before the digest does.
- The harness facts (10) feed the deferred CodeMode decision recorded in
  `docs/plans/000_README.md` — revisit both together.
