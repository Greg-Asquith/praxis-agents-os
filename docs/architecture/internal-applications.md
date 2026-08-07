# Internal Applications

- **Status**: design position; the applications capability is **not yet
  built**. Everything below is design intent except where it names existing
  substrate. The load-bearing rule stands regardless of how the slicing
  evolves: applications ride the platform — its identity, dispatch, policy,
  and audit boundaries — rather than beside it.
- **Rule**: implementation work cites the section it implements. A change
  that deviates records the deviation back into this note in the same PR.
- This note contains **architecture, not product scope**. Intake flows,
  triage policy, and catalogue UX are product territory; where an
  application's code lives, what it may touch, and who may change what is
  this note's.

## 1. Objective

Let people inside an organisation use AI coding tools to build internal
applications that become shared, governed software — without inventing
their own identity, credentials, storage, permissions, approvals, audit,
or lifecycle. Praxis provides the architecture; builders provide the
workflow.

Two constraints shape everything below, both taken as product decisions:

1. **One place.** Applications run inside the organisation's Praxis
   deployment, under Praxis identity, on Praxis surfaces. No separately
   hosted services, no external identity federation, no second admin
   plane.
2. **Built anywhere.** Builders author applications locally with their own
   coding tools (Claude Code, Codex, Cursor) on their own subscriptions.
   Praxis is not the required build environment and carries no build-time
   model spend. Building *inside* Praxis (an agent authoring an app
   in-workspace) is a possible later on-ramp, never the required path.

These resolve the apparent tension by decoupling build time from run time:
**applications are built anywhere, published into Praxis, and run inside
it.**

## 2. Core position: applications are workspace content, not deployments

An application is a first-class workspace resource — like agents, skills,
and files — not a deployed service:

- **What it is**: a versioned application contract (§7) + a static
  frontend bundle + configuration that *references* Praxis resources
  (which registry tools it may call, which data collections it owns,
  which agents/schedules it uses).
- **Where the bytes live**: the bundle is object storage content versioned
  by the existing `File`/`FileRevision` machinery (immutable revisions,
  provenance, retention).
- **Where it runs**: in a sandboxed frame inside the Praxis shell. The
  user never leaves Praxis; the app never gets an origin of its own
  outside Praxis control.
- **Publishing** is a state change on the application row (draft →
  published to an audience), not a deployment. Rollback is pointing the
  current-version pointer at a prior revision. Disable is a flag.
  Retirement is soft delete under the standard retention laws
  (`governance.md` §3).

Consequences that fall out of this single choice:

| Lifecycle concern | Becomes |
|---|---|
| Deployment, versioning, rollback | `FileRevision` semantics + a current-version pointer |
| Catalogue | a workspace list surface over application rows |
| Audience control | workspace membership/roles at read time (groups later) |
| Ownership, transfer | columns + ordinary CRUD, audited |
| Audit and incident history | existing `audit_events`, actor = user *via* app |
| Disable/revoke | row flag checked at frame mint and token verify time |

This is where the codebase already points: artifacts serve versioned HTML
bundles sandboxed with strict CSP, and dormant scaffolding exists for exactly
this surface — `middleware/utils.py` matches `/apps/{id}/frame` paths,
`middleware/security_headers.py` relaxes `frame-ancestors` for them, and the
CORS allowlist already carries `X-Praxis-App-Frame-Token`. Internal
applications are artifacts grown up: bundle + contract + scoped capabilities +
audience.

## 3. The three-tier change model

The answer to "everyone commits to core" vs "everything sits separately"
is that neither happens. Three tiers of change, each with its own author,
artifact, and route:

| Tier | Who ships it | Artifact | Route | Repo access |
|---|---|---|---|---|
| **Application** — workflow, UI, config, business rules | Internal builder + their coding agent | Contract + bundle | Push/upload → validation gates → draft → publish | None |
| **Building block** — new tool, provider operation, collection type, UI component | Platform/technical owner | In-repo package | Normal review, following the packaging law (`integration-packaging.md`) | Yes, isolated |
| **Platform** — dispatch, identity, contracts, policy, serving | Core maintainers | Core code | Normal review | Yes |

- Builders **cannot** reach the repository. An application that needs a
  capability no existing building block provides produces a **capability
  request** (the brief's exception path), which a technical owner may
  implement as a tier-2 package — contribution stays isolated by the same
  import laws and enablement layers that govern integration providers.
- Tier 2 already has a proven shape: self-contained packages, boot-time
  enablement, AST-enforced import laws, one-line registration, default
  server-declared UI. Building blocks beyond integrations (e.g. an app
  data collection type) follow the same law.
- Enforcement never distributes. Registry, dispatch, credential handling,
  approvals, audit, and token minting stay singular
  (`integration-packaging.md` §2 principle 1 applies unchanged).

## 4. Identity and capability scoping

There is no external identity system. The app runs inside an
authenticated Praxis session, and identity work reduces to one scoped
token mechanism with two mint paths.

### 4.1 Frame tokens (runtime)

1. A user opens a published app from the catalogue. They are already
   authenticated, workspace-resolved, and role-checked by the existing
   dependency stack.
2. The server mints a **short-lived frame token** from that session:
   - principal: the user in the workspace (apps are never their own
     principal);
   - audience: the application id + version;
   - scopes: exactly the building blocks the application contract
     declares — never more, regardless of the user's role.
3. The sandboxed bundle calls the Praxis API bearing that token. Routes
   on the app capability surface (§5) verify audience and scope on every
   call.

The app is therefore a **narrower principal than its user**: a buggy or
malicious generated bundle can only do what its contract declares, and
only on behalf of a user entitled to do it anyway. Every audit row
records (user, via application X, version N).

Non-goals, explicitly: no OIDC/OAuth2 provider capability, no personal
access tokens as a general API surface, no service accounts, no machine
principals. If a future need arises for genuinely external callers, that
is a separate architecture decision, not an extension of this one.

### 4.2 Development tokens (build time)

The second mint path for the same verifier. From the application's page,
its owner creates a **development token**: same principal model, same
contract-derived scopes, longer-lived (bounded), revocable, audited, and
displayed once. The builder drops it in `.env.local`.

- **[default — confirm at review]** Dev tokens are read-scoped by
  default; write scopes are an explicit per-token toggle. App data
  collections resolve to a scratch/dev namespace under a dev token so
  builders do not iterate against shared rows.
- Dev tokens are a human's scoped credential for a build loop — they do
  not create machine identity, and they never appear in a published
  bundle (the validation gates reject any embedded credential, and the
  dev harness design in §6 keeps them out of browser code entirely).

### 4.3 CORS and CSRF posture (unchanged)

Production CORS, cookie, and CSRF posture is not loosened
(AGENTS.md security constraints). Frame tokens are same-origin. Local
development never talks cross-origin to the API from a browser: the app
template's dev server proxies `/api/*` to the configured Praxis instance
and attaches the dev token server-side (§6.2). Bearer-token requests are
already outside the cookie-CSRF path by design.

## 5. Runtime enforcement boundary

Policy checks alone are insufficient if the runtime still permits an
application to bypass Praxis. The boundary is structural:

### 5.1 The sandbox

The bundle is served on the artifact-style sandboxed surface (the artifacts
three-layer defense, extended): opaque/isolated origin,
`sandbox` attributes, and a strict CSP whose `connect-src` allows **only
the Praxis API origin** (the deliberate difference from artifacts'
`connect-src 'none'`). Consequences, enforced by the browser rather than
by scanning generated code:

- no undeclared external network access;
- no direct database, storage, or provider access — the only reachable
  surface is the app capability API;
- no credential exposure beyond the short-lived, scope-limited frame
  token;
- no cross-app or cross-workspace reach (audience-checked at mint,
  scope-checked per call, workspace-scoped rows underneath).

### 5.2 The app capability surface

A deliberately narrow API, every route requiring a frame/dev token and
enforcing contract scopes:

| Capability | Backed by | State |
|---|---|---|
| Execute registry tool | **Headless dispatch** — a non-agent entrypoint over the existing choke point (`services/agents/runtime/dispatch.py`), with an envelope minted for app principals | New; the dispatch module explicitly reserves this seam ("wrap this module") |
| App data collections | New app data service on the reserved `app` schema (`AppModel` base + empty `app` Alembic branch exist; zero tables today) | New, bounded |
| Files | Existing files service, app-scoped key namespace | Extension |
| Invoke an agent / read runs | Existing agent runtime + runs API, scope-gated | Extension |
| Approvals | A generic approval primitive (not a paused conversation), surfaced in the existing approvals UI | New |

Server-side application logic beyond this surface is not hosted.
Behavior that needs server-side trust is *expressed in Praxis
primitives* — an agent, a schedule, a job handler, a registry tool. If it
cannot be, that is a tier-2 capability request by design. The underlying
Python that calls provider APIs lives in exactly one place — registry
tools inside provider packages holding centrally-managed credentials —
and applications reach it only through dispatch.

### 5.3 Effects, approvals, audit

- Tool effect/scope classification, approval defaults, and the spend rule
  apply to app-originated calls exactly as to agent calls
  (`governance.md` §2). The app-principal envelope defaults external
  writes to `require_approval`; **[default — confirm at review]** app
  contracts may not weaken a tool's `supports_auto=False`.
- Every dispatch through the app surface writes the same tool-invocation
  audit rows (args digest, outcome, latency), attributed (user, via app,
  version).
- App-fetched provider content shown back to users is data display, not
  model context; if an app feeds content into an agent run, the existing
  threat-model channels apply unchanged (`threat-model.md` §2).

### 5.4 Known failure modes → countermeasures

| Brief failure mode | Countermeasure |
|---|---|
| Data embedded in source/HTML | App data service + validation gate (inline-data budget) |
| Persistence via downloads/self-modifying files | Immutable revisions; bundle is read-only at runtime; collections are the write path |
| Credentials in code or browser config | Secrets never reach builders; dev proxy keeps tokens server-side; secret-scan gate |
| Direct DB/external API access | CSP `connect-src` allowlist; no DB surface exists to reach |
| No shared authn/authz | Frame runs inside Praxis session; contract-scoped tokens |
| Undeclared side effects | Effect-classified dispatch + envelope + approvals |
| No audit/approval boundary | Single choke point; app calls cannot route around it |
| No deployment/versioning/ownership | Rows + revisions + owner columns (§2) |
| Unbounded dependencies/infrastructure | Bundle is static assets; there is no infrastructure to request |

## 6. The build loop (local-first)

### 6.1 Application kit

`praxis create-app` (or a template repository) scaffolds a normal web
project:

- Vite + the approved UI component baseline;
- a typed client for the app capability surface (generated from the
  authenticated OpenAPI schema route);
- a manifest/contract stub;
- **coding-agent instructions** (`AGENTS.md`/`CLAUDE.md`) plus a
  machine-readable building-block catalogue snapshot — tool names, input/
  output schemas, effects, approval defaults, example calls — so Claude
  Code/Codex/Cursor discover capabilities the way they discover anything:
  by reading files in the repo. Refreshable via the dev token from the
  live catalogue route.

All build-time model spend is on the builder's own tooling subscription.
Praxis model spend occurs only when a published app invokes agents or
models at runtime, metered by the existing per-run usage accounting.

### 6.2 Dev harness

The template's dev server serves the bundle locally in a shell-emulating
frame and proxies `/api/*` to the configured Praxis instance, attaching
the dev token server-side. The browser only ever talks to localhost;
production CORS is untouched; the token stays out of client code.

### 6.3 Publish

`praxis apps push` (CLI) or UI upload sends bundle + manifest. On
receipt, server-side validation gates run:

- secret/credential scan; inline-dataset and generated-binary budgets;
- manifest ↔ requested-scope consistency; every requested building block
  exists and is enabled;
- CSP compatibility (no external asset references, no forbidden
  directives);
- ownership and audience declared; maintainability budgets
  **[default — confirm at review]**.

Failures return a machine-readable report naming the violated contract
and the supported replacement pattern — feedback a coding agent can apply
directly. Pass → draft version → publish to audience. The CLI path is
also the future CI seam.

## 7. Application contract (minimum viable)

Versioned, machine-readable, stored with the application row; drives
provisioning, token scoping, validation, catalogue, and audit — never
documentation-only. Minimum fields:

- application id, version, title, purpose;
- owner (accountable user) and fallback owner;
- audience (workspace roles v1; groups when they exist);
- requested building blocks: tool names, collection declarations, file
  namespace, agent/schedule references;
- effect expectations: reads, writes, external side effects; approval
  posture per declared write;
- storage/retention expectations for its collections;
- support class **[default — confirm at review]** (best-effort v1).

Changes that widen audience, add write scopes, or add sensitive resources
re-enter validation rather than inheriting a prior approval — enforced by
scope-diffing contract versions at publish time.

## 8. Existing substrate this rides on

| Need | Existing asset | Gap |
|---|---|---|
| Capability contract | `RuntimeToolDefinition` — effect, effect_scope, policies, output model, presentation, import-time validation | No serialized **input** JSON Schema in the catalogue; no `version` field on tools; both cheap now, migrations later |
| One audited execution path | `dispatch.py` choke point + envelopes + audit | Agent-run-coupled; needs the headless entrypoint + app-principal envelope |
| Approvals | Suspend/resume + approvals UI | Conversation-coupled; needs a generic primitive |
| Per-workspace capability gating | `is_tool_allowed` seam + per-agent tool policies | No per-workspace grant model |
| Credentials/secrets | Integration credential engine + secrets providers | None for this note's purposes |
| Versioned content + serving | Files/`FileRevision`; the artifacts serving pipeline; `/apps/{id}/frame` middleware scaffolding | App serving route, mint/verify, and bundle conventions unbuilt |
| App data | `app` schema + Alembic branch + `AppModel` base | Zero tables; the collection service is greenfield |
| Background work | Generic jobs harness | App-attributed enqueue conventions only |
| Governance/threat model | `governance.md`, `threat-model.md` | New rows/sections, same shape |
| Working integrations to compose | OAuth, API-key, and service-account connections with discovery and context selection | None for this note's purposes |

## 9. Non-goals

- Hosting arbitrary backend code, runtimes, or infrastructure.
- External identity: OIDC provider, PATs-as-API, service accounts,
  machine principals.
- Externally-deployed applications consuming Praxis remotely.
- Making arbitrary generated software safe; replacing professional
  engineering for systems of record or customer-facing products.
- Automatic generation of new integrations from prompts (new providers
  are tier-2 human-owned packages).
- Public/external-user exposure of applications.

## 10. Open decisions

Resolved before implementation starts, with these working defaults:

1. First supported application shape and a first reference application
   (internal, read-mostly, recognisable to a non-technical operator) —
   maintainer decision.
2. Frame/dev token mechanics: lifetime, storage, revocation, and whether
   dev tokens default read-only (§4.2 default).
3. App data service v1 scope — default: schemaless JSONB + quotas.
4. Whether app-owned schedules ship in v1 (via a referenced agent) —
   default: not in v1; the contract's agent/schedule references (§7)
   reserve the seam.
5. Validation gate set for v1 and which checks must be runtime
   enforcement rather than publish-time validation.
6. Where the UI component baseline for templates comes from (shared
   package vs copied scaffold) — default: copied scaffold.

## 11. Adjacent notes

`governance.md`, `threat-model.md`, `integration-packaging.md`, and
`agent-runtime.md`.
