# Corrective Follow-up 002: Web Search offers only configured providers

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the row for this plan in the
> Corrective Follow-up Status table in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat efafa64..HEAD -- apps/api/services/agents/runtime/tools/ apps/api/services/agents/models/`
> Compare the "Current state" excerpts against live code; treat a mismatch in
> `web_search.py`'s provider resolution, the `provider_api_key` seam, or the
> `availability_check` plumbing as a STOP condition.

## Status

- **Status**: DONE 2026-07-24
- **Priority**: P1 (live defect: agents hard-fail runs by selecting an
  unconfigured search provider)
- **Effort**: S
- **Risk**: LOW-MED (tool schema change: `model_provider` becomes optional;
  behavior when omitted must stay deterministic)
- **Depends on**: none (all touched seams are landed: 025/028 registry, 082
  versioned schemas, UI-025 presentation options)
- **Category**: corrective follow-up (spike), same track as
  `001-enforce-context-group-workspace-scope`
- **Planned at**: working tree at commit `efafa64`, 2026-07-24

The empty-configured-set STOP condition was encountered during execution:
Python produces `Literal[()]`, which Pydantic rejects during registration-time
schema serialization. The plan's documented fallback was used: the function
accepts `str | None`, the configured enum is injected into its JSON schema,
and call-time validation remains strict through `ModelRetry`.

## Product intent

The `web_search` tool advertises three helper providers (anthropic, google,
openai) unconditionally. When an operator has configured only one provider
key, agents still see all three in the tool schema and keep picking an
unconfigured one (Google in practice). The missing key is only discovered at
execution time, where it raises `ModelConfigurationError` — a hard 500-class
failure that aborts the run instead of steering the model. After this plan,
every surface that names search providers — the LLM-facing schema and
descriptions, the approval-edit dropdown, call-time validation, and the
no-argument default — offers exactly the providers whose API keys are
configured, and the tool disappears entirely when none are.

## Decisions taken

1. **One configured-providers source of truth.** Add a non-raising
   `has_provider_api_key(provider) -> bool` beside `provider_api_key` in
   `services/agents/models/utils.py` (same `_PROVIDER_KEY_SETTING` mapping,
   no exception control flow). In `web_search.py`, add
   `configured_native_search_providers() -> tuple[str, ...]` returning the
   members of `SUPPORTED_NATIVE_SEARCH_PROVIDERS` with a configured key, in
   the fixed order anthropic, google, openai. No caching — settings are
   process-static and the check is a `getattr`, and tests monkeypatch
   settings.
2. **Gate the tool with the existing `availability_check` hook.** Pass
   `availability_check=lambda: bool(configured_native_search_providers())`
   to `@runtime_tool`. This is the first real user of the hook already
   plumbed through `RuntimeToolDefinition` and enforced by
   `permissions.is_tool_allowed`: with zero configured providers the tool
   drops out of the catalog routes, agent mounting, and saved
   `tool_names` resolution (logged skip) — no schema surface left to
   mislead the model.
3. **`model_provider` becomes optional.** Change the parameter to
   `NativeWebSearchProvider | None = None`. The existing no-provider branch
   in `resolve_web_search_model` (today unreachable because the field is
   required) becomes the default path, constrained to configured providers:
   reuse the agent's own provider when it is supported *and* configured,
   otherwise fall back to the first configured provider (replacing the
   hardcoded Anthropic fallback). The parameter description tells the model
   to omit it unless it has a reason to choose.
4. **Explicit-but-unconfigured picks get a `ModelRetry`, not a 500.**
   `_native_model_spec` (and the resolve path generally) validates the
   requested provider against the *configured* set, raising `ModelRetry`
   that names the configured providers. This converts today's run-aborting
   `ModelConfigurationError` into a one-step self-correction. The
   `ModelConfigurationError` inside `provider_api_key` stays as the last
   line of defense; after this plan it should be unreachable from
   `web_search`.
5. **Schema enum, descriptions, and presentation options are built at import
   from the configured set.** The `Literal` annotation, the
   `model_provider` field description, the tool description's provider
   list, and the presentation `options` tuple all derive from
   `configured_native_search_providers()` evaluated at registration.
   Settings are env-loaded at process start, so this matches every other
   settings-driven behavior; a newly added key requires an API/worker
   restart to appear, which is the existing operational contract. The
   approval-edit "Search Provider" dropdown consumes the server-declared
   options (UI-025 contract), so the web app needs no changes — verify,
   don't edit.
6. **Test posture: the suite env seeds all three provider keys.** So the
   registered catalog under test keeps the full enum and existing
   catalog/mounting assertions stay meaningful. Configured-subset behavior
   is unit-tested through `configured_native_search_providers()`,
   `resolve_web_search_model`, and the availability check with
   monkeypatched settings — not by re-registering the import-time catalog.

## Why this matters

This is the first tool whose *options* are configuration-dependent, and the
pattern chosen here (availability gate + configured-set helper + import-time
schema derivation + call-time `ModelRetry` steering) is the template the
integration providers and future native tools will copy. Getting the layering
right — hide when unusable, narrow what is advertised, steer instead of
crash — is worth more than the spike itself.

## Current state

All anchors verified on the working tree at `efafa64` (2026-07-24).

- **Tool definition**: `services/agents/runtime/tools/native/web_search.py`
  — `@runtime_tool(name="web_search", ...)` at 101–140; no
  `availability_check`. `model_provider` is a **required**
  `NativeWebSearchProvider` (Literal, 52) at 147–154; presentation
  `options=tuple(sorted(SUPPORTED_NATIVE_SEARCH_PROVIDERS))` at 135.
- **Resolution**: `resolve_web_search_model` (185–210) — explicit provider →
  `_native_model_spec` (311–335), which `ModelRetry`s only on *unsupported*
  names; the no-provider branch (203–210) reuses the agent model when
  supported, else hardcodes Anthropic + `DEFAULT_NATIVE_SEARCH_MODELS`.
- **Execution**: `run_native_web_search` (213–238) → `build_model` →
  `provider_api_key` (`services/agents/models/utils.py:70-85`), which raises
  `ModelConfigurationError` when the key setting is unset — propagates
  through dispatch's generic exception path as a hard failure with a
  FAILURE audit record.
- **Availability plumbing (unused today)**: `availability_check` on
  `RuntimeToolDefinition` (`contract.py:154`), accepted by `runtime_tool`
  (`registry.py:74,109`), enforced in `permissions.is_tool_allowed`
  (`permissions.py:18`), applied in `build_runtime_tools`,
  `build_runtime_native_capabilities`, and
  `list_allowed_tool_definitions`. No tool sets it yet.
- **Key settings**: `core/settings/models.py` — `ANTHROPIC_API_KEY` (69),
  `OPENAI_API_KEY` (70), `GOOGLE_API_KEY` (71–74), all optional
  `SecretStr`; mapping `_PROVIDER_KEY_SETTING` (`utils.py:29-34`).
- **Tests**: `tests/services/agents/runtime/test_native_tools.py` — catalog
  entry (76–96), mount + enum `["anthropic","google","openai"]` (98–129),
  unsupported-provider `ModelRetry` (146–154), execution with mocked search
  (157–210). `tests/routes/tools/test_tool_catalog_routes.py:50-78` asserts
  the catalog entry including the `model_provider` description.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Focused tests | `cd apps/api && uv run pytest tests/services/agents/runtime/test_native_tools.py tests/routes/tools -q` | all pass |
| Full API suite | `make check` (or the API-side subset per `apps/api/AGENTS.md`) | all pass |

## Scope

**In scope:**

- `services/agents/models/utils.py` — `has_provider_api_key`
- `services/agents/runtime/tools/native/web_search.py` — configured-set
  helper, availability check, optional `model_provider`, configured-set
  validation with `ModelRetry`, import-time schema/description/options
  derivation
- Test env/fixture seeding of the three provider keys (check the existing
  `apps/api/tests` conftest/settings fixture first — seed only what is
  missing)
- Tests: helper matrix, resolution matrix, availability gating, updated
  enum/catalog assertions

**Out of scope (do NOT touch):**

- Any web frontend change — the dropdown options flow from the server
  presentation; verify only.
- Per-request/per-workspace provider enablement, provider health checks, or
  making other tools configuration-aware (this plan sets the pattern; it
  does not sweep).
- The `provider_api_key` raising contract and `build_model` — the backstop
  stays as-is.
- Dispatch error handling — the fix is upstream steering, not new exception
  translation at the choke point.

## Git workflow

- Branch: `fix/002-web-search-enabled-providers`
- Commit: `API - Web Search Configured Providers Only`
- Do NOT commit without explicit operator approval, and do not push or open
  a PR unless instructed.

## Steps

1. **Configured-set seam**: `has_provider_api_key` in `utils.py`;
   `configured_native_search_providers` in `web_search.py`. *Verify*: unit
   tests with monkeypatched settings (none / one / all configured; azure
   never included).
2. **Availability gate**: wire `availability_check` into the decorator.
   *Verify*: with no keys configured, `web_search` is absent from
   `list_allowed_tool_definitions` and `build_runtime_tools` skips an agent
   that saved it; with one key it is present.
3. **Optional parameter + steering**: make `model_provider` optional;
   constrain both resolve branches to the configured set (`ModelRetry`
   naming configured providers on explicit misses; agent-provider-else-
   first-configured default when omitted). *Verify*: resolution matrix
   tests, including agent on azure → first configured, and agent on a
   supported-but-key-shared provider reusing its own model with
   `NATIVE_WEB_SEARCH_MAX_STEPS`.
4. **Import-time derivation**: build the Literal annotation, field/tool
   descriptions, and presentation options from the configured set; seed the
   test env keys so the registered catalog keeps the full enum. *Verify*:
   updated `test_native_tools.py` enum/catalog assertions and the catalog
   route test pass; grep the web app to confirm no hardcoded provider list
   exists client-side.
5. **Sweep + gate**: update the two existing tests that assert the old
   required-field/unsupported-only behavior; run lint + focused suites +
   the fullest gate available; update the README status row.

## Test plan

~10-12 tests: configured-set matrix (3), availability gating in catalog +
mounting (2-3), resolution matrix — explicit configured, explicit
unconfigured → `ModelRetry` text names configured set, omitted with
agent-provider configured, omitted with agent on azure, unsupported name
(4-5), schema/options derivation under the seeded test env (1-2).

## Done criteria

- [x] With only `ANTHROPIC_API_KEY` set, the tool schema enum, field
      description, tool description, and presentation options name only
      `anthropic`; picking `google` explicitly yields a `ModelRetry` that
      names the configured set; omitting the provider searches via
      anthropic
- [x] With no provider keys set, `web_search` is hidden from the catalog
      routes and never mounted, including for agents with it saved in
      `tool_names`
- [x] No path from `web_search` reaches `ModelConfigurationError` for a
      missing key
- [x] Existing full-enum behavior is byte-identical when all three keys are
      configured (regression suites pass)
- [x] `docs/plans/000_README.md` corrective follow-up row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Settings are not reliably constructed before tool registration runs
  (import-order hazard in `registry.py`'s side-effect imports, workers, or
  test bootstrap) — import-time derivation is then the wrong seam; propose
  registration-deferred derivation instead of working around import order.
- The test suite cannot seed provider keys before the registry import
  happens (fixtures run too late), so the registered catalog under test is
  key-dependent in a way that breaks unrelated suites.
- Making `model_provider` optional breaks the UI-025/UI-027 approval-edit
  contract for options fields with an absent value — report the rendering
  behavior rather than making the field required again or touching the web
  app.
- Dynamic `Literal` construction fights Pydantic schema serialization
  (`serialized_input_schema()` at registration) — if a clean typed form
  isn't achievable, propose `str | None` with the enum injected via the
  field's `json_schema_extra` rather than shipping an untyped free-text
  field silently.

## Maintenance notes

- Keys added or removed require an API and worker restart to change the
  advertised set — same contract as every other setting; call this out in
  operator-facing docs if a settings reference page appears later.
- This is the template for configuration-dependent tool options: hide via
  `availability_check`, narrow the advertised schema from one configured-set
  helper, steer explicit misses with `ModelRetry`. Future native tools
  (image generation's `fallback_model` pattern) and integration providers
  should copy it rather than invent parallel gating.
- Reviewers should scrutinize: the omitted-provider default order, that the
  `ModelRetry` text lists the *configured* set (not the supported set), and
  that no test weakened the all-keys regression posture.
