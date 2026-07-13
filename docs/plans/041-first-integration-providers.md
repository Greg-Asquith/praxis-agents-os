# Plan 041: First integration providers — Gmail, Google Ads, Airtable

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G1 pre-flight (HARD — run before Step 1)**: per
> `docs/plans/000_MASTER_ROADMAP.md` §3, plans 014 (OTel), 021–023, and
> the G1-extension plans 053–054 must be DONE before this plan ships
> agent-callable integration tools. All are DONE as of 2026-07-10
> (`docs/plans/000_README.md`). If any required row has regressed at
> execution time, **STOP and report — do not ship the tools disabled as
> a workaround.** This plan's Google Ads mutations spend real money.
>
> **Gate G6 pre-flight (run in Step 0)**:
> `docs/architecture/threat-model.md` §2 row **(g) integration-fetched
> content** exists (verified 2026-07-10) and names this plan as owner of
> its mechanical defense. This plan must NOT ship Gmail read tools before
> that defense and its fixture test exist (Step 7). If row (g) is missing
> at execution time, STOP and reconcile.
>
> **Notes pre-flight**: re-read `docs/architecture/governance.md` §2
> (spend rule) and §4 (Retry-After posture), and
> `docs/architecture/integration-packaging.md` (package layout, import
> laws §4.6, presentation rule §4.3, principle 2 — default-first UI).
> The notes win over this plan if they diverge.
>
> **Sibling-plan pre-flight**: 037 is DONE; verify the landed 038/039/040
> code matches the dictated contract in "Current state" (credential token
> seam, discovery job kind `integrations.discover_resources` + plugin
> dispatch, `IntegrationToolBinding`, `run_context_fan_out`). Mismatch =
> STOP.
>
> **Drift check (run first)**:
> `git diff --stat edc3abc..HEAD -- apps/api/services/agents/runtime/tools/ apps/api/services/agents/runtime/dispatch.py apps/api/services/agents/utils.py apps/api/services/audit_events/ apps/api/core/exceptions/integration.py apps/api/core/settings/ apps/api/integrations/ apps/api/services/integrations/`
> Files added by 037–040 are EXPECTED. If the tool contract, registry,
> dispatch, or `validate_tool_configuration` shape changed beyond what
> 040 specifies, compare against "Current state" (verified 2026-07-10)
> before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH (first tools with real external side effects; one of
  them spends money; OAuth token misuse or scope creep is a security
  incident)
- **Depends on**: 037 (hard, **DONE**), 038/039 (hard — connections,
  credentials, discovery), 040 (hard — bindings, fan-out, context
  resolution), 025/026 (hard, DONE — registry + dispatch), **Gate G1:
  014 + 021–023 + 053/054** (all DONE)
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md`
  §4 row 041, decision D4; governance §2 spend rule, §4 retries;
  threat-model channel (g))
- **Planned at**: commit `0cbbb39`, 2026-07-06. **Consolidated** at
  2026-07-10: plans 061 (provider packaging), 068 (SecretStr developer
  token), 077 (event posture), 080 (G6 channel (g), `effect_scope`,
  dispatch anchors) folded into the body; anchors re-verified against
  the tree with the 037 implementation present (post-`edc3abc`).

## Decisions taken

1. **Final tool names — snake_case, NOT dotted** (the registry name
   pattern `^[a-z][a-z0-9_]*$`, `tools/contract.py:34`, rejects dots at
   import time). Curated set of 10 tools, deliberately small:

   | Tool | Provider | Effect | Effect scope | Default policy | supports_auto | Binding (provider_keys / resource_types / requires_write) |
   |------|----------|--------|--------------|----------------|---------------|------------------------------------------------------------|
   | `gmail_search_messages` | gmail | read | internal | auto | yes | gmail / gmail_mailbox / no |
   | `gmail_read_message` | gmail | read | internal | auto | yes | gmail / gmail_mailbox / no |
   | `gmail_send_message` | gmail | write | **external** | **approval** | yes | gmail / gmail_mailbox / **yes** |
   | `google_ads_list_accounts` | google_ads | read | internal | auto | yes | google_ads / google_ads_account / no |
   | `google_ads_run_report` | google_ads | read | internal | auto | yes | google_ads / google_ads_account / no |
   | `google_ads_update_campaign_status` | google_ads | write | **external** | **approval** | **NO (`supports_auto=False`)** | google_ads / google_ads_account / **yes** |
   | `airtable_list_records` | airtable | read | internal | auto | yes | airtable / airtable_base / no |
   | `airtable_get_record` | airtable | read | internal | auto | yes | airtable / airtable_base / no |
   | `airtable_create_record` | airtable | write | **external** | **approval** | yes | airtable / airtable_base / **yes** |
   | `airtable_update_record` | airtable | write | **external** | **approval** | yes | airtable / airtable_base / **yes** |

   Reads stay `effect_scope="internal"` (the contract forces this,
   `contract.py:~174-183`); every write is `effect_scope="external"`.
2. **The spend rule needs no new machinery.** Governance §2 ("anything
   that spends money is `approval` with `supports_auto=False`; per-agent
   configuration may not weaken it") is enforced by existing 025 code:
   write-time, `normalize_tool_configuration` rejects a policy not in
   `allowed_policies()` (`services/agents/utils.py:108,~179-182`);
   runtime, `to_pydantic_tool` rejects it again. This plan sets the
   flags on `google_ads_update_campaign_status` and pins both layers
   with tests — the first hard Gate G1 test the roadmap promised.
3. **REST over httpx2 for all three providers — no provider SDKs.** The
   google-ads SDK drags grpc; the Gmail SDK duplicates what three REST
   calls do. Plain REST through the runtime HTTP dependency
   (`httpx2>=2.5.0`, `pyproject.toml:14`; plain `httpx` is dev-only)
   keeps the credential seam, the retry posture, and test mocking
   (`httpx2.MockTransport`) in our hands.
4. **Retry posture per governance §4 rides 037's shared helper**
   (`services/integrations/http.py::request_with_retries`,
   Retry-After-aware, bounded, typed errors — delivered). This plan does
   NOT create a second retry mechanism: every provider client calls that
   helper, and this plan *verifies at the provider layer* that it honors
   `Retry-After` (integer-seconds and HTTP-date), caps attempts, and
   NEVER retries non-idempotent calls after headers were sent unless the
   failure is a connect error or 429/503 (a send that timed out
   mid-flight surfaces as an error result — dispatch's
   unverified-mutation machinery warns the model). If the landed helper
   lacks a behavior, extend it in place — do not wrap it. The LLM
   transport retrier (`services/agents/models/utils.py
   retrying_http_client`) is a *different* seam; do not reuse it.
5. **Minimal OAuth scopes** (donor hard-won detail): Gmail requests
   exactly `gmail.readonly` + `gmail.send` (NOT `gmail.modify` or full
   mail) — already declared in the shipped gmail manifest. Google Ads
   requests exactly `https://www.googleapis.com/auth/adwords` (shipped).
   `include_granted_scopes=false` and persisted-scope filtering are
   038's job. Airtable is a personal access token entered as a secret
   reference (037/038 api-key flow); document required PAT scopes
   (`data.records:read`, `data.records:write`, `schema.bases:read`) in
   the manifest's user-facing help metadata.
6. **Resource shapes**: Gmail discovery yields exactly one
   `gmail_mailbox` resource (the authenticated address, from
   `users.getProfile`) — a mailbox is the operating target and gives
   Gmail the same context/fan-out shape as everything else. Google Ads
   discovery lists accessible customers then expands MCC hierarchies via
   `customers/{id}/googleAds:searchStream` on `customer_client`, storing
   `google_ads_account` resources with metadata `{manager,
   parent_external_id, level, currency_code, descriptive_name, status}`;
   manager (MCC) accounts are stored but non-operable
   (`metadata.manager=true`; `enabled` defaults false for them —
   reports/mutations target client accounts). Airtable discovery lists
   bases via the meta API, one `airtable_base` resource per base.
7. **Write-permission metadata feeds 040's gate, fail-closed**: Gmail
   mailbox `writable=true` only when the granted scopes include
   `gmail.send`; Google Ads account write metadata true only when the
   authenticated principal's access role permits mutation — when the
   role can't be determined, false; Airtable base write from the meta
   API `permissionLevel` (`create`/`edit` → true, `read`/`comment` →
   false).
8. **Per-account audit on every operation**: 026 dispatch already audits
   the outer tool call (`dispatch.py:244 dispatch_tool_execution`).
   Integration ops additionally emit one audit event **per resource
   entry** from inside the fan-out `operation`, via a new
   `services/audit_events/integration_events.py::
   record_integration_operation_audit_event` following the
   `tool_events.py:35` independent-transaction shape. Required context
   beyond the digest: `connection_id`, `integration_resource_id`,
   resource `external_id`, provider operation name, and the **external
   change reference** (Gmail sent message id; Google Ads mutate
   `resource_names`; Airtable record ids) — "which account did we touch
   and what changed" must be answerable from audit alone. Never message
   bodies, query results, or tokens in audit details. Provider packages
   call this one function; they never write audit rows their own way.
9. **Provider settings, env-gated availability**: extend the provider-owned
   `apps/api/integrations/google_ads/settings.py` object from 038 with
   `GOOGLE_ADS_DEVELOPER_TOKEN: SecretStr | None = None` (SecretStr per
   the `ANTHROPIC_API_KEY` precedent — the client reads it via
   `.get_secret_value()` for the `developer-token` header; the value
   must never appear in logs, audit details, or exception context),
   `GOOGLE_ADS_LOGIN_CUSTOMER_ID: str | None = None`. Keep the genuinely
   shared `INTEGRATION_REPORT_MAX_ROWS: int = 1000` in
   `core/settings/integrations.py`. Availability gating:
   `permissions.is_tool_allowed` (`tools/permissions.py:8-15` — the stub
   seam 040 deliberately left) returns `False` for integration-provider
   tools whose required settings are absent (gmail → provider-owned
   `GMAIL_OAUTH_CLIENT_ID`; google_ads → provider-owned
   `GOOGLE_ADS_OAUTH_CLIENT_ID` AND the developer
   token; airtable → always available once enabled). Keep it tiny and
   data-driven. This composes with 038's `configured` flag on
   `list_providers`; there is no manifest-level enable flag (enablement
   is the loader allowlist).
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
    operation rejects any query without a `SELECT` prefix (`ModelRetry`)
    and caps returned rows (`INTEGRATION_REPORT_MAX_ROWS`) with a
    truncation note in the output.
12. **Tool outputs are typed** (`output_model` on every tool, enforced
    by dispatch output-contract validation, `dispatch.py:166
    validate_output`): each tool returns `{"results":
    [FanOutEntryResult-shaped dicts]}` so the model always sees
    per-resource attribution — including single-resource contexts
    (uniform shape beats a special case).
13. **Provider code lands as self-contained packages** (packaging note;
    037 shipped them data-only): each provider is
    `apps/api/integrations/<key>/` — `__init__.py` (exports
    `PROVIDER: IntegrationProviderPlugin`), `manifest.py` if split out,
    `client.py`, `discover_resources.py`, `operations/` (one op per
    file), `tools.py`. Registration is via the loader +
    `INTEGRATIONS_ENABLED_PROVIDERS` — the loader registers manifests
    and tool definitions (`loader.py:12-31`, validating provider match
    and the `<key>_` name prefix at 34-51) and 039 retains the plugin
    for discovery dispatch. Do NOT edit the `registry.py` side-effect
    import block. Every tool definition carries a complete
    `ToolPresentation` — the default web row is the only UI these tools
    get in v1 (note principle 2). The §4.6 import laws apply (no
    `services/` → `integrations` imports outside the loader, no
    provider→provider imports), pinned by
    `tests/integrations/test_import_laws.py` (exists — extend it for
    the new modules).
14. **Threat-model channel (g) is implemented here** (Gate G6,
    threat-model §2 row (g), verified present): provider-fetched free
    text (Gmail bodies/snippets/headers, Airtable record fields, Ads
    report text) is attacker-authorable and enters model context only
    through dispatch tool results framed with the shared §3 marker
    vocabulary, carrying a server-minted source kind/ref (Gmail message
    id, Airtable record id) — provider code never hand-assembles its
    own delimiting. A hostile-email-body fixture joins the shared §4
    adversarial corpus; a deterministic test proves complete enclosure
    AND neutralization of forged markers; a named graded-eval case
    rides plan 055's injection-resistance category.
15. **Event posture recorded, no event code** (integration-events
    note): manifest `event_delivery` values are already shipped — gmail
    `"pubsub_push"` (users.watch + Pub/Sub + ~7-day renewal, a later
    plan's sweep), airtable `"webhook"` (per-webhook MAC secrets), the
    google_ads package stays `"none"` (no push surface exists). The
    package layout reserves an `events.py` module slot per provider —
    leave it absent, not stubbed; clients must not acquire
    push-registration calls here.

## Superseded decisions

Recorded so they are not re-proposed; full history in
`docs/plans/complete/{061,068,077,080}-*.md`.

- **`services/integrations/providers/<key>/` and
  `services/agents/runtime/tools/integrations/*.py`** — superseded by
  the packaging note: provider code lives in
  `apps/api/integrations/<key>/` (decision 13); nothing is registered
  through the registry's side-effect import block.
- **`GOOGLE_ADS_DEVELOPER_TOKEN: str | None`** — plan 068 typed it
  `SecretStr | None` (decision 9); it remains in the Google Ads provider
  settings object, not the global integration settings mixin.
- **Manifest entries "created env-gated in the 037 manifest module"** —
  manifests live inside the provider packages (delivered); there is no
  central manifest data and no `is_provider_enabled`. Step 2 edits the
  package manifests in place.
- **Gate G1 = 014/021–023 only** — plan 080 added 053/054 to the
  checklist (all DONE as of 2026-07-10).

## Why this matters

This is the plan the whole Phase 4a spine exists for: the first agent
capabilities that touch external systems users pay for. Gmail exercises
user-scoped OAuth + a single implicit resource; Google Ads exercises
workspace-scoped OAuth + deep resource discovery + money-spending
mutations (the roadmap's chosen first hard test of Gate G1); Airtable
exercises api-key + secret references. Between them they cover every
shape the manifest supports, so provider #4 onward is a package with a
manifest, a discovery function, and a handful of operation files — no
new machinery. Getting the *policy* right here (spend ops unweakenable,
writes approval-default, per-account audit, fail-closed write gating,
enclosed fetched content) sets the precedent every later provider
copies.

## Current state

Anchors verified 2026-07-10 against the tree with the 037 implementation
present.

- **Provider packages (delivered data-only, this plan fills them)**:
  `integrations/{gmail,google_ads,airtable}/__init__.py` each export
  `PROVIDER: IntegrationProviderPlugin(manifest, discover_resources=None)`.
  gmail: oauth, user scope, the two decision-5 scopes,
  `event_delivery="pubsub_push"`, **no `resource_types` and no
  `requires_discovery` yet** — Step 2 adds
  `resource_types=("gmail_mailbox",)`, `requires_discovery=True`.
  google_ads: oauth, workspace scope, adwords scope,
  `resource_types=("google_ads_account",)`, `requires_discovery=True`,
  capability flags include `"spend"`. airtable: api_key, workspace
  scope, `resource_types=("airtable_base",)`, `requires_discovery=True`,
  `required_form_fields=("api_key",)`, `event_delivery="webhook"`.
- **Loader/plugin**: `services/integrations/loader.py:12
  load_enabled_providers` — imports `integrations.{key}` per the
  allowlist, validates plugins (key match, tool provider match, `<key>_`
  name prefix, `validate_definition`), registers manifests and tool
  definitions (`register_tool_definition`,
  `tools/registry.py:35`). Invoked at registry import
  (`registry.py:279-286`). 039 adds `LOADED_PROVIDER_PLUGINS` for
  discovery dispatch.
- **Tool contract**: `tools/contract.py` — name pattern (34),
  `effect_scope` (92), `validate_definition` (162; reads must be
  `internal` ~174-183; write tools must support approval —
  `supports_auto=False` + `supports_approval=True` is valid);
  `ToolPresentation` exists. 040 adds `IntegrationToolBinding`, the
  deny-list, and binding validation.
- **Registry/policy**: `runtime_tool` decorator (registry.py:43),
  duplicate-name RuntimeError (39); `services/agents/utils.py` —
  `validate_tool_configuration` (96) / `normalize_tool_configuration`
  (108) reject agent `tool_policies` not in `allowed_policies()`
  (~179-182): the write-time half of decision 2.
- **Dispatch**: `dispatch.py` — `dispatch_tool_execution` (244),
  `MUTATION_OUTPUT_WARNING` (64), output-contract `validate_output`
  (166), run-envelope `check_envelope` (125).
- **Audit precedent**: `services/audit_events/tool_events.py:35
  record_tool_invocation_audit_event` (independent committed
  transaction; never raises into the tool path).
- **Exceptions**: `core/exceptions/integration.py:14-133` —
  `IntegrationError` hierarchy with
  `provider_key`/`connection_id`/`operation` context and RFC 7807
  mapping (auth 401, rate-limit 429, permission 403, etc.).
- **HTTP helper (delivered)**: `services/integrations/http.py::
  request_with_retries(method, url, *, operation, provider_key,
  **kwargs)` — Retry-After parsing, typed error mapping, settings-driven
  timeout/attempts, with existing tests at
  `tests/services/integrations/test_http_retries.py` (extend, don't
  duplicate).
- **Module-shape precedent**:
  `services/agents/runtime/tools/native/web_search.py` — probe findings
  in the module docstring, typed output model, `ModelRetry` for
  model-correctable errors.
- **Will exist after 038/039/040** (verify at execution): OAuth/api-key
  connect routes and the credential token seam (`ensure_fresh_credential`
  with the manifest-driven refresh callable); discovery job kind +
  plugin dispatch + `writable` population path; `IntegrationToolBinding`
  on the contract, `run_context_fan_out` (per-entry results, write
  gating, `ModelRetry` on empty), resolution into
  `RuntimeDeps.active_context`, the import-time deny-list.
- **Gate G1 inputs**: 014, 021, 022, 023, 053, 054 all DONE
  (`docs/plans/000_README.md`, verified 2026-07-10).
- **Threat model**: `docs/architecture/threat-model.md` §2 row (g)
  exists (integration-fetched content; owner 041/055).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Gate G1 check | the grep in Step 0 (pipes in the regex don't fit this table) | 014/053/054 rows DONE — else STOP |
| Lint | `uv run ruff check .` | exit 0 |
| Registry smoke | `INTEGRATIONS_ENABLED_PROVIDERS='["airtable","gmail","google_ads"]' uv run python -c "from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG; print(sorted(n for n in RUNTIME_TOOL_CATALOG if n.startswith(('gmail_','google_ads_','airtable_'))))"` | the 10 decision-1 names |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/integrations tests/services/integrations -q` | all pass |
| Policy invariants | `TEST_DATABASE_URL=... uv run pytest tests/services/agents -q` | all pass |
| Discovery smoke | `uv run python -m workers.job_runner --once` | exit 0 |

## Scope

**In scope:**

- `apps/api/integrations/gmail/` (fill): manifest additions
  (decision 6 resource types + `requires_discovery`), `client.py`,
  `discover_resources.py`, `operations/` (one per file), `tools.py`;
  wire `PROVIDER.discover_resources` and `PROVIDER.tool_definitions`
- `apps/api/integrations/google_ads/` (fill): same shape
- `apps/api/integrations/airtable/` (fill): same shape + PAT-scope help
  metadata (decision 5)
- `apps/api/core/settings/integrations.py` (extend — decision 9 fields)
- `apps/api/services/integrations/http.py` (extend only if a decision-4
  behavior is missing)
- `apps/api/services/agents/runtime/tools/permissions.py` — provider
  availability gating (decision 9)
- `apps/api/services/audit_events/integration_events.py` (create)
- `apps/api/tests/integrations/{gmail,google_ads,airtable}/` (create),
  `tests/integrations/test_import_laws.py` (extend), policy tests under
  `tests/services/agents/`, factory helpers

**Out of scope (do NOT touch):**

- OAuth flow mechanics, token encryption, refresh locking — 037/038 own
  the credential lifecycle; this plan only calls the credential-service
  token seam per fan-out entry.
- Discovery *harness* (job kind, status transitions, retries) — 039;
  this plan supplies each provider's `discover_resources` the harness
  invokes through the plugin.
- Context resolution, fan-out internals, prompt block, schedule wiring
  — 040.
- Any UI — 042. Event/webhook code (decision 15).
- More operations per provider than decisions 1/10 list.
- New migrations — this plan creates **no tables** (resources ride the
  generic `integration_resources`).

## Git workflow

- Branch: `advisor/041-first-integration-providers`
- Commit style: `API - Gmail, Google Ads & Airtable Providers` (split
  per provider if landing incrementally: `API - Gmail Provider`, etc.)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Gate pre-flights

Run the G1 and G6 pre-flights in the executor blockquote:

```bash
grep -E '^\| (014|021|022|023|053|054|037|038|039|040) ' ../../docs/plans/000_README.md
grep -n "(g) Integration-fetched content" ../../docs/architecture/threat-model.md
```

Every listed plan row must say DONE and the threat-model row must
exist. Any gap → STOP.

**Verify**: paste the status rows into your report before Step 1.

### Step 1: Settings + retry-helper audit

Add the decision 9 fields (SecretStr developer token). No
production-validator change (optional keys). Reuse — do not shadow —
the timeout/attempt settings the 037 helper already reads.

Audit the landed `request_with_retries` against decision 4:
`Retry-After` integer-seconds and HTTP-date forms, single-wait cap
(≤ `INTEGRATIONS_HTTP_RETRY_AFTER_CAP_SECONDS`), bounded attempts →
`IntegrationRateLimitError`, `IntegrationTimeoutError` on timeouts,
401/403/404 mapping, the non-idempotent-retry rule — always with
`provider_key`/`operation` context. Extend in place (with tests) only
where a behavior is missing.

**Verify**: ruff exit 0; behavior pinned by extending
`tests/services/integrations/test_http_retries.py`.

### Step 2: Manifest completion

Edit the three package manifests in place:

- `gmail`: add `resource_types=("gmail_mailbox",)`,
  `requires_discovery=True` (decision 6 — one implicit mailbox resource
  still flows through discovery so Gmail shares the context/fan-out
  shape).
- `google_ads`: flip `requires_discovery=True` alongside its real discovery
  callable. The 037 completion decision deliberately left it false while
  `discover_resources=None`.
- `airtable`: flip `requires_discovery=True` alongside its real discovery
  callable, and add the connect-form help text naming the required PAT
  scopes (decision 5) via the manifest metadata surface agreed with 038
  (extend `IntegrationProviderManifest` with an optional
  `connect_help: str = ""` field if 038 did not already — a data-only
  addition).

**Verify**: `INTEGRATIONS_ENABLED_PROVIDERS='["airtable","gmail","google_ads"]'
uv run python -c "from services.integrations.loader import
load_enabled_providers; load_enabled_providers(); from
services.integrations.manifest import PROVIDER_MANIFESTS;
print({k: m.resource_types for k, m in sorted(PROVIDER_MANIFESTS.items())})"`
shows the three providers with correct resource types.

### Step 3: Gmail provider (`integrations/gmail/`)

`client.py` — thin async client over
`https://gmail.googleapis.com/gmail/v1` using httpx2 + the Step 1
helper; constructor takes an access-token callable from the credential
service (so proactive refresh and `needs_reauth` transitions stay in
one place); one 401 triggers a forced refresh + single retry, a second
401 raises `IntegrationAuthError`.

Operations (one per file under `operations/`):

- `discover_resources.py` — `users/me/profile` → one `gmail_mailbox`
  resource (`external_id` = email address, write metadata from granted
  scopes per decision 7).
- `search_messages.py` — `users/me/messages?q=...&maxResults=N` (cap
  25) then batch `messages.get(format=metadata)` for
  From/To/Subject/Date + snippet. Returns typed rows; never full
  bodies.
- `read_message.py` — `messages.get(format=full)`, decode text/plain
  (fall back to stripped text/html), truncate body at 50k chars with a
  marker.
- `send_message.py` — args `to: list[str]`, `subject: str`,
  `body_text: str`, optional `cc`/`bcc`; builds RFC 2822, base64url,
  `users/me/messages/send`. Returns the sent message id (the
  decision-8 external change reference).

**Verify**: provider unit tests (Step 7) green against
`httpx2.MockTransport`; no live-call path in tests.

### Step 4: Google Ads provider (`integrations/google_ads/`)

`client.py` — async client over
`https://googleads.googleapis.com/v<pinned>` (pin the current stable
version in one constant; record it in the module docstring with the
verification date). Every request carries `developer-token` from
settings (via `.get_secret_value()`) and, when calling client accounts
under an MCC, `login-customer-id` (the manager's external id from the
resource's `parent_external_id` metadata — resolve per entry, no
if-ladders).

- `discover_resources.py` — `customers:listAccessibleCustomers`, then
  per accessible customer a `customer_client` GAQL query to expand the
  hierarchy; `google_ads_account` resources with decision-6 metadata;
  managers stored non-enabled by default.
- `list_accounts.py` — read of the *persisted* resource hierarchy for
  the active-context entries (no API call; gives the model the account
  tree cheaply).
- `run_report.py` — `googleAds:searchStream` with the GAQL `query`;
  decision-11 guards; returns rows keyed by GAQL field paths.
- `update_campaign_status.py` — args `campaign_ids: list[str]`,
  `status: Literal["ENABLED","PAUSED"]`; `campaigns:mutate` with one
  operation per id, `partial_failure=true`; returns mutate
  `resource_names` + per-campaign errors.

**Verify**: unit tests cover MCC header selection, report row cap, and
mutate partial-failure surfacing.

### Step 5: Airtable provider (`integrations/airtable/`)

`client.py` — async client over `https://api.airtable.com/v0`; the PAT
resolves at call time through the secret-reference seam (references
only).

- `discover_resources.py` — `meta/bases` (paginated) → `airtable_base`
  resources; `permissionLevel` → write metadata (decision 7).
- `list_records.py` — args `table: str`, optional `view`,
  `filter_by_formula`, `max_records` (cap 100).
- `get_record.py` — `table`, `record_id`.
- `create_record.py` — `table`, `fields: dict`; returns created id.
- `update_record.py` — `table`, `record_id`, `fields: dict` (PATCH
  semantics); returns updated id.

**Verify**: unit tests including a 429 with `Retry-After: 1` retried
then succeeding (Airtable's 5 rps limit is the realistic case).

### Step 6: Tool definitions + per-account audit + availability gating

`services/audit_events/integration_events.py` —
`record_integration_operation_audit_event(*, workspace_id, agent, run,
tool_name, provider_key, connection_id, integration_resource_id,
external_id, operation, status, external_ref: str | None, error_code:
str | None)` following the `tool_events.py:35` shape (independent
committed transaction; never raises into the tool path — log on
failure).

`integrations/<key>/tools.py` — build the decision-1
`RuntimeToolDefinition`s and export them via
`PROVIDER.tool_definitions`. Every tool:

- carries the decision-1 effect/effect_scope/policy/binding matrix
  (`integration_binding=IntegrationToolBinding(...)`), `takes_ctx=True`,
  `timeout=60`, `output_model` (decision 12), and a complete
  `ToolPresentation`;
- body: validate model-visible args (raise `ModelRetry` for correctable
  problems — empty query, no recipients, bad status value), then
  `await run_context_fan_out(ctx.deps, binding=..., operation=...,
  write=...)` where `operation` (a) resolves credentials for the
  entry's OWN connection, (b) calls the provider operation, (c) emits
  the per-entry audit event with the external change reference, and (d)
  returns the entry's data. Return `{"results": [...]}`;
- fetched free text is returned through the dispatch result frame with
  the server-minted source ref (decision 14) — no hand-rolled
  delimiting in provider code;
- no parameter names from 040's deny-list (the import-time guard
  enforces it; the context addresses accounts, never the model).

Update `permissions.is_tool_allowed` per decision 9.

**Verify**: the registry smoke lists exactly the 10 names;
`INTEGRATIONS_ENABLED_PROVIDERS='["google_ads"]' uv run python -c
"from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
as C; d=C['google_ads_update_campaign_status'];
print(d.default_policy, d.supports_auto, sorted(d.allowed_policies()))"`
→ `approval False ['approval']`.

### Step 7: Tests

`tests/integrations/{gmail,google_ads,airtable}/` (all HTTP mocked via
`httpx2.MockTransport` wired through the client constructors — live
calls are blocked in tests):

- `test_gmail_provider.py`: discovery creates the single mailbox
  resource with scope-derived write metadata; search caps results; read
  truncates; send builds correct RFC 2822 (base64url round-trip) and
  returns the message id.
- `test_google_ads_provider.py`: discovery expands an MCC fixture into
  parent-linked resources with managers non-enabled; report rejects
  non-SELECT GAQL (`ModelRetry`); row cap truncates with note; mutate
  sends `login-customer-id` for managed accounts and surfaces
  partial-failure errors per campaign.
- `test_airtable_provider.py`: discovery maps `permissionLevel` to
  write metadata; 429 retry; create/update return record ids.
- `test_integration_tools.py`: each tool's registered
  effect/effect_scope/policy/binding matches the decision-1 table (loop
  the table; every write tool is `effect_scope="external"`); fan-out
  partial failure reaches the model-visible output (`results` mixed
  success/error); per-entry audit events written with
  connection/resource/external-ref context; write tool against a
  read-only resource → `write_not_permitted` entry and NO provider
  call; **no tool schema contains a deny-listed parameter** (introspect
  `to_pydantic_tool()` JSON schema); `is_tool_allowed` hides google_ads
  tools when the developer token is absent.
- `test_fetched_content_enclosure.py` (decision 14, Gate G6): a
  hostile Gmail message body containing forged frame markers and
  embedded instructions is returned through dispatch entirely enclosed
  by the shared frame with markers neutralized and the source ref
  server-minted; the fixture is added to the shared §4 corpus, and a
  named graded-eval case is registered for plan 055's
  injection-resistance category.
- `tests/services/agents/test_spend_policy.py`: **the Gate G1
  invariants** — `validate_tool_configuration(tool_names=[...],
  tool_policies={"google_ads_update_campaign_status": "auto"})` raises
  (write-time cannot weaken); `to_pydantic_tool(policy="auto")` on that
  definition raises `ModelConfigurationError` (runtime cannot weaken);
  default policy is approval; `gmail_send_message` /
  `airtable_create_record` / `airtable_update_record` default to
  approval per governance §2.
- `tests/integrations/test_import_laws.py` (extend): the filled
  packages still satisfy §4.6 (no `services/`→`integrations` imports
  outside the loader; no provider→provider imports).

**Verify**: `TEST_DATABASE_URL=... uv run pytest tests/integrations
tests/services/integrations tests/services/agents -q` all pass; without
the env var, DB suites skip.

## Test plan

Covered by Step 7 (~35-40 tests). Pinned invariants: **the spend op
cannot be weakened to auto at either layer** (the roadmap's first hard
Gate G1 test), **every write defaults to approval and is
`effect_scope="external"`**, **write gating fails closed on missing
permission metadata**, **per-resource audit carries connection +
external change references**, **Retry-After is honored and bounded**,
**context never appears in tool schemas**, **fetched content is
enclosed and forged markers neutralized** (Gate G6 channel (g)), and
**all provider HTTP is mocked — zero live calls in CI**.

## Done criteria

- [ ] Gate G1 + G6 pre-flights passed; the required status rows quoted
      in the completion report
- [ ] `uv run ruff check .` exits 0; no new migrations exist
- [ ] Registry smoke lists exactly the 10 decision-1 tools; the spend
      op prints `approval False ['approval']`
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/integrations
      tests/services/integrations tests/services/agents -q` exits 0
- [ ] Grep confirms no `import httpx\b` under `integrations/` or
      `services/integrations/` (httpx2 only) and no deny-listed
      parameter names in tool signatures
- [ ] Per-entry audit events observable end to end in one integration
      test (tool call → N audit rows with external refs)
- [ ] The import-law test still passes against the filled packages
- [ ] `docs/architecture/governance.md` §2 spend-rule cell flipped to
      `[implemented: plan 041]`; §4 integration-retries row still
      reflects the landed helper; threat-model §2 row (g) marked
      implemented per its tracking convention
- [ ] No plan numbers cited in implementation code or docstrings
- [ ] `git status` clean outside the in-scope list;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Gate G1 fails**: 014, 053, or 054 not DONE (or 021–023 regressed)
  at execution time. Do not ship the tools "temporarily disabled".
- **Gate G6 fails**: threat-model §2 row (g) missing, or the shared
  marker vocabulary (§3) does not exist in dispatch — do not invent a
  provider-local framing.
- 038/039/040 are unimplemented or deviate from the dictated contract:
  no `IntegrationToolBinding`, different fan-out signature or result
  shape, no credential-service token seam, discovery job kind renamed,
  or no plugin-retention dispatch (039 decision 3).
- Google Ads REST requires an API version no longer served, or the
  developer token cannot be obtained for the environment — report; do
  not stub the provider with fake success paths.
- `validate_definition`'s write-must-support-approval rule or
  `normalize_tool_configuration`'s allowed-policies rejection changed —
  the spend rule's enforcement assumptions are broken.
- You feel the need to add a second HTTP retry mechanism, a provider
  SDK dependency, more than the 10 curated tools, event/webhook code,
  or any UI — scope leak.

## Maintenance notes

- **Provider #4 checklist**: a package under `apps/api/integrations/`
  (manifest, `client.py`, `discover_resources.py`, one file per
  operation, `tools.py` with bindings + presentations), per-entry audit
  via `record_integration_operation_audit_event`, MockTransport tests
  under `tests/integrations/<key>/`, import-law compliance, and
  governance §2 policy review — writes approval-default, spend ops
  `supports_auto=False`, fetched content enclosed per channel (g).
- **Scope changes are re-consent events**: widening Gmail scopes (e.g.
  adding `gmail.modify`) requires a manifest change AND every existing
  connection flowing through `needs_reauth` — never silently reuse old
  tokens for new capabilities (038's persisted-scope filtering enforces
  the read side).
- **Reviewers should scrutinize**: the fail-closed write metadata
  (absent → read-only), that `update_campaign_status` is the ONLY spend
  lever and stays single-field, `login-customer-id` selection for MCC
  children, that audit details never contain message bodies or record
  fields, and that a fan-out entry's token comes from *its own*
  connection (cross-connection token bleed is the multi-connection
  failure mode).
- 014's OTel spans wrap the dispatch layer; add provider/connection
  attributes to integration tool spans — record as a FOLLOW_UPS item at
  execution, not a scope change here.
