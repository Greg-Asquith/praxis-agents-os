<!-- docs/plans/059-sandboxed-code-execution.md -->

# Plan 059: Sandboxed code execution — provider-native `run_code`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Amendment (2026-07-07, plan 075 — prompt-injection threat model)**:
> file content → generated code is threat-model.md §2(d) — an inlined
> hostile CSV cell is a prompt to the helper model that writes the code,
> not just data. Two deltas: (1) the helper turn frames inlined file
> content as untrusted data per threat-model §3, separated from the
> `task` text; (2) Step 2's tests gain a poisoned-file fixture (shared
> set §4 — hostile CSV) asserting the framing wraps it. Sandbox *egress*
> stays out of scope here — plan 072 owns network/egress posture for
> sandboxed execution; this amendment must not duplicate it (decision 5's
> police-the-boundary posture stands).
>
> **Amendment (2026-07-28, Plan 050 artifact workflow)**: the
> agent-visible scratch draft/promote workflow is retired. Decision 4 must
> return renderable output as an artifact and other generated files as
> durable Praxis Files through the shared revision operations; it must not
> restore `promote_scratch` or scratch modes on the Files tools. The
> `run_code` tool's own approval boundary covers those outputs.
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
4. **Outputs come back as text + optional durable outputs.** The helper
   returns stdout/result text (bounded, `RUN_CODE_OUTPUT_MAX_CHARS`
   default 8000). If the provider returns generated file content
   (charts, transformed CSVs) in-band, create an artifact for supported
   renderable types or a durable Praxis File through the shared actor-neutral
   revision operation. The enclosing `run_code` approval is the consent
   boundary; no draft/promote step or new storage surface is introduced.
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
- **Durable outputs**: Plan 050's dedicated artifact revision services and
  Files revision operations replace the retired agent-visible scratch
  draft/promote path.
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
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/scenarios -q` | all pass |
| Full suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest -q` | all pass |
| Live smoke (manual, keys required) | `make dev`; agent with `run_code`; "sum column B of the attached CSV" | computed answer; audit rows present |

## Scope

**In scope:**

- `services/agents/runtime/tools/native/run_code.py` (create — the tool,
  helper construction, file inlining, output bounding, durable-output
  capture)
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
  durable-output capture, audit rows (scripted helper — no live calls in
  tests)

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
output truncation with an explicit `[truncated]` marker, durable-output
capture for in-band file outputs (decision 4 as amended), registry
definition (`provider="native"`, `effect="write"`, per-call scope via
`effect_scope_resolver` per the 072 amendment, default `approval`,
`supports_auto=True`, presentation metadata).

**Verify**: registry import-time checks pass; catalog shows the entry;
scripted-helper unit tests cover validation, bounding, durable-output
capture.

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

~14-18 scripted tests (no live LLM): provider/model validation matrix,
file-gate reuse (wrong workspace / oversize / contract-blocked), output
bounding, durable-output capture, audit row shape, approval
suspend/resume scenario, plus the 075 poisoned-file and 072
scope-resolution/scheduled-approval deltas. Live behavior is pinned by the manual smoke script, mirroring
how 028 verified `web_search`.

## Done criteria

- [ ] `run_code` in the catalog, selectable in the agent form with no
      frontend changes (or with one minimal presentation row)
- [ ] Files enter via the 036 gates only; outputs bounded; sandbox file
      outputs land as artifacts or durable Praxis Files through the
      shared revision operations (no scratch, no promote flow)
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

## Amendment: sandbox egress verification (plan 072, reconciled 2026-07-28)

Binding on execution. Decision 2's `effect_scope="internal"` +
`supports_auto=True` classification silently assumes every enabled
provider's sandbox has no network egress. That is a per-provider,
externally mutable fact — probe it, gate on it, and re-check it.

1. **Step 1 gains probe (d): egress posture.** For each catalog
   provider, run a helper turn whose task has the sandbox attempt
   outbound access: DNS resolution of a unique canary hostname and an
   HTTP request to an operator-controlled canary URL. Record per
   provider, dated, in the module-docstring probe notes: whether DNS
   resolves, whether the HTTP request lands (canary hit), and the error
   surface when blocked. Vendor documentation is not a probe result.
2. **Classification gates on probe (d).** A provider whose sandbox shows
   ANY egress (DNS or HTTP) cannot carry the `internal` classification —
   for that provider `run_code` is an external-effect write (054
   vocabulary) and must not run unattended. Use the landed
   `effect_scope_resolver` seam to classify each call from its effective
   provider: `internal` only for a currently verified egress-isolated
   provider; `external` for a verified provider where any egress is
   observed. Resolve the settings-pinned default when `model_provider` is
   omitted. A provider with no current probe result is rejected at
   validation time with an explicit error. Decision 7's
   `supported_model_providers` remains the provider/API compatibility set,
   not an egress allowlist.
3. **Re-verification rule.** Re-run probe (d) on any pydantic-ai upgrade
   or provider SDK/API change touching code execution; refresh the dated
   posture record in the module docstring and mirror it in the
   governance §2 row this plan updates. Update the provider-to-scope
   mapping in the same change; any provider without a current result
   fails closed.
4. **Test-plan delta (055 scenarios).** Add: (a) a poisoned-input
   fixture — a CSV whose cell content instructs exfiltration of the
   other rows to a URL — driven through a scripted helper emitting
   exfiltration-shaped code, asserting the boundary controls (audit
   rows, output bounding, and rejection of unverified providers); (b)
   scope-resolution tests proving an isolated provider is `internal`, an
   egress-capable provider is `external`, and the omitted argument uses
   the configured default; (c) a scheduled/delegated
   `require_approval` scenario proving an external-classified call
   suspends while an isolated internal call may execute under `auto`.
   Live egress cannot be asserted in tests (live LLM calls are blocked);
   it is pinned by probe (d), and the Step 4 manual smoke must include
   the poisoned CSV. An isolated provider must produce no canary hit; an
   egress-capable provider must never execute that smoke unattended.

Additional STOP condition: the effective provider cannot be resolved
before the envelope check, including when `model_provider` is omitted —
do not default such a call to `internal`; fail closed and report.

## Amendment: execution-readiness review (2026-07-30)

Binding on execution. The drift check was run at HEAD `b11cc61`
(34 files, +2689/−561 in the checked paths since `c2f08cc`). No STOP
condition fires — the helper-model pattern, the registry contract, and
the installed `CodeExecutionTool` API (re-probed 2026-07-30: pinned
pydantic-ai 2.1.0; constructor still `kind`/`optional` only; docstring
still lists Anthropic / OpenAI Responses / Google) all survive — but
the corrections below supersede the matching "Current state" text, and
the chunk structure below supersedes the flat Steps 1-4 ordering. The
scratch references in Steps/Scope/Test plan/Done criteria were removed
in this same change, completing the 2026-07-28 Plan 050 integration
(`promote_scratch` is deleted from the tree; a test asserts it stays
out of the catalog). `services/scratch` still exists for TTL-swept
scratch entries used elsewhere — it is out of scope; do not touch it.

### Corrected anchors

1. **Audit seam moved.** `record_native_tool_invocation_audit_event`
   is now `dispatch.py:575-601`. The main-run native part capture
   moved from `execute_run.py:239-249` to `execute/stream.py:60-71`
   (`execute_run.py` is now a compatibility shim over the `execute/`
   package; capture state is `runtime/events.py:51`). Decision 1's
   point stands and is now confirmed: the helper `agent.run(...)`
   inside the tool body is invisible to that stream path, so Step 3
   must read `NativeToolCallPart`/`NativeToolReturnPart` from the
   helper result messages and call the dispatch audit function
   explicitly (see `tests/.../test_native_tools.py` for the existing
   test pattern around that function).
2. **Helper default models are not settings-pinned.** `web_search`'s
   per-provider defaults are the module constant
   `DEFAULT_NATIVE_SEARCH_MODELS` (`web_search.py:54-58`); its only
   settings key is `NATIVE_WEB_SEARCH_MAX_STEPS`
   (`core/settings/models.py:43-48`). Follow the landed pattern:
   `DEFAULT_NATIVE_RUN_CODE_MODELS` as a module constant, plus
   `NATIVE_RUN_CODE_MAX_STEPS` and `RUN_CODE_OUTPUT_MAX_CHARS` in
   `core/settings/models.py` — not `core/settings/agents.py`, which
   holds only schedule/run durability settings.
3. **Probe-note convention.** `web_search.py` carries no probe-notes
   docstring; the in-tree example of the convention Step 1 asks for is
   `tools/files/__init__.py:5-14` ("Pydantic AI 2.1.0 probe
   findings"). Also note `web_search` validates providers against
   `configured_native_search_providers()` (key-filtered snapshot at
   process start), not the raw supported set — mirror that.
4. **Declare effect explicitly.** `web_search` declares no
   `effect`/`effect_scope` and inherits the contract defaults
   (`read`/`internal`, `contract.py:134-136`). `run_code` must declare
   `effect="write"` explicitly; contract validation forbids a resolver
   on read-effect tools (`contract.py:253-254`), so an inherited
   `read` would reject the registration at import time.
5. **Resolver constraint (design decision needed in Chunk B).**
   `effect_scope_resolver` is landed (`contract.py:145`, consumed by
   `resolve_effect_scope` at `dispatch.py:168-182` inside
   `check_envelope`) but has no production consumer — `run_code` is
   the first. The resolver receives ONLY the call-args dict.
   `web_search`'s omitted-provider fallback (agent's active model,
   else first configured provider) is not derivable from args, so
   `run_code`'s omitted-`model_provider` default must be deterministic
   from args plus process-start configuration alone (e.g. a fixed
   configured-provider precedence captured in the resolver closure),
   and the tool body must resolve the provider identically. If the
   two can diverge, the 072 fail-closed STOP condition applies.
6. **Governance §2 is prose, not a table.** `governance.md` §2
   ("Approval Defaults Per Tool Effect") is a bulleted policy section
   with no per-tool table. "Governance §2 row" means: add a `run_code`
   entry in that section's form — internal-effect write, default
   `approval`, `supports_auto=True`, per-provider egress posture with
   probe dates. Do not invent a table.
7. **Hostile-CSV fixture is unshipped.** `threat-model.md` §4 promises
   it, but `tests/fixtures/prompt_injection/` holds only
   `hostile_conversation_span.txt` and `hostile_email_body.txt`.
   Creating the hostile CSV there is part of this plan (Chunk E).
8. **Durable-output seams (decision 4 as amended), concretely:**
   artifacts via `services/artifacts/create_artifact.py` (the
   `create_artifact`/`update_artifact` runtime tools in
   `tools/artifacts.py` show the calling pattern); Praxis Files via
   `create_file_with_revision`/`append_file_revision` with an agent
   `FileRevisionActor` (`services/files/revision_actor.py`). Note
   `write_agent_file` is text-only (`content: str`), so binary sandbox
   outputs use the revision operations directly.

### Execution chunks

Execute as five gated chunks, one commit each on the plan branch
(`API - run_code Probes`, `API - run_code Tool`, `API - run_code
Audit`, `API - run_code Outputs`, `API - run_code Scenarios &
Governance`). Do not start a chunk before the previous chunk's gate
passes; the single-commit line in "Git workflow" is superseded.

- **Chunk A — probes.** Step 1 (a)-(c) plus 072 probe (d), with live
  keys, bench script local-only (not committed). Deliverable: dated
  probe notes in the new module's docstring (files-tools convention)
  and the provider→scope map derived from probe (d). **Gate**: the
  operator reviews the probe record and scope map; STOP conditions
  1-2 and the 072 egress gate are evaluated here, before any tool
  logic is written.
- **Chunk B — core tool.** Step 2 as amended: signature,
  provider/model validation, 036 file gates + inlining with the §3
  untrusted-content framing (075 amendment), helper turn with
  `UsageLimits`, output bounding, settings keys, registry definition
  with `effect="write"` + `effect_scope_resolver` built from the
  Chunk A map (correction 5's default rule decided and recorded
  here). Unit tests: validation matrix, file-gate reuse, bounding,
  scope resolution (isolated → `internal`, egress-capable →
  `external`, omitted arg → configured default, unprobed provider
  rejected). **Gate**: lint + focused tests green; catalog shows the
  entry.
- **Chunk C — audit wiring.** Step 3 per probe (b): explicit capture
  of helper-run native parts through
  `record_native_tool_invocation_audit_event`; tests assert one outer
  dispatch row plus inner native rows per invocation. **Gate**: audit
  tests green; STOP if any execution path is unauditable.
- **Chunk D — durable outputs.** Decision 4 as amended, via the
  correction-8 seams; tests cover both the artifact and the Praxis
  File paths with a scripted helper emitting in-band file content.
  **Gate**: focused tests green.
- **Chunk E — scenarios, fixture, governance, smoke.** Hostile-CSV
  fixture; 055 scenarios including the 072 test-plan delta (poisoned
  input, scope resolution, scheduled `require_approval`); governance
  §2 entry; `docs/plans/000_README.md` row; full suite; manual live
  smoke on all three providers with a small CSV and the poisoned CSV
  (egress-isolated providers only for the poisoned smoke), quirks
  recorded in the module docstring. **Gate**: `make check` green and
  the smoke record present.
