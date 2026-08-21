# Integration Provider Packaging

- **Status**: living document (binds every provider)
- **Rule**: implementation work follows this note; a change that deviates
  records the deviation back into this note in the same PR. Every new
  provider follows the checklist in §8 — a provider that needs edits
  outside its own package (beyond the four named shared edit points
  named in §8) is an architecture regression and a review failure.
- This note contains **structure, not product scope**. What each provider
  does is its plan's business; where its code lives and what it may touch
  is this note's.

## 1. The problem this solves

A tightly coupled integration architecture creates broad failure domains: every integration's tools,
credentials, and UI were woven through shared modules, so every deployment
carried every provider, and touching one provider meant regression-testing
all of them. Praxis will accumulate many providers (Google Ads, Meta,
Gmail, Drive, Microsoft variants, Airtable, …) and different customers
want disjoint subsets. Without a packaging law, the registry becomes
the same monolith with better naming.

Goals, in priority order:

1. **Adding provider N+1 touches only its own package** (plus the four
   named shared edit points in §8 when applicable). No unnamed shared-file
   sprawl.
2. **Per-deployment enablement**: a deployment that wants only Gmail runs
   only Gmail — disabled providers contribute no tools, no manifest
   entries, no provider cards, no UI bytes.
3. **Blast-radius isolation**: a provider's bugs, dependencies, and tests
   are contained in its package. Provider→provider imports are forbidden.
4. **No governance regression**: policy, approvals, audit, and credential
   handling stay centralized. Packaging distributes
   *contribution*, never *enforcement*.

## 2. Principles

1. **One registry, one choke point — modular population.** There is still
   exactly one `RUNTIME_TOOL_CATALOG`, one dispatch choke point, one
   provider-manifest map, one credential service, one OAuth engine, one
   discovery harness. Provider packages *contribute entries* to these; they
   never fork or wrap them. Interconnection is the failure mode, not
   centralization — a single audited dispatch seam is a feature.
2. **Default-first UI.** Every provider tool MUST ship a complete
   server-declared `ToolPresentation` (icon, status labels, arg/result
   fields, approval copy). The web app's declarative default row renders
   any provider tool acceptably with **zero** provider frontend code.
   Custom web UI per provider is opt-in polish for the few tools that earn
   it (rich previews, domain widgets) — the expectation is that most
   providers ship none. This, more than any packaging mechanism, is what
   keeps the tool-UI registry from becoming a monolith.
3. **Dependency direction is law.** Core never imports a specific
   provider; providers import only published core seams; providers never
   import each other. Both sides enforce this mechanically (§4.6, §5.5),
   not by convention.
4. **Enablement has two current layers**, checked in order:
   - *Install-time*: provider SDK dependencies are per-provider optional
     extras (`pyproject.toml`); the base install carries none. (v1
     providers are REST-over-httpx2 and need no extras; the pattern
     exists for the first SDK-needing provider.)
   - *Boot-time*: `INTEGRATIONS_ENABLED_PROVIDERS` (settings) names the
     provider packages to load. Not listed ⇒ never imported: no manifest
     entry, no tools, no catalog presence, invisible to the product.
   There is deliberately no second per-provider enable flag or manifest
   availability gate: a provider is either named in the boot allowlist or it
   is absent. Required deployment configuration is validated fail-fast when
   the provider's operational slice lands. Workspace-level provider toggles
   remain a future slice of the existing `is_tool_allowed` seam.
5. **New provider ≠ new protocol.** Provider tools flow through the
   existing SSE events (`tool.call`/`tool.result`/`tool.approval_required`)
   and the existing presentation schema. Adding SSE event types or
   presentation field formats is a platform change with its own review,
   never something a provider does in passing.
6. **Model output and transcript evidence may differ only through the governed
   public-result seam.** A tool may return Pydantic AI `ToolReturn` metadata
   named `public_result` when an operator needs complete bounded evidence that
   would be too large for model context. The tool must declare
   `max_public_result_chars`; dispatch converts the value to JSON-safe data,
   redacts sensitive-key values, validates it against the tool's output model,
   and rejects it above the declared budget before Pydantic AI persists or
   streams it. The ordinary `return_value` remains the only model-visible
   result. Provider code owns safe row construction; core owns enforcement.
7. **Provider-scoped references are provider-native.** A scoped reference
   serializes the provider-owned scope and entity IDs needed to reuse it (for
   example Google Ads customer + campaign/shared-set ID, Gmail mailbox +
   message ID, or Airtable base + table + record ID). It never serializes a
   Praxis integration-resource or connection UUID. At execution and approval
   resume, the shared context runtime resolves the provider scope through the
   canonical active context; unavailable scopes fail closed. Active-context
   resolution deterministically consolidates duplicate provider resources
   before tool execution.
   Internal UUIDs remain server-side for credentials, authorization, cursors,
   and audit evidence.
8. **Fixed integration outputs are concrete contracts.** Every integration
   tool declares an operation-specific Pydantic output model. Free-form object
   values are confined to provider/query-defined leaves such as report rows,
   BigQuery rows, and Airtable record fields. The shared fan-out envelope
   publishes provider key, provider scope, display name, status, data, and
   bounded error fields only; it never publishes connection/resource UUIDs.

## 3. What stays centralized (deliberately)

| Concern | Owner | Why it must not fragment |
|---|---|---|
| Tool contract, registry, dispatch, audit, approvals, envelopes | `services/agents/runtime/tools/` + `dispatch.py` | one policy/audit surface |
| Provider manifest contract + registration | `services/integrations/manifest.py` | one catalog the routes/UI read |
| Credential storage, encryption, refresh locking, crypto-shred | `services/integrations/credentials/` | security-critical, identical per provider |
| Secrets provider abstraction | `services/secrets/` | governance §5 |
| OAuth connect flows, api-key connect, state signing | `routes/integrations/` + engine services | one hardened flow, parameterized by manifest |
| Discovery job harness, status machine, sweeps | `services/integrations/discovery/` | one lifecycle; providers supply only `discover_resources` |
| Active-context resolution + provider-native targeting + safe fan-out | `services/integrations/context/` | one place that maps public provider scopes to exactly one authorized internal resource and publishes results without platform UUIDs |
| SSE protocol, `ToolActivity` shape, presentation schema, public-result enforcement | stream/protocol + tool contract | stale-client safety; closed vocabularies; bounded transcript evidence |

The presentation field-format vocabulary is closed:
`text`, `multiline`, `markdown`, `html`, `bytes`, `datetime`, `boolean`,
`url`, `list`, `number`, `keyvalue`, `records`, `entity`, and
`entity_list`. The platform-owned `records` format is argument-only and uses
server-declared scalar columns; providers may consume it but cannot extend its
row shape, column types, or rendering contract inside a provider package.
Record fields may declare a platform-bounded `min_rows`, and each declared
column may be marked `required`; approval preflight enforces those constraints
before a deferred tool resumes.

A provider package supplies: manifest data, a discovery function,
operation clients, one-module-per-tool definitions (with bindings and presentations),
optional preview definitions, tests — and optionally a small web UI module.

## 4. Backend layout

### 4.1 The package namespace

```
apps/api/integrations/
  __init__.py            # namespace only — no imports of provider packages
  gmail/
    __init__.py          # exports PROVIDER: IntegrationProviderPlugin
    manifest.py          # the IntegrationProviderManifest entry (data)
    client.py            # thin async client over httpx2 + semantic request policy
    discover_resources.py
    operations/          # one service op per file (AGENTS.md rule applies)
      search_messages.py
      read_message.py
      send_message.py
    tools/
      __init__.py        # composes exported definitions only
      schemas.py         # provider tool-result contracts
      utils.py           # shared bindings and provider-local helpers
      search_messages.py # one RuntimeToolDefinition per module
      read_message.py
      send_message.py
  google_ads/            # same shape
  airtable/              # same shape
  bigquery/              # same shape
```

`integrations/` is a top-level package beside `services/`, `routes/`,
`models/` — deliberately *outside* `services/` so the import laws in §4.6
are a package boundary, not a subdirectory convention. Tests mirror it at
`apps/api/tests/integrations/<key>/`.

### 4.2 The plugin contract

`services/integrations/plugin.py`:

```python
@dataclass(frozen=True)
class IntegrationProviderPlugin:
    manifest: IntegrationProviderManifest
    discover_resources: DiscoverResourcesFn | None  # required iff manifest.requires_discovery
    metadata_sync_job_kind: str | None = None       # provider-owned metadata handler
    oauth_config: OAuthConfigFn | None = None
    tool_definitions: tuple[RuntimeToolDefinition, ...] = ()
    preview_definitions: tuple[IntegrationPreviewDefinition, ...] = ()
    entity_resolvers: tuple[EntityResolverDefinition, ...] = ()
    event_definition: IntegrationEventDefinition | None = None
```

Each provider package's `__init__.py` exports exactly one
`PROVIDER: IntegrationProviderPlugin`. The contract is intentionally
boring — data plus bounded callable contributions. Preview definitions
contain a kind, audit operation name, and raw-content fetch function; the
engine retains connection scoping, response bounds, HTML sanitization, and
failure auditing. Successful preview renders are not audited: the governed
tool call that surfaced the content is the durable audit record, and
per-render read events would only add noise. Anything a provider needs
beyond this is a sign the engine is missing a seam; extend the engine,
don't grow the contract ad hoc. The optional metadata job kind lets a
warehouse-style provider trigger provider-owned cache refresh from discovery
and selection without an engine branch.

### 4.3 The loader

`services/integrations/loader.py`:

```python
def load_enabled_providers() -> None:
    for key in settings.INTEGRATIONS_ENABLED_PROVIDERS:
        module = importlib.import_module(f"integrations.{key}")
        plugin = module.PROVIDER
        _validate(plugin, expected_key=key)   # see invariants below
        register_provider_manifest(plugin.manifest)
        for definition in plugin.tool_definitions:
            register_tool_definition(definition)
```

- Called by `assemble_runtime_catalogs()` after built-in job handlers, internal
  entity resolvers, and core runtime tools are registered. The API lifespan,
  worker supervisor and standalone runners, maintenance commands, live eval
  runner, and test bootstrap invoke this explicit, idempotent composition entry
  point, so every process gets the same catalogs. Assembly serializes callers;
  after one attempt fails, later calls re-raise that failure instead of using or
  extending partially registered process state.
- **Fail-fast at boot**: an unknown key (module missing), a package without
  `PROVIDER`, or a plugin failing validation raises at startup. A
  misconfigured deployment must not come up half-integrated.
- Import-time invariants (extending the manifest and registry checks): `manifest.provider_key == key == package name`; every
  tool's `provider == key`; every tool name starts with `f"{key}_"`; oauth
  mode ⇒ scopes, api_key mode ⇒ form fields; `requires_discovery` ⇒
  `discover_resources` is not None; every tool carries a complete
  `ToolPresentation` (principle 2 is machine-checked, not aspirational).
- A future *external* distribution path (separately installed provider
  wheels discovered via an entry-point group) slots in behind the same
  contract: the loader gains a second source of `IntegrationProviderPlugin`
  values and nothing else changes. Not built until someone needs it.

### 4.4 Settings

- `INTEGRATIONS_ENABLED_PROVIDERS: list[str] = []` — the boot-time
  enablement list. Empty default: integrations are opt-in per deployment.
- Per-provider operational settings (OAuth client ids, developer tokens)
  live in provider-owned `BaseSettings` inside `integrations/<key>/`.
  Provider configuration is deployment state, but keeping its schema in the
  package preserves the import boundary. These values are prerequisites for
  loading or using the provider, not a second enablement mechanism.

### 4.5 Optional dependencies

Per-provider extras in `apps/api/pyproject.toml` when (and only when) a
provider needs an SDK, following the storage precedent exactly: extra
`integration-<key>`, guarded import inside the module
(`try: import x / except ImportError: x = None`), instantiation-time
failure with a clear error naming the extra. REST-only providers (all
current providers) declare no extra.

### 4.6 Import laws (enforced)

1. Nothing under `services/`, `routes/`, `models/`, `workers/`, or
   `core/` imports `integrations.*` — except `services/integrations/
   loader.py` (dynamically, by configured key).
2. `integrations.<key>` may import: `services/integrations/` published
   seams (plugin contract, `http.py` retries, credential accessors,
   domain vocabulary), `services/secrets/` ops,
   `services/agents/runtime/tools/` contract + decorator,
   `services/jobs/registry.py` solely to register a provider-owned handler,
   `core/exceptions/`, `core/settings`, and `utils/`. Nothing else in
   `services/` without adding the seam to this list first.
3. `integrations.<a>` never imports `integrations.<b>`.
4. Enforcement: a dedicated test (`tests/integrations/test_import_laws.py`)
   walks the AST of both trees and asserts 1–3. It runs in the default
   suite so violations fail CI, not review.

### 4.7 Integration operation runtime

Provider tools contribute typed operations and safe evidence; the integration
service owns the repeated lifecycle:

- `context/fan_out.py::run_context_fan_out` selects every compatible active
  resource, while `context/targeted.py::run_context_targets` groups exact
  scoped references. Both delegate authorization, denial evidence, exception
  isolation, sanitization, and result construction to one private execution
  loop.
- `context/results.py` publishes `IntegrationFanOutEntry`,
  `IntegrationFanOutOutput`, and `serialize_fan_out_results`. Provider result
  models subclass those bases only to narrow `data` or `results`; they never
  copy the nine outer fields or add another serializer.
- `services/integrations/operations.py` publishes
  `IntegrationAuditOutcome` and `run_audited_integration_operation`. The
  runner resolves the registered tool definition, validates the provider and
  binding against the actually dispatched tool, and derives external-write
  durability from effect/egress metadata. Caller-supplied tool names or context
  bindings that disagree with the dispatched definition fail before provider
  execution.
  An external write must supply bounded pending `IntegrationOperationDetail`;
  the runner commits it before provider execution and correlates strict
  terminal evidence. Outcomes accept terminal statuses only; reads remain
  best-effort.
  Every provider request also supplies the shared HTTP seam with one semantic
  policy: `read`, `idempotent_write`, or `mutation`. The policy is mandatory at
  the call site; neither an HTTP verb nor an operation-name string implies
  retry safety. Reads retain bounded retry behavior. `idempotent_write` is
  reserved for provider-documented and tested idempotency mechanisms. A
  `mutation` request is attempted once for timeout, connection, rate-limit, and
  server-failure paths; a received 401 may trigger exactly one credential
  refresh and new attempt because the rejection proves the mutation did not
  run.

  Failed requests carry a typed `not_dispatched`, `rejected`, or `ambiguous`
  disposition into the operation runner. The runner records provable
  non-dispatch/rejection as ordinary failure and ambiguity as
  `unverified_mutation`. Unknown mutation exceptions are conservative:
  cancellation or a lost/malformed response after transport begins is
  ambiguous. Cancellation before the transport call remains non-dispatched;
  cancellation during a request uses a bounded shielded terminal-audit
  finalizer and then propagates. No ambiguous mutation is automatically
  replayed.

A normal operation function resolves its provider client, executes one
provider operation, and returns one typed terminal projection:

```python
async def operation(entry: ResolvedContextEntry):
    async def execute():
        result = await provider_operation(...)
        return IntegrationAuditOutcome(
            result,
            external_ref=result.get("id"),
        )

    return await run_audited_integration_operation(
        ctx,
        entry,
        tool_name="provider_operation",
        operation="operation",
        execute=execute,
        # Required for registered external writes; omit for reads.
        pending_operation_detail=pending_detail(entry),
    )

results = await run_context_fan_out(ctx, binding=BINDING, operation=operation)
return {"results": serialize_fan_out_results(results)}
```

The provider must not choose audit durability, add a write-denial callback,
wrap the shared audit recorder, or recreate the outer envelope. A legitimate
one-provider-request/many-context topology may keep a narrowly named adapter,
as BigQuery does with `run_multi_context_query_with_audit`, but persistence
still delegates to the shared runner.

### 4.8 Graceful degradation

Disabling a provider must degrade agents, not brick them. Two engine
behaviors guarantee this:

- **Write-time stays strict**: saving an agent with a tool name absent
  from the live catalog is still rejected (`validate_tool_configuration`).
- **Run-time goes lenient for absences**: `build_runtime_tools` skips a
  saved `tool_names` entry that is missing from the catalog — logging a
  warning and recording the skipped names in run metadata — instead of
  raising `ModelConfigurationError`. An agent that had Gmail tools keeps
  running (without them) when Gmail is disabled; the tool selector
  renders unavailable saved tools, so the UI story is consistent.
  Unknown *policies* and other config corruption still raise — leniency
  applies only to catalog absence.

## 5. Frontend layout

### 5.1 No pnpm workspace (decision, revisit trigger recorded)

`apps/web` stays a single Vite SPA. A pnpm workspace with
`packages/integration-*` would add build orchestration, dependency-cruiser
and knip reconfiguration, and version management — and buy nothing at
runtime, because every workspace package still lands in the same bundle.
The two things that matter — **boundaries** and **not shipping disabled
providers' UI to the browser** — are achieved with directory law +
dependency-cruiser rules and per-provider lazy chunks. Revisit only if
provider UIs are ever distributed/installed separately from the app.

### 5.2 The module namespace

```
apps/web/src/integrations/
  contract.ts        # IntegrationUiModule type + re-exported tool-UI contracts
  registry.ts        # providerKey -> () => import('./<key>') map (the ONE shared edit point)
  gmail/
    index.ts         # default-exports IntegrationUiModule
    *-row.tsx        # custom ToolRowPresenters (only if earned — principle 2)
  google_ads/
  ...
```

`src/integrations/` sits beside `src/features/` — same reasoning as the
backend: a boundary, not a subfolder.

### 5.3 The module contract

```ts
export type IntegrationUiModule = {
  providerKey: string
  toolRowPresenters?: ToolRowPresenter[]        // custom rows, first-match-wins
  icons?: Record<string, LucideIcon>            // extends the tool-ui icon tokens
  ConnectHelp?: ComponentType<{ provider: IntegrationProviderEntry }>
}
```

- `registry.ts` holds a static `Record<string, () => Promise<{default:
  IntegrationUiModule}>>`. Static import literals are required for Vite to
  code-split — one chunk per provider, fetched only when needed.
- Load triggers: the integrations page loads modules for the provider keys
  the server catalog returns; the conversation view loads modules for the
  distinct provider keys present in rendered tool activities
  (`ToolPresentationEntry.provider` already flows to the client).
- **Progressive enhancement**: until a module resolves (or when a provider
  ships none), the declarative default row renders from the server-declared
  presentation. A missing/slow/broken provider chunk can never block a
  conversation from rendering.

### 5.4 Dispatch integration

Core presenter families contribute self-contained presenters from sibling
feature modules. `renderCustomToolCallRow` preserves their explicit order,
then consults loaded integration modules keyed by the activity's provider.
The tool-UI icon resolver checks module-contributed icons before the built-in
token map. No other shared file changes per provider.

### 5.5 Boundary rules (enforced in `.dependency-cruiser.cjs`)

1. `^src/integrations` may import only `^src/components/ui`,
   `^src/components/tool-ui`, `^src/lib`, and
   `^src/integrations/contract` — never `app/`, `routes/`, `features/`,
   `config/`. The engine-owned `^src/components/tool-ui` presenter kits may
   import only shared UI primitives, framework-light `lib` helpers, and
   sibling kit modules; they never reach back into features or providers.
2. `^src/(features|routes|app)` may import from `^src/integrations` only
   via `^src/integrations/(registry|contract)`.
3. No provider dir imports a sibling provider dir.
4. The tool-UI contract types a provider needs (`ToolActivity`,
   `ToolRowPresenter`/`ToolRowPresenterProps`, `ToolUi`) are published
   type-only through `src/integrations/contract.ts` (re-exporting from
   their current homes) so rule 1 stays a clean path rule. knip learns
   `src/integrations/*/index.ts` as entry points.

## 6. Provider enablement, end to end

| Layer | Mechanism | Effect when off |
|---|---|---|
| Install (backend) | pyproject extra `integration-<key>` | SDK absent; package import-guards explain which extra to install |
| Boot (backend) | `INTEGRATIONS_ENABLED_PROVIDERS` | package never imported: no manifest, no tools, no catalog/provider-card presence |
| Boot (frontend) | server catalog is the source of truth | provider card absent; module chunk never requested |
| Workspace (future) | per-workspace provider toggles on the same `is_tool_allowed` seam | provider hidden for that workspace |

## 7. Failure modes → countermeasures

| Failure mode | Countermeasure here |
|---|---|
| Everything shipped always | boot-time enablement list; lazy web chunks; per-provider extras |
| Provider logic woven through shared modules | package namespaces + machine-enforced import laws (§4.6, §5.5) |
| Every tool needed bespoke UI | default-first: server-declared presentation renders everything; custom rows exceptional |
| One provider's change regression-tested all | per-package tests; provider→provider imports forbidden |
| Registry sprawl | single registry retained; contribution via one boring contract; loader invariants machine-check it |
| Disabling anything broke agents | lenient run-time resolution (§4.8); UI preserves unavailable saved tools |

## 8. Provider N+1 checklist

Adding a provider touches:

1. `apps/api/integrations/<key>/` — the package (manifest, client,
   discovery, operations, a one-module-per-tool tree with presentations,
   per-package tests).
2. `apps/api/pyproject.toml` — an extra, only if it needs an SDK.
3. Provider-owned `BaseSettings` in the package for operational values such
   as client ids and tokens, only if OAuth/config-gated.
4. Optionally contribute preview definitions from the provider package;
   do not add provider routes or branches to shared services.
5. If the provider owns a metadata cache, register its handler through
   `services/jobs/registry.py` and declare only the kind on the plugin.
6. Optionally `apps/web/src/integrations/<key>/` + **one line** in
   `src/integrations/registry.ts` — only if it earns custom UI. Add a semantic
   token to the closed `VALID_TOOL_ICONS` set when its tool presentations need
   a provider icon.
7. Ask whether any tool returns content a person would want to **see** rather
   than read about. If so, name the engine-owned presenter kits and optional
   preview kinds the provider package composes; provider packages contribute
   adapters only and never add kit logic.
8. Governance §2 policy review: writes default `approval`; spend ops
   `supports_auto=False`. No exceptions by packaging.
9. Build each normal tool over the §4.7 context, audit-outcome, and result
   seams. External writes supply bounded pending intent; providers do not own
   denial callbacks, durability switches, audit runners, or outer serializers.
10. Declare `IntegrationRequestPolicy` on every provider-client call. Query
    POSTs are reads; external writes are mutations unless a real provider
    idempotency mechanism is documented and covered.
11. For Google OAuth providers, add the provider key to the shared Google
    userinfo allowlist when `openid email` supplies the external principal.
12. Extend test-only provider enumeration fixtures; these are coverage seams,
    not runtime registration.

It must NOT touch: the registry/dispatch internals, the manifest module,
the loader, the SSE protocol, the presentation schema, another provider,
or any `features/` code. Reviewers hold the line here.

## 9. Current provider set

The shipped providers are Gmail, Google Ads, Airtable, BigQuery, and Google
Analytics through the §8 N+1 checklist. There is no fake or sample provider in product
code: contract and loader tests use a suite-local test provider registered
through the loader in test code — fixtures under the test tree — with provider
HTTP (token/userinfo/discovery endpoints) mocked at the transport layer.
Manual QA connects real dev credentials (Airtable's API key is the cheapest
connect). The engine's generic manifest-driven OAuth flow is the only token
path; revisit only if a real provider cannot use it.

BigQuery demonstrates the checklist end to end. Its package under
`integrations/bigquery/` contributes a workspace-owned service-account
manifest, a bounded REST client, dataset discovery, a schema-cache metadata
sync job declared through the plugin's job kind and registered via the narrow
jobs-registry seam (§4.6), and three read tools: cache-backed table listing
and schema lookup plus a dry-run-gated SELECT query bounded by active
datasets, reference count, bytes, rows, and location. It needs no SDK extra,
provider-specific engine branch, or registration edit. The shared Google
service-account helper receives the provider key from each caller so
validation and token errors stay correctly attributed without coupling the
credential layer to any one Google provider. Warehouse values remain plain
typed data under the operator-controlled database exception recorded in the
threat model. Its lazy frontend module supplies a BigQuery icon,
plain-language connection guidance, and guarded table, schema, and query
presenters; the shared service-account form stays manifest-driven and
write-only.

Google Analytics demonstrates the OAuth-plus-service-account variant. Its
workspace-owned package uses its own Google Cloud OAuth client, requests only
`analytics.readonly`, and discovers selectable GA4 properties from paged Admin
API account summaries without per-property enrichment calls. Accounts remain
display metadata rather than selectable resources. Its Data/Admin REST client
uses bearer authorization, explicit read policies, bounded pagination, and the
shared refresh-once credential seam. The lazy frontend module contributes the
provider mark and setup guidance. Its five code-eligible read tools list bounded
standard/custom report fields, check which candidate fields can be added to a
compatible standard report per property, and run structured standard or
realtime GA4 reports with typed metric values and the shared report row bound.
They also expose each property's bounded Admin API Google Ads link list without
creator email addresses so an agent can verify the provider-native bridge before
comparing reports. Standard reports also surface access-restriction and sampling
metadata.
