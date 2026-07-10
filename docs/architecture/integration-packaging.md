# Integration Provider Packaging

- **Status**: living document (binds Phase 4a and every later provider)
- **Written**: 2026-07-07 at `71ef591` (plan 061)
- **Rule**: plans 037–042 implement slices of this note; a plan that
  deviates records the deviation back into this note in the same PR. Every
  provider added after Phase 4a follows the checklist in §8 — a provider
  that needs edits outside its own package (beyond the two one-line
  registration points named in §8) is an architecture regression and a
  review failure.
- This note contains **structure, not product scope**. What each provider
  does is its plan's business; where its code lives and what it may touch
  is this note's.

## 1. The problem this solves

The donor system died of interconnection: every integration's tools,
credentials, and UI were woven through shared modules, so every deployment
carried every provider, and touching one provider meant regression-testing
all of them. Praxis will accumulate many providers (Google Ads, Meta,
Gmail, Drive, Microsoft variants, Airtable, …) and different customers
want disjoint subsets. Without a packaging law, Phase 4a's registry
becomes the same monolith with better naming.

Goals, in priority order:

1. **Adding provider N+1 touches only its own package** (plus the two
   one-line registration points in §8). No shared-file sprawl.
2. **Per-deployment enablement**: a deployment that wants only Gmail runs
   only Gmail — disabled providers contribute no tools, no manifest
   entries, no provider cards, no UI bytes.
3. **Blast-radius isolation**: a provider's bugs, dependencies, and tests
   are contained in its package. Provider→provider imports are forbidden.
4. **No governance regression**: policy, approvals, audit, and credential
   handling stay centralized (roadmap Target 1). Packaging distributes
   *contribution*, never *enforcement*.

## 2. Principles

1. **One registry, one choke point — modular population.** There is still
   exactly one `RUNTIME_TOOL_CATALOG`, one dispatch choke point, one
   provider-manifest map, one credential service, one OAuth engine, one
   discovery harness. Provider packages *contribute entries* to these; they
   never fork or wrap them. The donor's failure was interconnection, not
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

## 3. What stays centralized (deliberately)

| Concern | Owner | Why it must not fragment |
|---|---|---|
| Tool contract, registry, dispatch, audit, approvals, envelopes | `services/agents/runtime/tools/` + `dispatch.py` (025/026) | one policy/audit surface — Gate G1 |
| Provider manifest contract + registration | `services/integrations/manifest.py` (037) | one catalog the routes/UI read |
| Credential storage, encryption, refresh locking, crypto-shred | `services/integrations/credentials/` (037) | security-critical, identical per provider |
| Secrets provider abstraction | `services/secrets/` (037) | governance §5 |
| OAuth connect flows, api-key connect, state signing | `routes/integrations/` + engine services (038) | one hardened flow, parameterized by manifest |
| Discovery job harness, status machine, sweeps | 039 | one lifecycle; providers supply only `discover_resources` |
| Active-context resolution + fan-out | 040 | one place that decides what agents operate on |
| SSE protocol, `ToolActivity` shape, presentation schema | stream/protocol + tool contract | stale-client safety; closed vocabularies |

A provider package supplies: manifest data, a discovery function,
operation clients, tool definitions (with bindings and presentations),
tests — and optionally a small web UI module.

## 4. Backend layout

### 4.1 The package namespace

```
apps/api/integrations/
  __init__.py            # namespace only — no imports of provider packages
  fake/                  # the 037 contract-fake, first package (local-only) — superseded, see §10 (decision D11): removed; the first packages are 041's real providers
  gmail/
    __init__.py          # exports PROVIDER: IntegrationProviderPlugin
    manifest.py          # the IntegrationProviderManifest entry (data)
    client.py            # thin async client over httpx2 + shared retries
    discover_resources.py
    operations/          # one service op per file (AGENTS.md rule applies)
      search_messages.py
      read_message.py
      send_message.py
    tools.py             # RuntimeToolDefinitions: bindings + presentations
  google_ads/            # same shape
  airtable/              # same shape
```

`integrations/` is a top-level package beside `services/`, `routes/`,
`models/` — deliberately *outside* `services/` so the import laws in §4.6
are a package boundary, not a subdirectory convention. Tests mirror it at
`apps/api/tests/integrations/<key>/`.

### 4.2 The plugin contract

`services/integrations/plugin.py` (part of the 037 engine):

```python
@dataclass(frozen=True)
class IntegrationProviderPlugin:
    manifest: IntegrationProviderManifest          # 037 shape, unchanged
    discover_resources: DiscoverResourcesFn | None # required iff manifest.requires_discovery
    tool_definitions: tuple[RuntimeToolDefinition, ...]
```

Each provider package's `__init__.py` exports exactly one
`PROVIDER: IntegrationProviderPlugin`. The contract is intentionally
boring — data plus two kinds of callables. Anything a provider needs
beyond this is a sign the engine is missing a seam; extend the engine,
don't grow the contract ad hoc. (Addendum §9 adds one optional
attribute: `oauth_operations`, default `None`.) *(superseded — see §10
(decision D11): §9 is withdrawn; the contract stays `manifest +
discover_resources + tool_definitions`)*

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

- Called once from the registry assembly point (the import-for-side-effects
  block at the bottom of `runtime/tools/registry.py`), so the API process
  and both workers get identical catalogs.
- **Fail-fast at boot**: an unknown key (module missing), a package without
  `PROVIDER`, or a plugin failing validation raises at startup. A
  misconfigured deployment must not come up half-integrated.
- Import-time invariants (extends the 037 manifest checks and the 025
  registry checks): `manifest.provider_key == key == package name`; every
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
- Settings validator: `"fake"` in the list is rejected outside
  `ENVIRONMENT=local` (same law as local_fs storage / console email).
  *(superseded — see §10 (decision D11): no `"fake"` key exists to gate;
  the clause is not built)*
- Per-provider operational settings (OAuth client ids, developer tokens)
  stay in the core settings mixins as today — settings are deployment
  config, not provider code. They are prerequisites for loading the provider,
  not a second enablement mechanism.

### 4.5 Optional dependencies

Per-provider extras in `apps/api/pyproject.toml` when (and only when) a
provider needs an SDK, following the storage precedent exactly: extra
`integration-<key>`, guarded import inside the module
(`try: import x / except ImportError: x = None`), instantiation-time
failure with a clear error naming the extra. REST-only providers (all of
v1, per 041 decision 3) declare no extra.

### 4.6 Import laws (enforced)

1. Nothing under `services/`, `routes/`, `models/`, `workers/`, or
   `core/` imports `integrations.*` — except `services/integrations/
   loader.py` (dynamically, by configured key).
2. `integrations.<key>` may import: `services/integrations/` published
   seams (plugin contract, `http.py` retries, credential accessors,
   domain vocabulary), `services/secrets/` ops,
   `services/agents/runtime/tools/` contract + decorator,
   `core/exceptions/`, `core/settings`, and `utils/`. Nothing else in
   `services/` without adding the seam to this list first.
3. `integrations.<a>` never imports `integrations.<b>`.
4. Enforcement: a dedicated test (`tests/integrations/test_import_laws.py`)
   walks the AST of both trees and asserts 1–3. It runs in the default
   suite so violations fail CI, not review.

### 4.7 Graceful degradation

Disabling a provider must degrade agents, not brick them. Two changes to
the engine (landing with the 037/041 slices):

- **Write-time stays strict**: saving an agent with a tool name absent
  from the live catalog is still rejected (`validate_tool_configuration`).
- **Run-time goes lenient for absences**: `build_runtime_tools` skips a
  saved `tool_names` entry that is missing from the catalog — logging a
  warning and recording the skipped names in run metadata — instead of
  raising `ModelConfigurationError`. An agent that had Gmail tools keeps
  running (without them) when Gmail is disabled; the 027 tool selector
  already renders unavailable saved tools, so the UI story is consistent.
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

`renderCustomToolCallRow` keeps its ordered core presenters (delegation,
skills, files, todos — platform tools, not integrations), then consults
loaded integration modules keyed by the activity's provider. The tool-UI
icon resolver checks module-contributed icons before the built-in token
map. No other shared file changes per provider.

### 5.5 Boundary rules (enforced in `.dependency-cruiser.cjs`)

1. `^src/integrations` may import only `^src/components/ui`, `^src/lib`,
   and `^src/integrations/contract` — never `app/`, `routes/`,
   `features/`, `config/`.
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

## 7. Old-system failure modes → countermeasures

| Donor failure | Countermeasure here |
|---|---|
| Everything shipped always | boot-time enablement list; lazy web chunks; per-provider extras |
| Provider logic woven through shared modules | package namespaces + machine-enforced import laws (§4.6, §5.5) |
| Every tool needed bespoke UI | default-first: server-declared presentation renders everything; custom rows exceptional |
| One provider's change regression-tested all | per-package tests; provider→provider imports forbidden |
| Registry sprawl | single registry retained; contribution via one boring contract; loader invariants machine-check it |
| Disabling anything broke agents | lenient run-time resolution (§4.7); UI preserves unavailable saved tools |

## 8. Provider N+1 checklist

Adding a provider touches:

1. `apps/api/integrations/<key>/` — the package (manifest, client,
   discovery, operations, tools with presentations, per-package tests).
2. `apps/api/pyproject.toml` — an extra, only if it needs an SDK.
3. Core settings mixin — its operational settings (client id, tokens),
   only if OAuth/config-gated.
4. Optionally `apps/web/src/integrations/<key>/` + **one line** in
   `src/integrations/registry.ts` — only if it earns custom UI.
5. Governance §2 policy review: writes default `approval`; spend ops
   `supports_auto=False`. No exceptions by packaging.

It must NOT touch: the registry/dispatch internals, the manifest module,
the loader, the SSE protocol, the presentation schema, another provider,
or any `features/` code. Reviewers hold the line here.

## 9. Addendum (2026-07-10, plan 080): optional OAuth-operations seam *(superseded — see §10 (decision D11))*

*(This entire section is superseded — see §10 (decision D11): the seam
is withdrawn with its only consumer.)*

Recorded from plan 080 decision 1 (amends §4.2; 037 implements):

- `IntegrationProviderPlugin` gains one optional attribute —
  `oauth_operations`, default `None` — for providers that cannot use the
  engine's generic manifest-driven OAuth HTTP flow (038). The generic
  flow remains the default; a provider supplies `oauth_operations` only
  when its token issuance/refresh/revoke cannot be expressed as
  manifest-driven HTTP against provider endpoints.
- The fake provider is the first consumer: its in-process token
  issuance/refresh/revoke back the 037/038 credential state machine
  without real OAuth, resolving the gap between the 037 amendment (the
  fake moves wholly into `integrations/fake/`) and a plugin contract
  that previously had no token seam.
- Resolution is loader-only: the engine (credential service refresh,
  038's connect-flow short-circuits) reaches a provider's
  `oauth_operations` through the loaded plugin, never by importing
  `integrations.*` directly — the §4.6 import laws are unchanged.
- The registry/dispatch singularity (§2 principle 1, §3) is unaffected:
  this distributes contribution of an auth *implementation*, not
  policy, audit, credential storage, or dispatch.

## 10. Addendum (2026-07-10, decision D11): the fake provider is removed

Recorded from roadmap decision D11 (2026-07-10): "**The fake integration
provider is removed entirely.** The shipped provider set is exactly D4 —
Gmail, Google Ads, Airtable." Where this section conflicts with anything
above (including §9), this section wins.

- **The fake provider is removed from the design.** The §4.1 package
  tree's `fake/` first-package entry and the §4.4 settings-validator
  rejection of `"fake"` in `INTEGRATIONS_ENABLED_PROVIDERS` no longer
  apply — no fake provider package, no fake manifest entry, and no
  fake-specific validator clause ships. The first packages under
  `apps/api/integrations/` are 041's real providers (`gmail/`,
  `google_ads/`, `airtable/`).
- **§9's `oauth_operations` seam is withdrawn with its only consumer.**
  The plugin contract stays
  `manifest + discover_resources + tool_definitions` (§4.2 as originally
  written); the engine's generic manifest-driven OAuth flow (038) is the
  only token path. Revisit only if a real provider cannot use the
  generic flow.
- **Contract/loader tests use a suite-local test provider registered
  through the loader in test code** — fixtures under the test tree,
  never product code — with provider HTTP (token/userinfo/discovery
  endpoints) mocked at the transport layer. Manual QA connects real dev
  credentials (Airtable's API key is the cheapest connect). The import
  laws (§4.6), loader invariants (§4.3), and enablement layers (§4.4,
  §6) are otherwise unchanged.
