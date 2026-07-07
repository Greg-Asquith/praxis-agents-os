# Plan 041: First integration providers — Gmail, Google Ads, Airtable

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G1 pre-flight (HARD — run before Step 1)**: per
> `docs/plans/000_MASTER_ROADMAP.md` §3, plans 021–023 AND 014 (OTel) must
> be DONE before this plan ships agent-callable integration tools. At
> `0cbbb39`, 021–023 are DONE but **014 is TODO**
> (`docs/plans/000_README.md` status table). If 014 is still TODO at
> execution time, **STOP and report — do not proceed, do not ship the
> tools disabled as a workaround.** This plan's Google Ads mutations spend
> real money; the roadmap requires tracing before they exist.
>
> **Sibling-plan pre-flight**: verify the implemented 037/038/039/040 code
> matches the dictated contract in "Current state" (manifest shape,
> credential service, discovery job kind `integrations.discover_resources`,
> `IntegrationToolBinding`, `run_context_fan_out`). Mismatch = STOP.
>
> **Governance pre-flight**: re-read `docs/architecture/governance.md` §2
> (spend rule) and §4 (Retry-After posture) — the note wins over this plan
> if they diverge.
>
> **Drift check (run first)**: `git diff --stat 0cbbb39..HEAD -- apps/api/services/agents/runtime/tools/ apps/api/services/agents/utils.py apps/api/services/audit_events/ apps/api/core/exceptions/integration.py apps/api/core/settings/`
> Files added by 037–040 are EXPECTED. If the tool contract, registry,
> dispatch, or `validate_tool_configuration` shape changed beyond what 040
> specifies, compare against "Current state" before proceeding; on a
> mismatch, treat it as a STOP condition.

> **Amendment (2026-07-07, plan 061 — provider packaging)**: provider code
> lands as self-contained packages per
> `docs/architecture/integration-packaging.md` (the note wins on
> structure; this plan still owns all product scope and policy):
>
> 1. Each provider is `apps/api/integrations/<key>/` — `__init__.py`
>    (exports `PROVIDER: IntegrationProviderPlugin`), `manifest.py`,
>    `client.py`, `discover_resources.py`, `operations/` (one op per
>    file), `tools.py` — **replacing** the in-scope paths
>    `services/integrations/providers/<key>/` and
>    `services/agents/runtime/tools/integrations/*.py`. 037's amendment
>    already created the three packages manifest-data-only; this plan
>    fills them.
> 2. Registration is via the 037 loader + `INTEGRATIONS_ENABLED_PROVIDERS`
>    — do NOT edit the `registry.py` side-effect import block.
> 3. Every tool definition must carry a complete `ToolPresentation`
>    (loader-enforced, note §4.3) — the default web row is the only UI
>    these tools get in v1 (note principle 2).
> 4. Provider tests live under `apps/api/tests/integrations/<key>/`;
>    the note §4.6 import laws apply (no `services/`→`integrations`
>    imports outside the loader, no provider→provider imports) and are
>    pinned by `tests/integrations/test_import_laws.py`.
> 5. Per-account audit (decision 8) stays centralized in
>    `services/audit_events/integration_events.py`; provider packages
>    call it, never write audit rows their own way.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH (first tools with real external side effects; one of them
  spends money; OAuth token misuse or scope creep is a security incident)
- **Depends on**: 037/038/039 (hard — connections, credentials, discovery),
  040 (hard — bindings, fan-out, context resolution), 025/026 (hard, DONE —
  registry + dispatch), **Gate G1: 014 + 021–023** (hard — pre-flight above)
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md` §4
  row 041, decision D4; donor `DONOR_PORT_ROADMAP.md` §4.2 / §6 row C5;
  governance `governance.md` §2 spend rule, §4 retries)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Final tool names — snake_case, NOT dotted.** The roadmap sketched
   `gmail.search_messages`-style names, but the registry name pattern is
   `^[a-z][a-z0-9_]*$` (`contract.py:29`) — dots are invalid at import
   time. Final curated set (10 tools, deliberately small; the manifest
   makes later additions incremental):

   | Tool | Provider | Effect | Default policy | supports_auto | Binding (provider_keys / resource_types / requires_write) |
   |------|----------|--------|----------------|---------------|------------------------------------------------------------|
   | `gmail_search_messages` | gmail | read | auto | yes | gmail / gmail_mailbox / no |
   | `gmail_read_message` | gmail | read | auto | yes | gmail / gmail_mailbox / no |
   | `gmail_send_message` | gmail | write | **approval** | yes | gmail / gmail_mailbox / **yes** |
   | `google_ads_list_accounts` | google_ads | read | auto | yes | google_ads / google_ads_account / no |
   | `google_ads_run_report` | google_ads | read | auto | yes | google_ads / google_ads_account / no |
   | `google_ads_update_campaign_status` | google_ads | write | **approval** | **NO (`supports_auto=False`)** | google_ads / google_ads_account / **yes** |
   | `airtable_list_records` | airtable | read | auto | yes | airtable / airtable_base / no |
   | `airtable_get_record` | airtable | read | auto | yes | airtable / airtable_base / no |
   | `airtable_create_record` | airtable | write | **approval** | yes | airtable / airtable_base / **yes** |
   | `airtable_update_record` | airtable | write | **approval** | yes | airtable / airtable_base / **yes** |

2. **The spend rule needs no new machinery.** Governance §2 ("anything
   that spends money is `approval` with `supports_auto=False`; per-agent
   configuration may not weaken it") is enforced by existing 025 code:
   write-time, `normalize_tool_configuration` rejects a policy not in
   `allowed_policies()` (`services/agents/utils.py:186-196`); runtime,
   `to_pydantic_tool` rejects it again (`contract.py:85-94`). This plan
   sets the flags on `google_ads_update_campaign_status` and pins both
   layers with tests — the first hard Gate G1 test the roadmap promised.
3. **REST over httpx2 for all three providers — no provider SDKs.** The
   google-ads SDK drags grpc; the Gmail SDK duplicates what three REST
   calls do. Plain REST through the runtime HTTP dependency (`httpx2`,
   `pyproject.toml:14`; plain `httpx` is dev-only per AGENTS.md) keeps the
   credential seam (037's credential service supplies the token per call),
   the retry posture, and test mocking (`httpx2.MockTransport`, verified
   present in 2.5.0) in our hands.
4. **Retry posture per governance §4 rides 037's shared helper.** Plan
   037 ships `services/integrations/http.py::request_with_retries`
   (Retry-After-aware, bounded attempts — governance §4 names 037 as the
   owning plan, and 037's written plan claims the module). This plan does
   NOT create a second retry mechanism: every provider client calls that
   helper, and this plan *verifies at the provider layer* that it honors
   `Retry-After` (integer-seconds and HTTP-date forms), caps attempts,
   and NEVER retries non-idempotent calls after headers were sent unless
   the failure is a connect error or 429/503 (a send that timed out
   mid-flight surfaces as an error result — the model is warned by
   dispatch's unverified-mutation machinery, `dispatch.py:50-53`). If the
   landed helper lacks one of these behaviors, extend it in place — do
   not wrap it. The LLM transport retrier
   (`services/agents/models/utils.py:63 retrying_http_client`) is a
   *different* seam for a different problem; do not reuse it.
5. **Minimal OAuth scopes** (donor hard-won detail, §4.2): Gmail requests
   exactly `gmail.readonly` + `gmail.send` (NOT `gmail.modify` or full
   mail). Google Ads requests exactly
   `https://www.googleapis.com/auth/adwords` (the API has one scope).
   `include_granted_scopes=false` and persisted-scope filtering are 038's
   job — this plan only declares scopes in the manifest. Airtable is a
   personal access token entered as a secret reference (037 api-key flow);
   document required PAT scopes (`data.records:read`,
   `data.records:write`, `schema.bases:read`) in the manifest entry's
   user-facing help text.
6. **Resource shapes**: Gmail discovery yields exactly one
   `gmail_mailbox` resource (the authenticated address, from
   `users.getProfile`) — a mailbox is the operating target and gives
   Gmail the same context/fan-out shape as everything else. Google Ads
   discovery lists accessible customers then expands MCC hierarchies via
   `customers/{id}/googleAds:searchStream` on `customer_client`, storing
   `google_ads_account` resources with metadata `{manager, parent_external_id,
   level, currency_code, descriptive_name, status}`; manager (MCC)
   accounts are stored but marked non-operable (`metadata.manager=true` —
   reports/mutations target client accounts; the fan-out skips managers
   via `enabled` defaulting false for them). Airtable discovery lists
   bases via the meta API, one `airtable_base` resource per base.
7. **Write-permission metadata feeds 040's gate, fail-closed**: Gmail
   mailbox `write_allowed=true` only when the granted scopes include
   `gmail.send`; Google Ads account write metadata true only when the
   authenticated principal's access role permits mutation
   (`customer_user_access` / non-read-only login) — when the role can't be
   determined, false; Airtable base write from the meta API
   `permissionLevel` (`create`/`edit` → true, `read`/`comment` → false).
8. **Per-account audit on every operation** (donor §4.2 runtime rule): 026
   dispatch already audits the outer tool call (name, provider, args
   digest, outcome — `dispatch.py:127-227`). Integration ops additionally
   emit one audit event **per resource entry** from inside the fan-out
   `operation`, via a new `services/audit_events/integration_events.py::
   record_integration_operation_audit_event` following the
   `tool_events.py:34-50` independent-transaction shape. Extra context
   integration ops must add beyond the digest: `connection_id`,
   `integration_resource_id`, resource `external_id`, provider operation
   name, and the **external change reference** (Gmail sent message id;
   Google Ads mutate `resource_names`; Airtable record ids) — "which
   account did we touch and what changed" must be answerable from audit
   alone. Never message bodies, query results, or tokens in audit details.
9. **Provider settings, env-gated availability**: new
   `core/settings/integrations.py` mixin adds
   `GOOGLE_ADS_DEVELOPER_TOKEN: str | None = None` and
   `GOOGLE_ADS_LOGIN_CUSTOMER_ID: str | None = None` (038 owns the shared
   Google OAuth client id/secret settings). A manifest entry whose
   required settings are absent reports itself unavailable
   (manifest capability flag from the 037 contract) and its tools are
   hidden via the `is_tool_allowed` seam (`permissions.py:8-15`) — the
   seam 040 deliberately left for exactly this (040 decision 9).
10. **Curated operation surface, v1**: no Gmail attachments, drafts,
    labels, threads-as-first-class; no Ads campaign creation, budget
    edits, or asset mutations; no Airtable schema writes or deletes.
    `google_ads_update_campaign_status` mutates exactly one field
    (`ENABLED`/`PAUSED`) on named campaigns — the smallest real spend
    lever, which is the point of the G1 test. Record follow-ups in
    `docs/plans/FOLLOW_UPS.md` rather than growing this plan.
11. **GAQL is the read surface**: `google_ads_run_report` takes a GAQL
    `query` string. GAQL is query-only by API design (mutations live on
    separate endpoints), so arbitrary GAQL stays `effect="read"`; the
    operation additionally rejects any query string containing no
    `SELECT` prefix and caps returned rows
    (`INTEGRATION_REPORT_MAX_ROWS`, default 1000) with a truncation note
    in the output.
12. **Tool outputs are typed** (`output_model` on every tool, enforced by
    dispatch output-contract validation, `dispatch.py:106-124`): each tool
    returns `{"results": [FanOutEntryResult-shaped dicts]}` so the model
    always sees per-resource attribution — including single-resource
    contexts (uniform shape beats a special case).

## Why this matters

This is the plan the whole Phase 4a spine exists for: the first agent
capabilities that touch external systems users pay for. Gmail exercises
user-scoped OAuth + a single implicit resource; Google Ads exercises
workspace-scoped OAuth + deep resource discovery + money-spending
mutations (the roadmap's chosen first hard test of Gate G1); Airtable
exercises api-key + secret references. Between them they cover every shape
the 037 manifest supports, so provider #4 onward is a manifest entry, a
discovery function, and a handful of operation files — no new machinery.
Getting the *policy* right here (spend ops unweakenable, writes
approval-default, per-account audit, fail-closed write gating) sets the
precedent every later provider copies.

## Current state

All anchors verified at `0cbbb39`.

- `apps/api/services/agents/runtime/tools/contract.py` — name pattern
  `^[a-z][a-z0-9_]*$` (line 29); `RuntimeToolDefinition` (33-57) with
  `provider`, `effect`, `default_policy`, `supports_auto`,
  `supports_approval`, `timeout`, `output_model`; policy enforcement in
  `to_pydantic_tool` (85-94); `validate_definition` (109-176) requires
  write tools to support approval (171-176) — `supports_auto=False` +
  `supports_approval=True` on a write tool is a valid combination.
- `apps/api/services/agents/runtime/tools/registry.py` — `runtime_tool`
  decorator (33-91), duplicate-name `RuntimeError` (86-87), registration
  side-effect imports at 254-258 (**the assembly point this plan
  extends**), `is_tool_allowed` gates at 127/162/200.
- `apps/api/services/agents/utils.py:96-196` —
  `validate_tool_configuration`/`normalize_tool_configuration` reject
  agent `tool_policies` not in `allowed_policies()` (186-196): the
  write-time half of decision 2, already enforced.
- `apps/api/services/agents/runtime/dispatch.py` — the 026 choke point:
  every tool call audited (127-227) with digest, latency, outcome,
  approval refs; mutation warning constants (50-53); denied approvals
  audited on resume (230-259).
- `apps/api/services/audit_events/tool_events.py:34-50` —
  `record_tool_invocation_audit_event(...)` independent-transaction
  precedent decision 8 copies for per-resource events.
- `apps/api/core/exceptions/integration.py:14-137` — `IntegrationError`
  hierarchy with `provider_key`/`connection_id`/`operation` context and
  RFC 7807 mapping (`IntegrationAuthError` 401, `IntegrationRateLimitError`
  429, `IntegrationPermissionError` 403, etc.) — raise these, never ad-hoc
  exceptions.
- `apps/api/services/agents/runtime/tools/native/web_search.py` — the 028
  helper-model precedent: a registry tool built on external capability
  with probe findings recorded in the module docstring (1-19), typed
  output model (67-73), `ModelRetry` for model-correctable errors
  (120-121). This plan's tools follow its module shape.
- `core/settings/` — per-concern mixins composed in
  `core/settings/__init__.py`; the production-safety `model_validator`
  there must keep rejecting unsafe combinations (no change expected here —
  the new keys are optional).
- Gate G1 inputs: `docs/plans/000_README.md` — 021/022/023 DONE, **014
  TODO** at `0cbbb39`.
- httpx2 2.5.0 installed with `MockTransport` (probed 2026-07-06);
  `httpx2>=2.5.0` is the runtime dep (`pyproject.toml:14`).
- Will exist after sibling plans (dictated contract — verify at
  execution): 037 manifest (`services/integrations/manifest.py`) +
  credential service (locked proactive refresh, `needs_reauth`) +
  `services/secrets/`; 038 OAuth/api-key connect routes; 039 discovery
  job kind `integrations.discover_resources` + resource selection; 040
  `IntegrationToolBinding` on the contract, `run_context_fan_out`
  (per-entry results, write gating, `ModelRetry` on empty), resolution
  into `RuntimeDeps.active_context`, and the import-time deny-list on
  connection/account parameter names.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Gate G1 check | `grep -E '^\| 014 ' ../../docs/plans/000_README.md` | row says DONE — else STOP |
| Lint | `uv run ruff check .` | exit 0 |
| Registry smoke | `uv run python -c "from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG; print(sorted(n for n in RUNTIME_TOOL_CATALOG if n.startswith(('gmail_','google_ads_','airtable_'))))"` | the 10 decision-1 names |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/integrations -q` | all pass |
| Policy invariants | `TEST_DATABASE_URL=... uv run pytest tests/services/agents -q` | all pass |
| Discovery smoke | `uv run python -m workers.job_runner --once` | exit 0 (no pending discovery jobs fail) |

## Scope

**In scope:**

- Manifest entries for `gmail`, `google_ads`, `airtable` in the 037
  manifest (auth mode, owner scope, resource types, scopes, capability
  flags, required-settings gating)
- `apps/api/core/settings/integrations.py` additions (decision 9) —
  extend, don't duplicate, whatever mixin 037/038 created
- `apps/api/services/integrations/http.py` (extend only if a decision-4
  behavior is missing — 037 creates it)
- `apps/api/services/integrations/providers/gmail/` (create):
  `client.py`, `schemas.py`, `discover_resources.py`,
  `search_messages.py`, `read_message.py`, `send_message.py`
- `apps/api/services/integrations/providers/google_ads/` (create):
  `client.py`, `schemas.py`, `discover_resources.py`, `run_report.py`,
  `list_accounts.py`, `update_campaign_status.py`
- `apps/api/services/integrations/providers/airtable/` (create):
  `client.py`, `schemas.py`, `discover_resources.py`, `list_records.py`,
  `get_record.py`, `create_record.py`, `update_record.py`
- Registry tool modules
  `apps/api/services/agents/runtime/tools/integrations/` (create):
  `__init__.py`, `gmail.py`, `google_ads.py`, `airtable.py` + the
  registration import at `tools/registry.py:254-258`
- `apps/api/services/agents/runtime/tools/permissions.py` — provider
  availability gating (decision 9)
- `apps/api/services/audit_events/integration_events.py` (create)
- `apps/api/tests/services/integrations/providers/`, policy tests under
  `tests/services/agents/`, factory helpers

**Out of scope (do NOT touch):**

- OAuth flow mechanics, token encryption, refresh locking — 037/038 own
  the credential lifecycle; this plan only calls
  `credential service → access token` per fan-out entry.
- Discovery *harness* (job kind, status transitions, retries) — 039; this
  plan supplies each provider's `discover_resources` function the harness
  invokes via the manifest.
- Context resolution, fan-out internals, prompt block, schedule wiring —
  040.
- Any UI — 042.
- More operations per provider than decision 1/10 lists (follow-ups go to
  `FOLLOW_UPS.md`).
- New migrations — this plan creates **no tables** (resources ride 037's
  generic `integration_resources`).

## Git workflow

- Branch: `advisor/041-first-integration-providers`
- Commit style: `API - Gmail, Google Ads & Airtable Providers` (split into
  per-provider commits if landing incrementally: `API - Gmail Provider`,
  etc.)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Gate G1 pre-flight

Run the pre-flight in the executor blockquote. Confirm in
`docs/plans/000_README.md`: 014 DONE, 021 DONE, 022 DONE, 023 DONE, and
037/038/039/040 DONE. Any TODO among these → STOP.

**Verify**: paste the five status rows into your report before Step 1.

### Step 1: Settings + retry-helper audit

Extend the integrations settings mixin with
`GOOGLE_ADS_DEVELOPER_TOKEN: str | None = None` (secret value — document
that production should supply it via the 037 secrets provider, env-var
provider locally) and `GOOGLE_ADS_LOGIN_CUSTOMER_ID: str | None = None`,
plus `INTEGRATION_REPORT_MAX_ROWS: int = 1000`. All `Field(...,
description=...)`; no production-validator change (optional keys).
Reuse — do not shadow — whatever timeout/attempt settings 037's helper
already reads.

Audit the landed `services/integrations/http.py::request_with_retries`
(037) against decision 4: `Retry-After` parsing (integer seconds and
HTTP-date), a cap on any single wait (≤60s), bounded attempts raising
`IntegrationRateLimitError` on exhaustion, `IntegrationTimeoutError` on
timeouts, `IntegrationAuthError`/`IntegrationPermissionError`/
`IntegrationNotFoundError` mapping for 401/403/404, and the
non-idempotent-retry rule — always with
`provider_key`/`connection_id`/`operation` context filled. Extend it in
place (with tests) only where a behavior is missing.

**Verify**: `uv run ruff check .` exit 0; helper behavior pinned by
Step 7's `test_http_retries.py` (extends 037's existing helper tests —
do not duplicate them).

### Step 2: Manifest entries

Finalize the three data-only entries 037 already ships in the manifest
(037 decision 6 registers `gmail`/`google_ads`/`airtable` as env-gated
placeholders — edit those entries in place; a second `_register` call for
the same key raises at import). Target shape:

- `gmail`: auth mode oauth, owner scope **user**, scopes
  `["https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.send"]`, resource types
  `["gmail_mailbox"]`, capability flags per 037's schema, available when
  038's Google OAuth client settings are present.
- `google_ads`: auth mode oauth, owner scope **workspace**, scopes
  `["https://www.googleapis.com/auth/adwords"]`, resource types
  `["google_ads_account"]`, available only when the Google OAuth client
  AND `GOOGLE_ADS_DEVELOPER_TOKEN` are configured (decision 9).
- `airtable`: auth mode api_key (secret reference per 037), owner scope
  **workspace**, resource types `["airtable_base"]`, connect-form help
  text naming the required PAT scopes (decision 5).

Each entry wires its provider's `discover_resources` function (Step 3-5)
into 039's discovery job kind.

**Verify**: the manifest's import-time invariant checks pass
(`uv run python -c "import services.integrations.manifest"` exit 0); a
manifest listing shows the three providers with correct owner scopes.

### Step 3: Gmail provider (`services/integrations/providers/gmail/`)

`client.py` — thin async client over
`https://gmail.googleapis.com/gmail/v1` using httpx2 + Step 1 retries;
constructor takes an access-token callable from 037's credential service
(so proactive refresh and `needs_reauth` transitions stay in one place);
one 401 triggers a forced refresh + single retry, a second 401 raises
`IntegrationAuthError` (credential service flips the connection to
`needs_reauth` per the 037 contract).

Operations (one per file, service-op-per-file rule):

- `discover_resources.py` — `users/me/profile` → one `gmail_mailbox`
  resource (`external_id` = email address, `display_name` = email,
  write metadata from granted scopes per decision 7).
- `search_messages.py` — `users/me/messages?q=...&maxResults=N` (cap 25)
  then batch `messages.get(format=metadata)` for From/To/Subject/Date +
  snippet. Returns typed rows; never full bodies.
- `read_message.py` — `messages.get(format=full)`, decode text/plain
  (fall back to stripped text/html), truncate body at 50k chars with a
  marker.
- `send_message.py` — args `to: list[str]`, `subject: str`, `body_text:
  str`, optional `cc`/`bcc`; builds RFC 2822, base64url,
  `users/me/messages/send`. Returns the sent message id (the decision-8
  external change reference).

**Verify**: provider unit tests (Step 7) green against
`httpx2.MockTransport`; no live-call path in tests.

### Step 4: Google Ads provider (`services/integrations/providers/google_ads/`)

`client.py` — async client over
`https://googleads.googleapis.com/v<pinned>` (pin the current stable
version in one constant; record it in the module docstring with the
verification date). Every request carries `developer-token` from
settings and, when calling client accounts under an MCC,
`login-customer-id` (the manager's external id from the resource's
`parent_external_id` metadata — resolve per entry, no if-ladders).

- `discover_resources.py` — `customers:listAccessibleCustomers`, then per
  accessible customer a `customer_client` GAQL query to expand the
  hierarchy; upsert `google_ads_account` resources with decision-6
  metadata; managers stored non-enabled by default. This is the 039
  discovery shape: counters into `integration_discovery_runs`, failures
  keep the credential (donor rule — retry without reconnecting).
- `list_accounts.py` — read of the *persisted* resource hierarchy for
  the active-context entries (no API call; answers "what am I operating
  on" cheaply and gives the model the account tree).
- `run_report.py` — `googleAds:searchStream` with the GAQL `query`;
  decision-11 guards (SELECT-only prefix check, row cap + truncation
  note); returns rows as plain dicts keyed by GAQL field paths.
- `update_campaign_status.py` — args `campaign_ids: list[str]`, `status:
  Literal["ENABLED","PAUSED"]`; `campaigns:mutate` with one operation per
  id, `partial_failure=true`; returns mutate `resource_names` +
  per-campaign errors (decision-8 change reference).

**Verify**: unit tests cover MCC header selection (client account under a
manager gets `login-customer-id`), report row cap, and mutate
partial-failure surfacing.

### Step 5: Airtable provider (`services/integrations/providers/airtable/`)

`client.py` — async client over `https://api.airtable.com/v0`; the PAT
resolves at call time through the 037 secret-reference seam (references
only — a raw key never appears outside the connect flow).

- `discover_resources.py` — `meta/bases` (paginated) → `airtable_base`
  resources; `permissionLevel` → write metadata (decision 7).
- `list_records.py` — args `table: str`, optional `view`,
  `filter_by_formula`, `max_records` (cap 100); returns records with ids
  + fields.
- `get_record.py` — `table`, `record_id`.
- `create_record.py` — `table`, `fields: dict`; returns created id.
- `update_record.py` — `table`, `record_id`, `fields: dict` (PATCH
  semantics); returns updated id.

**Verify**: unit tests including a 429 with `Retry-After: 1` retried then
succeeding (Airtable's 5 rps limit is the realistic case for Step 1's
helper).

### Step 6: Registry tools + per-account audit

`services/audit_events/integration_events.py` —
`record_integration_operation_audit_event(*, workspace_id, agent, run,
tool_name, provider_key, connection_id, integration_resource_id,
external_id, operation, status, external_ref: str | None, error_code:
str | None)` following `tool_events.py:34-50` (independent committed
transaction; never raises into the tool path — log on failure).

`services/agents/runtime/tools/integrations/{gmail,google_ads,airtable}.py`
— one module per provider registering the decision-1 tools. Every tool:

- `@runtime_tool(name=..., provider="gmail"|"google_ads"|"airtable",
  takes_ctx=True, effect=..., default_policy=..., supports_auto=...,
  timeout=60, output_model=..., integration_binding=
  IntegrationToolBinding(provider_keys=frozenset({...}),
  resource_types=frozenset({...}), requires_write=...))` per the
  decision-1 table.
- Body: validate model-visible args (raise `ModelRetry` for correctable
  problems — empty query, no recipients, bad status value — the
  `web_search.py:120-121` shape), then
  `await run_context_fan_out(ctx.deps, binding=..., operation=...,
  write=...)` where `operation` (a) resolves credentials for the entry's
  connection, (b) calls the provider operation service, (c) emits the
  per-entry audit event with the external change reference, and (d)
  returns the entry's data. Return `{"results": [...]}` per decision 12.
- **No parameter names from 040's deny-list** — the import-time guard
  enforces it; write signatures accordingly (the model never addresses
  accounts; the context does).

Register the package import at the `registry.py:254-258` assembly point.
Update `permissions.is_tool_allowed` to return `False` for
integration-provider tools whose manifest entry reports unavailable
(decision 9) — keep the function tiny and data-driven off the manifest.

**Verify**: the registry smoke command lists exactly the 10 names;
`uv run python -c "from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG as C; d=C['google_ads_update_campaign_status']; print(d.default_policy, d.supports_auto, sorted(d.allowed_policies()))"`
→ `approval False ['approval']`.

### Step 7: Tests

`tests/services/integrations/providers/` (async marker + factories rules
as in plan 030 Step 7; all HTTP mocked via `httpx2.MockTransport` wired
through the client constructors — live LLM/integration calls are blocked
in tests):

- `test_http_retries.py`: Retry-After seconds and HTTP-date honored;
  attempt cap raises `IntegrationRateLimitError`; 401→refresh→retry once
  then `IntegrationAuthError`; error mapping table (403/404/timeout).
- `test_gmail_provider.py`: discovery creates the single mailbox resource
  with scope-derived write metadata; search caps results; read truncates;
  send builds correct RFC 2822 (assert base64url round-trip) and returns
  the message id.
- `test_google_ads_provider.py`: discovery expands an MCC fixture into
  parent-linked resources with managers non-enabled; report rejects
  non-SELECT GAQL (`ModelRetry`); row cap truncates with note; mutate
  sends `login-customer-id` for managed accounts and surfaces
  partial-failure errors per campaign.
- `test_airtable_provider.py`: discovery maps `permissionLevel` to write
  metadata; 429 retry; create/update return record ids.
- `test_integration_tools.py`: each tool's registered
  effect/policy/binding matches the decision-1 table (loop the table —
  one assertion set per tool); fan-out partial failure reaches the
  model-visible output (`results` mixed success/error); per-entry audit
  events written with connection/resource/external-ref context; write
  tool against a read-only resource → `write_not_permitted` entry and NO
  provider call; **no tool schema contains a deny-listed parameter**
  (introspect `to_pydantic_tool()` JSON schema — the 040 law pinned at
  the 041 layer too).
- `tests/services/agents/test_spend_policy.py`: **the Gate G1 invariants**
  — `validate_tool_configuration(tool_names=[...],
  tool_policies={"google_ads_update_campaign_status": "auto"})` raises
  `AppValidationError` (write-time cannot weaken);
  `to_pydantic_tool(policy="auto")` on that definition raises
  `ModelConfigurationError` (runtime cannot weaken); default policy is
  approval; `gmail_send_message`/`airtable_create_record`/
  `airtable_update_record` default to approval per governance §2.

**Verify**: `TEST_DATABASE_URL=... uv run pytest
tests/services/integrations tests/services/agents -q` all pass; without
the env var, DB suites skip.

## Test plan

Covered by Step 7 (~35-40 tests). Pinned invariants: **the spend op
cannot be weakened to auto at either layer** (the roadmap's first hard
Gate G1 test), **every write defaults to approval**, **write gating fails
closed on missing permission metadata**, **per-resource audit carries
connection + external change references**, **Retry-After is honored and
bounded**, **context never appears in tool schemas**, and **all provider
HTTP is mocked — zero live calls in CI**.

## Done criteria

- [ ] Gate G1 pre-flight passed and the five status rows are quoted in
      the completion report
- [ ] `uv run ruff check .` exits 0; no new migrations exist
- [ ] Registry smoke lists exactly the 10 decision-1 tools with the
      decision-1 policy matrix (spot-check the spend op prints
      `approval False ['approval']`)
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/integrations
      tests/services/agents -q` exits 0
- [ ] Grep confirms no `import httpx\b` in `services/integrations/`
      (httpx2 only) and no deny-listed parameter names in tool signatures
- [ ] Per-entry audit events observable end to end in one integration
      test (tool call → N audit rows with external refs)
- [ ] `docs/architecture/governance.md` §2 spend-rule cell flipped to
      `[implemented: plan 041]`; §4 integration-retries row already
      flipped by 037 — confirm it still reflects the landed helper
- [ ] No plan numbers cited in implementation code or docstrings
- [ ] `git status` clean outside the in-scope list;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Gate G1 fails**: 014 is TODO (or 021–023 regressed) at execution
  time. Do not ship the tools "temporarily disabled" — that is the
  improvisation this gate exists to prevent.
- 037/038/039/040 are unimplemented or deviate from the dictated
  contract: no `IntegrationToolBinding`, different fan-out signature or
  result shape, manifest without `provider_keys`/`resource_types`, no
  credential-service token seam, or discovery job kind renamed.
- The manifest cannot express a provider whose availability depends on
  settings (decision 9) without modifying 037's schema — coordinate, do
  not fork a second gating mechanism.
- Google Ads REST requires an API version no longer served, or the
  developer token cannot be obtained for the environment — report;
  do not stub the provider with fake success paths.
- `validate_definition`'s write-must-support-approval rule
  (`contract.py:171-176`) or `normalize_tool_configuration`'s
  allowed-policies rejection (`utils.py:186-196`) changed — the spend
  rule's enforcement assumptions are broken.
- You feel the need to add a second HTTP retry mechanism, a provider SDK
  dependency, more than the 10 curated tools, or any UI — scope leak.

## Maintenance notes

- **Provider #4 checklist** (what this plan's shape demands): manifest
  entry, `providers/<key>/` with `client.py` + `discover_resources.py` +
  one file per operation, one registry module with bindings, per-entry
  audit in every operation, MockTransport tests, and governance §2
  policy review — writes approval-default, spend ops
  `supports_auto=False`.
- **Scope changes are re-consent events**: widening Gmail scopes (e.g.
  adding `gmail.modify`) requires a manifest change AND every existing
  connection flowing through `needs_reauth` — never silently reuse old
  tokens for new capabilities (038's persisted-scope filtering enforces
  the read side; the manifest entry documents the rule).
- **Reviewers should scrutinize**: the fail-closed write metadata
  (absent → read-only), that `update_campaign_status` is the ONLY spend
  lever and stays single-field, `login-customer-id` selection for MCC
  children, that audit details never contain message bodies or record
  fields, and that a fan-out entry's token comes from *its own*
  connection (cross-connection token bleed is the multi-connection
  failure mode).
- 014's OTel spans wrap the dispatch layer; once both are live, add
  provider/connection attributes to integration tool spans — record that
  as a FOLLOW_UPS item at execution, not a scope change here.
