# Plan 059: Sandboxed code execution — provider-native `run_code`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agents/runtime/tools/ apps/api/services/agents/runtime/dispatch.py apps/api/services/files/`
> Compare the "Current state" excerpts against live code; treat a mismatch
> in the `web_search` helper-model pattern, the registry contract, or the
> installed `CodeExecutionTool` API as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED (workspace file content leaves Praxis for a provider
  sandbox — same trust class as 036 multimodal attachments, but
  tool-initiated; misclassifying the tool's effect would skip the right
  approvals)
- **Depends on**: 025/026/028 (registry, dispatch, helper-model pattern —
  all DONE), 031-034 (files + scratch, DONE). Soft: 036 content-assembly
  helpers, 055 (scenarios), 054 (effect-scope vocabulary).
  Ordering: after Phase 6 (050/051) in the default stream — artifacts and
  code execution both compete for "what the agent makes"; artifacts ship
  first per the roadmap.
- **Category**: Lane H — harness hardening / capability (post-roadmap
  additions 053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07

## Product intent

Knowledge work is not only reading and writing text — it is computing over
data: summing a CSV, reconciling two exports, plotting a trend, checking a
date calculation. Today an agent asked "what did we spend per campaign
last month, from this export?" must *guess arithmetic in its head*.
Artifacts (050) will let agents present; nothing lets them compute.

Decision taken with the operator (2026-07-07): **start with the
provider-native sandboxes** (Anthropic code execution, OpenAI Responses
code interpreter, Google code execution) exposed as one audited registry
tool, and treat external sandbox vendors (e2b, Vercel, Cloudflare) as
*future integration providers behind the same tool seam* — not built now.
This follows the exact pattern 028 established for `web_search`: native
capability wrapped in a helper model, exposed as a normal function tool,
audited through the dispatch choke point.

## Decisions taken

1. **One registry tool, `run_code`, helper-model wrapped.** Mirror
   `tools/native/web_search.py`: a helper pydantic-ai agent whose
   capability list carries the native code-execution tool
   (installed probe 2026-07-07: `pydantic_ai.CodeExecutionTool(kind=
   'code_execution', optional=False)` wrapped via
   `pydantic_ai.capabilities.NativeTool`; supported per its docstring on
   Anthropic, OpenAI Responses, Google — exactly the catalog's three
   cloud providers). The outer tool takes `task` (what to compute, in
   natural language + any inline data), optional `model_provider`/`model`
   (the 028 per-call selection pattern), and optional `file_ids`. Local
   tool hooks do not fire for provider-native calls (dispatch.py probe
   note), so as with `web_search` the *outer* function tool is the
   audited, policy-bearing unit; the native execution inside the helper
   turn additionally lands as native-tool audit rows via
   `record_native_tool_invocation_audit_event` (`execute_run.py:239-249`
   pattern applies to the helper run's stream — verify it does, since the
   helper runs outside `execute_run`; if not, capture native parts from
   the helper result messages and audit them explicitly).
2. **Classification: `effect="read"` is wrong; `effect="write"` +
   `effect_scope="internal"`, default policy `approval`,
   `supports_auto=True`.** The sandbox cannot mutate external systems
   (that is the point), but "read" would exempt it from every write-side
   guard while it ships workspace data to a provider and runs arbitrary
   generated code. `approval` by default gives workspaces the 034-style
   staged consent; workspaces that trust it can relax to `auto` per
   agent. Envelope note (054): `internal` scope means scheduled runs may
   run code without human approval *if* the agent policy is `auto` —
   that is the intended behavior for scheduled data digests.
3. **Files enter the sandbox as content, not as a provider file-store
   bridge — v1.** For `file_ids`: resolve through the same gates as 036
   attachments (workspace scope, file contract, size caps), then inline
   into the helper turn as `BinaryContent`/text parts using the 036
   assembly helpers (`services/files/build_attachment_user_content.py`).
   The model writes code that re-materializes the data inside the sandbox
   (for CSV/text this is native; for binary formats the provider's
   container tooling handles what it handles). A true provider file-store
   bridge (Anthropic Files API `container_upload`, OpenAI file ids) is a
   recorded follow-up: pydantic-ai 2.1.0's `CodeExecutionTool` surface
   exposes no file-attachment parameters (probe: constructor takes only
   `kind`/`optional`), so v1 honesty is inlining, with the same size caps
   as 036.
4. **Outputs come back as text + optional scratch files.** The helper
   returns stdout/result text (bounded, `RUN_CODE_OUTPUT_MAX_CHARS`
   default 8000). If the provider returns generated file content
   (charts, transformed CSVs) in-band, write it to **scratch** (034) via
   the existing scratch service and return scratch references — promotion
   to durable Files stays behind the existing approval-gated
   `promote_scratch`. No new storage surface.
5. **Denylist nothing inside the sandbox; police the boundary.** The
   sandbox is the provider's isolation problem; Praxis's controls are:
   which files go in (gates above), what policy the tool carries, audit
   of every invocation (args digest includes the task text hash), and
   output bounding. No attempt to filter generated code — that is
   security theater.
6. **External sandbox vendors are integrations, later.** e2b / Vercel /
   Cloudflare arrive (if ever) as 037-style providers whose credentials
   ride the secret-reference model, surfaced as alternative executors
   behind this same `run_code` registry entry (an `executor` argument or
   per-workspace config — decided then). Recorded so nobody builds a
   parallel tool. Similarly, pydantic-ai-harness CodeMode remains
   separately deferred (README rejection stands — CodeMode is about
   collapsing local tool calls, not about compute).
7. **Model gating.** `supported_model_providers` on the definition limits
   `run_code` to anthropic/openai/google helper execution; the
   `model_provider` argument validates against that set (exact
   `web_search` mechanics, including the settings-pinned default helper
   models per provider).

## Why this matters

For SME knowledge work this is the single biggest capability gap after
integrations: spreadsheets are the lingua franca of small-business data,
and "upload the export, ask the question, get a computed answer" is the
moment the product stops being a chat UI. Doing it provider-native means
zero sandbox infrastructure, zero new attack surface beyond the data
egress already accepted for 036, and full reuse of the registry/dispatch/
audit/approval machinery.

## Current state

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **The pattern to copy**: `services/agents/runtime/tools/native/
  web_search.py` — module-docstring probe notes; helper agent built via
  `build_model(resolve...)` with a native capability; per-call
  provider/model arguments validated against
  `SUPPORTED_NATIVE_SEARCH_PROVIDERS`; settings-pinned default helper
  models; registered via `@runtime_tool` with `TOOL_POLICY_APPROVAL`
  default and `presentation` metadata; helper `UsageLimits` bound the
  inner turn.
- **Installed API (probe 2026-07-07)**: `pydantic_ai.CodeExecutionTool`
  exists (`__init__(self, *, kind='code_execution', optional=False)`),
  docstring lists Anthropic / OpenAI Responses / Google / Bedrock / xAI;
  `pydantic_ai.capabilities.NativeTool(tool, *, id=None, description=None,
  defer_loading=False)` wraps it. There is no dedicated `CodeExecution`
  capability class in 2.1.0 (capabilities module listing probed).
  Native-tool *event* class names were flagged unverified in the docs
  digest (`07-streaming.md:240`) — the helper-model pattern sidesteps the
  SSE question, but the audit capture in decision 1 must be probed.
- **Native audit seam**: `dispatch.record_native_tool_invocation_audit_
  event` (dispatch.py:292-317) + the `NativeToolCallPart`/`ReturnPart`
  capture in `execute_run.py:239-249` — written for the *main* run's
  stream; the helper turn runs via its own `agent.run(...)` inside the
  tool body, so native parts must be read from the helper's result
  messages.
- **File gates**: `services/files/resolve_chat_attachments.py` +
  `build_attachment_user_content.py` (036) — workspace/contract/size
  validation and `BinaryContent` assembly; `MAX_FILE_SIZE_*` keys in
  `core/settings/files.py`.
- **Scratch**: `services/scratch/` + `write_file` scratch mode +
  approval-gated `promote_scratch` (034); governance §3 scratch row
  (7 d TTL) applies to decision 4's outputs unchanged.
- **Registry contract**: `runtime/tools/contract.py` fields incl.
  `supported_model_providers`, `presentation`, `kind` — 028 added the
  native/helper vocabulary this tool reuses; 054 adds `effect_scope`.
- **Governance**: §2 — this tool is a new row: internal-effect write,
  default `approval`, relaxable (`supports_auto=True`); the plan updates
  the governance cell on ship.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/services/scratch tests/scenarios -q` | all pass |
| Full suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest -q` | all pass |
| Live smoke (manual, keys required) | `make dev`; agent with `run_code`; "sum column B of the attached CSV" | computed answer; audit rows present |

## Scope

**In scope:**

- `services/agents/runtime/tools/native/run_code.py` (create — the tool,
  helper construction, file inlining, output bounding, scratch capture)
- `core/settings/agents.py` (or the tools settings home):
  `RUN_CODE_OUTPUT_MAX_CHARS`, per-provider default helper models
  (mirror the web-search settings naming)
- Native-audit capture for helper-run parts (decision 1 probe outcome —
  either confirm the existing seam fires or add explicit capture in the
  tool body)
- Registry/catalog additions (auto-exposed via `/api/v1/tools/catalog`;
  the 027 agent form picks it up with no frontend change; presentation
  metadata for chat rendering)
- Frontend: a `run_code` result presentation row **only if** the generic
  tool rendering is inadequate (035 added file-tool rows; reuse those
  patterns; keep it minimal)
- `docs/architecture/governance.md` §2 row; scenario additions (055)
- Tests: argument/provider validation, file-gate reuse, output bounding,
  scratch capture, audit rows (scripted helper — no live calls in tests)

**Out of scope (do NOT touch):**

- e2b/Vercel/Cloudflare executors (decision 6 — future integrations).
- A provider file-store bridge (decision 3 follow-up).
- pydantic-ai-harness CodeMode (separate rejected/deferred item).
- Long-running/background execution (the helper turn is bounded by its
  `UsageLimits` and tool timeout; batch compute is a jobs-harness idea
  for another day).
- Artifacts integration (an obvious later composition: run_code → chart →
  artifact; not v1).

## Git workflow

- Branch: `advisor/059-sandboxed-code-execution`
- Commits: `API - run_code Provider Sandbox Tool` (+ `Web - run_code Row`
  only if needed)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: probes, recorded

In the new module's docstring (web_search convention): (a) how each of
the three providers accepts `NativeTool(CodeExecutionTool())` on a helper
agent in 2.1.0 and what the result parts look like; (b) whether native
call/return parts appear in `agent.run()` result messages for the helper
(decision 1 audit capture); (c) what comes back when the sandbox produces
a file (per provider), feeding decision 4's capture. Bench with real keys
locally; tests stay scripted.

### Step 2: the tool

`run_code` per decisions 1-5,7: signature, provider/model validation,
file resolution + inlining, helper turn with bounded `UsageLimits`,
output truncation with an explicit `[truncated]` marker, scratch capture
for in-band file outputs, registry definition (`provider="native"`,
`effect="write"`, `effect_scope="internal"`, default `approval`,
`supports_auto=True`, presentation metadata).

**Verify**: registry import-time checks pass; catalog shows the entry;
scripted-helper unit tests cover validation, bounding, scratch capture.

### Step 3: audit wiring

Per the Step 1(b) outcome, ensure every `run_code` invocation produces:
one dispatch audit row (outer tool, digest-only args) and native-tool
audit rows for the inner execution. Add the audit assertions to the unit
tests.

### Step 4: scenarios + governance + smoke

Scenario (055): approval-gated `run_code` suspends and resumes with
scripted helper; auto-policy agent executes and audits. Governance §2
row update. Manual live smoke on all three providers with a small CSV;
record per-provider quirks in the module docstring.

## Test plan

~10-12 scripted tests (no live LLM): provider/model validation matrix,
file-gate reuse (wrong workspace / oversize / contract-blocked), output
bounding, scratch capture, audit row shape, approval suspend/resume
scenario. Live behavior is pinned by the manual smoke script, mirroring
how 028 verified `web_search`.

## Done criteria

- [ ] `run_code` in the catalog, selectable in the agent form with no
      frontend changes (or with one minimal presentation row)
- [ ] Files enter via the 036 gates only; outputs bounded; sandbox file
      outputs land in scratch behind the existing promote flow
- [ ] Every invocation audited (outer dispatch row + inner native rows)
- [ ] Default policy `approval`, relaxable per agent; governance §2 row
      updated
- [ ] Full suite + scenarios green; probes recorded;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- A catalog provider does not accept `CodeExecutionTool` through
  `NativeTool` on the installed 2.1.0 (the docstring says it should;
  probes decide) — ship the providers that work and record the gap; do
  not hack provider-specific request bodies.
- Helper-run native parts are invisible to any audit capture path — an
  unauditable execution violates the dispatch contract; report before
  shipping with outer-row-only audit.
- Inlined file content blows helper context on realistic CSVs (>the 036
  caps) — that is the signal to accelerate the file-store bridge
  follow-up, not to raise caps.
- You are tempted to add a local Python executor "just for dev" — no
  local code execution without its own security review; provider
  sandboxes only.

## Maintenance notes

- **The executor seam is the contract**: e2b/Vercel/Cloudflare later mean
  a new executor behind `run_code`, credentialed via 037 secret
  references — never a second code tool.
- **The file-store bridge follow-up** (decision 3) becomes worthwhile
  when pydantic-ai exposes container/file params or when users hit the
  inlining caps — whichever first.
- **Artifacts composition** (run_code output → artifact) is the natural
  050-adjacent follow-up for charts.
- Reviewers should scrutinize: the effect/effect_scope classification
  (decision 2's reasoning), the audit completeness, and that file access
  reuses the 036 gates verbatim rather than a parallel resolver.
